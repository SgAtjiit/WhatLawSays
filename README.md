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
  - The offence-identification pass searches **offence-creating law only** — BNS, IT Act and POSH Act. The criminal corpus is 1,719 sections of the 2,336 indexed; an unscoped search left substantive penal law outnumbered roughly 3:1, so procedural and constitutional provisions displaced the offence sections the analyst needs.
  - A second pass retrieves **BNSS / BSA / Constitution** separately. These populate the procedural tab only and are never candidates for the offences array.
  - Within the substantive Acts, a section is eligible to be an offence only if it **prescribes a penalty**, a flag derived at ingest from the section's own verbatim text. The IT Act and POSH Act are internally mixed, so act-level scoping alone would have reported POSH s.8 (Grants and audit) and s.4 (Constitution of the Internal Complaints Committee) as offences.
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
│   │   ├── contract_graph.py    # Second LangGraph: contract review pipeline
│   │   ├── contract_state.py    # TypedDict ContractGraphState
│   │   ├── contract_nodes/      # profiler, classifier, query_builder, retriever,
│   │   │                        # explainer, red_flag_analyst, gap_detector,
│   │   │                        # consistency, grounding, compiler
│   │   └── nodes/
│   │       ├── extractor.py     # Agent 1: Established & Allegation Fact Extractor
│   │       ├── query_builder.py # Agent 2: Fact-Clean Query Generator
│   │       ├── retriever.py     # Act-Scoped Hybrid Retriever (offence + procedural passes)
│   │       ├── reranker_node.py # Step 3: Legal Reranker Node
│   │       ├── analyst.py       # Agent 3: Deductive Analyst, Exceptions & Action Mapper
│   │       ├── verifier.py      # Agent 4: Claim-Evidence & Exception Verification Judge
│   │       └── compiler.py      # Step 5: Response Compiler & Confidence Estimation
│   ├── core/
│   │   ├── acts.py              # Canonical Act names & the three retrieval pools
│   │   ├── document_parser.py   # Contract upload -> normalized text with offsets
│   │   ├── clause_segmenter.py  # Contract text -> clauses, with deterministic labels
│   │   ├── red_flag_rules.py    # Deterministic red-flag rules, each carrying citations
│   │   ├── clause_checklists.py # Per-contract-type missing-protection checklists
│   │   ├── pattern_utils.py     # Line-wrap-tolerant pattern compilation
│   │   ├── clause_triage.py     # HOT/WARM/COLD tiering that bounds LLM cost
│   │   ├── llm_batch.py         # Bounded-concurrency batching with per-batch degradation
│   │   ├── contract_confidence.py # Contract-review confidence estimator
│   │   ├── vector_store.py      # Qdrant Client Hybrid Dense + BM25 Integration
│   │   ├── reranker.py          # Reranking Engine & Fallback Manager
│   │   ├── confidence.py        # Multi-Component Confidence Estimator
│   │   ├── task_queue.py        # Redis Async Task Queue Producer/Consumer
│   │   ├── database.py          # SQLAlchemy PostgreSQL Async Models & Operations
│   │   └── logger.py            # Colorized Pipeline Stage Logging Engine
│   └── schemas/
│       ├── contract.py          # Contract review schemas: clauses, findings, party sides
│       ├── contract_review.py   # Model-facing payloads & the review response envelope
│       ├── legal.py             # Pydantic Schemas for Requests, Offenses, Actions & Duties
│       └── corpus.py            # Legal Section Data Schemas
├── scripts/
│   ├── ingest_legal_corpus.py   # Seed Data Ingestion Script (Batch & Async Setup)
│   ├── fetch_indiacode_act.py   # Fetches an Act's sections verbatim from India Code
│   ├── find_indiacode_act.py    # Looks up an Act's India Code act_id by name
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

## 📄 Contract Review

A second LangGraph pipeline reviews an uploaded contract: it explains each clause in
plain words, flags terms that work against the reader, and names the gaps. It shares
the corpus, retrieval and reranking of the criminal pipeline but answers a different
question, so it is a separate graph rather than extra nodes on the existing one.

