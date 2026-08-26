# Browser end-to-end journey

Drives the real production bundle against a real API and asserts on what a user
actually sees — routing, rendering, chart drawing, downloads, theme switching,
responsive layout and cross-account isolation. This is the layer the backend
tests cannot reach.

## Running it

The journey loads two samples: *Retail Sales Performance* for most of it, and
*SaaS Subscriptions* — the only two-sheet one — for the cleaning and join
sections. Both come from the API, so nothing needs seeding by hand.

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
unavailable — for example a pre-installed Chromium whose build number does not
match the one the installed Playwright expects:

```bash
CHROMIUM_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome npm run e2e
```

## What it checks

127 assertions across the whole journey:

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
| Ask Your Data | Five real questions answered, calculation and confidence shown, **a prompt-injection question is treated as data**, every answer states how it was read, and a follow-up (`"and by Product?"`) inherits the measure it did not name and says so. |
| Data Quality | Score with reasoning, the five components, column classification, impact statements, and that cleaning is offered as a proposal with the file declared untouched. |
| Projection | The page states that projections are not measurements; every measure is either projected — with its method, interval and assumptions — or refused with a reason. |
| Column classification | The inferred reading of every column, **a text column never offered as a measure**, a numeric one offered, the blocked reason shown, and a real correction applied that re-runs the analysis. |
| Insight feedback | A rating is recorded and explained, the bound is stated, and rating **never removes or rewrites** the finding. |
| What Changed | With one analysis it says so rather than inventing a comparison; with two it offers the earlier one, compares metrics before and after, states its matching method, and reports no movement for identical uploads. |
| Cleaning and joins | On the two-sheet sample: a fix proposed with before/after values and its risk, **nothing accepted until accepted**, preview changing nothing, applying declared on every page and audited; then a relationship detected, a join previewed with match counts, cardinality and the repeated-column warning, and the joined analysis produced as its own session. |
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
* A text column must not be offered as a measure, however the user asks.
* No cleaning proposal may be checked until someone checks it, and previewing
  must change nothing.
* Rating a finding must leave the finding itself untouched.
* With only one analysis, "What Changed" must say so rather than invent a
  comparison.

## Known-good baseline

A clean run is `Checks passed: 127 / Checks failed: 0 / Console errors: 0`.
The console-error gate is deliberately part of the pass condition; the only
suppressed case is the 404 raised by the isolation probe, which proves
isolation works.
