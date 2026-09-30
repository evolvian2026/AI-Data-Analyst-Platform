# Deployment

## Prerequisites

* Docker 24+ with Compose v2, or Python 3.11+ and Node 20+ for a bare-metal
  install.
* PostgreSQL 14+ in production. SQLite is the zero-configuration default and is
  fine for a single-user evaluation, but it serialises writes and will not
  survive a container restart unless the file is on a volume.
* A TLS terminator in front of the stack. The application never assumes it is
  reachable over plain HTTP but does not terminate TLS itself.

---

## Deploying with Compose

```bash
python3 scripts/init-env.py
```

That creates `.env` from `.env.example` and generates the two secrets Compose
will not start without. Copying the example by hand is not enough: it leaves
`SECRET_KEY` and `POSTGRES_PASSWORD` deliberately blank, and Compose treats an
empty required variable exactly like a missing one.

The script only fills values that are still blank. That matters for
`POSTGRES_PASSWORD` in particular — see the warning below before you change it
on a stack that has already run.

Set `CORS_ORIGINS` to the origin browsers will actually use, then:

```bash
docker compose up --build -d
docker compose ps
curl -fsS http://localhost:8080/api/system/health
```

Four services come up:

| Service | Role |
|---|---|
| `db` | PostgreSQL with a named volume. |
| `api` | FastAPI on Uvicorn with two workers, uploads on a named volume. Single-stage image: every dependency ships a prebuilt wheel, so it needs no compiler and installs nothing from apt — the health check uses the Python already in the image rather than curl. Budget 4 GB of memory for the build; the scientific wheels are large. |
| `web` | The built frontend behind nginx, proxying `/api` to `api`. |
| `cleanup` | Runs both retention sweeps hourly: uploaded files, and analyses once `RESULT_RETENTION_DAYS` is set. |

