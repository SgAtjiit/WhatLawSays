"""Contract review page.

Talks to the FastAPI gateway when it is reachable and falls back to invoking the
graph in-process, mirroring how the scenario page works.
"""

import asyncio
import os
import sys

import httpx
import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from frontend.components import inject_custom_css
from frontend.contract_components import (
    inject_contract_css,
    render_clauses,
    render_qa,
    render_redlines,
    render_confidence_basis,
    render_consistency,
    render_contract_header,
    render_document_view,
    render_findings,
    render_missing_clauses,
    render_review_json,
    render_risk_summary,
)

st.set_page_config(
    page_title="Contract Review - WhatLawSays",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_custom_css()
inject_contract_css()

CONTRACT_TYPES = [
    "EMPLOYMENT", "NDA", "LEASE", "SERVICE", "FREELANCE",
    "VENDOR", "SAAS", "LOAN", "OTHER",
]
# Weaker side first: it is who asks for a review, and the default should not
# quietly score the document from the drafter's point of view.
POSITIONS = {
    "EMPLOYMENT": ["EMPLOYEE", "EMPLOYER"],
    "NDA": ["RECEIVING_PARTY", "DISCLOSING_PARTY"],
    "LEASE": ["TENANT", "LANDLORD"],
    "SERVICE": ["SERVICE_PROVIDER", "CLIENT"],
    "FREELANCE": ["SERVICE_PROVIDER", "CLIENT"],
    "VENDOR": ["SERVICE_PROVIDER", "CLIENT"],
    "SAAS": ["CLIENT", "SERVICE_PROVIDER"],
    "LOAN": ["BORROWER", "LENDER"],
    "OTHER": ["UNKNOWN"],
}


def backend_online(url: str) -> bool:
    try:
        response = httpx.get(f"{url.rstrip('/')}/health", timeout=3.0)
        return response.status_code == 200
    except Exception:
        return False


def review_via_api(url, data, filename, media_type, contract_type, position):
    response = httpx.post(
        f"{url.rstrip('/')}/api/v1/contracts",
        files={"file": (filename, data, media_type or "application/octet-stream")},
        data={"contract_type": contract_type, "position": position, "jurisdiction": "India"},
        timeout=600.0,
    )
    if response.status_code == 200:
        return response.json()
    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        detail = response.text
    if isinstance(detail, list):  # FastAPI validation errors arrive as a list
        detail = "; ".join(str(d.get("msg", d)) for d in detail)
    raise RuntimeError(f"{response.status_code}: {detail}")


def ask_via_api(url, contract_id, question):
    response = httpx.post(
        f"{url.rstrip('/')}/api/v1/contracts/{contract_id}/ask",
        json={"question": question},
        timeout=120.0,
    )
    if response.status_code == 200:
        return response.json()
    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        detail = response.text
    raise RuntimeError(f"{response.status_code}: {detail}")


async def ask_direct(review, question):
    from types import SimpleNamespace

    from src.core.contract_qa import answer_question

    clauses = [SimpleNamespace(**c) for c in review.get("clauses", [])]
    explanations = {c["index"]: {"plain_english": c.get("plain_english", "")} for c in review.get("clauses", [])}
    return await answer_question(
        question=question, clauses=clauses, findings=review.get("findings", []),
        explanations=explanations, position=review.get("position", "UNKNOWN"),
    )


def pdf_via_api(url, contract_id):
    response = httpx.get(f"{url.rstrip('/')}/api/v1/contracts/{contract_id}/report.pdf", timeout=60.0)
    response.raise_for_status()
    return response.content


def pdf_direct(review):
    from src.core.report_export import build_report_pdf

    return build_report_pdf(review, review.get("redlines", []))


async def review_direct(data, filename, media_type, contract_type, position):
    from src.core.contract_service import review_contract
    from src.schemas.contract import ContractType, PartyPosition

    return await review_contract(
        data=data,
        filename=filename,
        declared_media_type=media_type,
        contract_type=ContractType(contract_type) if contract_type else None,
        position=PartyPosition(position) if position and position != "UNKNOWN" else None,
    )


with st.sidebar:
    st.title("Contract Review")
    backend_url = st.text_input("FastAPI Backend URL", value="http://localhost:8000")
    online = backend_online(backend_url)
    # A statement, not an expression: Streamlit's "magic" wraps bare expression
    # statements in st.write and its AST pass could not parse the multi-line
    # ternary, so the page failed to load at all with a SyntaxError.
    if online:
        st.success("🟢 Backend API Connected")
    else:
        st.warning("🔴 Backend Offline (Direct Mode Available)")
    mode = st.radio(
        "Execution",
        ["FastAPI Gateway (HTTP)", "Direct LangGraph (Python)"],
        index=0 if online else 1,
        key="execution_mode",
    )
    try:
        from src.core import ocr as _ocr

        if _ocr.is_available():
            st.caption("🔍 OCR available — scans and photographs can be reviewed.")
        else:
            st.caption(
                "🔍 OCR not installed — documents with no text layer will be "
                "refused. Install it with `brew install tesseract`."
            )
    except Exception:
        pass

    st.divider()
    st.subheader("📚 Contract Corpus")
    st.markdown(
        """
        - **Indian Contract Act, 1872**
        - **Transfer of Property Act, 1882**
        - **Specific Relief Act, 1963**
        - **Arbitration & Conciliation Act, 1996**
        - **Consumer Protection Act, 2019**
        - **DPDP Act, 2023**
        """
    )
    st.divider()
    st.caption(
        "Findings quote your document verbatim. Anything that cannot be located "
        "in the file you uploaded is discarded rather than shown."
    )

render_contract_header()

if "contract_review" not in st.session_state:
    st.session_state["contract_review"] = None
    st.session_state["contract_text"] = ""

uploaded = st.file_uploader(
    "Upload your contract",
    type=["pdf", "docx", "txt", "md", "png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp"],
    help="PDF, Word, plain text, or a scan or photograph. A document with no text "
         "layer is read by OCR and clearly labelled -- every finding then shows the "
         "region of the scan it came from, because a quote checked against a "
         "transcription only proves the transcription is self-consistent.",
)
# Deliberately not inside st.form: a form defers every rerun until submit, so
# the side selector never followed the contract type and quietly submitted the
# first side of whatever type was showing when the page loaded.
left, right = st.columns(2)
with left:
    contract_type = st.selectbox("Contract type", CONTRACT_TYPES, index=0, key="contract_type")
with right:
    sides = POSITIONS.get(contract_type, ["UNKNOWN"])
    position = st.selectbox(
        "Which side are you on?",
        sides,
        help="This is not cosmetic. An uncapped indemnity is catastrophic for "
             "the party giving it and unremarkable for the party receiving it.",
    )
submitted = st.button("📄 Review Contract", use_container_width=True, type="primary")

if submitted:
    if uploaded is None:
        st.error("Please choose a contract file to review.")
    else:
        data = uploaded.getvalue()
        with st.spinner(
            "Parsing, segmenting clauses, retrieving statute and reviewing... "
            "a long contract can take a couple of minutes."
        ):
            try:
                if mode.startswith("FastAPI") and online:
                    review = review_via_api(
                        backend_url, data, uploaded.name, uploaded.type,
                        contract_type, position,
                    )
                else:
                    review = asyncio.run(
                        review_direct(data, uploaded.name, uploaded.type, contract_type, position)
                    )
                st.session_state["contract_review"] = review
                st.session_state["qa_history"] = []
                # Kept only for the highlighted document view; offsets in the
                # review index into exactly this text.
                # Offsets in the review index into the NORMALISED text, so the
                # raw bytes must be put through the same normalisation or every
                # highlight lands in the wrong place on a CRLF or indented file.
                if uploaded.name.lower().endswith((".txt", ".md")):
                    from src.core.document_parser import normalize

                    st.session_state["contract_text"] = normalize(
                        data.decode("utf-8", errors="replace")
                    )
                else:
                    st.session_state["contract_text"] = ""
                st.success("Review complete.")
            except Exception as e:
                st.error(f"{e}")

review = st.session_state.get("contract_review")

if review:
    st.divider()
    render_risk_summary(review)

    use_api = mode.startswith("FastAPI") and online and review.get("contract_id")
    try:
        pdf_bytes = pdf_via_api(backend_url, review["contract_id"]) if use_api else pdf_direct(review)
        st.download_button(
            "⬇️ Download review as PDF",
            data=pdf_bytes,
            file_name=f"contract-review-{review.get('contract_id', 'result')}.pdf",
            mime="application/pdf",
        )
    except Exception as e:
        st.caption(f"PDF export unavailable: {e}")

    tabs = st.tabs([
        "🚩 Red Flags",
        "✍️ What to Ask For",
        "💬 Ask the Contract",
        "📋 Clause by Clause",
        "🕳️ What's Missing",
        "🔀 Consistency",
        "📄 Document View",
        "🎯 Confidence",
        "💾 Raw JSON",
    ])

    with tabs[0]:
        render_findings(review)
    with tabs[1]:
        render_redlines(review)
    with tabs[2]:
        if use_api:
            render_qa(review, lambda q: ask_via_api(backend_url, review["contract_id"], q))
        else:
            render_qa(review, lambda q: asyncio.run(ask_direct(review, q)))
    with tabs[3]:
        render_clauses(review)
    with tabs[4]:
        render_missing_clauses(review)
    with tabs[5]:
        render_consistency(review)
    with tabs[6]:
        if review.get("source") == "ocr":
            st.info(
                "This document was read from an image, so there is no source text "
                "to highlight. Each finding on the Red Flags tab carries a crop of "
                "the page it was read from instead.",
                icon="🔍",
            )
        else:
            render_document_view(review, st.session_state.get("contract_text", ""))
    with tabs[7]:
        render_confidence_basis(review)
    with tabs[8]:
        render_review_json(review)

    st.caption(review.get("disclaimer", ""))
