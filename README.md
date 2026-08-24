# AI Data Analyst

Turn any structured Excel workbook into an analytics experience that behaves
like a data analyst rather than a dashboard generator.

```
Upload → Understand → Analyze → Discover → Prioritize → Explain → Visualize → Ask → Recommend → Report
```

Upload a workbook and the platform profiles it, scores its quality, picks the
metrics worth showing, detects trends and anomalies, ranks what it found by
analytical importance, builds a narrated Data Story, answers questions in plain
English, and produces a professional PDF or Excel report.

**Nothing is a mock.** Every engine described below is implemented and covered
by tests.

---

## The core promise

A traditional tool says:

> Revenue = ₹12.5M

A better tool says:

> Revenue increased 18% compared with the previous period.

This says:

> Revenue increased 18% compared with the previous period, primarily driven by
> the North region and Product A. However, the growth is concentrated in two
> categories, creating a potential concentration risk. Investigate whether the
> same growth pattern exists in other regions.

Each claim carries the columns, calculation, values and record count behind it.

---

## What it does

| | |
|---|---|
| **Understands any dataset** | Semantic types are inferred from *values*, not column names — currency, percentage, date, identifier, geographic, email, URL, boolean, categorical, text. No schema is hardcoded, so sales, HR, finance, student, survey and government data all work. |
| **Scores data quality** | A weighted 0–100 score with its reasoning, plus the *analytical impact* of every issue ("8.4% of records have no Region, so any regional breakdown understates that share") rather than a bare count. |
| **Selects KPIs** | 5–8 metrics chosen by relevance, magnitude, availability and analytical usefulness, with derived metrics (margin, conversion rate, per-customer averages) generated only when mathematically valid and always labelled with their formula. |
| **Detects trends** | OLS regression on an aggregation grain chosen from data density, incomplete boundary periods removed, seasonality, growth and decline runs, sudden changes, and a volume-vs-value decomposition that separates "more records" from "bigger records". |
| **Finds anomalies** | IQR fences confirmed by a modified z-score for records, de-trended residuals for time series, then an investigation pass that decomposes an anomalous period across every dimension — phrased as concentration and coincidence, never causation. |
| **Ranks insights** | Every finding gets a priority score from magnitude, unusualness, relevance, confidence, coverage and analytical importance, so a 32% revenue drop outranks a 1.1% move in average order value. |
| **Tells a Data Story** | Twelve sections from Executive Summary to Next Questions, ordered by analytical importance, each card carrying a headline, a supporting number, a chart, the evidence, a confidence level and a next step. |
| **Answers questions** | A controlled query layer: intent detection → column mapping → validated calculation. No code is ever generated or executed from a question. |
| **Produces reports** | Executive (2–5 pages), Standard (5–15) or Detailed (15+) PDFs with native charts, a table of contents, page numbers and a methodology appendix — plus a 17-sheet Excel analysis workbook. |

### It cannot make numbers up

The analytics engine is the source of truth. The default AI provider is
`deterministic`: narration is composed from calculated values and **no external
model is called at all**. When a model *is* configured it may only rephrase that
narration, and every figure in its response is checked against the evidence —
any unverifiable number causes the whole response to be discarded in favour of
the engine's wording. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#ai-layer).

---

## Quick start

### Docker (the whole stack)

```bash
cp .env.example .env
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"   # paste into .env
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))"  # paste into .env

docker compose up --build
```

Open <http://localhost:8080>, create an account, and load a sample dataset.

### Local development

Two terminals. **Backend:**

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt     # runtime deps plus the test runner
python -m app.samples.generate          # build the sample workbooks
uvicorn app.main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev                             # http://localhost:5173, proxies /api to :8000
```

With no `.env`, the backend runs on SQLite at `backend/data/app.db` and stores
uploads under `backend/data/uploads`. Interactive API docs are at
<http://localhost:8000/api/docs>.

---

## Environment variables

Every setting is environment driven, so the same image promotes unchanged from a
laptop to production. Copy [`.env.example`](.env.example) and fill it in.

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | generated per process | JWT signing key. **Set this in production** — a generated key invalidates every session on restart. |
| `ENVIRONMENT` | `development` | Reported by `/api/system/health`. |
| `DEBUG` | `false` | Verbose logging. |
| `DATABASE_URL` | `sqlite:///backend/data/app.db` | SQLAlchemy URL. Use `postgresql+psycopg2://…` in production. |
| `STORAGE_DIR` | `backend/data/uploads` | Where uploaded workbooks are written (mode `0600`, per-user subdirectories). |
| `MAX_UPLOAD_MB` | `100` | Rejected above this size. |
| `FILE_RETENTION_HOURS` | `72` | Uploads are deleted this long after a session was last touched. |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Comma-separated browser origins. |
| `ALLOW_REGISTRATION` | `true` | Set `false` to close signups on a shared deployment. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | Token lifetime. |
| `MAX_ROWS_ANALYZED` | `1000000` | Hard row cap per workbook. |
| `SAMPLE_ROWS_FOR_PROFILING` | `50000` | Profiling samples above this row count. |
| `MAX_CHARTS` | `14` | Cap on generated charts. |
| `MAX_PRIMARY_KPIS` | `8` | Cap on the headline KPI strip. |
| `REDIS_URL` | *(empty)* | Reserved for moving background analysis onto Celery. Nothing reads it today — analysis runs in an in-process worker pool. |
| `AI_PROVIDER` | `deterministic` | `deterministic`, `anthropic` or `openai`. |
| `AI_API_KEY` | *(empty)* | Required by the non-deterministic providers. |
| `AI_MODEL` | `claude-sonnet-4-5` | Model identifier. |
| `AI_BASE_URL` | `https://api.anthropic.com` | Override for a compatible endpoint. |
| `AI_ALLOW_RAW_ROWS` | `false` | Keep `false`: only aggregates, profiles and statistics are shared with a model. |

