"""
UI Component renderers and custom CSS for WhatLawSays Streamlit frontend.
Designed for high visual polish, readability, and legal clarity.
"""

import json
import streamlit as st


def inject_custom_css():
    """Inject modern CSS styles for cards, badges, gauges, and high-contrast legal typography."""
    st.markdown(
        """
        <style>
        /* Modern Container Cards */
        .wls-card {
            background-color: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            padding: 1.25rem;
            margin-bottom: 1rem;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
        }
        
        /* Stat Badges */
        .wls-badge {
            display: inline-block;
            padding: 0.25rem 0.6rem;
            font-size: 0.75rem;
            font-weight: 600;
            border-radius: 6px;
            margin-right: 0.4rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .badge-bns { background-color: #1e3a8a; color: #93c5fd; border: 1px solid #3b82f6; }
        .badge-bnss { background-color: #064e3b; color: #6ee7b7; border: 1px solid #10b981; }
        .badge-bss { background-color: #701a75; color: #f0abfc; border: 1px solid #c084fc; }
        .badge-agent { background-color: #7c2d12; color: #fdba74; border: 1px solid #f97316; }
        
        /* Status Banner Pills */
        .status-pill {
            display: inline-block;
            padding: 0.4rem 1rem;
            border-radius: 20px;
            font-weight: 700;
            font-size: 0.9rem;
            letter-spacing: 0.5px;
        }
        .status-undetermined { background-color: #451a03; color: #fbbf24; border: 1px solid #d97706; }
        .status-established { background-color: #064e3b; color: #34d399; border: 1px solid #059669; }
        .status-exonerated { background-color: #172554; color: #60a5fa; border: 1px solid #2563eb; }
        
        /* Urgency Badges */
        .urgency-high { background-color: #7f1d1d; color: #fca5a5; border: 1px solid #ef4444; }
        .urgency-medium { background-color: #78350f; color: #fde047; border: 1px solid #eab308; }
        .urgency-low { background-color: #064e3b; color: #6ee7b7; border: 1px solid #10b981; }
        
        /* Fact Lists */
        .fact-box-established {
            border-left: 4px solid #10b981;
            background-color: rgba(16, 185, 129, 0.05);
            padding: 0.75rem 1rem;
            border-radius: 0 8px 8px 0;
            margin-bottom: 0.5rem;
        }
        .fact-box-allegation {
            border-left: 4px solid #f59e0b;
            background-color: rgba(245, 158, 11, 0.05);
            padding: 0.75rem 1rem;
            border-radius: 0 8px 8px 0;
            margin-bottom: 0.5rem;
        }
        .fact-box-unknown {
            border-left: 4px solid #3b82f6;
            background-color: rgba(59, 130, 246, 0.05);
            padding: 0.75rem 1rem;
            border-radius: 0 8px 8px 0;
            margin-bottom: 0.5rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header():
    """Render main application header banner with title and statutory tags."""
    st.markdown(
        """
        <div style="text-align: center; margin-bottom: 1.5rem;">
            <h1 style="font-weight: 800; font-size: 2.4rem; margin-bottom: 0.3rem;">
                ⚖️ WhatLawSays
            </h1>
            <p style="font-size: 1.1rem; color: #94a3b8; margin-bottom: 0.8rem;">
                Source-Grounded Multi-Agent Legal Reasoning & System Architecture Engine
            </p>
            <div>
                <span class="wls-badge badge-bns">BNS 2023</span>
                <span class="wls-badge badge-bnss">BNSS 2023</span>
                <span class="wls-badge badge-bss">BSS 2023</span>
                <span class="wls-badge badge-agent">LangGraph Orchestrated</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_executive_summary(data: dict):
    """Render executive summary banner with status pill and confidence progress bar."""
    status = data.get("status", "UNDETERMINED").upper()
    offense_status = (data.get("offense_status") or "").upper()
    confidence = data.get("confidence_score", 0.0) or 0.0
    basis = data.get("confidence_basis") or {}
    domain = data.get("scenario_domain", "GENERAL_LEGAL")
    reason = data.get("reason", "No detailed reasoning provided.")

    # A confident "no offence is made out" is a SUCCESS status, but showing it with
    # the scales icon would read as though an offence had been established.
    if offense_status == "NOT_ESTABLISHED":
        pill_label = "NO OFFENCE ESTABLISHED"
        status_class = "status-exonerated"
        status_icon = "🛡️"
    elif status == "UNDETERMINED":
        pill_label = status
        status_class = "status-undetermined"
        status_icon = "⚠️"
    elif "EXONERAT" in status or status == "NO_OFFENSE":
        pill_label = status
        status_class = "status-exonerated"
        status_icon = "🛡️"
    else:
        pill_label = status
        status_class = "status-established"
        status_icon = "⚖️"

    col1, col2 = st.columns([1, 2])

    with col1:
        st.markdown(
            f"""
            <div class="wls-card" style="text-align: center;">
                <div style="font-size: 0.85rem; color: #94a3b8; text-transform: uppercase;">Legal Evaluation State</div>
                <div style="margin: 0.8rem 0;">
                    <span class="status-pill {status_class}">
                        {status_icon} {pill_label}
                    </span>
                </div>
                <div style="font-size: 0.8rem; color: #cbd5e1;">Domain: <code>{domain}</code></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown("<div class=\"wls-card\">", unsafe_allow_html=True)
        st.markdown(f"**Confidence Estimate**: `{confidence:.2f} / 1.00`")
        st.progress(confidence, text=f"Confidence Level: {int(confidence * 100)}%")
        st.markdown(f"**Reasoning Summary**: {reason}")
        st.markdown("</div>", unsafe_allow_html=True)

        _render_confidence_basis(basis)


COMPONENT_LABELS = {
    "offense_support": "Offence support (elements × grounding)",
    "retrieval": "Retrieval relevance",
    "verification": "Verification outcome",
    "fact_completeness": "Fact completeness",
    "exclusion_evidence": "Exclusion evidence",
}


def _render_confidence_basis(basis: dict):
    """Show what the confidence estimate was actually computed from."""
    if not basis:
        return

    components = basis.get("components") or {}
    caps = basis.get("caps_applied") or []
    notes = basis.get("notes") or []
    per_offense = basis.get("offenses") or []

    if caps:
        st.warning(
            "Confidence capped because a pipeline stage degraded: "
            + ", ".join(caps),
            icon="⚠️",
        )

    with st.expander("How this confidence was calculated"):
        if components:
            st.markdown("##### Components")
            for key, value in components.items():
                label = COMPONENT_LABELS.get(key, key.replace("_", " ").title())
                st.markdown(f"- **{label}**: `{value:.3f}`")

        if per_offense:
            st.markdown("##### Per-offence")
            for off in per_offense:
                st.markdown(
                    f"- **{off.get('act_name', '')} {off.get('section_number', '')}** — "
                    f"score `{off.get('score', 0):.3f}` "
                    f"(elements `{off.get('element_support', 0):.2f}`, "
                    f"grounding `{off.get('grounding', 0):.2f}`)"
                )

        for note in notes:
            st.caption(note)


def render_fact_matrix(facts: dict):
    """Render factual matrix separating Established Facts, Allegations, and Unknowns."""
    if not facts:
        st.info("No structured fact extraction available.")
        return

    established = facts.get("established_facts", []) or facts.get("explicit_facts", [])
    allegations = facts.get("user_allegations", [])
    unknowns = facts.get("unknown_facts", [])
    actor = facts.get("actor", "N/A")
    action = facts.get("action", "N/A")

    st.markdown(f"**Core Actor**: `{actor}` &nbsp;|&nbsp; **Primary Action**: `{action}`")
    st.divider()

    c1, c2, c3 = st.columns(3)

    with c1:
        st.subheader("📌 Established Facts")
        st.caption("Objective, undisputed factual assertions.")
        if established:
            for item in established:
                st.markdown(
                    f'<div class="fact-box-established">✔️ {item}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.write("None recorded.")

    with c2:
        st.subheader("💬 User Allegations")
        st.caption("Subjective allegations requiring verification.")
        if allegations:
            for item in allegations:
                st.markdown(
                    f'<div class="fact-box-allegation">❓ {item}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.write("No unverified allegations.")

    with c3:
        st.subheader("❓ Indeterminate Unknowns")
        st.caption("Enforces rule: UNKNOWN ≠ FALSE.")
        if unknowns:
            for item in unknowns:
                st.markdown(
                    f'<div class="fact-box-unknown">🔍 {item}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.write("No critical unknown variables.")


def render_offenses_tab(data: dict):
    """Render list of identified offenses, statutory elements, and applied defences."""
    offenses = data.get("identified_offenses", [])
    defences = data.get("applied_defences", [])

    if defences:
        st.success("🛡️ **Statutory Defences & Exemptions Applied**")
        for d in defences:
            if isinstance(d, dict):
                st.markdown(f"- **{d.get('defence_name', 'Defence')}** ({d.get('statutory_provision', 'BNS')}): {d.get('reasoning', '')}")
            else:
                st.markdown(f"- {d}")
        st.divider()

    if not offenses:
        st.info("ℹ️ No specific statutory offenses were conclusively established based on supplied facts.")
        return

    st.subheader("⚖️ Identified Statutory Offenses (BNS 2023)")

    for idx, off in enumerate(offenses, 1):
        section = off.get("section_number", "BNS Section")
        title = off.get("offense_name", "Statutory Offense")
        cog = off.get("cognizability", "N/A")
        bail = off.get("bailability", "N/A")
        severity = off.get("severity", "N/A")
        reasoning = off.get("legal_reasoning", "")
        # element_audits is the actual schema field; the previous matched_elements /
        # missing_elements keys never existed on the payload, so both element
        # sections silently rendered empty on every response.
        audits = off.get("element_audits", []) or []
        matched_elms = [
            a.get("element_name", "")
            for a in audits
            if str(a.get("status", "")).upper() == "SUPPORTED"
        ]
        missing_elms = [
            f"{a.get('element_name', '')} ({a.get('status', '')})"
            for a in audits
            if str(a.get("status", "")).upper() in ("UNPROVEN", "CONTRADICTED_BY_FACT")
        ]

        with st.expander(f"**{idx}. {title}** ({section})", expanded=(idx == 1)):
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Cognizability", cog)
            col_b.metric("Bailability", bail)
            col_c.metric("Punishment Severity", severity)

            st.markdown(f"**Legal Reasoning**: {reasoning}")

            if matched_elms:
                st.markdown("##### Matched Statutory Elements")
                for me in matched_elms:
                    st.markdown(f"- ✅ `{me}`")

            if missing_elms:
                st.markdown("##### Missing / Contradicted Elements")
                for me in missing_elms:
                    st.markdown(f"- ❌ `{me}`")


def render_procedural_tab(data: dict):
    """Render procedural provisions under BNSS 2023 & evidentiary standards under BSS 2023."""
    provisions = data.get("procedural_provisions", [])

    st.subheader("📋 Procedural & Evidentiary Guidance")
    st.caption("Mapped under Bharatiya Nagarik Suraksha Sanhita (BNSS) & Bharatiya Sakshya Adhiniyam (BSS)")

    if provisions:
        for prov in provisions:
            st.markdown(f'<div class="wls-card">📖 <strong>{prov}</strong></div>', unsafe_allow_html=True)
    else:
        st.info("No explicit procedural classifications specified.")


def render_actions_and_duties_tab(data: dict):
    """Render Immediate Action Steps, Citizen Duties, and Clarification Questions."""
    actions = data.get("immediate_action_steps", [])
    duties = data.get("citizen_duties", [])
    questions = data.get("clarification_questions", [])

    c1, c2 = st.columns(2)

    with c1:
        st.subheader("🚨 Immediate Citizen Action Steps")
        if actions:
            for act in actions:
                urgency = act.get("urgency", "MEDIUM").upper()
                u_class = f"urgency-{urgency.lower()}"
                title = act.get("title", "Action Step")
                details = act.get("action_details", "")
                stat_ref = act.get("statutory_duty_reference")

                st.markdown(
                    f"""
                    <div class="wls-card">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <strong>{title}</strong>
                            <span class="wls-badge {u_class}">{urgency} URGENCY</span>
                        </div>
                        <p style="font-size: 0.9rem; margin-top: 0.5rem;">{details}</p>
                        {f'<small style="color: #94a3b8;">Ref: {stat_ref}</small>' if stat_ref else ''}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.write("No urgent action steps required.")

    with c2:
        st.subheader("⚖️ Citizen Statutory Duties")
        if duties:
            for duty in duties:
                st.markdown(f'<div class="wls-card">📜 {duty}</div>', unsafe_allow_html=True)
        else:
            st.write("No specific mandatory statutory duties triggered.")

        if questions:
            st.subheader("❓ Clarification Questions Needed")
            st.caption("Facts required to resolve undetermined state:")
            for q in questions:
                st.markdown(f"- ❓ {q}")


def render_raw_json(data: dict):
    """Render formatted raw JSON response with download option."""
    st.subheader("💾 Raw API JSON Payload")
    json_str = json.dumps(data, indent=2)
    st.code(json_str, language="json")
    st.download_button(
        label="📥 Download Legal Analysis JSON",
        data=json_str,
        file_name="whatlawsays_legal_analysis.json",
        mime="application/json",
    )
