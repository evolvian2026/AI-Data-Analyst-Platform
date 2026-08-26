# Architecture

## Shape of the system

```
Browser (React + TypeScript)
      |  HTTPS, JWT bearer
      v
API Gateway (FastAPI)  ── auth, per-user isolation, upload validation
      |
      v
Analytics Orchestrator ── runs the pipeline, reports progress
      |
      +-- Excel Parser          +-- Insight Ranking Engine
      +-- Data Profiler         +-- Visualization Engine
      +-- Data Quality Engine   +-- Data Story Engine
      +-- KPI Engine            +-- Recommendation Engine
      +-- Statistical Engine    +-- Ask Your Data Engine
      +-- Trend Engine          +-- PDF Engine
      +-- Anomaly Engine        +-- Export Engine
      +-- Correlation Engine    +-- AI Provider (optional, verified)
      +-- Forecast Engine       +-- Comparison Engine
      +-- Cleaning Engine       +-- Feedback Engine
      +-- Relationship / Join Engine
      |
      v
PostgreSQL (sessions, results, audit)   Filesystem (uploads, retention-swept)
```

Every engine is a module in `backend/app/engines/`. They are pure functions over
a `DataFrame` plus a profile — no shared mutable state, no database access — so
each is independently testable and independently replaceable.

## The pipeline

`orchestrator.analyze_workbook()` runs twelve stages and reports progress after
each, which is what the processing screen polls.

| # | Stage | Module | What happens |
|---|---|---|---|
| 1 | File uploaded | `api/routes_sessions` | Extension, size and magic-byte validation; the file is written to a per-user directory with mode `0600`. |
| 2 | Workbook read | `excel_parser` | Every sheet is read, the header row is located by scoring the first rows, blank rows and columns are dropped, duplicate headers are made unique, text is trimmed and instruction-like cells are neutralised. |
| 3 | Dataset understood | `profiler`, `derived`, `narrative` | Semantic type per column from its values; analytical role; aggregation policy; detection of columns that are arithmetic combinations of others; a generated dataset summary. |
| 4 | Data quality checked | `quality` | Missing values, duplicates, constant columns, inconsistent categories, conversion failures, suspicious values, untrusted content — each with its analytical impact — and a weighted 0–100 score. |
| 5 | KPIs calculated | `kpi` | Direct, distinct-count, derived and growth metrics, scored and capped at the most useful 5–8. |
| 6 | Trends detected | `trend`, `forecast` | Aggregation grain chosen from data density, incomplete boundary periods trimmed, OLS classification, seasonality, runs, sudden changes, period comparisons and a volume-vs-value decomposition — then a projection per leading measure, or a stated reason for withholding one. |
| 7 | Anomalies detected | `anomaly` | Record-level IQR + modified z-score, time-series de-trended residuals, then investigation of the top findings. |
| 8 | Relationships analyzed | `correlation`, `segments`, `stats_engine` | Pearson and Spearman with significance testing, segment comparison, Pareto/HHI concentration, distribution analysis. |
| 9 | Insights ranked | `insights` | Eight discovery passes produce findings; each is scored, de-duplicated and ranked. |
| 10 | Charts generated | `visualization` | Charts selected to answer questions, de-duplicated, then linked to the insights they evidence. |
| 11 | Data Story created | `story`, `recommendations` | Twelve sections, ordered cards, recommendations, the executive briefing and the story strength score. |
| 12 | Report ready | `pdf_report`, `excel_export` | Generated on demand from the stored result. |

### What sits between the sheets and the pipeline

`orchestrator.prepare_frame()` turns a workbook's sheets into the one table the
analysis runs on, applying three user-controlled steps in order:

1. a **cross-sheet join**, when the user has acted on a detected relationship;
2. otherwise sheet selection, or the union of sheets that share a schema;
3. an accepted **cleaning recipe**, replayed onto a copy of the result.

It is used by both the analysis worker and every interactive endpoint, which is
the point: exploring rows, filtering and drilling down can never operate on a
different table from the one the reported numbers came from. Column
classification overrides are deliberately *not* applied here — they change how
the table is interpreted, not what the table is, and belong to profiling.

## Type inference and roles

Detection reads values, never column names — a column called `Revenue` holding
`North`/`South` is categorical. Names act only as a weak tie-breaker when values
are ambiguous (`Student ID` nudges a unique integer column towards identifier).

