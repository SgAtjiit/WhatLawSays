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
│   │   ├── procurement_graph.py   # Third LangGraph: procurement compliance
│   │   ├── procurement_state.py   # TypedDict ProcurementGraphState
│   │   ├── procurement_nodes/     # profiler, statute_retriever, narrator,
│   │   │                          # narrative_verifier, compiler
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
│   │   ├── procurement_rules.py # Statutory checks + the 14 policy templates
│   │   ├── procurement_evidence.py # Path resolver, computation registry, verifier
│   │   ├── bid_integrity.py     # Collusion-pattern statistics, reported as indicators
│   │   ├── procurement_confidence.py # Procurement-review confidence estimator
│   │   ├── procurement_remediations.py # What to do, per check, per side
│   │   ├── procurement_service.py # Single entry point for an award review
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
│       ├── procurement.py       # Event, policy rules, Evidence union, findings
│       ├── procurement_review.py # Award review response envelope
│       ├── contract_review.py   # Model-facing payloads & the review response envelope
│       ├── legal.py             # Pydantic Schemas for Requests, Offenses, Actions & Duties
│       └── corpus.py            # Legal Section Data Schemas
├── scripts/
│   ├── ingest_legal_corpus.py   # Seed Data Ingestion Script (Batch & Async Setup)
│   ├── evaluate_procurement_review.py  # Precision/recall over labelled events
│   ├── calibrate_procurement_confidence.py # Reliability under degradation
│   ├── generate_sample_events.py       # Demo sourcing events
│   ├── generate_procurement_fixtures.py # The labelled evaluation set
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
clean contracts) so a regression fails the build.

### Does the confidence score mean anything

Strict calibration — when it says 0.7 it is right 70% of the time — needs far more
labelled reviews than ten contracts on which the rules are near-perfect. That remains
unfitted, and the score is still an estimate. What `scripts/calibrate_confidence.py`
does measure is **reliability**: each labelled contract is reviewed under seven
deliberate degradations, and the score must move the right way by the right amount.

| condition | predicted | observed | |
|---|---|---|---|
| everything healthy | 0.937 | 1.000 | |
| only half the contract analysed | 0.832 | 1.000 | |
| cross-encoder unavailable | 0.750 | 1.000 | capped |
| clause boundaries guessed | 0.700 | 0.754 | capped |
| no reviewing side declared | 0.650 | 0.912 | capped |
| a quote not in the document | 0.622 | 0.964 | capped |
| no model reached at all | 0.600 | 1.000 | capped |

Every gap is the score reading *lower* than measured quality, which is the right
direction to be wrong in here. The ordering and the caps are asserted in
`tests/test_calibration.py`, so an estimator change that makes a review
over-confident fails the build.

Building this found a real miscalibration: with no clause numbering anywhere, every
boundary is a guess, yet the weighted mean alone still reported 0.81 — segmentation
carries only 0.20 of the weight and could not express it. It is now capped at 0.70,
which the measurement puts within 0.05 of observed quality.

### Frontend

Streamlit multipage. `frontend/app.py` is the entrypoint; the workbenches are in
`frontend/pages/`. The contract page shows red flags, a clause-by-clause read, the
missing protections, consistency conflicts, the document with every finding highlighted
in place, and the full confidence basis.

---

## 🧾 Procurement Compliance

A third LangGraph pipeline checks a **sourcing event** — the bid tab, the approvals
and the award — against the buying organisation's own procurement policy and against
Indian statute, before the purchase order is released. It shares the corpus and
retrieval of the other two and answers a third question, so it is a third graph
rather than extra nodes on either.

```
normalize event + evaluate checks + bid integrity + PO sub-review  (all deterministic,
                                                                    outside the graph)
  -> event_profiler -> statute_retriever -> narrator
  -> narrative_verifier --(a number not in the review)--> narrator
  -> procurement_compiler
```

- **The compliance determination is entirely deterministic.** Evaluation runs *before*
  `ainvoke`, which is the opposite of where the contract pipeline puts its rules, and
  for a reason: there, relabelling a clause legitimately changes which rules apply, so
  the model's output is an input to the rules. Here the event is typed, structured data
  and nothing a model does can change what a check reads. Running the engine first means
  the retry loop can never move a value out from under recorded evidence, a total LLM
  outage still yields the complete finding set, and `evaluate_procurement` stays a pure
  function the harness can score without standing Qdrant or Groq up.