---

## Database setup

Tables are created automatically at startup (`init_db()`), so no migration step
is needed for a first run.

**PostgreSQL:**

```bash
createdb ai_data_analyst
export DATABASE_URL="postgresql+psycopg2://analyst:password@localhost:5432/ai_data_analyst"
```

Four tables: `users`, `analysis_sessions` (the analysis result is stored as
JSON), `query_logs` (an audit trail of natural-language questions) and
`shared_reports`. Alembic is included in `requirements.txt` for schema changes
once you are past the first deployment.

---

## AI configuration

The platform is fully functional with **no AI provider configured** — that is
the default and the recommended starting point.

```bash
# Default: no external model, nothing can be fabricated, no data leaves the box.
AI_PROVIDER=deterministic
```

To let a model improve the prose:

```bash
AI_PROVIDER=anthropic          # or: openai
AI_API_KEY=sk-...
AI_MODEL=claude-sonnet-4-5
```

What is sent: aggregated metrics, statistical results, data profiles and
schema — never the uploaded rows. Everything is sanitised and wrapped in a block
explicitly labelled as untrusted data. What comes back is verified figure by
figure against the calculated results before it is used.

`GET /api/system/config` reports the active provider and what it shares.

---

## Testing

```bash
cd backend
pip install -r requirements-dev.txt
pytest                      # 193 tests, on SQLite or PostgreSQL
pytest tests/test_e2e.py    # the journey, plus verification against pandas
pytest tests/test_security.py -v
```

```bash
cd frontend
npm run lint                # TypeScript, strict mode
npm run build
npm run e2e                 # 84 browser checks against the built bundle
```

Three layers: engine and API tests, an end-to-end suite that recomputes every
reported figure from the source workbook with plain pandas, and a browser
journey that drives the production bundle. See
[`docs/TESTING.md`](docs/TESTING.md).

---

## Production build

```bash
# Backend image
docker build -t ai-data-analyst-api ./backend

# Frontend image (static bundle behind nginx, proxying /api to the API service)
docker build -t ai-data-analyst-web ./frontend

# Or build both through compose
docker compose build
```

Deployment, scaling, backup and hardening notes are in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md), including a precise statement of
[what has and has not been verified](docs/DEPLOYMENT.md#what-has-and-has-not-been-verified)
— the images themselves have not been built, because the development
environment's egress policy blocks the base-image registry CDN.

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Module map, the pipeline stage by stage, the insight and evidence model, the AI safety layer, performance and extension points. |
| [`docs/API.md`](docs/API.md) | Every endpoint with request and response shapes, error codes and a worked example. |
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | How to use each of the eight sections, and how to read a confidence level. |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Production deployment, scaling, backups, retention and the security checklist. |
| [`docs/TESTING.md`](docs/TESTING.md) | What is covered, how to run it, and how to add a test. |

---

## Repository layout

```
backend/
  app/
    core/         configuration, database, security
    api/          HTTP routes and dependencies
    engines/      the analytics engines (see docs/ARCHITECTURE.md)
    services/     session lifecycle and background analysis
    samples/      generated sample datasets
    tasks/        the retention cleanup job
  tests/          193 tests
frontend/
  src/
    pages/        the eight workspace sections plus landing and sign-in
    components/   charts, insight cards, evidence panel, filters, drill-down
    context/      auth, theme and analysis state
    lib/          typed API client, formatting, types
docs/             architecture, API, user guide, deployment, testing
```

---

## Technology

React 18 · TypeScript · Tailwind CSS · Recharts · FastAPI · pandas · NumPy ·
SciPy · scikit-learn · OpenPyXL · XlsxWriter · ReportLab · SQLAlchemy ·
PostgreSQL · Docker.
