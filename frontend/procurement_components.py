"""UI components for the procurement pages.

Reuses the card, chip and severity system from `contract_components` so the
three workbenches read as one product. What it adds is the vocabulary this
domain needs and the other two do not: a status chip that can say UNDETERMINED,
an evidence renderer for structured field reads, and a layout that keeps
breaches, indicators and gaps visually apart.

That separation is the whole design here. A reader scanning one list will read a
gap as a pass and an indicator as a finding, and both misreadings are worse than
useless in a compliance report -- so they never share a list.
"""

import html
import json

import streamlit as st

from frontend.contract_components import SEVERITY_COLOURS, severity_pill

# Status carries its own colour, independent of severity. A CRITICAL check that
# could not be run is not a critical finding, and colouring it like one would
# make the page lie at a glance.
STATUS_COLOURS = {
    "BREACH": ("#7f1d1d", "#fca5a5", "#ef4444"),
    "INDICATOR": ("#4c1d95", "#c4b5fd", "#8b5cf6"),
    "UNDETERMINED": ("#374151", "#d1d5db", "#9ca3af"),
    "PASS": ("#064e3b", "#6ee7b7", "#10b981"),
    "NOT_APPLICABLE": ("#1f2937", "#9ca3af", "#4b5563"),
    "NOT_EVALUATED": ("#1f2937", "#9ca3af", "#4b5563"),
}

STATUS_HELP = {
    "BREACH": "The data shows this requirement was not met",
    "INDICATOR": "A pattern worth asking about. Not a finding that anyone acted improperly",
    "UNDETERMINED": "This check could not be performed. It has NOT passed",
    "PASS": "Checked, and the requirement was met",
    "NOT_APPLICABLE": "This requirement does not apply to this award",
    "NOT_EVALUATED": "No ratified rule enabled this check",
}

OVERALL_LABELS = {
    "BREACHES_FOUND": ("Breaches found", "#ef4444"),
    "INDICATORS_ONLY": ("Patterns to ask about", "#8b5cf6"),
    "NO_BREACH_FOUND_WITH_GAPS": ("No breach found, but gaps remain", "#eab308"),
    "NO_BREACH_FOUND": ("No breach found", "#10b981"),
}


