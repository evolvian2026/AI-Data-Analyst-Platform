# API reference

Base URL: `/api`. Interactive documentation (OpenAPI) is served at `/api/docs`,
and the schema at `/api/openapi.json`.

All endpoints except `/system/*`, `/auth/*`, `/samples` and `/shared/{token}`
require a bearer token:

```http
Authorization: Bearer <access_token>
```

Errors return `{"detail": "A sentence explaining what to do about it."}` with an
appropriate status code. Every response carries an `X-Request-ID` header, which
appears in the server logs for the same request.

---

## System

### `GET /system/health`

```json
{ "status": "ok", "environment": "production" }
```

### `GET /system/config`

Client-visible limits and capabilities — never secrets.

```json
{
  "app_name": "AI Data Analyst",
  "max_upload_mb": 100,
  "file_retention_hours": 72,
  "accepted_formats": [".xlsx", ".xls"],
  "pipeline_stages": [{ "key": "uploaded", "label": "File uploaded" }, "..."],
  "audiences": { "executive": { "label": "Executive", "depth": "minimal", "description": "..." } },
  "ai": {
    "active_provider": "deterministic",
    "raw_rows_shared": false,
    "narration_mode": "Calculated by the analytics engine; no external model is used."
  }
}
```

---

## Authentication

### `POST /auth/register` → `201`

```json
{ "email": "analyst@acme.com", "password": "Str0ngPassw0rd!",
  "full_name": "R. Patel", "organization": "Acme" }
```

Passwords must be at least 8 characters and combine letters with numbers or
symbols. Returns the same body as login. `409` if the email is taken, `403` if
`ALLOW_REGISTRATION=false`.

### `POST /auth/login`

```json
{ "email": "analyst@acme.com", "password": "Str0ngPassw0rd!" }
```

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in_minutes": 720,
  "user": { "id": "…", "email": "analyst@acme.com", "full_name": "R. Patel",
            "organization": "Acme", "created_at": "2026-08-24T09:00:00Z" }
}
```

`401` for both a wrong password and an unknown account — deliberately
indistinguishable.

### `GET /auth/me`

The current user.

---

## Datasets and sessions

### `POST /datasets/upload` → `202`

`multipart/form-data` with `file` (required) and optional `name`.

Returns the session immediately with `status: "pending"`; the analysis runs in
the background. Poll `/sessions/{id}/status`.

| Status | Cause |
|---|---|
| `415` | Not an `.xlsx`, `.xls` or `.xlsm` file. |
| `400` | Empty, or the bytes are not a valid workbook. |
| `413` | Larger than `MAX_UPLOAD_MB`. |

### `GET /sessions`

Your analysis sessions, newest first.

### `GET /sessions/{id}` · `GET /sessions/{id}/status`

```json
{
  "id": "…", "status": "processing", "error": "",
  "progress": {
    "stages": [{ "key": "uploaded", "label": "File uploaded", "done": true, "active": false }, "..."],
    "completed": 5, "total": 12, "percent": 42, "elapsed_seconds": 1.8
  },
  "sheets": [{ "name": "Sales", "rows": 4613, "columns": 15, "is_analyzable": true }]
}
```

`status` is one of `pending`, `processing`, `completed`, `failed`. On `failed`,
`error` explains what to do.

### `GET /sessions/{id}/analysis`

The complete analysis. `409` while the session is still processing.

| Key | Contents |
|---|---|
| `summary` | The generated dataset description. |
| `profile` | Row and column counts, per-column classification, roles, currency symbol. |
| `derived_columns` | Columns that are arithmetic combinations of others. |
| `quality` | Score, grade, explanation, components, metrics, issues with impact, recommendations. |
| `kpis` | `primary` (the headline strip) and `all`, each with its formula and record count. |
| `statistics` | Descriptive statistics per measure, value counts per dimension. |
| `distributions` | Histograms, box summaries and skew interpretations. |
| `trends` | Per measure: points, classification, decomposition, seasonality, runs, sudden changes, comparisons. |
| `anomalies` | Summary plus every finding, with method and evidence. |
| `investigations` | Decomposition of the top anomalies across dimensions. |
| `correlations` | Matrix, all pairs, the meaningful subset, and the causation caveat. |
| `segments`, `concentration` | Segment comparisons and Pareto/HHI concentration. |
| `insights` | Every finding, ranked, with evidence and priority components. |
| `charts` | Chart descriptors with question, reason, calculation and data. |
| `recommendations` | Prioritised actions with their evidence. |
| `story` | Twelve sections and the ordered presentation cards. |
| `briefing` | The two-minute executive briefing. |
| `story_score` | Data story strength with its components. |
| `filters` | Filter definitions generated from the dataset's own dimensions. |
| `next_questions` | Follow-up questions built from the available columns. |
| `relationships` | Shared keys detected between sheets. |

### `POST /sessions/{id}/analyze` → `202`

```json
{ "scope": "sheet", "sheet": "Q1 Sales" }
```

Re-runs the pipeline against one sheet, or the whole workbook with
`{"scope": "workbook"}`. `410` if the upload has passed its retention window.

### `PATCH /sessions/{id}`

```json
{ "name": "Q4 board review",
  "notes": { "ins_001": "Check with finance" },
  "bookmarks": ["ins_001", "ins_002"] }
