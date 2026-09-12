# WhatLawSays — Local Setup (macOS)

Verified end-to-end on macOS (Darwin 25.3.0, Apple Silicon) on 2026-09-11.
This supplements `README.md`, which is accurate in outline but has a few gaps noted below.

---

## 0. What actually has to be true

| Requirement | Why |
|---|---|
| Python **3.13+** | `pyproject.toml` sets `requires-python = ">=3.13"` |
| `uv` | project uses a uv-managed venv + lockfile |
| A **valid Groq model** | without it the agents silently degrade to rule-based fallbacks |
| Qdrant | needed for retrieval (Docker, or embedded fallback) |
| Redis / Postgres | **optional** — both degrade gracefully to in-memory |

Docker is optional. Every backing service has a fallback:

- Qdrant unreachable → embedded on-disk Qdrant at `./qdrant_db` (`src/core/vector_store.py:44`)
- Redis unreachable → in-memory asyncio queue (`src/core/task_queue.py:27`)
- Postgres unreachable → in-memory result cache (`src/core/database.py:48`)
- Cross-encoder unavailable → RRF score fallback (`src/core/reranker.py:19`)

---

## 1. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"     # add to ~/.zshrc to persist
uv --version
```

## 2. Rebuild the virtualenv on Python 3.13

The `.venv` shipped in the working tree was Python 3.9 (pip-created) and cannot satisfy
`requires-python = ">=3.13"`. Remove it and let uv rebuild:

```bash
cd /Users/abcom/Desktop/WhatLawSays
rm -rf .venv
uv sync
uv run python -c "import sys; print(sys.version)"   # expect 3.13.x
```

## 3. Add the missing `greenlet` dependency

SQLAlchemy's async engine requires `greenlet`, which was not declared. Without it every
database call fails with `ValueError: the greenlet library is required to use this function`,
which the code swallows into a misleading "PostgreSQL instance unauthenticated" warning.

```bash
uv add greenlet
```

## 4. Start the backing services

```bash
open -a Docker                                  # wait for the daemon
docker compose up -d qdrant redis postgres      # NOT the `api` service — it collides with local uvicorn on :8000
docker compose ps
```

Health checks:

```bash
curl -s http://localhost:6333/healthz
docker exec whatlawsays-redis-1 redis-cli ping
docker exec whatlawsays-postgres-1 pg_isready -U postgres
```

### Port-collision caveat (macOS)

This machine already runs **native Postgres and Redis** bound to `127.0.0.1:5432` / `127.0.0.1:6379`.
Docker only binds the `*` wildcard, so `localhost` resolves to the **native** services first — the
containers for redis and postgres are started but unused. Only Qdrant (`:6333`) actually comes
from Docker.

Check what owns a port:

```bash
lsof -iTCP:5432,6379,6333 -sTCP:LISTEN -n -P
```

The native Postgres has no `postgres` role (its superuser is your macOS username), which is why
the container credentials from `docker-compose.yml` fail. Two ways out — this setup used (a):

**(a) Use the native Postgres** — create the database and point the app at it:

```bash
psql -h 127.0.0.1 -U "$USER" -d postgres -c "CREATE DATABASE whatlawsays;"
# DATABASE_URL="postgresql+asyncpg://$USER@127.0.0.1:5432/whatlawsays"
```

**(b) Use the container** — remap it in `docker-compose.yml` to `"5433:5432"` and set
`DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/whatlawsays"`.

## 5. Configure `.env`

```bash
cat > .env <<'EOF'
PROJECT_NAME="WhatLawSays Backend"
API_V1_STR="/api/v1"
GROQ_MODEL="openai/gpt-oss-120b"
QDRANT_URL="http://localhost:6333"
REDIS_URL="redis://localhost:6379/0"
DATABASE_URL="postgresql+asyncpg://abcom@127.0.0.1:5432/whatlawsays"
EOF
```