There is deliberately no Redis service: analysis runs in an in-process worker
pool and nothing connects to a queue today. Add Redis when you wire up Celery
(see [Scaling](#scaling)) rather than running a container nothing talks to.

### Behind a reverse proxy

Point your proxy at the `web` service and forward the standard headers:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    client_max_body_size 120M;   # must exceed MAX_UPLOAD_MB
    proxy_read_timeout   300s;   # analysis of a large workbook
}
```

Two settings must agree with your proxy or uploads will fail confusingly:
`client_max_body_size` has to exceed `MAX_UPLOAD_MB`, and the read timeout has
to outlast the longest analysis you expect.

---

## Bare metal

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # add -dev to also run the tests
export SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
export DATABASE_URL="postgresql+psycopg2://analyst:password@localhost:5432/ai_data_analyst"
export STORAGE_DIR=/var/lib/ai-data-analyst/uploads
python -m app.samples.generate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

```bash
# Frontend
cd frontend
npm ci
VITE_API_URL="https://analytics.example.com" npm run build
# serve ./dist with nginx, Caddy or any static host
```

Schedule the retention sweep:

```cron
0 * * * * cd /srv/ai-data-analyst/backend && .venv/bin/python -m app.tasks.cleanup
```

---

## Production checklist

**Before the first real upload**

- [ ] `SECRET_KEY` set explicitly. Without it a key is generated per process,
      so every restart signs out every user, and multiple workers reject each
      other's tokens.
- [ ] `DATABASE_URL` points at PostgreSQL, not the SQLite default.
- [ ] `STORAGE_DIR` is on a persistent, backed-up volume.
- [ ] `CORS_ORIGINS` lists only origins you control.
- [ ] `ALLOW_REGISTRATION=false` if the deployment is not open to the public.
- [ ] TLS terminated in front; HSTS enabled.
- [ ] `FILE_RETENTION_HOURS` matches your data-handling policy — this bounds
      the uploaded workbook.
- [ ] `RESULT_RETENTION_DAYS` matches it too. This bounds the *analysis*, which
      holds aggregates, column names and sample values drawn from the upload.
      It defaults to `0` (keep indefinitely) because an upgrade must not start
      deleting a user's analyses unasked — so it is a deliberate choice, not a
      default you can leave alone if you have a policy.
- [ ] `AI_PROVIDER` is a deliberate choice. `deterministic` sends nothing
      anywhere; the others send aggregates and profiles to a third party.
- [ ] `AI_ALLOW_RAW_ROWS` left `false`.

**Operationally**

- [ ] Back up the database (the analysis results live there) and the uploads
      volume.
- [ ] Monitor `/api/system/health`. The `api`, `web` and `db` containers each
      declare a Docker health check; `cleanup` deliberately does not, because it
      runs the retention loop rather than a server and an HTTP check there would
      report it permanently unhealthy. Its liveness is covered by
      `restart: unless-stopped`, and each sweep logs what it removed.
- [ ] Watch disk on the uploads volume — the retention sweep bounds it, but a
      short retention window with heavy use still needs headroom.
- [ ] Ship logs somewhere durable. Every request carries an `X-Request-ID` that
      appears in the log line for the same request.

---

## Scaling

**The API is stateless** apart from the uploads directory and the in-process
frame cache, so it scales horizontally as long as every replica sees the same
`STORAGE_DIR` (shared volume, NFS or object storage) and the same database.

**Analysis runs in a worker pool inside the API process.** That is the right
default: it removes a moving part, and analysis is measured in seconds. When it
stops being right — long-running analyses of very large workbooks starving
request handling, or a need to scale workers separately — add a Redis service,
add `celery` to `requirements.txt`, set `REDIS_URL`, and move
`analysis_service.schedule_analysis()` onto a Celery task. The service boundary
is already in place; only the dispatch call changes.

**Tuning knobs**

| Variable | Raise it when | Lower it when |
|---|---|---|
| `MAX_ROWS_ANALYZED` | You need whole large workbooks analysed. | Memory pressure. |
| `SAMPLE_ROWS_FOR_PROFILING` | Profiling accuracy on wide datasets matters more than speed. | Profiling is the slow stage. |
| `MAX_CHARTS` | Analysts want more views. | Payloads are large. |
| `RESULT_RETENTION_DAYS` | Never — raise means keep longer, so raise it only if your policy allows. | Your policy requires a shorter window; also bounds database growth. |
| Uvicorn `--workers` | CPU-bound analysis is queueing. | Memory per worker is tight — each holds its own frame cache. |

Rough sizing: a 5,000-row, 15-column workbook completes the full pipeline in
about two seconds and produces roughly a 1.5 MB analysis payload. Budget around
500 MB of memory per worker for workbooks in the low hundreds of thousands of
rows.

---

## Backup and recovery

| What | Where | Why it matters |
|---|---|---|
| Database | `db-data` volume | Contains users, sessions, insight ratings and **every analysis result**. Losing it loses the reports. |
| Uploads | `uploads` volume | Only needed to re-explore rows or re-analyse. Retention-swept anyway, so a shorter backup horizon is reasonable. |

```bash
# Database
docker compose exec -T db pg_dump -U analyst ai_data_analyst | gzip > backup-$(date +%F).sql.gz

# Restore
gunzip -c backup-2026-08-24.sql.gz | docker compose exec -T db psql -U analyst ai_data_analyst
```

Uploads are disposable by design: an analysis whose file has been swept still
serves its report, and the UI explains that the file must be re-uploaded to
explore rows again.

**Two windows, deliberately separate.** `FILE_RETENTION_HOURS` removes the raw
rows — the most sensitive artefact — while keeping the analysis readable.
`RESULT_RETENTION_DAYS` removes the analysis itself, which still contains
aggregates, column names and sample values taken from the file. Set both to
match your policy; a retention sweep with `RESULT_RETENTION_DAYS=0` touches only
files, which is the historical behaviour.

Deleting an analysis is a hard delete: its notes, query log and share links
cascade with it.

---

## Upgrading

```bash
git pull
docker compose build
docker compose up -d
```

Tables are created on startup, so a first deployment needs no migration step,
and a release that only *adds a table* upgrades by restart alone — which is
tested, not assumed.

`create_all()` has one sharp edge worth knowing before you rely on it: it
creates missing **tables** but never adds a missing **column** to a table that
already exists. A release that changes an existing table therefore needs a real
migration even though the last one did not. `test_every_model_column_exists_in_a_freshly_created_schema`
fails the moment the models and a created schema disagree, which is the signal
to write one with Alembic (already in `requirements.txt`).

---

## What has and has not been verified

Being precise about this matters more than a green tick.

**Verified**

- **Both images build, and the whole stack runs.** `docker compose up --build`
  brings up db, api, web and cleanup; the API container reports healthy on its
  own health check; and the browser journey's 127 checks pass against the
  composed stack — nginx serving the built bundle, proxying to the API
  container, on PostgreSQL — with no console errors.
- **Upgrading an existing deployment works.** A database created by the
  previous release was started against the new code: `init_db()` added the new
  `insight_feedback` table, and existing sessions kept their stored results.
- The exact pinned dependency set in `requirements.txt` installs from scratch
  and the full 332-test suite passes against it — so the image installs the
  software the code was actually validated with, not a nearby version.
- The image's own `CMD` (`uvicorn app.main:app --workers 2`) starts both workers
  and serves `/api/system/health`, and the health check in the image passes.
- `npm ci` succeeds against the committed lockfile, and `npm run build`
  produces the bundle the frontend image copies into nginx.
- `docker-compose.yml` parses and resolves.
- **The full suite passes against PostgreSQL 16** as well as SQLite (332 tests
  on each), with the schema created by `init_db()` and no connections left
  idle in transaction afterwards.
- **The browser journey passes against the production bundle** — 127 checks,
  no console errors — including the propose-and-confirm cleaning flow, a
  cross-sheet join, a column-classification correction that re-runs the
  analysis, a conversational follow-up, insight ratings and a projection.

**Not verified**

- **No live vendor endpoint has been called.** The provider code is now
  exercised over real HTTP against a local server speaking the Anthropic and
  OpenAI wire formats — request shaping, auth headers, response parsing,
  timeouts, error paths and the rejection of a fabricated figure all run
  against a real socket (`tests/test_ai_transport.py`). What that cannot catch
  is a contract change at Anthropic or OpenAI themselves, because no request
  has been made to either with a real API key.
- **The images were built in an environment with a TLS-inspecting proxy.** The
  Dockerfiles are unmodified and the build is otherwise exactly what ships; the
  only local difference was making the base image trust that proxy's CA so
  `pip` could reach PyPI. On a normal network no such step is needed.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Build fails at `pip install -r requirements.txt` with **exit code 2** | pip's exit 2 is `UNKNOWN_ERROR`, not a resolution failure — it usually means the process was killed. Almost always memory or disk: numpy, pandas, scipy and scikit-learn unpack to well over a gigabyte. Raise Docker's memory limit to 4 GB+ (Docker Desktop → Settings → Resources) and check free disk with `docker system df`, then `docker builder prune` / `docker system prune -a`. Exit **1** with "no matching distribution" is the different problem of a dependency having no wheel for your platform. |
| `required variable SECRET_KEY is missing a value` | `.env` was copied from `.env.example`, which leaves it blank — and Compose treats blank as missing. Run `python3 scripts/init-env.py`. |
| `password authentication failed for user "analyst"` after changing `.env` | PostgreSQL reads `POSTGRES_PASSWORD` **only when it initialises an empty data directory**. Changing it later leaves the `db-data` volume on the old password while the API uses the new one. Either restore the old password, or `ALTER USER analyst PASSWORD '…'` inside the container, or — if the data is expendable — `docker compose down -v` to discard the volume and re-initialise. |
| Every user signed out after a restart | `SECRET_KEY` not set, so a new key was generated. |
| Uploads fail at a certain size | The reverse proxy's `client_max_body_size` is below `MAX_UPLOAD_MB`. |
| Analysis stuck at `processing` | Check `docker compose logs api` — a parse failure sets `status: failed` with an explanation, but an OOM kill will not. |
| A migration hangs | Something is holding an open transaction. Check `pg_stat_activity` for `idle in transaction`; the analysis worker deliberately holds no connection while it runs, so a hang points at another client. |
| `410 Gone` when exploring rows | The upload passed its retention window. The analysis survives; re-upload to explore rows. |
| `410 Gone` when correcting a column or applying a cleaning fix | Both re-run the analysis, which needs the file. It has been swept; re-upload the workbook. |
| A whole analysis has vanished | `RESULT_RETENTION_DAYS` is set and the session passed it. `GET /api/sessions` reports `result_expires_at` before that happens. |
| A join is refused with "would be overstated" | The key repeats on both sheets, so the join multiplies rows. Aggregate one sheet to one row per key first. |
| The browser reports a CORS error on a request that should work | Check the API logs for a 500 on the same `X-Request-ID`. The CORS middleware is outermost so genuine errors keep their headers, but a proxy that strips them can reintroduce this. |
| Browser blocked by CORS | `CORS_ORIGINS` does not list the origin the browser is using. |
| Report generation times out | Raise the proxy read timeout; a detailed report on a large dataset takes a few seconds. |
