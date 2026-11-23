# WhatLawSays — Local Setup (macOS)

Verified end-to-end on macOS (Darwin 25.3.0, Apple Silicon) on 2026-09-11.
This supplements `README.md`, which is accurate in outline but has a few gaps noted below.

**Layout (2026-11-23).** The backend lives in `backend/` and the React frontend in
`frontend/`. Run every `uv` command from `backend/` and every `npm` command from
`frontend/`. The Streamlit UI has been replaced; see section 8.

**Demo.** With uv, Node and Docker installed (sections 1 and 4), `./demo.sh` from the repository root
starts the Auth emulator, the backend on port 8010 and the app on 5173, with two
seeded demo accounts. It needs no Firebase project and no Groq key. See `DEMO.md`.
The demo accounts exist only in the emulator; the app offers them only when
built with `--mode demo` against the emulator, and a production build leaves
them out entirely.

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
cd backend
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

## 5. Configure `backend/.env`

```bash
cd backend
cp .env.example .env    # then set GROQ_API_KEY, FIREBASE_PROJECT_ID and DATABASE_URL
```

`src/config.py` is committed and holds no secrets: every value is read from the
environment or `backend/.env`, which stays gitignored. Keep keys in `.env`, never in
`config.py`.

### The model default is dead

`src/config.py:8` defaults to `llama-3.3-70b-versatile`, which Groq has **decommissioned**.
It returns `404 model_not_found`. Because each agent catches exceptions and falls back, the
pipeline still returns `SUCCESS` — while running **no LLM at all**. Check available models:

```bash
curl -s https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer $GROQ_API_KEY" | python3 -m json.tool | grep '"id"'
```

`src/config.py` used to be gitignored, so a fresh clone could not import the app at all.
It is now committed, with the measured contract-review defaults
(`CONTRACT_LLM_CONCURRENCY=4`, `CONTRACT_LLM_CALL_BUDGET=40` and the batch sizes).

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
cd backend && uv run uvicorn src.main:app --reload --port 8000   # API + docs at /docs
cd frontend && npm ci && npm run dev                             # UI at :5173, proxies to :8000
```

If port 8000 is taken (a local DynamoDB often is), run the API on another port and tell
Vite where it is: `BACKEND_URL=http://127.0.0.1:8010 npm run dev`.

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
cd backend && uv run pytest              # backend
cd frontend && npm test && npm run e2e   # frontend unit and end-to-end
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
cd backend && uv run uvicorn src.main:app --reload     # API, including /api/v1/contracts
cd backend && uv run python -m scripts.contract_worker # consumes queued reviews
cd frontend && npm run dev                             # the React app
```

Review a contract from the shell:

```bash
curl -X POST http://localhost:8000/api/v1/contracts \
  -H "Authorization: Bearer $ID_TOKEN" \
  -F "file=@my-offer-letter.pdf" \
  -F "contract_type=EMPLOYMENT" -F "position=EMPLOYEE"
```

`position` matters more than it looks: the same clause is scored CRITICAL for the
employee and INFO for the employer, because that is what it actually is.

Score the rules against the labelled contracts, and check the confidence score
still moves the right way when a review is degraded:

```bash
uv run python -m scripts.evaluate_contract_review --verbose
uv run python -m scripts.calibrate_confidence --verbose
```


---

## 8. Sign-in (Firebase) and the React frontend

### Firebase project

1. In the Firebase console, create a project (or pick one).
2. **Authentication → Sign-in method**: enable **Google** and **Email/Password**.
3. **Authentication → Settings → Authorized domains**: add your production domain.
   `localhost` is there already.
4. **Project settings → Your apps**: register a **Web app** and copy its config.
5. Put the config in `frontend/.env.local` (copy `frontend/.env.example`), and the
   project id in `backend/.env` as `FIREBASE_PROJECT_ID`.

The backend checks ID tokens against Google's public keys using only the project id;
it needs no service-account key. The web config is not secret, but it stays out of git.

### Without a Firebase project: the Auth emulator

```bash
cd frontend && npm run emulator                                   # :9099, no Java needed
cd backend && FIREBASE_PROJECT_ID=demo-whatlawsays \
  FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099 uv run uvicorn src.main:app --port 8010
cd frontend && npm run dev:emulator                               # uses .env.emulator
```

Verification emails are not sent by the emulator. Confirm an address by opening the
link it records:

```bash
curl -s http://127.0.0.1:9099/emulator/v1/projects/demo-whatlawsays/oobCodes
```

### Tests

```bash
cd frontend
npm run lint
npm test        # Vitest
npm run e2e     # Playwright against the emulator, using your installed Chrome
```

### Production

`docker compose up --build` builds one image: the React app is built in a Node stage and
served by FastAPI from the same origin as the API. Set the `VITE_FIREBASE_*` variables
in the shell or a root `.env` before building.

A contract review is a single request that can run for a couple of minutes. Any reverse
proxy in front of the API needs a read timeout of at least 600 seconds, or long reviews
are cut off.

Talk it through streams its answers as server-sent events
(`POST /api/v1/conversations/{id}/messages`). The proxy must pass the response through
unbuffered:
- **nginx:** honours the `X-Accel-Buffering: no` header the API sends; otherwise set `proxy_buffering off` for `/api/`.
- **Other proxies:** turn response buffering off, or the answer arrives in one piece at the end.
