"""Policy Library.

Turn a procurement policy into machine-checkable rules, and ratify them.

The ratification step is the point of this page, not an administrative wrapper
around it. A rule this system inferred is its reading of your policy document; a
rule you confirmed is your policy. Only the second is ever enforced, and a review
run against unratified rules is capped at 0.45 confidence and marked provisional
throughout.
"""

import os
import sys

import httpx
import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from frontend.components import inject_custom_css
from frontend.contract_components import inject_contract_css
from frontend.procurement_components import inject_procurement_css, status_chip

st.set_page_config(
    page_title="Policy Library - WhatLawSays",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_custom_css()
inject_contract_css()
inject_procurement_css()

STARTER_RULES = [
    {"rule_id": "R1", "kind": "MIN_QUOTES_BY_VALUE",
     "params": {"above_value": 500000, "min_quotes": 3}},
    {"rule_id": "R2", "kind": "APPROVAL_AUTHORITY",
     "params": {"above_value": 500000, "required_role": "CFO"}},
    {"rule_id": "R3", "kind": "APPROVAL_BEFORE_COMMITMENT", "params": {}},
    {"rule_id": "R4", "kind": "PAYMENT_TERMS_CAP", "params": {"max_days": 45}},
    {"rule_id": "R5", "kind": "SPLIT_PO_AVOIDANCE",
     "params": {"window_days": 30, "threshold": 500000}},
    {"rule_id": "R6", "kind": "LOWEST_RESPONSIVE_AWARD", "params": {}},
    {"rule_id": "R7", "kind": "SINGLE_SOURCE_JUSTIFICATION", "params": {}},
    {"rule_id": "R8", "kind": "APPROVED_VENDOR_REQUIRED", "params": {}},
]


def api(url: str) -> str:
    return url.rstrip("/") + "/api/v1"


def backend_online(url: str) -> bool:
    try:
        return httpx.get(f"{url.rstrip('/')}/health", timeout=3.0).status_code == 200
    except Exception:
        return False


def call(method: str, url: str, **kwargs):
    response = getattr(httpx, method)(url, timeout=30.0, **kwargs)
    if response.status_code < 300:
        return response.json()
    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        detail = response.text
    raise RuntimeError(f"{response.status_code}: {detail}")


with st.sidebar:
    st.title("📐 Policy Library")
    backend_url = st.text_input("FastAPI Backend URL", value="http://localhost:8000")
    online = backend_online(backend_url)
    if online:
        st.success("Backend online", icon="🟢")
    else:
        st.error("Backend offline — this page needs the API", icon="🔴")
    st.divider()
    st.caption(
        "A rule becomes enforceable only once a person has confirmed or corrected it. "
        "Until then it is this system's reading of your policy, not your policy."
    )

st.markdown(
    """
    <div style="padding:0.5rem 0 1rem 0;">
      <h1 style="margin-bottom:0.2rem;">📐 Policy Library</h1>
      <p style="opacity:0.8;margin-top:0;">
        Your procurement policy, as rules an award can actually be checked against.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)

if not online:
    st.info(
        "Start the API to use this page:  `uv run uvicorn src.main:app --reload --port 8000`",
        icon="ℹ️",
    )
    st.stop()

catalogue = {}
try:
    catalogue = call("get", f"{api(backend_url)}/procurement/meta/checks")
except Exception as e:
    st.error(f"Could not load the check catalogue: {e}")

tab_build, tab_manage, tab_catalogue = st.tabs(
    ["➕ Build a policy", "📚 Your policies", "🧭 What can be checked"]
)

with tab_build:
    st.caption(
        "Start from the common controls below, adjust the thresholds to your own "
        "delegation of authority, then ratify and activate."
    )
    org_label = st.text_input("Organisation", value="Acme Manufacturing Ltd")

    kinds = [k["kind"] for k in catalogue.get("policy_kinds", [])]
    chosen = st.multiselect(
        "Controls to include",
        options=kinds,
        default=[r["kind"] for r in STARTER_RULES if r["kind"] in kinds],
    )

    st.caption("**Thresholds**")
    threshold_value = st.number_input(
        "Competitive-quote threshold (₹)", value=500000, step=50000,
        help="Above this value the policy requires the minimum number of quotes.",
    )
    minimum_quotes = st.number_input("Minimum quotes above that value", value=3, step=1)
    approver_role = st.text_input("Approver required above that value", value="CFO")
    payment_cap = st.number_input("Payment terms cap (days)", value=45, step=5)
    split_window = st.number_input("Structuring window (days)", value=30, step=5)

    defaults = {
        "MIN_QUOTES_BY_VALUE": {"above_value": threshold_value, "min_quotes": minimum_quotes},
        "APPROVAL_AUTHORITY": {"above_value": threshold_value, "required_role": approver_role},
        "PAYMENT_TERMS_CAP": {"max_days": payment_cap},
        "SPLIT_PO_AVOIDANCE": {"window_days": split_window, "threshold": threshold_value},
        "MANDATORY_BID_WINDOW": {"min_days": 7},
        "PO_EXCEEDS_AWARDED_VALUE": {"tolerance_pct": 0},
        "LOWEST_RESPONSIVE_AWARD": {"tolerance_pct": 0},
        "RATE_CONTRACT_ADHERENCE": {"tolerance_pct": 0},
    }

    if st.button("Create this policy", type="primary", use_container_width=True):
        try:
            created = call(
                "post", f"{api(backend_url)}/policies",
                json={
                    "org_label": org_label,
                    "company_id": org_label,
                    "rules": [
                        {
                            "rule_id": f"R{index + 1}",
                            "kind": kind,
                            "params": defaults.get(kind, {}),
                            "status": "DRAFT",
                        }
                        for index, kind in enumerate(chosen)
                    ],
                },
            )
            st.session_state["policy_id"] = created["policy_id"]
            st.success(f"Created policy {created['policy_id']} with {len(chosen)} drafted rules.")
            if created.get("not_addressed"):
                st.info(
                    "This policy says nothing about: "
                    + ", ".join(created["not_addressed"])
                    + ". Those controls will report as not evaluated rather than as passing.",
                    icon="🕳️",
                )
        except Exception as e:
            st.error(f"{e}")

with tab_manage:
    try:
        listing = call("get", f"{api(backend_url)}/policies").get("policies", [])
    except Exception as e:
        listing = []
        st.error(f"{e}")

    if not listing:
        st.caption("No policies yet. Build one in the first tab.")
    else:
        labels = {
            f'{p.get("org_label") or p["policy_id"]} · v{p.get("version")} · {p.get("status")}':
                p["policy_id"]
            for p in listing
        }
        selected = st.selectbox("Policy", list(labels))
        policy_id = labels[selected]

        try:
            rule_set = call("get", f"{api(backend_url)}/policies/{policy_id}")
        except Exception as e:
            rule_set = {}
            st.error(f"{e}")

        rules = rule_set.get("rules", [])
        active = rule_set.get("status") == "ACTIVE"
        drafted = [r for r in rules if r["status"] == "DRAFT"]

        columns = st.columns(4)
        columns[0].metric("Status", rule_set.get("status", "?"))
        columns[1].metric("Rules", len(rules))
        columns[2].metric("Ratified", sum(1 for r in rules if r["status"] in {"RATIFIED", "EDITED"}))
        columns[3].metric("Awaiting review", len(drafted))

        if active:
            st.info(
                "This version is active and therefore immutable, so reviews run against it "
                "stay re-derivable against the rules that actually produced them.",
                icon="🔒",
            )

        for rule in rules:
            with st.container(border=True):
                head, buttons = st.columns([3, 2])
                with head:
                    st.markdown(
                        f'{status_chip(rule["status"])} &nbsp;<b>{rule["kind"]}</b>'
                        f'<span style="opacity:0.6;font-size:0.8rem;"> · {rule["rule_id"]}'
                        f' · {rule["origin"]}</span>',
                        unsafe_allow_html=True,
                    )
                    if rule.get("params"):
                        st.caption(", ".join(f"{k} = {v}" for k, v in rule["params"].items()))
                    if rule.get("grounding"):
                        st.markdown(
                            f'<div class="evidence-box">“{rule["grounding"]["quote"]}”</div>',
                            unsafe_allow_html=True,
                        )
                if not active:
                    with buttons:
                        ratify, reject = st.columns(2)
                        if ratify.button("Ratify", key=f"rat-{rule['rule_id']}",
                                         disabled=rule["status"] != "DRAFT"):
                            call("patch",
                                 f'{api(backend_url)}/policies/{policy_id}/rules/{rule["rule_id"]}',
                                 json={"action": "RATIFY", "actor": "ui"})
                            st.rerun()
                        if reject.button("Reject", key=f"rej-{rule['rule_id']}",
                                         disabled=rule["status"] != "DRAFT"):
                            call("patch",
                                 f'{api(backend_url)}/policies/{policy_id}/rules/{rule["rule_id"]}',
                                 json={"action": "REJECT", "actor": "ui"})
                            st.rerun()

        if not active:
            if st.button("Activate this version", type="primary", use_container_width=True):
                try:
                    call("post", f"{api(backend_url)}/policies/{policy_id}/activate")
                    st.success("Activated. This version is now in force and frozen.")
                    st.rerun()
                except Exception as e:
                    st.error(f"{e}")

        with st.expander("Raw rule set", expanded=False):
            st.json(rule_set)

with tab_catalogue:
    st.caption(
        "Everything this system can check. What is not on this list was not checked — "
        "that is why the catalogue is published rather than kept internal."
    )
    st.subheader("Statute")
    for check in catalogue.get("statutory_checks", []):
        with st.container(border=True):
            st.markdown(f'**{check["title"]}** · `{check["check_id"]}` · {check["severity"]}')
            for citation in check.get("citations", []):
                st.caption(f'{citation["act"]} — {citation["section_number"]}: {citation["note"]}')

    st.subheader("Policy controls")
    for kind in catalogue.get("policy_kinds", []):
        st.markdown(
            f'**{kind["title"]}** · `{kind["kind"]}`'
            + (f' · parameters: {", ".join(kind["parameters"])}' if kind.get("parameters") else "")
        )

    st.subheader("Bid-integrity signals")
    st.caption(
        "All reported as indicators, never as breaches. A bid tab cannot establish the "
        "agreement Competition Act s.3(3) attaches to."
    )
    for signal in catalogue.get("bid_integrity_signals", []):
        st.markdown(f'**{signal["title"]}** · `{signal["check_id"]}` · {signal["severity"]}')
