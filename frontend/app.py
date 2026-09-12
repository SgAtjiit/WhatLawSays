"""
WhatLawSays - Streamlit Interactive Frontend Application
Source-Grounded Multi-Agent Legal Reasoning Workbench

Multipage entrypoint. The workbenches live in `frontend/pages/`: scenario
analysis maps a citizen's situation onto criminal law, contract review reads a
document the user is about to be bound by, and award review checks a purchase
before it is committed to. They share a corpus and a retrieval stack but answer
different questions, so they are separate pages.
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

st.markdown("<div style='height:0.75rem'></div>", unsafe_allow_html=True)

lower_left, lower_right = st.columns(2)

with lower_left:
    st.markdown(
        """
        <div class="wls-card">
          <h3>🧾 Award Review</h3>
          <p>Check a sourcing event against your own procurement policy and Indian
          statute <b>before</b> the purchase order goes out. Breaches, bid-integrity
          patterns and checks that could not be run are reported separately, because a
          gap read as a pass is worse than no report. Cites the <b>MSMED Act</b>,
          <b>Companies Act</b>, <b>Competition Act</b>, <b>Contract Act</b> and
          <b>DPDP Act</b>.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("pages/4_🧾_Award_Review.py", label="Open Award Review", icon="🧾")

with lower_right:
    st.markdown(
        """
        <div class="wls-card">
          <h3>📐 Policy Library</h3>
          <p>Turn a procurement policy into rules an award can actually be checked
          against. A rule becomes enforceable only once a person has confirmed or
          corrected it &mdash; until then it is this system's reading of your policy,
          not your policy, and anything it produces is marked provisional.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("pages/3_📐_Policy_Library.py", label="Open Policy Library", icon="📐")

st.divider()
st.caption(
    "WhatLawSays v1.2.0 - 2,894 sections across fifteen statutes. "
    "Source-grounded legal information, not legal advice."
)
