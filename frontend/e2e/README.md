# Browser end-to-end journey

Drives the real production bundle against a real API and asserts on what a user
actually sees — routing, rendering, chart drawing, downloads, theme switching,
responsive layout and cross-account isolation. This is the layer the backend
tests cannot reach.

## Running it

```bash
# 1. Start the API (any database; a throwaway SQLite file is fine)
cd backend
SECRET_KEY=local-dev-key \
DATABASE_URL="sqlite:///$(pwd)/data/e2e.db" \
CORS_ORIGINS="http://127.0.0.1:4173" \
uvicorn app.main:app --port 8000

# 2. Build the frontend against that API and serve it
cd frontend
npm install
VITE_API_URL="http://127.0.0.1:8000" npm run build
npx vite preview --port 4173 --host 127.0.0.1

# 3. Run the journey
npm run e2e
```

Exits non-zero if any check fails or the browser logs an error.

### Options

| Flag | Effect |
|---|---|
| `--base <url>` | Point at a different deployment (default `http://127.0.0.1:4173`). |
| `--headed` | Watch it run in a visible browser. |
| `--shots <dir>` | Save a full-page screenshot at each stage. |

`CHROMIUM_PATH` overrides the browser binary when Playwright's own download is
unavailable.

## What it checks

84 assertions across the whole journey:

| Section | Checks |
|---|---|
| Landing page | Headline, workflow steps, samples loaded from the API. |
| Registration | Account creation, redirect, signed-in identity. |
| Upload and processing | Pipeline stages shown, analysis completes. |
| Overview | Generated summary, KPI cards, "Show the math", ranked findings, fact/interpretation/recommendation separation, evidence panel. |
| Executive briefing | Opens, states a status, lists wins and concerns, closes on Escape. |
| Data Story | Opens on the summary, Next/Previous navigation, **audience changes depth but never the finding**, document view. |
| Dashboard | Charts render and draw marks, each states its question, "Why this chart", table view, drill-down opens and breaks the value down, **filters recalculate the KPIs** and clearing restores them. |
| Insights | All findings listed, filtering by type, bookmarking, anomaly investigation, **refusal to claim causation**. |
| Ask Your Data | Five real questions answered, calculation and confidence shown, **a prompt-injection question is treated as data**. |
| Data Quality | Score with reasoning, the five components, column classification, impact statements. |
| Explore Data | Rows listed, paging, search. |
| Reports | Three styles offered, PDF and Excel download and are real files, share link created. |
| Chart export | SVG exports with mark colours **and CSS-driven label colours** inlined. |
| Theme and layout | Dark mode applies and survives a reload; no horizontal overflow at 390, 768 or 1440px. |
| Isolation | Signed-out users are redirected; **a second account cannot open or see the first account's analysis**. |

## Why some checks are worded oddly

Several assert a *negative* — that the product refuses to do something:

* An audience change must alter the depth of explanation and leave every
  headline byte-identical. The alternative (findings that shift with the
  reader) is the failure mode this whole product is built to avoid.
* Anomaly investigation must contain "association" or "not causation".
* A prompt-injection question must not surface the system prompt.
* A second account must get "not found", not an empty dashboard.

## Known-good baseline

A clean run is `Checks passed: 84 / Checks failed: 0 / Console errors: 0`.
The console-error gate is deliberately part of the pass condition; the only
suppressed case is the 404 raised by the isolation probe, which proves
isolation works.