```
parse + segment (deterministic, outside the graph)
  -> profiler -> clause_classifier -> query_builder -> clause_retriever
  -> explainer -> red_flag_analyst -> gap_detector -> consistency_checker
  -> grounding_verifier --(ungrounded)--> red_flag_analyst
  -> contract_compiler
```

- **A finding is only meaningful relative to a side.** An uncapped indemnity is
  catastrophic for the indemnifier and unremarkable for the indemnitee. The reviewing
  party is declared by the user, and the same employment contract scores
  `BROAD_IP_ASSIGNMENT` as **CRITICAL** for the employee and **INFO** for the employer.
  A clause that is void whoever it favours is never demoted to noise.
- **Rules first, model second.** 17 deterministic rules detect the known-dangerous
  patterns and carry their own statutory citations. The model explains what the rules
  found and adds concerns the rules do not encode; it never decides whether a clause is
  void. Asked directly, `llama-3.3-70b` calls an Indian non-compete "unenforceable in
  some jurisdictions" — the US reasonableness framing. Contract Act s.27 voids it
  outright, with no reasonableness test.
- **The model never supplies offsets.** Model findings carry only a verbatim quote,
  which the pipeline locates in the document itself. A quote that cannot be located is
  discarded rather than repaired, so every finding in the output points at real text.
- **Contract wording does not retrieve statute.** Measured against this corpus,
  `"restraint of trade void agreement"` returns Contract Act s.27 at **rank 1**, while
  `"employee shall not join a competing business for two years"` does **not return it at
  all**. The query builder translates each clause into statutory register before
  retrieval; all eight statute-bearing categories then retrieve their governing
  provision in the top 5.
- **Triage bounds cost by the cap, not by the contract.** A 120-clause agreement would
  otherwise be hundreds of LLM calls. Clauses are tiered HOT/WARM/COLD by rule evidence
  and category, capped at 24/60, so the worst case is ~30 calls. No tier suppresses a
  deterministic finding — a COLD clause with a rule finding still reports it, it just
  gets no model prose.
- **Every stage degrades on its own.** Measured on this Groq key: 12 concurrent
  structured-output calls succeed at ~0.8s, 40 concurrent rate-limit 45% of the time.
  Batches therefore fail individually rather than cancelling their siblings, and with
  Groq entirely unreachable the pipeline still produces a complete rule-based review —
  findings, gaps, consistency and all — with confidence capped at `0.60`.

Confidence is measured from five signals, not asserted: segmentation quality, character
coverage, quote grounding, finding provenance (rule vs model), and how well the review
knows what it is reading and for whom. An ungrounded quote caps the score at `0.50`, an
unknown reviewing side at `0.65`, a degraded LLM at `0.60`.

