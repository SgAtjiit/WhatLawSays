"""Award Review workbench.

Check an award against your own procurement policy and Indian statute before the
purchase order goes out.

The page is built around one idea: breaches, patterns and gaps are three
different things, and a reader scanning a single list will misread two of them.
So they are three tabs, and the summary strip says how many of each.
"""

import glob
import json
import os
import pathlib
import sys

import httpx
import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from frontend.components import inject_custom_css
from frontend.contract_components import inject_contract_css
from frontend.procurement_components import (
    inject_procurement_css,
    render_checks_table,
    render_confidence,
    render_finding_card,
    render_gaps,
    render_indicators,
    render_raw,
    render_remediations,
    render_summary,
)

st.set_page_config(
    page_title="Award Review - WhatLawSays",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_custom_css()
inject_contract_css()
inject_procurement_css()

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SAMPLE_DIR = ROOT / "samples" / "events"


def sample_events():
    if not SAMPLE_DIR.exists():
        return {}
    out = {}
    for path in sorted(glob.glob(str(SAMPLE_DIR / "*.json"))):
        name = pathlib.Path(path).stem
        label = name.split("_", 1)[-1].replace("_", " ").title()
        out[label] = path
    return out


def backend_online(url: str) -> bool:
    try:
        return httpx.get(f"{url.rstrip('/')}/health", timeout=3.0).status_code == 200
    except Exception:
        return False


def review_via_api(url, event_json, policy_id, side, po_file, include_drafts):
    files = None
    if po_file is not None:
        files = {"po_file": (po_file.name, po_file.getvalue(), "application/octet-stream")}
    response = httpx.post(
        f"{url.rstrip('/')}/api/v1/awards",
        data={
            "event": event_json,
            "policy_id": policy_id or "",
            "side": side,
            "include_draft_rules": str(include_drafts).lower(),
        },
        files=files,
        timeout=600.0,
    )
    if response.status_code == 200:
        return response.json()
    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        detail = response.text
    if isinstance(detail, list):
        detail = "; ".join(str(d.get("msg", d)) for d in detail)
    raise RuntimeError(f"{response.status_code}: {detail}")


def review_direct(event_json, policy_id, side, po_file, include_drafts):
    """Run the pipeline in this process, so the page works with no server."""
    import asyncio

    from src.core.procurement_service import review_award
    from src.schemas.procurement import ProcurementEvent, ProcurementSide

    event = ProcurementEvent(**json.loads(event_json))
    rule_set = st.session_state.get("proc_rule_set")
    return asyncio.run(
        review_award(
            event=event,
            rule_set=rule_set,
            side=ProcurementSide(side),
            po_bytes=po_file.getvalue() if po_file else None,
            po_filename=po_file.name if po_file else None,
            include_draft_rules=include_drafts,
            persist=False,
        )
    )


def policies_via_api(url):
    try:
        response = httpx.get(f"{url.rstrip('/')}/api/v1/policies", timeout=5.0)
        if response.status_code == 200:
            return response.json().get("policies", [])
    except Exception:
        pass
    return []


# --- Sidebar ---------------------------------------------------------------

with st.sidebar:
    st.title("🧾 Award Review")
    backend_url = st.text_input("FastAPI Backend URL", value="http://localhost:8000")
    online = backend_online(backend_url)
    if online:
        st.success("Backend online", icon="🟢")
    else:
        st.warning("Backend offline — using the in-process pipeline", icon="🟡")

    mode = st.radio(
        "Execution mode",
        ["HTTP API", "Direct (in-process)"],
        index=0 if online else 1,
    )

    st.divider()
    st.caption("**Statute checked**")
    st.caption(
        "MSMED Act 2006 · Companies Act 2013 · Competition Act 2002 · "
        "Indian Contract Act 1872 · DPDP Act 2023"
    )
    st.caption(
        "Findings cite the section they rest on. Checks that could not be performed "
        "are reported as gaps, never as passes."
    )

# --- Header ----------------------------------------------------------------

st.markdown(
    """
    <div style="padding:0.5rem 0 1rem 0;">
      <h1 style="margin-bottom:0.2rem;">🧾 Award Review</h1>
      <p style="opacity:0.8;margin-top:0;">
        Check a sourcing event against your procurement policy and Indian statute
        &mdash; before the purchase order goes out.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# --- Sample picker ---------------------------------------------------------

samples = sample_events()
if samples:
    st.caption("**Load a sample event**")
    columns = st.columns(min(len(samples), 3))
    for index, (label, path) in enumerate(samples.items()):
        if columns[index % len(columns)].button(label, use_container_width=True):
            st.session_state["event_json"] = pathlib.Path(path).read_text()
            st.session_state.pop("award_review", None)
            st.rerun()

# --- Input -----------------------------------------------------------------

event_json = st.text_area(
    "Sourcing event (JSON)",
    value=st.session_state.get("event_json", ""),
    height=220,
    placeholder='{"event_id": "EVT-1", "bids": [...], "provided_collections": ["bids"]}',
    help=(
        "`provided_collections` is required: it names which parts of the event you "
        "actually supplied, so that an omitted array is reported as a gap rather than "
        "treated as an empty one."
    ),
)

left, middle, right = st.columns(3)
with left:
    side = st.selectbox(
        "Reviewing for",
        ["BUYER", "SUPPLIER"],
        help=(
            "A supplier-side review runs statute and the order's own terms. It does not "
            "run the buyer's internal controls, which are not the supplier's obligation."
        ),
    )
with middle:
    policy_options = {"(statute only)": ""}
    if mode == "HTTP API" and online:
        for policy in policies_via_api(backend_url):
            label = (
                f'{policy.get("org_label") or policy["policy_id"]} '
                f'v{policy.get("version")} · {policy.get("status")}'
            )
            policy_options[label] = policy["policy_id"]
    policy_label = st.selectbox("Policy", list(policy_options))
with right:
    po_file = st.file_uploader("Purchase order (optional)", type=["pdf", "docx", "txt", "md"])

include_drafts = st.checkbox(
    "Enforce unratified rules (provisional)",
    value=False,
    help=(
        "Off by default. Rules nobody has ratified are this system's reading of your "
        "policy document, not your confirmation of it. What they produce is marked "
        "provisional, excluded from every count, and caps confidence at 0.45."
    ),
)

if st.button("Review this award", type="primary", use_container_width=True):
    if not event_json.strip():
        st.error("Paste an event, or load one of the samples above.")
    else:
        try:
            with st.spinner("Checking policy, statute and bid integrity..."):
                if mode == "HTTP API" and online:
                    review = review_via_api(
                        backend_url, event_json, policy_options[policy_label],
                        side, po_file, include_drafts,
                    )
                else:
                    review = review_direct(
                        event_json, policy_options[policy_label], side, po_file, include_drafts
                    )
            st.session_state["award_review"] = review
            st.success("Review complete.")
        except Exception as e:
            st.error(f"{e}")

# --- Results ---------------------------------------------------------------

review = st.session_state.get("award_review")

if review:
    st.divider()
    render_summary(review)

    tabs = st.tabs([
        "🚩 Breaches",
        "🔍 Bid Integrity",
        "🕳️ Could Not Be Checked",
        "🛠️ What To Do",
        "📋 Every Check",
        "🎯 Confidence",
        "💾 Raw JSON",
    ])

    with tabs[0]:
        findings = review.get("findings", [])
        if not findings:
            st.success("No breach of policy or statute was found in what was checked.", icon="✅")
            st.caption(
                "Read that alongside the gaps tab: a review can only speak to the checks "
                "it was able to run."
            )
        for finding in findings:
            render_finding_card(finding)

    with tabs[1]:
        render_indicators(review.get("indicators", []))

    with tabs[2]:
        render_gaps(review.get("undetermined_checks", []))

    with tabs[3]:
        render_remediations(review.get("remediations", []))

    with tabs[4]:
        render_checks_table(review.get("checks_run", []))

    with tabs[5]:
        render_confidence(review)

    with tabs[6]:
        render_raw(review, name=f'award-{review.get("review_id", "review")}')

    if review.get("po_review"):
        st.divider()
        st.subheader("Purchase order terms")
        st.caption(
            "The order document was read by the contract pipeline as a vendor agreement. "
            f'That review scored {review.get("po_confidence", 0):.2f}, and this review '
            "cannot be more confident than the document read it rests on."
        )
        for finding in review["po_review"].get("findings", [])[:10]:
            st.markdown(f"**{finding.get('title')}** — {finding.get('plain_summary')}")

    st.divider()
    st.caption(review.get("disclaimer", ""))
