"""Render a completed review as a PDF.

A review that only exists inside a web page is hard to act on: the thing people
actually do with it is take it into a conversation with the other side, or with
a lawyer. So the export leads with what to ask for, keeps every finding attached
to the words that triggered it, and carries the confidence basis rather than
just the number -- a report that hides how sure it is invites more trust than it
has earned.
"""

import io
import os
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# reportlab's built-in Helvetica and Courier carry no glyph for the rupee sign,
# so every "₹50,000" in an Indian contract rendered as a black square, and any
# Devanagari as a row of them. A Unicode TrueType font is registered when one
# can be found; the rupee sign is additionally written as "Rs." regardless,
# which is how Indian legal drafting most often renders it anyway.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def _matplotlib_dejavu() -> Optional[str]:
    try:
        import matplotlib  # matplotlib bundles DejaVuSans, rupee sign included

        path = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf", "DejaVuSans.ttf")
        return path if os.path.exists(path) else None
    except Exception:
        return None


def _register_unicode_font() -> Optional[str]:
    candidates = ([_matplotlib_dejavu()] if _matplotlib_dejavu() else []) + _FONT_CANDIDATES
    for path in candidates:
        if path and os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("WLSUnicode", path))
                return "WLSUnicode"
            except Exception:
                continue
    return None


UNICODE_FONT = _register_unicode_font()
BODY_FONT = UNICODE_FONT or "Helvetica"
BOLD_FONT = UNICODE_FONT or "Helvetica-Bold"
MONO_FONT = UNICODE_FONT or "Courier"

SEVERITY_COLOURS = {
    "CRITICAL": colors.HexColor("#b91c1c"),
    "HIGH": colors.HexColor("#c2410c"),
    "MEDIUM": colors.HexColor("#a16207"),
    "LOW": colors.HexColor("#047857"),
    "INFO": colors.HexColor("#1d4ed8"),
}


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName=BOLD_FONT, fontSize=20, spaceAfter=4),
        "subtitle": ParagraphStyle(
            "st", parent=base["Normal"], fontName=BODY_FONT, fontSize=9.5,
            textColor=colors.HexColor("#4b5563"), spaceAfter=12,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName=BOLD_FONT, fontSize=13, spaceBefore=14, spaceAfter=6,
            textColor=colors.HexColor("#111827"),
        ),
        "body": ParagraphStyle(
            "b", parent=base["Normal"], fontName=BODY_FONT, fontSize=9.5, leading=13.5, alignment=TA_LEFT
        ),
        "small": ParagraphStyle(
            "s", parent=base["Normal"], fontName=BODY_FONT, fontSize=8, leading=11,
            textColor=colors.HexColor("#6b7280"),
        ),
        "quote": ParagraphStyle(
            "q", parent=base["Normal"], fontName=MONO_FONT, fontSize=8, leading=11,
            leftIndent=8, textColor=colors.HexColor("#1f2937"),
            backColor=colors.HexColor("#f3f4f6"), borderPadding=5, spaceBefore=4,
            spaceAfter=4,
        ),
    }


