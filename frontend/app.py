"""
WhatLawSays - Streamlit Interactive Frontend Application
Source-Grounded Multi-Agent Legal Reasoning Workbench

Multipage entrypoint. The two workbenches live in `frontend/pages/`:
scenario analysis maps a citizen's situation onto criminal law, contract review
reads a document the user is about to be bound by. They share a corpus and a
retrieval stack but answer different questions, so they are separate pages.
"""

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from frontend.components import inject_custom_css

st.set_page_config(
    page_title="WhatLawSays - Legal Reasoning Engine",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_custom_css()

st.markdown(
    """
    <div style="text-align:center;padding:2rem 0 1rem 0;">
      <h1 style="margin-bottom:0.3rem;">⚖️ WhatLawSays</h1>
      <p style="opacity:0.8;font-size:1.05rem;margin-top:0;">
        Source-grounded legal reasoning over Indian statute.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)

left, right = st.columns(2)

with left:
    st.markdown(
        """
        <div class="wls-card">
          <h3>⚖️ Scenario Analysis</h3>
          <p>Describe an incident and see which offences the facts actually establish
          under the <b>BNS</b>, with procedure under the <b>BNSS</b> and evidence under
          the <b>BSA</b>. Every element is audited against the facts, and an offence whose
          element is contradicted is reported as excluded rather than quietly dropped.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("pages/1_⚖️_Scenario_Analysis.py", label="Open Scenario Analysis", icon="⚖️")

with right:
    st.markdown(
        """
        <div class="wls-card">
          <h3>📄 Contract Review</h3>
          <p>Upload a contract and get it explained in plain words, with the terms that
          work against you flagged and the protections it lacks named. Findings quote
          your document verbatim and cite the provision that governs them &mdash;
          <b>Contract Act</b>, <b>TPA</b>, <b>Arbitration Act</b>, <b>CPA</b> or <b>DPDP</b>.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("pages/2_📄_Contract_Review.py", label="Open Contract Review", icon="📄")

st.divider()
st.caption(
    "WhatLawSays v1.1.0 - 2,336 sections across twelve statutes. "
    "Source-grounded legal information, not legal advice."
)