def inject_procurement_css():
    st.markdown(
        """
        <style>
          .status-chip {
            display:inline-block; padding:0.1rem 0.5rem; border-radius:6px;
            font-size:0.68rem; font-weight:700; letter-spacing:0.4px;
            text-transform:uppercase;
          }
          .proc-card {
            background: rgba(255,255,255,0.03);
            border:1px solid rgba(255,255,255,0.08);
            border-left:4px solid var(--sev, #3b82f6);
            border-radius:10px; padding:0.9rem 1rem; margin-bottom:0.75rem;
          }
          .evidence-box {
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size:0.78rem; line-height:1.5;
            background: rgba(255,255,255,0.04);
            border-radius:6px; padding:0.45rem 0.6rem; margin:0.35rem 0;
            color:#cbd5e1;
          }
          .resolve-box {
            border-left:3px solid #eab308; padding-left:0.65rem;
            font-size:0.85rem; color:#fde047; margin-top:0.5rem;
          }
          .gap-banner {
            background: rgba(234,179,8,0.08); border:1px solid rgba(234,179,8,0.3);
            border-radius:8px; padding:0.7rem 0.9rem; font-size:0.9rem;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_chip(status: str) -> str:
    background, text, border = STATUS_COLOURS.get(status, STATUS_COLOURS["NOT_EVALUATED"])
    return (
        f'<span class="status-chip" style="background:{background};color:{text};'
        f'border:1px solid {border};">{html.escape(status.replace("_", " "))}</span>'
    )


def _evidence_line(evidence: dict) -> str:
    kind = evidence.get("kind")
    if kind == "DOCUMENT_SPAN":
        return f'&ldquo;{html.escape(evidence.get("quote", ""))}&rdquo;'
    if kind == "FIELD":
        shown = evidence.get("observed_display") or evidence.get("observed")
        line = f'<b>{html.escape(evidence.get("field_path", ""))}</b> = {html.escape(str(shown))}'
        if evidence.get("required") is not None:
            line += (
                f' &nbsp;<span style="opacity:0.65">(required: '
                f'{html.escape(str(evidence.get("comparator")))} '
                f'{html.escape(str(evidence.get("required")))})</span>'
            )
        if evidence.get("note"):
            line += f' &mdash; <span style="opacity:0.7">{html.escape(evidence["note"])}</span>'
        return line
    if kind == "ABSENCE":
        complete = evidence.get("scope_declared_complete")
        return (
            f'<b>{html.escape(evidence.get("field_path", ""))}</b> is absent from '
            f'{html.escape(evidence.get("scope_path", ""))}'
            + (" (a complete record)" if complete else " (not supplied)")
        )
    if kind == "DERIVED":
        line = (
            f'<b>{html.escape(evidence.get("computation", ""))}</b> = '
            f'{html.escape(str(evidence.get("value")))}'
        )
        if evidence.get("note"):
            line += f' &mdash; <span style="opacity:0.7">{html.escape(evidence["note"])}</span>'
        return line
    return html.escape(str(evidence))


def render_finding_card(finding: dict, show_resolution: bool = False):
    _, _, border = SEVERITY_COLOURS.get(finding.get("severity"), SEVERITY_COLOURS["INFO"])
    source = finding.get("source", "STATUTE")
    subject = finding.get("subject_ref")
    provisional = (
        '<span class="status-chip" style="background:#78350f;color:#fde047;'
        'border:1px solid #eab308;margin-left:0.3rem;">PROVISIONAL</span>'
        if finding.get("provisional") else ""
    )
    citations = "".join(
        f'<span class="cite-chip">{html.escape(c["act"].split("(")[-1].rstrip(")"))} '
        f'{html.escape(c["section_number"])}</span>'
        for c in finding.get("citations", [])
    )
    evidence = "".join(
        f'<div class="evidence-box">{_evidence_line(e)}</div>'
        for e in finding.get("evidence", [])[:4]
    )
    resolution = ""
    if show_resolution and finding.get("what_would_resolve_it"):
        resolution = (
            f'<div class="resolve-box"><b>To resolve:</b> '
            f'{html.escape(finding["what_would_resolve_it"])}</div>'
        )
    corroborating = "".join(
        f'<div style="opacity:0.75;font-size:0.82rem;">&bull; {html.escape(s)}</div>'
        for s in finding.get("corroborating_signals", [])
    )

    st.markdown(
        f"""
        <div class="proc-card" style="--sev:{border};">
          <div>{severity_pill(finding.get("severity", "INFO"))}
            {status_chip(finding.get("status", ""))}{provisional}
            <b style="margin-left:0.5rem;">{html.escape(finding.get("title", ""))}</b>
            <span style="opacity:0.55;font-size:0.78rem;"> &mdash; {html.escape(source)}
            {(" &middot; " + html.escape(str(subject))) if subject else ""}</span>
          </div>
          <div style="margin-top:0.5rem;">{html.escape(finding.get("plain_summary", ""))}</div>
          {evidence}
          <div style="opacity:0.85;font-size:0.88rem;margin-top:0.4rem;">
            {html.escape(finding.get("why_it_matters", ""))}
          </div>
          {corroborating}
          {resolution}
          <div style="margin-top:0.5rem;">{citations}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for citation in finding.get("citations", []):
        with st.expander(f"Why {citation['section_number']} applies", expanded=False):
            st.markdown(f"**{citation['act']} — {citation['section_number']}**")
            st.write(citation["note"])


def render_summary(review: dict):
    overall = review.get("overall_status", "UNKNOWN")
    label, colour = OVERALL_LABELS.get(overall, (overall.replace("_", " ").title(), "#9ca3af"))

    columns = st.columns(4)
    columns[0].metric("Outcome", label)
    columns[1].metric("Breaches", len(review.get("findings", [])))
    columns[2].metric("Could not check", len(review.get("undetermined_checks", [])))
    columns[3].metric("Confidence", f'{review.get("confidence_score", 0):.2f}')

    counts = review.get("risk_counts", {})
    if counts:
        st.markdown(
            " ".join(
                f'{severity_pill(s)}<span style="opacity:0.7;font-size:0.8rem;"> '
                f'&times;{n}</span>'
                for s, n in counts.items()
            ),
            unsafe_allow_html=True,
        )

    gaps = review.get("undetermined_checks", [])
    if gaps:
        st.markdown(
            f'<div class="gap-banner"><b>{len(gaps)} check(s) could not be performed.</b> '
            "They have not passed &mdash; they were not run. Each one names what would let "
            "it run, under <i>Could Not Be Checked</i>.</div>",
            unsafe_allow_html=True,
        )

    if review.get("dropped_findings"):
        st.warning(
            f'{len(review["dropped_findings"])} finding(s) were dropped because their '
            "evidence could not be re-derived from the event data. They are named in the "
            "raw JSON, and they still cost confidence.",
            icon="⚠️",
        )
    for node in review.get("degraded_nodes", []):
        st.info(node, icon="ℹ️")


def render_indicators(indicators: list):
    if not indicators:
        st.success("No bid-integrity patterns were found in this event.", icon="✅")
        return
    st.warning(
        "These are patterns in the bid data. They are **not** findings that anyone acted "
        "improperly, and they name real companies — treat them as questions to ask before "
        "the award is released, not as conclusions.",
        icon="🔍",
    )
    for indicator in indicators:
        render_finding_card(indicator)


def render_gaps(gaps: list):
    if not gaps:
        st.success("Every applicable check could be performed.", icon="✅")
        return
    st.info(
        "These checks were not performed, for want of data. A gap is not a pass. "
        "Each one names exactly what would let it run.",
        icon="🕳️",
    )
    for gap in gaps:
        render_finding_card(gap, show_resolution=True)


def render_checks_table(checks: list):
    """Every check and its outcome, so silence is legible.

    Without this a reader cannot tell a review that looked and found nothing from
    one where the check never ran -- the same reason the contract page shows COLD
    clauses rather than hiding them.
    """
    if not checks:
        st.caption("No checks were run.")
        return
    by_status: dict = {}
    for check in checks:
        by_status.setdefault(check["status"], []).append(check)

    for status in ["BREACH", "INDICATOR", "UNDETERMINED", "PASS", "NOT_APPLICABLE",
                   "NOT_EVALUATED"]:
        rows = by_status.get(status)
        if not rows:
            continue
        st.markdown(
            f'{status_chip(status)} <span style="opacity:0.7;font-size:0.8rem;">'
            f'{len(rows)} &mdash; {html.escape(STATUS_HELP.get(status, ""))}</span>',
            unsafe_allow_html=True,
        )
        for row in rows:
            st.markdown(
                f'<div style="opacity:0.8;font-size:0.84rem;padding-left:0.8rem;">'
                f'{html.escape(row["check_id"])}'
                f'{(" &middot; " + html.escape(str(row["subject_ref"]))) if row.get("subject_ref") else ""}'
                f'</div>',
                unsafe_allow_html=True,
            )
        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)