### The model default is dead

`src/config.py:8` defaults to `llama-3.3-70b-versatile`, which Groq has **decommissioned**.
It returns `404 model_not_found`. Because each agent catches exceptions and falls back, the
pipeline still returns `SUCCESS` — while running **no LLM at all**. Check available models:

```bash
curl -s https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer $GROQ_API_KEY" | python3 -m json.tool | grep '"id"'
```

`GROQ_API_KEY` is not in `.env` above because `src/config.py` carries a working default.
Note that `src/config.py` is **gitignored** (the bare `config.py` pattern in `.gitignore`
catches it), so a fresh clone has no config at all and the app will not import — set
`GROQ_API_KEY` in `.env` in that case.

If you recreate `src/config.py`, the contract-review pipeline also needs these fields on
`Settings` (values are the measured defaults; see the comments in the file for why):

```python
CONTRACT_LLM_CONCURRENCY: int = 4     # 12 concurrent succeed, 40 rate-limit 45%
CONTRACT_LLM_CALL_BUDGET: int = 40    # worst case is ~30 calls; room for retries
CONTRACT_HOT_BATCH: int = 4
CONTRACT_WARM_BATCH: int = 10
CONTRACT_CLASSIFY_BATCH: int = 12
```

Without them `settings.CONTRACT_LLM_CONCURRENCY` raises and every contract review fails.

## 6. Seed the legal corpus

Indexes 2336 sections (BNS, BNSS, BSA, Constitution, IT Act, POSH Act, and the
contract pool: Contract Act, TPA, CPA, Arbitration Act, SRA, DPDP Act). Point ids are
derived from act + section, so re-running is idempotent. The first run downloads the
`bge-small-en-v1.5` and `Qdrant/bm25` ONNX models. Takes ~2 minutes.

```bash
uv run python -m scripts.ingest_legal_corpus
```

Verify:

```bash
curl -s http://localhost:6333/collections/whatlawsays_legal_corpus \
  | python3 -c "import sys,json; d=json.load(sys.stdin)['result']; print(d['points_count'], d['status'])"
# -> 2336 green
```

## 7. Run it (two terminals)

```bash
uv run uvicorn src.main:app --reload --port 8000   # API + docs at /docs
uv run streamlit run frontend/app.py               # UI at :8501, defaults to the :8000 backend
```

> With embedded Qdrant (no Docker), `./qdrant_db` is locked by a single process — ingest and the
> API cannot run at once, and `--reload` can trip over it. Run Qdrant in Docker to avoid this.

---

## Verifying it works

```bash
curl -s http://localhost:8000/health
# {"status":"healthy","service":"whatlawsays-backend"}

curl -s -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"scenario_text":"My neighbour broke into my locked house at night and stole my laptop.","jurisdiction":"India"}' \
  | python3 -m json.tool
```

Expect `status: SUCCESS`, 9 offenses led by BNS Section 303 (Theft), each with
`punishment_severity`, `cognizable`, and `bailable` populated, and a confidence in
the **0.80–0.95** band.

Confidence is measured per request, not fixed, so do not assert an exact value: it
moves with how decisively retrieval separated a best match, how many statutory
elements the facts actually support, whether verification passed on the first
attempt, and how many facts the scenario left unknown. The `confidence_basis` object in the response shows the
per-component breakdown behind the number.

If a component degraded, confidence is capped and `confidence_basis.caps_applied`
says which: `llm_fallback<=0.60`, `reranker_fallback<=0.75`,
`ungrounded_citation<=0.50` (a cited section absent from the retrieved corpus), or
`undetermined<=0.45`. The estimator never returns above `0.95` or below `0.05`.

The README's President's-residence scenario is the no-offence path. It resolves one
of two ways, which the previous build collapsed into a single hardcoded `0.35`:

