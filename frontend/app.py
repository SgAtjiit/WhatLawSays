"""
WhatLawSays - Streamlit Interactive Frontend Application
Source-Grounded Multi-Agent Legal Reasoning Workbench
"""

import sys
import os
import asyncio
import httpx
import streamlit as st

# Add workspace root to Python path for direct agent imports if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from frontend.sample_scenarios import SAMPLE_SCENARIOS
from frontend.components import (
    inject_custom_css,
    render_header,
    render_executive_summary,
    render_fact_matrix,
    render_offenses_tab,
    render_procedural_tab,
    render_actions_and_duties_tab,
    render_raw_json,
)

# Set Streamlit Page Configuration
st.set_page_config(
    page_title="WhatLawSays - Legal Reasoning Engine",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject Custom CSS
inject_custom_css()


def check_backend_health(url: str) -> bool:
    """Check if the FastAPI backend server is reachable and healthy."""
    try:
        health_url = f"{url.rstrip('/')}/health"
        res = httpx.get(health_url, timeout=3.0)
        return res.status_code == 200 and res.json().get("status") == "healthy"
    except Exception:
        return False


def run_api_analysis(backend_url: str, scenario_text: str, jurisdiction: str) -> dict:
    """Send scenario analysis request to FastAPI backend endpoint."""
    endpoint = f"{backend_url.rstrip('/')}/api/v1/analyze"
    payload = {
        "scenario_text": scenario_text,
        "jurisdiction": jurisdiction,
    }
    response = httpx.post(endpoint, json=payload, timeout=120.0)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(
            f"API returned status {response.status_code}: {response.text}"
        )


async def run_direct_agent_analysis(scenario_text: str, jurisdiction: str) -> dict:
    """Fallback direct Python execution calling LangGraph agent app directly."""
    from src.agents.graph import legal_agent_app
    import uuid

    task_id = str(uuid.uuid4())[:8]
    initial_state = {
        "task_id": task_id,
        "scenario_text": scenario_text,
        "jurisdiction": jurisdiction,
        "extracted_facts": None,
        "candidate_chunks": [],
        "retrieved_chunks": [],
        "candidate_procedural_chunks": [],
        "procedural_chunks": [],
        "draft_offenses": [],
        "verification_passed": False,
        "verification_feedback": None,
        "retry_count": 0,
        "llm_available": True,
        "reranker_available": True,
        "confidence_score": None,
        "confidence_basis": None,
        "final_response": None,
    }
    final_state = await legal_agent_app.ainvoke(initial_state)
    return final_state.get("final_response", {})


# --- SIDEBAR CONFIGURATION ---
with st.sidebar:
    st.image(
        "https://img.icons8.com/color/96/scales.png",
        width=64,
    )
    st.title("System Control Panel")

    backend_url = st.text_input(
        "FastAPI Backend URL",
        value="http://localhost:8000",
        help="URL of the running FastAPI server",
    )

    # Health Check Button / Pill
    is_online = check_backend_health(backend_url)
    if is_online:
        st.success("🟢 Backend API Connected")
    else:
        st.warning("🔴 Backend Offline (Direct Mode Available)")

    execution_mode = st.radio(
        "Execution Orchestrator",
        options=["FastAPI Gateway (HTTP)", "Direct LangGraph (Python)"],
        index=0 if is_online else 1,
        help="FastAPI Gateway handles rate-limiting and tasks queue; Direct Mode invokes the agent graph directly in memory.",
    )

    st.divider()

    st.subheader("📚 Statutory Corpus")
    st.markdown(
        """
        - **BNS 2023** (*Bharatiya Nyaya Sanhita*)
        - **BNSS 2023** (*Bharatiya Nagarik Suraksha Sanhita*)
        - **BSS 2023** (*Bharatiya Sakshya Adhiniyam*)
        - **Constitution of India**
        """
    )

    st.divider()
    st.caption("WhatLawSays v1.0.0 • Multi-Agent Legal AI Platform")


# --- MAIN AREA ---
render_header()

# Scenario State Handling
if "scenario_input" not in st.session_state:
    st.session_state["scenario_input"] = ""
if "jurisdiction_input" not in st.session_state:
    st.session_state["jurisdiction_input"] = "India"
if "analysis_result" not in st.session_state:
    st.session_state["analysis_result"] = None

# Quick Scenario Sample Selectors
st.markdown("### 💡 Quick Sample Test Scenarios")
sample_cols = st.columns(len(SAMPLE_SCENARIOS))

for idx, (label, sample_data) in enumerate(SAMPLE_SCENARIOS.items()):
    with sample_cols[idx]:
        if st.button(label, use_container_width=True, key=f"sample_btn_{idx}"):
            st.session_state["scenario_input"] = sample_data["scenario_text"]
            st.session_state["jurisdiction_input"] = sample_data["jurisdiction"]
            st.rerun()

# Input Form
st.markdown("### 📝 Enter Citizen Scenario")

with st.form("scenario_form"):
    scenario_text = st.text_area(
        "Describe the incident, allegations, or factual situation in detail:",
        value=st.session_state["scenario_input"],
        height=140,
        placeholder="e.g., A person received an official invitation to attend a gathering at a government building, but was stopped at the main security check post...",
    )

    col_j, col_btn = st.columns([1, 2])
    with col_j:
        jurisdiction = st.selectbox(
            "Jurisdiction",
            options=["India"],
            index=0,
        )

    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        submit_btn = st.form_submit_button(
            "⚖️ Analyze Legal Scenario",
            use_container_width=True,
            type="primary",
        )

# Form Submission Processing
if submit_btn:
    if not scenario_text.strip():
        st.error("Please enter a valid legal scenario text to analyze.")
    else:
        st.session_state["scenario_input"] = scenario_text
        with st.spinner("🧠 Orchestrating Multi-Agent Pipeline (Extractor ➔ Retriever ➔ Analyst ➔ Verifier ➔ Compiler)..."):
            try:
                if execution_mode == "FastAPI Gateway (HTTP)":
                    if not is_online:
                        st.error(f"Cannot connect to FastAPI backend at {backend_url}. Please start the server or switch to Direct Mode.")
                    else:
                        result = run_api_analysis(backend_url, scenario_text, jurisdiction)
                        st.session_state["analysis_result"] = result
                else:
                    # Direct Python execution
                    result = asyncio.run(run_direct_agent_analysis(scenario_text, jurisdiction))
                    st.session_state["analysis_result"] = result

                st.success("✅ Multi-Agent Reasoning Complete!")
            except Exception as e:
                st.error(f"Execution Error: {str(e)}")

# Display Results
result_data = st.session_state.get("analysis_result")

if result_data:
    st.divider()
    st.markdown("## 📊 Legal Analysis Results")

    # Executive Summary Banner
    render_executive_summary(result_data)

    # Multi-Tab Dashboard
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "📌 Fact Separation Matrix",
            "⚖️ Identified Offenses & Defences",
            "📋 BNSS & BSS Procedural Rules",
            "🚨 Citizen Actions & Duties",
            "💾 Raw JSON Payload",
        ]
    )

    with tab1:
        facts = result_data.get("extracted_facts", {})
        render_fact_matrix(facts)

    with tab2:
        render_offenses_tab(result_data)

    with tab3:
        render_procedural_tab(result_data)

    with tab4:
        render_actions_and_duties_tab(result_data)

    with tab5:
        render_raw_json(result_data)
