"""UI components for the contract review page.

Reuses the card, badge and pill system from `components.inject_custom_css` so
the two pages read as one product, and adds only what contract review needs:
severity colouring, a clause table, and highlighted source text.
"""

import html
import json

import streamlit as st

SEVERITY_COLOURS = {
    "CRITICAL": ("#7f1d1d", "#fca5a5", "#ef4444"),
    "HIGH": ("#7c2d12", "#fdba74", "#f97316"),
    "MEDIUM": ("#78350f", "#fde047", "#eab308"),
    "LOW": ("#064e3b", "#6ee7b7", "#10b981"),
    "INFO": ("#1e3a8a", "#93c5fd", "#3b82f6"),
}

TIER_HELP = {
    "HOT": "Full analysis: statutory retrieval, plain-language pass and model review",
    "WARM": "Plain-language explanation only",
    "COLD": "Rule checks only -- no model analysis was spent on this clause",
}


def inject_contract_css():
    st.markdown(
        """
        <style>
        .sev-pill {
            display: inline-block; padding: 0.2rem 0.6rem; border-radius: 6px;
            font-size: 0.72rem; font-weight: 700; letter-spacing: 0.5px;
        }
        .finding-card {
            border-left: 4px solid var(--sev, #3b82f6);
            background-color: rgba(255,255,255,0.03);
            border-radius: 0 10px 10px 0; padding: 0.9rem 1.1rem; margin-bottom: 0.75rem;
        }
        .quote-box {
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.82rem; background-color: rgba(255,255,255,0.05);
            border-radius: 6px; padding: 0.6rem 0.8rem; margin: 0.5rem 0;
            white-space: pre-wrap; line-height: 1.5;
        }
        .cite-chip {
            display: inline-block; background-color: #1e3a8a; color: #bfdbfe;
            border: 1px solid #3b82f6; border-radius: 5px; padding: 0.12rem 0.5rem;
            font-size: 0.72rem; margin: 0.15rem 0.3rem 0.15rem 0;
        }
        .detector-chip {
            display: inline-block; border-radius: 5px; padding: 0.1rem 0.45rem;
            font-size: 0.68rem; letter-spacing: 0.4px; margin-left: 0.4rem;
        }
        .det-rule { background-color: #064e3b; color: #6ee7b7; border: 1px solid #10b981; }
        .det-llm  { background-color: #581c87; color: #e9d5ff; border: 1px solid #a855f7; }
        .doc-view {
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.78rem; line-height: 1.65; white-space: pre-wrap;
            background-color: rgba(255,255,255,0.02); border-radius: 10px;
            padding: 1rem; max-height: 640px; overflow-y: auto;
        }
        mark.hl { border-radius: 3px; padding: 0.05rem 0.15rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def severity_pill(severity: str) -> str:
    background, text, border = SEVERITY_COLOURS.get(severity, SEVERITY_COLOURS["INFO"])
    return (
        f'<span class="sev-pill" style="background:{background};color:{text};'
        f'border:1px solid {border};">{html.escape(severity)}</span>'
    )


def render_contract_header():
    st.markdown(
        """
        <div style="padding:1.1rem 0 0.4rem 0;">
          <h1 style="margin-bottom:0.2rem;">📄 Contract Review</h1>
          <p style="opacity:0.75;margin-top:0;">
            Upload a contract. Every finding quotes the document and, where the law
            decides the point, cites the provision that governs it.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_risk_summary(review: dict):
    """Headline risk, confidence and coverage."""
    counts = review.get("risk_counts", {})
    columns = st.columns(4)
    columns[0].metric("Overall risk", review.get("overall_risk", "UNKNOWN"))
    columns[1].metric("Findings", len(review.get("findings", [])))
    columns[2].metric(
        "Clauses analysed",
        f"{review.get('analysed_clause_count', 0)}/{review.get('clause_count', 0)}",
    )
    columns[3].metric("Confidence", f"{review.get('confidence_score', 0):.2f}")

    if counts:
        chips = " ".join(
            f"{severity_pill(severity)} <b>{count}</b>&nbsp;&nbsp;"
            for severity, count in counts.items()
        )
        st.markdown(f"<div style='margin:0.5rem 0 1rem 0;'>{chips}</div>", unsafe_allow_html=True)

    if review.get("position_source") == "USER_DECLARED":
        st.caption(
            f"Reviewed from the position of the **{review.get('position', '').replace('_', ' ').lower()}**. "
            "The same clause can be a serious risk to one side and routine to the other."
        )
    else:
        st.warning(
            "No side was declared, so severities are unweighted. Tell the review which "
            "party you are and the findings will be re-scored for you.",
            icon="⚠️",
        )

    for warning in review.get("extraction_warnings", []):
        st.warning(warning, icon="📄")
    if review.get("degraded_nodes"):
        st.info(
            "Some stages fell back to their rule-based engines, and confidence is "
            "capped accordingly: " + ", ".join(review["degraded_nodes"]),
            icon="🔌",
        )


def render_findings(review: dict):
    findings = review.get("findings", [])
    if not findings:
        st.success("No red flags were raised against this contract.", icon="✅")
        return

    for finding in findings:
        _, _, border = SEVERITY_COLOURS.get(finding["severity"], SEVERITY_COLOURS["INFO"])
        detector = finding.get("detector", "rule")
        detector_chip = (
            f'<span class="detector-chip det-{detector}">'
            f'{"RULE" if detector == "rule" else "MODEL"}</span>'
        )
        citations = "".join(
            f'<span class="cite-chip">{html.escape(c["act"])} {html.escape(c["section_number"])}</span>'
            for c in finding.get("citations", [])
        )
        st.markdown(
            f"""
            <div class="finding-card" style="--sev:{border};">
              <div>{severity_pill(finding['severity'])}{detector_chip}
                <b style="margin-left:0.5rem;">{html.escape(finding['title'])}</b>
                <span style="opacity:0.6;font-size:0.8rem;"> &mdash; clause {html.escape(str(finding.get('clause_number') or '-'))}</span>
              </div>
              <div style="margin-top:0.5rem;">{html.escape(finding['plain_summary'])}</div>
              <div class="quote-box">{html.escape(finding['matched_quote'])}</div>
              <div style="opacity:0.85;font-size:0.88rem;">{html.escape(finding['why_it_matters'])}</div>
              <div style="margin-top:0.5rem;">{citations}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        for citation in finding.get("citations", []):
            with st.expander(f"Why {citation['section_number']} applies", expanded=False):
                st.markdown(f"**{citation['act']} — {citation['section_number']}**")
                st.write(citation["note"])


def render_missing_clauses(review: dict):
    missing = review.get("missing_clauses", [])
    st.caption(
        "Absence is invisible to a clause-by-clause read, so these are checked "
        "against what a contract of this type should contain."
    )
    if not missing:
        st.success("Every protection on the checklist for this contract type is present.", icon="✅")
        return
    for gap in missing:
        st.markdown(
            f"""
            <div class="finding-card" style="--sev:{SEVERITY_COLOURS.get(gap['severity'], SEVERITY_COLOURS['INFO'])[2]};">
              <div>{severity_pill(gap['severity'])}
                <b style="margin-left:0.5rem;">{html.escape(gap['title'])}</b></div>
              <div style="margin-top:0.45rem;opacity:0.88;">{html.escape(gap['why_it_matters'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_consistency(review: dict):
    issues = review.get("consistency_issues", [])
    if not issues:
        st.success("No conflicting terms or broken references were found.", icon="✅")
        return
    for issue in issues:
        st.markdown(
            f"""
            <div class="finding-card" style="--sev:{SEVERITY_COLOURS.get(issue.get('severity','MEDIUM'), SEVERITY_COLOURS['INFO'])[2]};">
              <div>{severity_pill(issue.get('severity', 'MEDIUM'))}
                <b style="margin-left:0.5rem;">{html.escape(issue['kind'].replace('_', ' ').title())}</b></div>
              <div style="margin-top:0.45rem;">{html.escape(issue['description'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_clauses(review: dict):
    findings_by_clause = {}
    for finding in review.get("findings", []):
        findings_by_clause.setdefault(finding.get("clause_index"), []).append(finding)

    only_flagged = st.checkbox("Show only clauses with findings", value=False)

    for clause in review.get("clauses", []):
        clause_findings = findings_by_clause.get(clause["index"], [])
        if only_flagged and not clause_findings:
            continue

        worst = max(
            (f["severity"] for f in clause_findings),
            key=lambda s: list(SEVERITY_COLOURS).index(s) * -1,
            default=None,
        )
        label = f"Clause {clause.get('number') or clause['index']}"
        if clause.get("heading"):
            label += f" — {clause['heading']}"
        if worst:
            label += f"  [{worst}]"

        with st.expander(label, expanded=bool(clause_findings) and not only_flagged):
            st.caption(
                f"{clause['category'].replace('_', ' ').title()} · {clause['tier']} · "
                f"{TIER_HELP.get(clause['tier'], '')}"
            )
            if clause.get("plain_english"):
                st.markdown(f"**In plain words:** {clause['plain_english']}")
            if clause.get("obligations"):
                st.markdown("**What you must do:**")
                for item in clause["obligations"]:
                    st.markdown(f"- {item}")
            if clause.get("watch_outs"):
                st.markdown("**Watch out for:**")
                for item in clause["watch_outs"]:
                    st.markdown(f"- {item}")
            for finding in clause_findings:
                st.markdown(
                    f"{severity_pill(finding['severity'])} **{html.escape(finding['title'])}**",
                    unsafe_allow_html=True,
                )
            with st.expander("Original text", expanded=False):
                st.markdown(
                    f'<div class="quote-box">{html.escape(clause["text"])}</div>',
                    unsafe_allow_html=True,
                )


def render_document_view(review: dict, document_text: str):
    """The contract with every finding highlighted in place.

    Offsets come straight from the review, which is what makes this possible at
    all: every finding records where in this exact text it came from.
    """
    if not document_text:
        st.info("The source text is not available for this review.")
        return

    spans = sorted(
        (
            (f["match_start"], f["match_end"], f["severity"], f["title"])
            for f in review.get("findings", [])
            if f.get("match_end", 0) > f.get("match_start", 0)
        ),
        key=lambda s: s[0],
    )

    pieces, cursor, drawn = [], 0, 0
    for start, end, severity, title in spans:
        if start < cursor:
            continue  # overlapping finding; the first one already marks this text
        drawn += 1
        background, text_colour, _ = SEVERITY_COLOURS.get(severity, SEVERITY_COLOURS["INFO"])
        pieces.append(html.escape(document_text[cursor:start]))
        pieces.append(
            f'<mark class="hl" style="background:{background};color:{text_colour};" '
            f'title="{html.escape(title)}">{html.escape(document_text[start:end])}</mark>'
        )
        cursor = end
    pieces.append(html.escape(document_text[cursor:]))

    st.caption(f"{drawn} highlighted passage(s). Hover a highlight to see the finding.")
    st.markdown(f'<div class="doc-view">{"".join(pieces)}</div>', unsafe_allow_html=True)


def render_confidence_basis(review: dict):
    basis = review.get("confidence_basis") or {}
    if not basis:
        return
    st.metric("Confidence", f"{basis.get('score', 0):.2f}")
    st.caption(
        "An estimate measured from the pipeline's own signals, not a calibrated "
        "probability. Nothing here is fitted against labelled reviews."
    )
    components = basis.get("components", {})
    if components:
        st.markdown("**Components**")
        for name, value in components.items():
            st.progress(min(1.0, max(0.0, float(value))), text=f"{name} — {value:.2f}")
    if basis.get("caps_applied"):
        st.markdown("**Caps applied**")
        for cap in basis["caps_applied"]:
            st.markdown(f"- `{cap}`")
    for note in basis.get("notes", []):
        st.caption(note)
    if basis.get("detail"):
        st.markdown("**Detail**")
        st.json(basis["detail"])


def render_review_json(review: dict):
    st.download_button(
        "Download review as JSON",
        data=json.dumps(review, indent=2),
        file_name=f"contract-review-{review.get('contract_id', 'result')}.json",
        mime="application/json",
    )
    st.json(review)


def render_redlines(review: dict):
    """What to ask for, worst first."""
    redlines = review.get("redlines", [])
    st.caption(
        "Negotiation asks, not drafting to paste unread. The wording is a starting "
        "point for the conversation, to be reviewed by a lawyer."
    )
    if not redlines:
        st.success("Nothing here needs renegotiating.", icon="✅")
        return
    for redline in redlines:
        _, _, border = SEVERITY_COLOURS.get(redline["severity"], SEVERITY_COLOURS["INFO"])
        st.markdown(
            f"""
            <div class="finding-card" style="--sev:{border};">
              <div>{severity_pill(redline['severity'])}
                <b style="margin-left:0.5rem;">{html.escape(redline['title'])}</b>
                <span style="opacity:0.6;font-size:0.8rem;"> &mdash; clause {html.escape(str(redline.get('clause_number') or '-'))}</span>
              </div>
              <div style="margin-top:0.55rem;"><b>Ask:</b> {html.escape(redline['ask'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if redline.get("suggested_wording"):
            with st.expander("Illustrative wording", expanded=False):
                st.markdown(
                    f'<div class="quote-box">{html.escape(redline["suggested_wording"])}</div>',
                    unsafe_allow_html=True,
                )
        if redline.get("fallback"):
            st.caption(f"**If refused:** {redline['fallback']}")


def render_qa(review: dict, ask):
    """Question box over the reviewed contract.

    `ask(question) -> dict` is supplied by the page so the same component works
    against the API and in direct mode.
    """
    st.caption(
        "Answered only from the clauses in your document, and it tells you which. "
        "A question the contract does not address is told so."
    )
    if "qa_history" not in st.session_state:
        st.session_state["qa_history"] = []

    for turn in st.session_state["qa_history"]:
        with st.chat_message("user"):
            st.write(turn["question"])
        with st.chat_message("assistant"):
            if not turn.get("answered_from_contract", True):
                st.warning("The contract does not appear to address this.", icon="🕳️")
            st.write(turn["answer"])
            for clause in turn.get("cited_clauses", []):
                label = f"Clause {clause.get('number') or clause['index']}"
                if clause.get("heading"):
                    label += f" — {clause['heading']}"
                with st.expander(label, expanded=False):
                    st.markdown(
                        f'<div class="quote-box">{html.escape(clause["text"])}</div>',
                        unsafe_allow_html=True,
                    )
            if turn.get("statutory_context"):
                st.markdown(
                    "".join(
                        f'<span class="cite-chip">{html.escape(c["act"])} {html.escape(c["section_number"])}</span>'
                        for c in turn["statutory_context"]
                    ),
                    unsafe_allow_html=True,
                )
            if turn.get("degraded"):
                st.caption("Answered by the rule-based engine; the model was unavailable.")

    question = st.chat_input("Ask about this contract, e.g. 'What is my notice period?'")
    if question:
        with st.spinner("Reading the contract..."):
            try:
                result = ask(question)
                st.session_state["qa_history"].append({"question": question, **result})
                st.rerun()
            except Exception as e:
                st.error(str(e))