| Outcome | When | Confidence |
|---|---|---|
| `status: SUCCESS`, `offense_status: NOT_ESTABLISHED` | relevant law retrieved and its elements are contradicted by the facts | high — an affirmative finding |
| `status: UNDETERMINED`, `offense_status: UNDETERMINED` | weak retrieval, or nothing contradicted | low, capped at `0.45` |

Persistence:

```bash
psql -h 127.0.0.1 -U "$USER" -d whatlawsays -c \
  "select task_id, status, confidence_score from legal_analysis_records order by 1 desc limit 5;"
```

Tests:

```bash
uv run pytest tests/     # 3 passed
```

### Reading the pipeline log

The API logs every stage in colour as the request flows through the graph. One request
produces this sequence — watching it is the fastest way to see the pipeline working:

```
[API GATEWAY]          request intake, rate-limit check, task id assigned
[TASK QUEUE (REDIS)]   task enqueued
[WORKER CONSUMER]      LangGraph orchestrator invoked
[AGENT 1: FACT EXTRACTOR]              established / alleged / unknown facts
[AGENT 2: LEGAL QUERY BUILDER]         fact-clean retrieval queries
[QDRANT VECTOR STORE]                  act-scoped hybrid search, two pools:
                                       BNS/IT/POSH (offences) + BNSS/BSA/Constitution (procedural)
[STEP 3: LEGAL RERANKER]               each pool reranked independently, top-N -> top-K
[AGENT 3: LEGAL ANALYST]               statutory elements, exceptions, actions
[AGENT 4: VERIFICATION AGENT]          claim -> evidence -> fact judge
[STEP 5: RESPONSE COMPILER]            confidence estimate, final response
[POSTGRESQL DB]        record persisted
[CLIENT API]           JSON returned
```

**`WARNING` lines mean a component silently degraded** — worth watching:

| Log line | Meaning |
|---|---|
| `Groq API Info (NotFoundError). Using Rule-Based ...` | LLM is **not** running — bad model id |
| `Local PostgreSQL instance unauthenticated` | DB unreachable, or `greenlet` missing |
| `Cross-encoder unavailable (ImportError)` | reranker stage skipped (see below) |

Each of those degradations now also caps the confidence estimate, so a silently
degraded pipeline can no longer report the same confidence as a healthy one.
| `Redis connection fallback` | using the in-memory queue |

---

## Known issues

1. **Reranker never runs.** `src/core/reranker.py:16` imports
   `fastembed.rerank.cross_encoder.TextReRanker`, which does not exist in fastembed 0.8.
   It always falls back to RRF scoring, so the `bge-reranker-base` stage advertised in the
   README is inactive. Retrieval still works.
2. **README references scripts that do not exist**: `scripts/test_pipeline.py`,
   `test_hybrid_search.py`, `test_president_invitation.py`. Only `ingest_legal_corpus.py` is present.
3. **`docker-compose.yml` has an obsolete `version:` key**, which Docker warns about on every command.
4. **`@app.on_event("startup")`** (`src/main.py:34`) is deprecated in current FastAPI;
   use a lifespan handler.

---

## Teardown

```bash
kill $(lsof -ti:8000) $(lsof -ti:8501)
docker compose down          # add -v to drop volumes
```


## Contract review

Start the API, the worker, and the UI:

```bash
uv run uvicorn src.main:app --reload            # API, including /api/v1/contracts
uv run python -m scripts.contract_worker        # consumes queued reviews
uv run streamlit run frontend/app.py            # multipage UI
```

Review a contract from the shell:

```bash
curl -X POST http://localhost:8000/api/v1/contracts \
  -F "file=@my-offer-letter.pdf" \
  -F "contract_type=EMPLOYMENT" -F "position=EMPLOYEE"
```

`position` matters more than it looks: the same clause is scored CRITICAL for the
employee and INFO for the employer, because that is what it actually is.

Score the rules against the labelled contracts:

```bash
uv run python -m scripts.evaluate_contract_review --verbose
```