**Semantic types:** integer, decimal, currency, percentage, date, datetime,
time, categorical, text, boolean, identifier, geographic, email, url, unknown.

**Roles:** measure, dimension, time, identifier, descriptive.

A **foreign key** — an id-shaped column whose values repeat, because it names an
entity that lives in another sheet — is classified as an identifier rather than
falling through to free text. Without that, the column disappears from the
analysis and takes every cross-sheet relationship built on it with it.

### Corrections

Inference is right most of the time and not all of the time, and when it is
wrong every number downstream inherits the mistake. `profiler.apply_overrides()`
folds a user's corrections into the profile immediately after profiling and
before any engine reads it, so a correction propagates through KPI selection,
aggregation, charting and narration without any of them knowing overrides exist.

`profiler.override_options()` offers only what the values can support — a column
holding no numerically coercible values is never offered as a measure — so a
correction can never put the engines in a state they cannot compute.

### The aggregation policy

Summing a rating or a percentage produces a number with no meaning, so
`profiler.default_aggregation()` decides `sum` or `mean` for every measure and
the whole stack asks before aggregating. This single decision propagates into
trends, segments, concentration, charts, drill-down and Ask Your Data — and is
why the platform reports *Average* Customer Rating but *Total* Revenue.

Two related guards:

* **Shares need a one-signed additive measure.** A "share of the total" is
  undefined when the total mixes credits and debits, so segment shares and
  concentration analysis are suppressed for signed or averaged measures.
* **Percentage change needs a positive base.** A move from −30 to +12 is not a
  "140% increase", so `trend.pct_change()` returns `None` and callers report the
  absolute movement instead.

## Insight and evidence model

Every insight is derived from a value the engine already calculated:

```python
{
  "id": "ins_003",
  "type": "risk",                      # performance | trend | driver | anomaly
                                       # risk | opportunity | data_quality
                                       # relationship | distribution
  "headline": "Concentration risk: 3 of 5 Product values produce 80% of Revenue",
  "fact":            "...",            # calculated directly
  "interpretation":  "...",            # what the pattern may mean
  "recommendation":  "...",            # what to investigate next
  "so_what":         "...",            # why it matters
  "confidence": "high",                # high | medium | low
  "confidence_reason": "Shares are calculated directly from the aggregated totals.",
  "priority": {
    "score": 89.0,
    "components": {                    # the six components from the spec
      "magnitude": 17.8, "unusualness": 14.0, "relevance": 20.0,
      "confidence": 15.0, "coverage": 10.0, "analytical_importance": 20.0
    }
  },
  "evidence": {
    "metric": "Revenue",
    "value": 24572457.66,
    "formatted_value": "24.57M",
    "source_columns": ["Revenue", "Product"],
    "calculation": "SUM(Revenue) GROUP BY Product, sorted descending, cumulative share",
    "math": {"formula": "...", "substitution": "...", "result": "44.4%"},
    "records_used": 4613,
    "statistics": {"hhi": 2859, "top1_pct": 44.4},
    "aggregation": [...]               # the supporting rows
  },
  "chart_id": "chart_04",
  "next_questions": [...]
}
```

The UI renders this as "Why am I seeing this insight?" and "Show the math". A
test asserts that every number appearing in an insight headline also appears in
that insight's own evidence.

### De-duplication

Two passes. First, identical `(type, subject)` pairs collapse. Second, findings
keyed on a time period collapse across measures and types — so a single unusual
month is not reported once as a trend break, again as an anomaly, and again for
Revenue, Cost and Profit separately. Record-level outlier findings across
correlated measures describe the same rows, so at most two survive.

## Projection

`engines/forecast.py` is the one place a number appears that was never measured,
and it is built around that fact.

**Method selection.** Trend and seasonality are estimated independently, because
a series can be strongly seasonal with no trend at all — which is what a year of
retail data usually looks like.

| Method | When |
|---|---|
| `linear_trend` | OLS slope significant at p < 0.05 with R² ≥ 0.25. |
| `level` | No significant trend: the recent mean is carried forward flat. Saying "about the same" is an honest forecast; extrapolating noise is not. |
| `seasonal_trend` / `seasonal_level` | Either of the above plus additive cycle offsets — kept only when an F-test says the `cycle − 1` extra parameters explain more than they cost. Two cycles of noise will not become a seasonal pattern. |

