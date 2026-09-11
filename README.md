<div align="center">

# ⚖️ WhatLawSays
### Source-Grounded Multi-Agent Legal Reasoning & System Architecture Engine

[![Python](https://img.shields.io/badge/Python-3.13+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.42+-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-FF6F00?style=for-the-badge&logo=langchain&logoColor=white)](https://www.langchain.com/langgraph)
[![Qdrant](https://img.shields.io/badge/Qdrant-Hybrid--Vector--DB-DC2626?style=for-the-badge&logo=qdrant&logoColor=white)](https://qdrant.tech/)
[![Groq](https://img.shields.io/badge/Groq-Llama3.3%20%2F%20GPT--OSS-f55036?style=for-the-badge&logo=groq&logoColor=white)](https://groq.com/)
[![Redis](https://img.shields.io/badge/Redis-Task--Queue-DC382D?style=for-the-badge&logo=redis&logoColor=white)](https://redis.io/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Persistence-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Containers-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)

<p align="center">
  A production-grade, source-grounded legal reasoning platform engineered to map citizen scenarios to Indian Criminal Statutes (<b>BNS 2023</b>, <b>BNSS 2023</b>, <b>BSS 2023</b>) and the <b>Constitution of India</b> while eliminating factual contamination and hallucinated charges.
</p>

</div>

---

## 🌟 Architectural Highlights

Unlike basic RAG chatbots that perform naive similarity searches and generate unchecked responses, **WhatLawSays** implements a strict, multi-agent deductive reasoning pipeline:

- 🧠 **Immutable Fact Contracts (`established_facts` vs `user_allegations` vs `unknown_facts`)**:
  - Strictly separates objective, undisputed facts from subjective user allegations and indeterminate unknowns.
  - Enforces the core legal reasoning rule: $\text{UNKNOWN} \neq \text{FALSE}$ and $\text{UNKNOWN} \neq \text{TRUE}$.
- 🎯 **Fact-Clean Legal Query Generator**:
  - Generates retrieval queries strictly using explicit scenario terms without injecting premature section numbers or assumptions.
- 🔍 **Expanded Hybrid Retrieval (Dense + Sparse BM25)**:
  - Executes parallel **Dense Cosine** (`bge-small-en-v1.5`) and **Sparse BM25** (`Qdrant/bm25`) vector search over Qdrant, merged via **Reciprocal Rank Fusion (RRF)**.
  - Unfiltered retrieval recall across full statutory corpus prevents premature category classification failures.
- ⚖️ **Element-Based Verification & Statutory Exception Evaluation**:
  - Verification Agent acts as a two-part logic judge: audits factual alignment first, then audits statutory accuracy.
  - Evaluates section-specific statutory exceptions (e.g. Grave & Sudden Provocation) and general legal defences (e.g. Right of Private Defence BNS Sec 38–44).
  - Automatically exonerates accused parties if statutory elements are `CONTRADICTED_BY_FACT` (e.g. valid invitation negates criminal trespass).
- 🔍 **Act-Scoped Two-Pass Retrieval**:
  - The offence-identification pass searches **BNS only**. The corpus is 1,580 sections of which BNS is just 358, so an unscoped search left substantive penal law outnumbered roughly 3:1 and procedural/constitutional provisions displaced the offence sections the analyst needs.
  - A second pass retrieves **BNSS / BSA / Constitution** separately. These populate the procedural tab only and are never candidates for the offences array.
  - Each pool is reranked independently, and the act filter is applied inside both the dense and sparse prefetches so it shapes candidate generation rather than merely trimming the fused result.
  - Confidence grounding is measured against the substantive pool alone, so a BNSS citation appearing in the offences array reads as ungrounded.
- 📊 **Measured Confidence Estimation**:
  - Confidence is computed per request from four measured components — how decisively retrieval separated a best match, the fraction of statutory elements the facts actually support, the verification outcome (discounted by retry count), and how complete the supplied facts are — combined as a weighted geometric mean.
  - Retrieval signals are **scale-free**. Cross-encoder logits are not calibrated relevance probabilities: `BAAI/bge-reranker-base` scores this statutory corpus entirely below zero, so reading them absolutely collapsed even the correct top hit to near zero. Relevance is therefore min-max normalized within each query's candidate set, which also works unchanged for the RRF fallback.
  - Every cited section is checked against the retrieved corpus. A section the retriever never returned caps confidence at `0.50`, since that is the strongest available hallucination signal.
  - A silently degraded stage cannot report a healthy score: an LLM fallback caps at `0.60`, a cross-encoder fallback at `0.75`.
  - The estimator never asserts certainty: results are bounded to `[0.05, 0.95]`.
  - Distinguishes a confident `NOT_ESTABLISHED` (relevant law retrieved, its elements contradicted by the facts) from a low-confidence `UNDETERMINED` (weak retrieval or too many unknowns).
  - `confidence_basis` in every response carries the full per-component and per-offence breakdown, the caps applied, and why.
  - This is an **estimate, not a calibrated probability** — nothing here is fitted against labelled outcomes yet.
- 📋 **Procedural Classification & Evidentiary Mapping (BNSS & BSS)**:
  - Automatically classifies offenses by **Cognizability**, **Bailability**, and **Punishment Severity** (`CAPITAL_LIFE`, `SERIOUS`, `MINOR`).
  - Maps procedural provisions under **BNSS 2023** (e.g. Sec 173 e-FIR, Sec 185 search rules) and evidentiary standards under **BSS 2023** (Sec 63 electronic records certificate).
- 🚨 **Actionable Citizen Guidance & Statutory Reporting Duties**:
  - Generates prioritized immediate action steps (emergency helpline 112, filing e-FIR, medical audit, digital evidence preservation).
  - Highlights statutory duties required of citizens under Indian criminal procedure (e.g. BNSS Section 33 obligation to report certain offenses).
- 🛡️ **System `UNDETERMINED` State**:
  - Returns a grounded legal explanation when facts are insufficient to establish an offense instead of making false claims.



## 📂 Project Structure

```text
├── frontend/
│   ├── app.py                   # Streamlit Interactive Web Application
│   ├── components.py            # Streamlit UI Components, Styling & Cards
│   └── sample_scenarios.py      # Predefined Legal Test Scenarios
├── src/
│   ├── main.py                  # FastAPI Application Gateway & Middleware
│   ├── config.py                # Pydantic Settings & Environment Configurations
│   ├── agents/
│   │   ├── graph.py             # LangGraph Multi-Agent Workflow Definition
│   │   ├── state.py             # TypedDict GraphState Engine Representation
│   │   └── nodes/
│   │       ├── extractor.py     # Agent 1: Established & Allegation Fact Extractor
│   │       ├── query_builder.py # Agent 2: Fact-Clean Query Generator
│   │       ├── retriever.py     # Act-Scoped Hybrid Retriever (offence + procedural passes)
│   │       ├── reranker_node.py # Step 3: Legal Reranker Node
│   │       ├── analyst.py       # Agent 3: Deductive Analyst, Exceptions & Action Mapper
│   │       ├── verifier.py      # Agent 4: Claim-Evidence & Exception Verification Judge
│   │       └── compiler.py      # Step 5: Response Compiler & Confidence Estimation
│   ├── core/
│   │   ├── vector_store.py      # Qdrant Client Hybrid Dense + BM25 Integration
│   │   ├── reranker.py          # Reranking Engine & Fallback Manager
│   │   ├── confidence.py        # Multi-Component Confidence Estimator
│   │   ├── task_queue.py        # Redis Async Task Queue Producer/Consumer
│   │   ├── database.py          # SQLAlchemy PostgreSQL Async Models & Operations
│   │   └── logger.py            # Colorized Pipeline Stage Logging Engine
│   └── schemas/
│       ├── legal.py             # Pydantic Schemas for Requests, Offenses, Actions & Duties
│       └── corpus.py            # Legal Section Data Schemas
├── scripts/
│   ├── ingest_legal_corpus.py   # Seed Data Ingestion Script (Batch & Async Setup)
│   ├── test_pipeline.py         # End-to-End Pipeline Integration Test
│   ├── test_hybrid_search.py   # Hybrid Vector Search Verification Script
│   └── test_president_invitation.py # Test Script for Undetermined Scenario
├── tests/
│   └── test_agents.py           # Pytest Suite for Agents & Workflows
├── docker-compose.yml           # Multi-Container Deployment (FastAPI, Redis, Qdrant)
├── pyproject.toml               # Dependencies & UV Project Configuration
└── README.md                    # System Documentation
```

---

## ⚡ Quick Start & Installation

### Prerequisites
- **Python 3.13+**
- **Docker & Docker Compose** (for Qdrant & Redis)
- **uv** package manager (`pip install uv`)

### 1. Clone Repository & Install Dependencies
```bash
git clone https://github.com/your-username/whatLawSays.git
cd whatLawSays
uv sync
```

### 2. Environment Configuration
Create a `.env` file in the root directory:
```env
PROJECT_NAME="WhatLawSays Backend"
API_V1_STR="/api/v1"
GROQ_API_KEY="gsk_your_groq_api_key_here"
GROQ_MODEL="openai/gpt-oss-120b"
QDRANT_URL="http://localhost:6333"
REDIS_URL="redis://localhost:6379/0"
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/whatlawsays"
```

### 3. Launch Services with Docker Compose
```bash
docker-compose up -d
```

### 4. Seed Legal Corpus into Qdrant
```bash
uv run python -m scripts.ingest_legal_corpus
```

### 5. Run FastAPI Application Server
```bash
uv run uvicorn src.main:app --reload --port 8000
```
Interactive API Documentation will be available at: **`http://localhost:8000/docs`**

### 6. Run Interactive Streamlit Frontend UI
```bash
uv run streamlit run frontend/app.py
```
Interactive Web Workbench will open at: **`http://localhost:8501`**

---

## 🧪 Testing & Verification

Run the automated agent pytest suite:
```bash
uv run pytest tests/
```

Run the hybrid search verification script:
```bash
uv run python -m scripts.test_hybrid_search
```

Run the President's Residence Invitation integration test:
```bash
uv run python -m scripts.test_president_invitation
```

---

## 📡 API Usage Example

### Request
`POST /api/v1/analyze`

```json
{
  "scenario_text": "A person was going to enter the President's residence with an invitation to attend a party.",
  "jurisdiction": "India"
}
```

### Response (`UNDETERMINED` State Example)
```json
{
  "status": "UNDETERMINED",
  "scenario_domain": "POTENTIAL_CRIMINAL",
  "offense_status": "UNDETERMINED",
  "confidence_score": 0.45,
  "confidence_basis": {
    "score": 0.45,
    "components": {
      "retrieval": 0.622,
      "exclusion_evidence": 0.25,
      "fact_completeness": 0.84
    },
    "offenses": [],
    "caps_applied": ["undetermined<=0.45"],
    "notes": [
      "Insufficient retrieval or fact support to determine whether an offence arises."
    ]
  },
  "reason": "The supplied facts do not establish the elements of an offence.",
  "excluded_provisions": [],
  "extracted_facts": {
    "explicit_facts": [
      "A person was going to enter the President's residence",
      "The person had an invitation to attend a party"
    ],
    "established_facts": [
      "The person possessed an invitation to attend a party at the President's residence"
    ],
    "user_allegations": [],
    "unknown_facts": [
      "Whether the person actually entered the residence",
      "Whether the invitation was valid or authorized"
    ],
    "actor": "person",
    "action": "enter",
    "scenario_domain": "POTENTIAL_CRIMINAL",
    "offense_status": "UNDETERMINED"
  },
  "identified_offenses": [],
  "applied_defences": [],
  "procedural_provisions": [
    "BNSS 2023 Section 173 - Procedure for recording information regarding cognizable offences"
  ],
  "immediate_action_steps": [
    {
      "step_number": 1,
      "title": "Verify Authorization",
      "action_details": "Confirm invitation authenticity with the event organizers or venue security prior to entry.",
      "statutory_duty_reference": null,
      "urgency": "MEDIUM"
    }
  ],
  "citizen_duties": [],
  "clarification_questions": [
    "Whether the person actually entered the residence",
    "Whether the invitation was valid or authorized"
  ],
  "disclaimer": "This platform provides legal information based on BNS/BNSS/BSS, not formal legal advice."
}
```

---

## 📜 License
Distributed under the MIT License. See `LICENSE` for more information.