- **The model does not propose findings here, and that is not timidity.** A contract is
  arbitrary prose, so a model can genuinely notice something no rule encodes — hence
  `red_flag_analyst`. A sourcing event is structured data with a fixed schema, and every
  field is already visible to every check. There is no unread text to find something in,
  so a model "finding" would not be a reading of the data; it would be an invented rule,
  arrived at once, unreproducibly, next to findings that carry statutory citations. What
  the model does is write the review up. Every number it writes is checked against the
  material it was shown, and one that is not there sends the narrative back to be
  rewritten — a wrong figure about somebody's money reads exactly like a right one.
- **A missing collection is not an empty one.** `approvals: []` would be the worst bug
  this feature could ship: a payload that simply omits its approvals array reads exactly
  like an award nobody approved, and the difference is "we could not check" versus
  "nobody signed it". `ProcurementEvent.provided_collections` is the caller's explicit
  statement of what it supplied, an `AbsenceEvidence` outside that set can support only
  `UNDETERMINED`, and the API refuses a payload that does not declare it.
- **Nothing here certifies compliance.** There is no `COMPLIANT` status and no compliance
  percentage. `OverallStatus` tops out at `NO_BREACH_FOUND`, and any material check that
  could not be performed makes it `NO_BREACH_FOUND_WITH_GAPS`. Breaches, indicators and
  gaps are three separate lists in the response and three separate tabs in the UI,
  because a reader scanning one list will read a gap as a pass.
- **A bid pattern is never a finding of collusion.** Section 3(3)(d) presumes an adverse
  effect once bid rigging is *established*, and what s.3(3) attaches to is an agreement
  between bidders — which a bid tab cannot establish. So every integrity signal is
  `INDICATOR`, never `BREACH`; severity is capped below CRITICAL; titles are prefixed
  "Indicator:"; corroboration is listed on one finding rather than raising severity; and
  no LLM touches the wording, because a model asked to explain a bid pattern writes that
  the vendors colluded. All of it is asserted in `tests/test_bid_integrity.py`.
- **A finding is only meaningful relative to a side**, as in contract review. A
  supplier-side review runs every statutory check and the purchase order's own terms,
  and reports the buyer's internal controls as `NOT_APPLICABLE` — a delegation of
  authority is not an obligation the supplier owes anyone. The same MSMED finding then
  produces opposite instructions: the buyer is told to cut the term to 45 days before
  release; the supplier is told the term is void to that extent and interest accrues
  whatever they signed.

### Grounding structured data

Contract review grounds a finding with a verbatim quote and offsets, and `verify_quotes`
re-derives the span. Most procurement findings are about structured facts instead —
"policy requires three quotes, the event carries two" — where there is no span to quote.
`Evidence` generalises grounding to four kinds, and `verify_evidence` holds all four to
the same standard rather than a softer one:

| kind | how it is re-derived |
|---|---|
| `DOCUMENT_SPAN` | the same whitespace-normalised string comparison `verify_quotes` uses |
| `FIELD` | the path is re-resolved against the event and the stated comparison re-run |
| `ABSENCE` | checked against `provided_collections`; outside it, supports only UNDETERMINED |
| `DERIVED` | the registered computation is **re-executed** and must give the same Decimal |

A path that resolves to *two* elements is an `AMBIGUOUS` failure, not a first-match —
the direct analogue of a quote appearing twice with no way to tell which was meant. Every
`field_path` comes from a check's declared `reads` tuple, which is code, so no model ever
writes one. Anything that fails re-derivation is dropped by the compiler and named in
`dropped_findings`, and confidence is computed on the pre-drop list so the drop still
costs score.

Every figure is `Decimal`, never float: verification is equality-based, float arithmetic
does not reliably give the same answer twice, and a flaky verifier is a disabled one.

### Policy: the model drafts, a person ratifies

A procurement manual is prose; the checks need parameters. This is the only place a model
comes near a rule, and it does not break "rules first, model second" because the
predicates are a closed registry of 14 hand-written, regression-tested functions. The
model chooses a `PolicyCheckKind` and fills typed parameter slots; it cannot write a
comparison. A `MODEL_DRAFT` rule with no grounding quote cannot even be constructed — the
validator rejects it.