**Refusals.** A projection is withheld, with its reason returned in place of the
numbers, when the series is shorter than 8 periods, varies by more than 75% of
its own mean, or would produce a prediction interval wider than 1.5× that mean.
The horizon never exceeds a quarter of the observed history, capped at 6.

**Separation.** Projected points never enter `trends[*].points`, a KPI, a total
or a share. On a chart they are appended as rows whose `value` is null and whose
`projected` key holds the model output, rendered as a dashed line over a shaded
prediction interval starting at a labelled boundary. One bridging row repeats
the last measured value in both keys so the two lines meet; it is flagged so no
marker is drawn and no total counts it.

## Comparison

`engines/comparison.py` diffs two stored analysis results. Everything is matched
structurally — metrics by calculation key, segments by `(dimension, measure)`,
findings by what they are about rather than by their wording — so a metric
present in only one run is reported as *added* or *removed*, never silently
compared. A metric whose aggregation changed between runs is marked
`incomparable` rather than differenced, and percentage change goes through
`trend.pct_change()`, so a non-positive baseline yields "undefined" instead of
the "declined 860%" class of nonsense.

## Cleaning

`engines/cleaning.py` proposes; it never applies. A proposal carries the exact
cell count, real before/after values from this dataset, and an honest risk
statement including whether it discards data. An accepted proposal is stored as
a *recipe* on the session and replayed onto a copy of the dataframe every time
it is read: the uploaded workbook is byte-for-byte untouched, and removing the
recipe restores the original analysis exactly. Every applied step is audited and
the audit is attached to the analysis, so a reader can always see that the
numbers came from cleaned data and how.

Surrounding whitespace is deliberately absent from the fix catalogue: the parser
already trims every text cell on the way in.

## Joins

`engines/relationships.py` detects shared keys between sheets and then acts on
them. `describe_join()` reports what a join would cost before it runs — how many
rows on each side find a partner, how many the chosen join type drops, and the
expected result size, computed from key counts rather than by joining, so an
oversized join is refused before any memory is spent on it. `ensure_joinable()`
raises for a many-to-many fan-out, and is called by every path that would
*analyse* a join while `describe_join()` alone stays available to a preview —
showing a user the danger is useful; analysing inflated totals is not.

A many-to-one join repeats the lookup side's columns across every matching row.
Those columns describe an entity rather than an event, so they are marked
repeated attributes: averaged rather than summed, and excluded from trends. A
time series of a static attribute tracks which entities appear in each period,
not any change in the value.

## Feedback

`engines/feedback.py` lets a "useful" / "not useful" vote nudge the *order* of
findings, under three constraints. It moves ranking only — no number, headline,
evidence value or confidence level is ever touched, and a downvoted finding is
still true. It is bounded to 8 points against a statistical score whose
components total 100, with `tanh` diminishing returns, so a large, unusual,
high-confidence finding cannot be voted off the front page. And it is
explainable: every adjusted insight carries the adjustment and the reason.

Votes are keyed on what a finding is *about*, not on its id, so a rating
survives a re-analysis that renumbers insights and informs a later dataset of
the same shape.

## Visualization

Charts are selected to answer questions, not to fill space. Each carries its
question, columns, calculation, reason for selection and the insight it
supports; a signature-based pass drops any chart that would show the same
relationship twice.

Two rules the renderer never breaks:

* **One axis.** A Pareto chart plots share and cumulative share — both
  percentages of the same total — on a single axis, in the browser and in the
  PDF. A second y-scale would invite a false visual comparison.
* **Colour follows the entity, not its rank**, and categorical hues are assigned
  in fixed order and never cycled, so filtering out a series never repaints the
  survivors.

## Ask Your Data

```
question → intent detection → column mapping → analytical operation
        → validated calculation → answer (+ optional chart)
```

The question selects an operation from a fixed catalogue and binds columns to
it. **No code is generated or executed**, so a hostile question can at worst
produce an unhelpful answer. Sixteen intents are supported (ranking, aggregate,
trend, growth, period comparison, correlation, distribution, outliers, drivers,
key findings, recommendations, data quality, count, summary and their
variations); anything unrecognised falls back to the ranked findings.