def _escape(text: Any) -> str:
    return (
        str(text or "")
        .replace("\u20b9", "Rs. ")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _finding_block(finding: Dict[str, Any], style) -> List[Any]:
    colour = SEVERITY_COLOURS.get(finding.get("severity"), colors.grey)
    detector = "RULE" if finding.get("detector") == "rule" else "MODEL"
    head = (
        f'<font color="{colour.hexval()}"><b>{_escape(finding.get("severity"))}</b></font>'
        f'&nbsp;&nbsp;<b>{_escape(finding.get("title"))}</b>'
        f'&nbsp;&nbsp;<font size="7" color="#6b7280">clause '
        f'{_escape(finding.get("clause_number") or "-")} &middot; {detector}</font>'
    )
    parts = [
        Paragraph(head, style["body"]),
        Paragraph(_escape(finding.get("plain_summary")), style["body"]),
        Paragraph(_escape(finding.get("matched_quote")), style["quote"]),
        Paragraph(_escape(finding.get("why_it_matters")), style["body"]),
    ]
    for citation in finding.get("citations", []):
        parts.append(
            Paragraph(
                f'<font color="#1d4ed8"><b>{_escape(citation["act"])} '
                f'{_escape(citation["section_number"])}</b></font> &mdash; '
                f'{_escape(citation["note"])}',
                style["small"],
            )
        )
    parts.append(Spacer(1, 7))
    return parts


def build_report_pdf(review: Dict[str, Any], redlines: List[Dict[str, Any]] = None) -> bytes:
    style = _styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title="Contract Review", author="WhatLawSays",
    )

    story: List[Any] = [
        Paragraph("Contract Review", style["title"]),
        Paragraph(
            f'{_escape(review.get("contract_type", "UNKNOWN"))} &middot; reviewed for the '
            f'{_escape(str(review.get("position", "UNKNOWN")).replace("_", " ").lower())}'
            f' &middot; {len(review.get("findings", []))} findings',
            style["subtitle"],
        ),
        HRFlowable(width="100%", color=colors.HexColor("#e5e7eb")),
        Spacer(1, 8),
    ]

    counts = review.get("risk_counts", {})
    summary = [["Overall risk", "Findings", "Clauses analysed", "Confidence"],
               [review.get("overall_risk", "UNKNOWN"),
                str(len(review.get("findings", []))),
                f'{review.get("analysed_clause_count", 0)}/{review.get("clause_count", 0)}',
                f'{review.get("confidence_score", 0):.2f}']]
    table = Table(summary, colWidths=[42 * mm] * 4)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), BODY_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#6b7280")),
        ("FONTNAME", (0, 1), (-1, 1), BOLD_FONT),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.HexColor("#e5e7eb")),
    ]))
    story.append(table)
    if counts:
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            " &nbsp; ".join(
                f'<font color="{SEVERITY_COLOURS.get(s, colors.grey).hexval()}">'
                f'<b>{_escape(s)}</b>: {n}</font>'
                for s, n in counts.items()
            ),
            style["body"],
        ))

    if review.get("position_source") != "USER_DECLARED":
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "<b>No reviewing side was declared</b>, so severities here are unweighted. "
            "The same clause can be a serious risk to one party and routine to the other.",
            style["small"],
        ))

    # Redlines lead: what to ask for is the actionable part of the review.
    if redlines:
        story.append(Paragraph("What to ask for", style["h2"]))
        for redline in redlines:
            colour = SEVERITY_COLOURS.get(redline.get("severity"), colors.grey)
            block = [
                Paragraph(
                    f'<font color="{colour.hexval()}"><b>{_escape(redline.get("severity"))}</b></font>'
                    f'&nbsp;&nbsp;<b>{_escape(redline.get("title"))}</b>',
                    style["body"],
                ),
                Paragraph(_escape(redline.get("ask")), style["body"]),
            ]
            if redline.get("suggested_wording"):
                block.append(Paragraph(
                    "<b>Illustrative wording</b> (a starting point for the conversation, "
                    "to be reviewed by a lawyer):", style["small"]))
                block.append(Paragraph(_escape(redline["suggested_wording"]), style["quote"]))
            if redline.get("fallback"):
                block.append(Paragraph(
                    f'<b>If refused:</b> {_escape(redline["fallback"])}', style["small"]))
            block.append(Spacer(1, 8))
            story.append(KeepTogether(block))

    findings = review.get("findings", [])
    if findings:
        story.append(PageBreak())
        story.append(Paragraph("Findings", style["h2"]))
        story.append(Paragraph(
            "Every quote below was located in the document you uploaded. Anything that "
            "could not be located was discarded rather than shown.", style["small"]))
        story.append(Spacer(1, 6))
        for finding in findings:
            story.append(KeepTogether(_finding_block(finding, style)))

    missing = review.get("missing_clauses", [])
    if missing:
        story.append(Paragraph("Protections this contract does not contain", style["h2"]))
        for gap in missing:
            colour = SEVERITY_COLOURS.get(gap.get("severity"), colors.grey)
            story.append(KeepTogether([
                Paragraph(
                    f'<font color="{colour.hexval()}"><b>{_escape(gap.get("severity"))}</b></font>'
                    f'&nbsp;&nbsp;<b>{_escape(gap.get("title"))}</b>', style["body"]),
                Paragraph(_escape(gap.get("why_it_matters")), style["body"]),
                Spacer(1, 6),
            ]))

    issues = review.get("consistency_issues", [])
    if issues:
        story.append(Paragraph("Internal inconsistencies", style["h2"]))
        for issue in issues:
            story.append(Paragraph(
                f'<b>{_escape(issue.get("kind", "").replace("_", " ").title())}</b> &mdash; '
                f'{_escape(issue.get("description"))}', style["body"]))
            story.append(Spacer(1, 4))

    basis = review.get("confidence_basis") or {}
    if basis:
        story.append(Paragraph("How confident this review is, and why", style["h2"]))
        rows = [["Component", "Score"]] + [
            [name, f"{value:.2f}"] for name, value in basis.get("components", {}).items()
        ]
        component_table = Table(rows, colWidths=[60 * mm, 20 * mm])
        component_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), BODY_FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#6b7280")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.HexColor("#e5e7eb")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(component_table)
        for cap in basis.get("caps_applied", []):
            story.append(Paragraph(f"Cap applied: <b>{_escape(cap)}</b>", style["small"]))
        for note in basis.get("notes", []):
            story.append(Paragraph(_escape(note), style["small"]))
        story.append(Paragraph(
            "This is an estimate measured from the pipeline's own signals, not a "
            "calibrated probability. Nothing here is fitted against labelled reviews.",
            style["small"]))

    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#e5e7eb")))
    story.append(Paragraph(_escape(review.get("disclaimer", "")), style["small"]))

    document.build(story)
    return buffer.getvalue()