### API

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/contracts` | Upload and review synchronously |
| `POST` | `/api/v1/contracts/async` | Enqueue a review, returns a `contract_id` to poll |
| `GET` | `/api/v1/contracts/{id}` | Fetch a stored review, or its status while queued |
| `DELETE` | `/api/v1/contracts/{id}` | Delete the contract and its review |
| `GET` | `/api/v1/contracts/meta/supported` | Accepted formats, types, and the sides of each |

Uploads are capped at 15 MB and 200 pages, limited to 6 per minute per IP, and sniffed
by extension before the browser's declared type. A review is roughly thirty LLM calls
against one shared key, which is why the ceiling is far below the scenario endpoint's.

`DELETE` genuinely removes the row. The extracted text is retained so a finding's quote
stays re-verifiable, and a contract carries salaries, addresses and party names — a
retention promise the service cannot keep would be worse than none.

The long path has a real worker, which is where the Redis queue finally earns its place
(the scenario endpoint enqueues and then runs inline):

```bash
uv run python -m scripts.contract_worker
```

File bytes travel base64-encoded on the queue rather than through a shared path, since
the worker may be a different container.

### Asking the contract, redlines, export

`POST /api/v1/contracts/{id}/ask` answers a question from the clauses in the document
and says which ones it relied on. Retrieval is BM25 in process rather than a vector
store: a contract is at most a couple of hundred clauses, the same question must return
the same clauses every time, and most questions people ask of their own contract name
the thing they are asking about. A question the contract does not address is told so —
not answered from what contracts usually say, which is how a reader comes to believe
their agreement contains a protection it does not.

Every finding carries a **redline**: what to ask for, illustrative wording, and what to
settle for if refused. These are negotiation asks tied to the rule that fired, not
drafting to paste unread. `GET /api/v1/contracts/{id}/report.pdf` exports the review
leading with them, and carries the confidence basis rather than just the number.

### Evaluation

`scripts/evaluate_contract_review.py` scores the deterministic spine against ten
hand-labelled contracts in `tests/fixtures/eval/` — seven with known red flags and
three deliberately fair, so false positives are measured rather than assumed. A finding
counts only when rule **and** clause both match: the right rule on the wrong clause is a
segmentation bug wearing a correct answer's clothes.

```
precision 1.000  recall 1.000  f1 1.000   (40 TP / 0 FP / 0 FN over 10 contracts)
findings on clean contracts: 0   quote grounding failures: 0
```

The first run scored 0.950 recall and surfaced three real bugs: a category gate that
hid ouster-of-remedy language filed under "WAIVER", unilateral *price* variation not
being recognised as unilateral amendment, and loan repayment schedules not classifying
as payment terms. Model findings are not held to the answer key — they are not
reproducible enough for one — and their quality is checked by grounding instead.
`tests/test_evaluation.py` holds the floors (0.90 precision and recall, zero findings on
clean contracts) so a regression fails the build. The confidence estimator itself is
still uncalibrated; this measures the rules, not the score.

### Frontend

Streamlit multipage. `frontend/app.py` is the entrypoint; the two workbenches are
`frontend/pages/`. The contract page shows red flags, a clause-by-clause read, the
missing protections, consistency conflicts, the document with every finding highlighted
in place, and the full confidence basis.

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

### Legal corpus

2,336 sections indexed from twelve statutes, in three retrieval pools:

| Statute | Sections | Pool |
|---|---|---|
| Bharatiya Nyaya Sanhita, 2023 (BNS) | 358 | offence |
| Information Technology Act, 2000 | 109 | offence |
| Sexual Harassment of Women at Workplace Act, 2013 (POSH) | 30 | offence |
| Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS) | 533 | procedural |
| Constitution of India | 519 | procedural |
| Bharatiya Sakshya Adhiniyam, 2023 (BSA) | 170 | procedural |
| Indian Contract Act, 1872 | 192 | contract |
| Transfer of Property Act, 1882 | 135 | contract |
| Consumer Protection Act, 2019 | 107 | contract |
| Arbitration and Conciliation Act, 1996 | 93 | contract |
| Specific Relief Act, 1963 | 46 | contract |
| Digital Personal Data Protection Act, 2023 | 44 | contract |

The **contract** pool serves contract review and is never visible to either criminal
pass. Mixing it into the offence pool would be harmful in both directions: a lease
dispute would start surfacing BNS offences, and an assault scenario would start
surfacing lease covenants. `prescribes_penalty` cannot gate this pool the way it gates
penal law — only 1 of the Contract Act's 192 sections carries punishment language — so the
contract pass does not apply that filter.

Every Act except the four seed statutes is sourced from
**[India Code](https://indiacode.gov.in)**, the Government of India's official
legislative repository, via its DSpace REST API. Section text is copied verbatim and
never paraphrased. To refresh or add an Act, find its `act_id` and harvest it:

```bash
uv run python scripts/find_indiacode_act.py "Indian Contract Act"
uv run python scripts/fetch_indiacode_act.py <act_id> "<Short Tag>" data/<file>.json
```

Provisions that India Code marks as omitted or repealed are excluded — 16 for the IT
Act, including **s. 66A**, struck down in *Shreya Singhal v. Union of India* but still
printed in the bare Act, and 76 for the Contract Act, being ss. 76–123 (moved to the
Sale of Goods Act 1930) and ss. 239–266 (moved to the Partnership Act 1932). A repealed
section keeps its original title and replaces its body with a repeal note, so it is
detected from the body as well as the title — dead law that the analyst could otherwise
cite as though it were in force. Cognizability and bailability are not stated in the source text and are left
unset rather than inferred.

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