**Follow-ups.** A question that only makes sense after the previous one — "and
by product?", "what about the North region?" — inherits the previous *plan*,
but only into the slots it left empty: anything it names explicitly always wins.
Every answer states how it was read ("Understood as: … carried over from your
previous question: measure"), so a wrong assumption is visible rather than
silent. The conversation lives in the client, which echoes the previous answer's
context back with the next question, so the API holds no per-user state to
expire or isolate.

## AI layer

Two rules govern `engines/ai_provider.py`:

1. **The analytics engine is the source of truth.** A model is only ever asked
   to rephrase values already calculated. Every generated sentence is checked
   against the numbers in the evidence, and a response introducing a figure the
   engine did not produce is discarded in favour of the deterministic text.
2. **Spreadsheet content is data, never instruction.** Only aggregates,
   profiles and statistics are sent — never raw rows unless explicitly enabled —
   and everything is sanitised and wrapped in a block labelled as untrusted.

The default provider is `deterministic`: narration is composed from calculated
values with no external call at all, so the product works fully offline and
cannot hallucinate.

## Security model

| Threat | Mitigation |
|---|---|
| Cross-user data access | Every session lookup goes through `owned_session()`, which enforces ownership; a mismatch is a 404, so ids cannot be probed. |
| Malicious uploads | Extension allow-list, size cap and magic-byte check (`PK\x03\x04` for xlsx, OLE2 for xls) before anything is parsed. |
| Prompt injection through cells | Instruction-like cells are detected and neutralised **once, in the parser**, so no output path — chart label, insight headline, export or AI prompt — can leak them. What was found is reported as a data quality issue. |
| Formula / CSV injection | Values beginning `=`, `+`, `-` or `@` are prefixed on every export path. Text columns are identified with `is_text_column()` rather than a `dtype == object` check, which silently misses pandas' string dtype. |
| Path traversal | File names are reduced to a safe basename before touching the filesystem. |
| Account enumeration | Login returns one message for both "no such account" and "wrong password". |
| Data at rest | Uploads are per-user, mode `0600`, and swept on a retention schedule; the analysis result survives so reports remain readable after the file is gone. `RESULT_RETENTION_DAYS` bounds the analysis itself, which still holds aggregates and sample values drawn from the upload. |
| A server error leaking as a CORS failure | The CORS middleware is registered last so it runs outermost. The catch-all error handler returns its 500 directly; with CORS inside it, that response would carry no `Access-Control-Allow-Origin` and the browser would report a CORS problem for what is really a server error. |
| Sharing | A share link exposes the findings only — never the underlying rows — and expires. |

## Performance

* **Server-side computation.** The browser never receives the workbook; only
  aggregated chart data and a page of rows at a time.
* **Streaming-friendly parsing.** Sheets are read once; row caps apply.
* **Sampling.** Profiling samples above `SAMPLE_ROWS_FOR_PROFILING`; the row
  count reported is always the true one.
* **Background analysis.** Uploads return `202` immediately and the pipeline
  runs in a worker pool, persisting progress after each stage. Setting
  `REDIS_URL` is the seam for moving this to Celery.
* **Frame cache.** An LRU of parsed frames keeps Ask Your Data, drill-down and
  Explore Data responsive without re-reading the workbook.
* **Chart caps.** At most `MAX_CHARTS` charts and `MAX_PRIMARY_KPIS` headline
  metrics, so a wide dataset cannot produce an unbounded payload.

## Extension points

* **A new insight type** — add a discovery pass in `insights.py` that appends
  through `InsightBuilder.add()` with a components dict; ranking, de-duplication
  and the story pick it up automatically.
* **A new chart** — add a builder in `visualization.py` with a signature, and a
  renderer branch in `frontend/src/components/charts/ChartRenderer.tsx`.
* **A new AI provider** — implement `AIProvider.complete()` and register it in
  `_PROVIDERS`; verification applies automatically.
* **A new cleaning fix** — add a type to `cleaning.FIX_TYPES`, a proposal
  builder in `propose_fixes()` and a branch in `apply_recipe()`; validation,
  preview, audit and the revert path all follow.
* **A new forecasting method** — add a branch to `forecast.build_forecast()`
  and a label; the refusal guards, interval arithmetic and chart separation are
  method-agnostic.
* **Datasets across workbooks** — joins today are between sheets of one
  workbook. `relationships.describe_join()` takes a dict of frames and knows
  nothing about where they came from, so the extension is in how the frames are
  gathered, not in the join itself.