`DRAFT → RATIFIED | EDITED | REJECTED`, and only ratified or edited rules in an
**activated** set are ever enforced. Editing a rule transfers it to the person: `origin`
becomes `HUMAN` and the grounding quote is cleared, because it evidenced what the model
read and that is no longer what the rule says. An activated version is immutable, so a
review from six months ago stays re-derivable against the rules that actually produced
it. Running against unratified rules is opt-in, marks every finding `provisional`,
excludes them from every count, and caps confidence at **0.45**.

### Checks

| family | count | examples |
|---|---|---|
| Statute | 6 | MSMED s.15 payment ceiling, s.16 interest exposure, Companies Act s.188 / s.177 related-party approval, DPDP s.8 processor agreement |
| Policy | 14 | quote counts by value, delegation of authority, approval before commitment, structuring across a threshold, scope drift, late bids, budget |
| Bid integrity | 7 | near-identical totals, constant spread, identical unit prices, shared PAN root across GSTINs, cover bidding, rotating winners |

MSMED s.15 is **not** a flat 45 days, and reading it that way would clear terms that are
already outside the section. Where the period is agreed in writing the proviso caps it at
45 days; where there is no written agreement the appointed day is **15**. So a 30-day term
is compliant with a written agreement, a breach without one, and `UNDETERMINED` when
nobody has said which — a fact that is itself often absent. Chapter V protects micro and
small enterprises only (s.2(n)), so a medium enterprise is `NOT_APPLICABLE`, not a breach.
And s.16's quantum is three times the *RBI bank rate* compounded monthly over a changing
rate, so the system reports that interest is running and returns `UNDETERMINED` for the
amount rather than quoting a rate hardcoded at build time.

### API

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/awards` | Review an event, optionally with the purchase order |
| `GET` | `/api/v1/awards/{id}` | Fetch a stored review |
| `DELETE` | `/api/v1/awards/{id}` | Delete the review and its event snapshot |
| `GET` | `/api/v1/awards/{id}/actions` | What to do, worst first |
| `GET` | `/api/v1/awards/{id}/report.pdf` | The review as an audit memo |
| `POST` | `/api/v1/policies` | Create a rule set |
| `PATCH` | `/api/v1/policies/{id}/rules/{rule_id}` | Ratify, edit or reject one rule |
| `POST` | `/api/v1/policies/{id}/activate` | Freeze a version and put it in force |
| `GET` | `/api/v1/procurement/meta/checks` | The full check catalogue |

The catalogue is published rather than kept internal: it is what makes a ratification UI
buildable, and it is the honest public statement of the system's reach — a reader can see
what is *not* on it and know it was not checked.

There is no async queue here, deliberately. A contract review is roughly thirty LLM calls,
which is what earns `contract_worker` its place; a procurement review is one, because the
compliance work is deterministic. A queue would be the decorative kind the scenario
endpoint already has.

`DELETE` genuinely removes the row. A bid tab carries vendor pricing, PAN and bank
details — commercially sensitive in the same way a contract carries salaries.

### Evaluation

`scripts/evaluate_procurement_review.py` scores the deterministic spine against sixteen
hand-labelled events in `tests/fixtures/procurement_eval/` — thirteen with known findings
and three deliberately clean, so false positives are measured rather than assumed. The
match key is `(check_id, subject_ref, status)`: the right check on the wrong vendor is a
normalisation bug wearing a correct answer's clothes, and reporting `BREACH` where the key
says `UNDETERMINED` is not a near miss — it is the specific failure this feature exists to
prevent, so it counts as both a false positive and a false negative.

```
precision 1.000  recall 1.000  f1 1.000   (32 TP / 0 FP / 0 FN over 16 events)
findings on clean events: 0   evidence verification failures: 0
UNDETERMINED sold as PASS: 0   as BREACH: 0   INDICATOR sold as BREACH: 0
```

The clean fixtures earned their place on the first run: `CONSTANT_SPREAD` fired on an
ordinary 790k/845k/902k three-bid spread. With three bids there are only two gaps to
compare, and two numbers always look consistent — a signal that fires on what a
competitive market routinely produces is measuring having too little data, not collusion.
It now requires four bids. `tests/test_procurement_evaluation.py` holds the floors,
including three zero-tolerance counters and a guard that every check in the registry has a
labelled event, so a new check cannot ship unexercised.

### Does the confidence score mean anything

The same question the contract estimator answers, measured the same way: each labelled
event is reviewed under eight deliberate degradations, and the score must move the right
way by the right amount.

| condition | predicted | observed | |
|---|---|---|---|
| everything supplied | 0.817 | 1.000 | |
| cross-encoder unavailable | 0.706 | 1.000 | capped |
| no model reached at all | 0.600 | 1.000 | capped |
| vendor MSME status unknown | 0.675 | 0.812 | capped |
| caller did not declare what it supplied | 0.650 | 0.802 | capped |
| no procurement policy at all | 0.684 | 0.667 | capped |
| evidence that will not re-derive | 0.500 | 1.000 | capped |
| enforcing unratified rules | 0.450 | 1.000 | capped |

This harness also found a real miscalibration, and the shape is familiar. A statute-only
review scored **0.889** against a full review's 0.817 — *higher* — because dropping
`policy_authority` renormalised the weights over four components that were all near 1.0.
The estimator was rewarding a review for never having looked at the customer's policy.
`STATUTE_ONLY_CAP = 0.70` came out of that measurement and sits within 0.02 of observed
quality. It is the same failure `PARAGRAPH_FALLBACK_CAP` fixed in contract review: a
weighted mean can express a component's *value*, never its absence.

One cap crosses a pipeline boundary. Where any finding rests on the purchase order
document, the procurement score cannot exceed the confidence of the contract sub-review
that read it — a purchase order is usually an unnumbered form, so that sub-review
routinely lands on `PARAGRAPH_FALLBACK_CAP`, and burying it inside a nested payload would
let a 0.91 headline sit on top of a 0.70 document read.

### Frontend

Two more Streamlit pages. `📐 Policy Library` drafts, ratifies and activates rule sets and
publishes the check catalogue. `🧾 Award Review` takes a sample event, pasted JSON or an
uploaded purchase order, and shows Breaches, Bid Integrity, Could Not Be Checked, What To
Do, Every Check, Confidence and Raw JSON as separate tabs.

```bash
uv run python scripts/generate_sample_events.py      # six demo events
uv run python -m scripts.evaluate_procurement_review --verbose
uv run python -m scripts.calibrate_procurement_confidence --verbose
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