def render_remediations(remediations: list):
    if not remediations:
        st.success("Nothing to act on before this order goes out.", icon="✅")
        return
    for item in remediations:
        _, _, border = SEVERITY_COLOURS.get(item.get("severity"), SEVERITY_COLOURS["INFO"])
        st.markdown(
            f"""
            <div class="proc-card" style="--sev:{border};">
              <div>{severity_pill(item.get("severity", "INFO"))}
                {status_chip(item.get("status", ""))}
                <b style="margin-left:0.5rem;">{html.escape(item.get("title", ""))}</b>
              </div>
              <div style="margin-top:0.5rem;">{html.escape(item.get("action", ""))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if item.get("what_good_looks_like"):
            with st.expander("What good looks like", expanded=False):
                st.markdown(
                    f'<div class="evidence-box">{html.escape(item["what_good_looks_like"])}</div>',
                    unsafe_allow_html=True,
                )
        if item.get("if_refused"):
            st.caption(f"If that is refused: {item['if_refused']}")


def render_confidence(review: dict):
    basis = review.get("confidence_basis") or {}
    if not basis:
        st.caption("No confidence basis was recorded.")
        return
    st.metric("Confidence", f'{basis.get("score", 0):.2f}')
    for name, value in (basis.get("components") or {}).items():
        st.markdown(f"**{name.replace('_', ' ').title()}** — {value:.2f}")
        st.progress(min(1.0, max(0.0, float(value))))
    for cap in basis.get("caps_applied", []):
        st.warning(f"Cap applied: `{cap}`", icon="🚧")
    for note in basis.get("notes", []):
        st.caption(note)
    st.caption(
        "This is an estimate measured from the pipeline's own signals, not a calibrated "
        "probability. Nothing here is fitted against labelled reviews."
    )
    with st.expander("Full basis", expanded=False):
        st.json(basis.get("detail", {}))


def render_raw(review: dict, name: str = "award-review"):
    st.download_button(
        "⬇️ Download the full review as JSON",
        data=json.dumps(review, indent=2),
        file_name=f"{name}.json",
        mime="application/json",
    )
    st.json(review)