```

### `DELETE /sessions/{id}` → `204`

Deletes the session and its uploaded file.

---

## Interactive analysis

Filters are structured descriptors — never expressions — and are validated
server side:

```json
{ "column": "Region", "type": "multi_select", "values": ["North", "South"] }
{ "column": "Order Date", "type": "date_range", "from": "2025-01-01", "to": "2025-06-30" }
{ "column": "Revenue", "type": "numeric_range", "min": 1000, "max": 50000 }
```

### `POST /sessions/{id}/filter`

`{"filters": [...]}` → the **complete analysis recalculated** for the matching
records, plus `filter_summary`. `422` if nothing matches.

### `POST /sessions/{id}/drilldown`

```json
{ "dimension": "Region", "value": "North", "measure": "Revenue", "filters": [] }
```

Returns metrics for that value with its share and its difference from the
dataset average, breakdowns by every other dimension, a trend, the largest
records, related anomalies, and `available_analyses` — which lists only the
analyses this dataset can actually support. `404` if no record matches.

### `POST /sessions/{id}/ask`

```json
{ "question": "Which region is growing fastest?", "filters": [] }
```

```json
{
  "question": "Which region is growing fastest?",
  "intent": "growth",
  "answer": "East is growing fastest: Revenue changed +28.4% between the first and second halves of the period. South changed +11.5%.",
  "calculation": "SUM(Revenue) per period for each Region, first half vs second half",
  "table": [ { "Region": "East", "growth_pct": 28.4, "Revenue": "12.94M", "records": 1045 } ],
  "chart": { "type": "bar", "title": "Revenue growth by Region", "data": [...] },
  "confidence": "medium",
  "supported": true,
  "records_used": 4613,
  "caveat": "The split point between halves is mechanical, not tied to a known event.",
  "plan": { "intent": "growth", "measure": "Revenue", "dimension": "Region" },
  "applied_filter": null
}
```

`supported: false` means the dataset cannot answer that question; `suggestions`
then offers questions it can.

### `GET /sessions/{id}/ask/suggestions` · `GET /sessions/{id}/ask/history`

Starter questions built from this dataset's columns, and the audit log of
questions asked.

### `GET /sessions/{id}/anomalies/{anomaly_id}/investigate`

Decomposes an anomaly across every dimension: share inside the flagged records
versus the rest, a volume-versus-value split, companion measures, the largest
contributing records, and a caveat stating that these are associations rather
than causes.

### `GET /sessions/{id}/story?audience=analyst`

The Data Story with narration depth tuned to the audience — `executive`,
`manager`, `analyst`, `researcher`, `student` or `general`. **The findings never
change; only the depth of explanation does.** `400` for an unknown audience.

### `GET /sessions/{id}/briefing?audience=executive`

Overall status with its reasoning, three wins, concerns, trends and
opportunities, recommended actions, key numbers and the data quality headline.

### `POST /sessions/{id}/data`

```json
{ "limit": 50, "offset": 0, "sort_by": "Revenue", "sort_desc": true,
  "search": "North", "columns": null, "filters": [] }
```

A page of rows with column classifications and the total count. Paging, sorting
and search all run server side. `410` once the upload has been swept.

---

## Exports

### `POST /sessions/{id}/report/pdf`

```json
{
  "style": "standard",
  "title": "Q4 Board Review",
  "organization": "Acme",
  "author": "R. Patel",
  "date_range": "Jan-Dec 2025",
  "audience": "executive",
  "sections": ["briefing", "executive_summary", "kpis", "story", "recommendations"],
  "include_charts": true,
  "logo_base64": "data:image/png;base64,...",
  "filters": []
}
```

Returns `application/pdf`. `style` is `executive` (2–5 pages), `standard`
(5–15) or `detailed` (15+); the engine sizes the report to what it found rather
than padding. `400` for an undecodable logo, `413` above 3 MB.

### `POST /sessions/{id}/export/excel`

`{"include_data": false, "data_row_limit": 20000, "filters": []}` → a workbook
with Executive Summary, KPIs, Data Story, Key Insights, Data Quality, Quality
Issues, Statistics, Correlations, Correlation Matrix, Outliers, Segment
Analysis, Concentration, Aggregated Data, Chart Data, Recommendations, Column
Profile and optionally the rows.

### `POST /sessions/{id}/export/data`

The filtered rows as CSV, with formula injection defused.

### `GET /reports/styles`

The available report styles, their page ranges and sections, plus the audiences.

### `POST /sessions/{id}/share` · `GET /shared/{token}`

Creates a read-only link to the findings — the underlying rows are never
included. `410` once expired.

---

## Samples

### `GET /samples`

Five sample datasets — sales, students, employees, marketing, finance — each
exercising a different part of the engine.

### `POST /samples/{key}/load` → `202`

Creates an analysis session from a sample and starts the pipeline.

---

## Worked example

```bash
BASE=http://localhost:8000/api

TOKEN=$(curl -s -X POST $BASE/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"analyst@acme.com","password":"Str0ngPassw0rd!"}' | jq -r .access_token)

SESSION=$(curl -s -X POST $BASE/samples/sales/load \
  -H "Authorization: Bearer $TOKEN" | jq -r .id)

# Wait for the pipeline
until [ "$(curl -s $BASE/sessions/$SESSION/status \
      -H "Authorization: Bearer $TOKEN" | jq -r .status)" = "completed" ]; do sleep 1; done

# The top three findings
curl -s $BASE/sessions/$SESSION/analysis -H "Authorization: Bearer $TOKEN" \
  | jq '.insights[:3] | .[] | {rank, type, headline, confidence}'

# Ask a question
curl -s -X POST $BASE/sessions/$SESSION/ask \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"Which region is growing fastest?"}' | jq '{answer, calculation}'

# Download the report
curl -s -X POST $BASE/sessions/$SESSION/report/pdf \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"style":"standard"}' -o report.pdf
```