### Legal corpus

2,894 sections indexed from fifteen statutes, in four retrieval pools:

| Statute | Sections | Pool |
|---|---|---|
| Bharatiya Nyaya Sanhita, 2023 (BNS) | 358 | offence |
| Information Technology Act, 2000 | 109 | offence |
| Sexual Harassment of Women at Workplace Act, 2013 (POSH) | 30 | offence |
| Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS) | 533 | procedural |
| Constitution of India | 484 | procedural |
| Bharatiya Sakshya Adhiniyam, 2023 (BSA) | 170 | procedural |
| Indian Contract Act, 1872 | 192 | contract |
| Transfer of Property Act, 1882 | 135 | contract |
| Consumer Protection Act, 2019 | 107 | contract |
| Arbitration and Conciliation Act, 1996 | 92 | contract |
| Specific Relief Act, 1963 | 46 | contract |
| Digital Personal Data Protection Act, 2023 | 44 | contract, procurement |
| Companies Act, 2013 | 483 | procurement |
| Competition Act, 2002 | 79 | procurement |
| Micro, Small and Medium Enterprises Development Act, 2006 | 32 | procurement |

Counts are what the collection actually holds after `is_dead_law` filtering, not what the
source files contain -- the table previously summed to 2,336 against 2,300 indexed.

The **procurement** pool adds the three Acts an award actually turns on, none of which
was reachable by either earlier pipeline. It also draws on the Contract Act and the DPDP
Act, which sit in the contract pool too -- a pool is a retrieval filter, not an ownership
claim, so an Act may belong to more than one. Measured against this corpus the pool
returns the governing provision at rank 1 for each of the questions it exists to answer:
MSMED s.15 for a delayed-payment query, s.16 for interest, Competition Act s.3 for bid
rigging, Companies Act s.188 for a related-party award -- and the Companies Act's 483
sections do not crowd out the 32 of the MSMED Act, because the act filter is applied
inside both prefetches.

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
