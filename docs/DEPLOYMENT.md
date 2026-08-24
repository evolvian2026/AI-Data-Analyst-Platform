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
cp .env.example .env
```

Fill in the two required secrets:

```bash
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))"
```

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
| `api` | FastAPI on Uvicorn with two workers, uploads on a named volume. |
| `web` | The built frontend behind nginx, proxying `/api` to `api`. |
| `cleanup` | Runs the retention sweep hourly. |

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
- [ ] `FILE_RETENTION_HOURS` matches your data-handling policy.
- [ ] `AI_PROVIDER` is a deliberate choice. `deterministic` sends nothing
      anywhere; the others send aggregates and profiles to a third party.
- [ ] `AI_ALLOW_RAW_ROWS` left `false`.

**Operationally**

- [ ] Back up the database (the analysis results live there) and the uploads
      volume.
- [ ] Monitor `/api/system/health`; both containers also declare Docker
      healthchecks.
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
| Uvicorn `--workers` | CPU-bound analysis is queueing. | Memory per worker is tight — each holds its own frame cache. |

Rough sizing: a 5,000-row, 15-column workbook completes the full pipeline in
about two seconds and produces roughly a 1.5 MB analysis payload. Budget around
500 MB of memory per worker for workbooks in the low hundreds of thousands of
rows.

---

## Backup and recovery

| What | Where | Why it matters |
|---|---|---|
| Database | `db-data` volume | Contains users, sessions and **every analysis result**. Losing it loses the reports. |
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

---

## Upgrading

```bash
git pull
docker compose build
docker compose up -d
```

Tables are created on startup, so a first deployment needs no migration step.
Once you have real data, use Alembic (already in `requirements.txt`) for schema
changes rather than relying on `create_all`.

---

## What has and has not been verified

Being precise about this matters more than a green tick.

**Verified**

- The exact pinned dependency set in `requirements.txt` installs from scratch
  and the full 191-test suite passes against it — so the image installs the
  software the code was actually validated with, not a nearby version.
- Both Dockerfile stages were replicated outside Docker: `pip wheel` builds all
  57 wheels, and `pip install --no-index --find-links=/wheels` then imports the
  application cleanly.
- The image's own `CMD` (`uvicorn app.main:app --workers 2`) starts both workers
  and serves `/api/system/health`.
- `npm ci` succeeds against the committed lockfile, and `npm run build`
  produces the bundle the frontend image copies into nginx.
- `docker-compose.yml` parses and resolves.

**Not verified**

- **The images have never been built.** Pulling `python:3.11-slim` and
  `node:22-alpine` requires `production.cloudfront.docker.com`, which the
  development environment's egress policy blocks. Everything above is the
  closest equivalent that could be run without it, but a first
  `docker compose up --build` is still the remaining step.
- **PostgreSQL has not been exercised.** Every test runs on SQLite. `psycopg2`
  is installed and imports, and the URL form is standard, but no query has run
  against Postgres.
- **No AI provider has been called.** The `deterministic` default is fully
  tested, and the verification layer is tested with a stub that returns
  invented numbers, but no live model request has been made.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Every user signed out after a restart | `SECRET_KEY` not set, so a new key was generated. |
| Uploads fail at a certain size | The reverse proxy's `client_max_body_size` is below `MAX_UPLOAD_MB`. |
| Analysis stuck at `processing` | Check `docker compose logs api` — a parse failure sets `status: failed` with an explanation, but an OOM kill will not. |
| `410 Gone` when exploring rows | The upload passed its retention window. The analysis survives; re-upload to explore rows. |
| Browser blocked by CORS | `CORS_ORIGINS` does not list the origin the browser is using. |
| Report generation times out | Raise the proxy read timeout; a detailed report on a large dataset takes a few seconds. |
