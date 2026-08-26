# Testing

Three layers:

| Layer | What it proves | How to run |
|---|---|---|
| **303 backend tests** | Every engine behaves, the API contract holds, and — in `test_e2e.py` — every reported figure matches an independent pandas recomputation of the source workbook. | `cd backend && pytest` |
| **127 browser checks** | The real production bundle works for a real user: routing, rendering, charts, downloads, theme, responsive layout, isolation. | `cd frontend && npm run e2e` |
| **Type checking** | The frontend compiles under strict TypeScript. | `cd frontend && npm run lint` |

The backend suite passes on both SQLite (the default) and PostgreSQL. Run it
against Postgres with `DATABASE_URL=postgresql+psycopg2://... pytest` — worth
doing before a release, because the two databases do not fail in the same way.

They run against real generated workbooks — no mocked dataframes — so a passing
suite means the pipeline genuinely works.

```bash
cd backend
pip install -r requirements-dev.txt  # runtime deps plus pytest and pypdf
pytest                              # everything
pytest tests/test_e2e.py -v         # the journey and the verification layer
pytest tests/test_forecasting.py    # what projection produces, and refuses to
pytest tests/test_security.py -v    # one area
pytest -k "insight or story"        # by name
pytest -x --lf                      # stop at the first failure, rerun last failures
```

The browser journey needs a running API and a built frontend; see
[`frontend/e2e/README.md`](../frontend/e2e/README.md) for the three commands.

```bash
cd frontend
npm run lint                        # TypeScript, strict mode
npm run build
npm run e2e                         # 127 checks against the built bundle
```

---

## What is covered

| File | Tests | Area |
|---|---:|---|
| `test_file_processing.py` | 11 | Excel upload, multiple sheets, header detection, duplicate and missing headers, empty rows and columns, large files, invalid files, sheet unioning. |
| `test_profiling.py` | 24 | Semantic type detection, name-independence, aggregation policy, currency and percentage handling, missing values, duplicates, constant columns, inconsistent categories, conversion failures, derived-column detection, sampling. |
| `test_analytics.py` | 28 | KPI calculation and prioritisation, derived metric validity, trend direction, frequency selection, partial-period trimming, percentage-change guards, volume-vs-value decomposition, outlier detection, time-series anomalies, anomaly investigation, correlation, segment comparison, concentration, distributions. |
| `test_insights_and_story.py` | 24 | Insight ranking, the six priority components, fact/interpretation/recommendation separation, evidence traceability, hedging on low-confidence claims, de-duplication, story section order, supporting evidence, executive summary length, the story score, recommendations and the briefing, audience adaptation. |
| `test_reports.py` | 14 | PDF generation for every style, page-count ranges, cover customisation, page numbers, table of contents, section selection, chart rendering, Excel sheet contents, formula-injection escaping. |
| `test_security.py` | 36 | Prompt injection detection and neutralisation, data-block isolation, injection through workbook cells, question safety, formula injection, path traversal, authentication, account enumeration, cross-user isolation, malicious and oversized uploads, AI verification, security headers. |
| `test_api.py` | 24 | Registration and login, pipeline progress, the analysis payload, chart rationale, Ask Your Data, filters, drill-down, anomaly investigation, audience adaptation, data exploration, downloads, sharing, re-analysis, samples, deletion, retention. |
| `test_forecasting.py` | 16 | Method selection (trend, level, seasonal), the F-test that stops two cycles of noise becoming a seasonal pattern, every refusal path, interval bounds, the non-negative floor, the horizon cap, and — most importantly — that no projected value reaches a trend series, a KPI or a measured chart series. |
| `test_comparison.py` | 14 | Structural matching of metrics, segments and findings; added, removed and incomparable metrics; movement arithmetic against the underlying values; the longer-period caveat; findings matched by subject rather than wording; the zero-baseline guard; a self-comparison reporting no movement. |
| `test_cleaning.py` | 21 | Proposals generated only for problems that exist, each with its cost, examples and risk; nothing applied until accepted; the source frame never mutated; removing the recipe restoring the original analysis exactly; the audit; recipe validation; and column-classification overrides, including the refusal to make text a measure. |
| `test_conversation.py` | 25 | Follow-up detection both ways, inheritance only into empty slots, the stated interpretation, the carried filter; and feedback that reorders without rewriting, stays bounded, cannot bury a dominant finding, and survives renumbering. |
| `test_extensions_api.py` | 31 | Every new endpoint end to end: corrections that reach the numbers, preview-before-apply, join preview and refusal, joined attributes never summed or trended, comparable-session discovery, cross-user isolation on comparison and feedback, the forecast contract, and both retention windows. |
| `test_e2e.py` | 35 | The complete journey through the API in the order a user performs it; **independent verification of every reported figure against pandas**; all six samples through the full journey including all three report styles, and the two-sheet sample's join; failure paths; the deployment settings that only break once deployed, and the connection
discipline that only PostgreSQL enforces. |

---

## Tests that assert the product's promises

A few are worth calling out, because they encode claims the product makes
rather than the behaviour of one function.

**No fabricated numbers.** Every number in an insight headline must also appear
in that insight's own evidence object, within tolerance:

```python
def test_story_numbers_appear_in_the_underlying_evidence(sales_analysis):
    for insight in sales_analysis["insights"]:
        available = _numbers(evidence_text)
        for number in _numbers(insight["headline"]):
            assert any(abs(number - candidate) <= max(abs(candidate) * 0.02, 0.05)
                       for candidate in available)
```

**A misbehaving model cannot get through.** A stub provider returns invented
figures; the engine's own wording is used instead:

```python
def test_narration_never_invents_a_number_when_a_model_misbehaves():
    result = narrate("Rewrite", {"revenue_growth_pct": 18.4}, "Revenue grew 18.4%.",
                     provider=LyingProvider())      # returns "grew 412% to 88 million"
    assert result["text"] == "Revenue grew 18.4%."
    assert "412" in result["rejected"]
```

**Important findings outrank trivial ones**, which is the spec's own example:

```python
def test_a_large_decline_outranks_a_trivial_change():
    # "Revenue fell 32%" must sort above "Average order value rose 1.1%"
```

**Low-confidence claims are hedged.** Any medium- or low-confidence
interpretation must contain qualifying language, and driver findings must never
claim causation.

**One user cannot reach another's data**, across every endpoint, by id.

**Spreadsheet cells are data.** Instruction-like content is detected, redacted,
reported as a quality issue, and never appears in the analysis output.

**Report length matches the chosen style** — executive 2–5 pages, standard
5–15, detailed 15+ — enforced by counting the pages of a real generated PDF,
**for every sample dataset**. Checking one small fixture was not enough: four of
six samples produced a Standard report a page or two over its declared cap. The
generator now trims its least important content and re-renders until the report
fits the range it advertises.

**A projection can never be mistaken for a measurement.** No projected value may
appear in a trend series, a KPI, or the measured series of a chart:

```python
def test_projections_never_enter_the_measured_series(sales_analysis):
    for trend in sales_analysis["trends"]:
        for point in trend["points"]:
            assert "projected" not in point
            assert point["value"] is not None
```

**Feedback moves order, never content.** A rated insight keeps its headline, its
evidence and its confidence byte for byte, and the adjustment is bounded so a
downvote cannot bury a finding the statistics put far above its neighbours.

**Nothing is cleaned without being accepted**, the source frame is never
mutated, and clearing the recipe restores the original analysis exactly —
asserted by comparing the quality score and row count before and after.

**A join that would inflate totals is refused**, at the API boundary rather than
in the worker, so it produces an explanation instead of a failed session.

---

## The verification layer

`test_e2e.py` recomputes what the platform reports, from the source workbook,
using plain pandas — because a pipeline can be internally consistent and still
be wrong:

```python
def test_segment_totals_match_a_groupby(client, auth_headers, journey, source_frame):
    segment = ...                                   # what the platform says
    expected = source_frame.groupby("Region")["Revenue"].sum()   # the truth

    # Every group must be present, not merely every reported group correct.
    assert {g["group"] for g in segment["groups"]} == set(expected.index)
    assert sum(g["count"] for g in segment["groups"]) == len(source_frame)
    for group in segment["groups"]:
        assert group["value"] == pytest.approx(float(expected[group["group"]]), rel=1e-9)
```

The same treatment covers KPI totals, derived margins, trend series against a
resample, correlations against `Series.corr`, descriptive statistics, quality
metrics, filtered analyses, drill-down, Ask Your Data answers, the exported CSV,
the exported workbook and the figures printed in the PDF.

Three structural checks catch a whole class of error at once: no reported total
may exceed the sum of its own column, no insight or chart may cite a column that
does not exist, and no finding may claim more records than the dataset has.

### These assertions were checked by mutation

A verification test that cannot fail is worse than none. Two deliberate bugs
were introduced to confirm these bite:

| Mutation | Result |
|---|---|
| Inflate every summed KPI by 0.5% | Caught — KPI totals and the Excel export both failed. |
| Drop the last group from every segment comparison | **Survived at first.** The test checked that reported groups were correct but never that all groups were reported. The assertion was strengthened, and the mutation then failed it. |
| Register the CORS middleware inside the catch-all error handler instead of outside it | Caught — `test_a_server_error_still_carries_its_cors_headers` failed, which is the point: with that ordering a 500 reaches the browser as an opaque CORS error and the real cause is invisible. |

---

## Fixtures

`tests/conftest.py` builds real workbooks:

| Fixture | What it is |
|---|---|
| `sales_frame` / `sales_workbook` | Two years of daily orders with a planted growth trend, regional concentration and a derived Profit column. |
| `sales_analysis` | The full pipeline result for that workbook, computed once per session. |
| `messy_frame` | Deliberately dirty: duplicate ids, inconsistent category spellings, currency stored as text, an unparseable number, a bad date, a constant column. |
| `messy_workbook` | The same kind of mess as a real workbook, used to exercise the cleaning proposals end to end. |
| `two_sheet_workbook` | Orders and customers sharing a key, for the join tests. |
| `client` | A `TestClient` bound to a fresh database. |
| `auth_headers` | A registered user's bearer token. |

Tests run against an isolated SQLite database and a temporary storage directory,
set in `conftest.py` before the application imports its configuration.

---

## Adding a test

Assert the behaviour the product promises, not the shape of the implementation.
A test named `test_reads_a_simple_workbook` should survive a rewrite of the
parser; one named `test_detect_header_row_returns_2` will not.

```python
def test_concentration_detects_a_dominant_group():
    frame = pd.DataFrame({
        "Customer": ["Big"] * 70 + [f"Small{i}" for i in range(30)],
        "Revenue": [1000.0] * 70 + [10.0] * 30,
    })
    analysis = concentration_analysis(frame, profile_of(frame), "Customer", "Revenue")
    assert analysis["is_risk"]
    assert analysis["top1_pct"] > 90
    assert analysis["groups_for_80pct"] == 1
```

For API tests, use the `client` and `auth_headers` fixtures and the
`wait_for_analysis` helper in `test_api.py` rather than sleeping.

---

## The browser journey

`frontend/e2e/journey.mjs` drives the production bundle against a running API
and asserts on what a user sees. See [`frontend/e2e/README.md`](../frontend/e2e/README.md)
for the full list. Several checks assert a *refusal*, which is the point:

* An audience change must alter the depth of explanation and leave every
  headline byte-identical.
* Anomaly investigation must say "association" or "not causation".
* A prompt-injection question must not surface the system prompt.
* A second account must get "not found", not an empty dashboard.
* A text column must not be offered as a measure, whatever the user wants.
* No cleaning proposal may be accepted until someone accepts it.
* Rating a finding must not remove it or change a word of it.
* With only one analysis, "What Changed" must say so rather than invent a
  comparison.

Console errors are part of the pass condition. A clean run is
`127 passed / 0 failed / 0 console errors`.

---

## Bugs this suite has already caught

Worth knowing, because they are the kind that ship silently:

* **Formula-injection escaping never ran.** The escape path was guarded by
  `dtype == object`, but pandas infers a dedicated string dtype for text
  columns, so a cell beginning `=` was written back into an export as a live
  formula. Now guarded by `is_text_column()`.
* **Instruction-like cell content reached chart labels and insight headlines**
  through category values, bypassing the sanitiser that only ran on AI prompts.
  Neutralisation moved into the parser, so no output path can leak it.
* **The request-validation handler returned a 500** when a pydantic error
  carried an exception object in its context — turning a bad request into a
  server error.
* **A medium-confidence growth claim was stated without qualification**, which
  the hedging test rejected.
* **Legend positioning silently failed** in the PDF (`deltaX` is not a valid
  ReportLab attribute), which the chart-rendering test caught by asserting that
  every chart type renders.

And from the end-to-end layers:

* **`CORS_ORIGINS` crashed the API on startup** when given the comma-separated
  value documented in `.env.example` and docker-compose. pydantic-settings tries
  to JSON-decode a `List[str]` from the environment before any validator runs,
  so the documented deployment configuration could not boot. Found by actually
  starting the server the way the docs say to.
* **Every in-flight analysis pinned a database connection open.** After the
  worker committed `status = "processing"`, SQLAlchemy expired the instance, so
  the next attribute access re-issued a SELECT and opened a transaction that
  stayed open for the entire analysis. On PostgreSQL that blocks DDL, stops
  autovacuum reclaiming dead tuples and holds a pool slot per concurrent run —
  a migration during an analysis simply hangs. SQLite hid it completely; the
  bug only appeared when the suite was pointed at a real Postgres server, where
  it deadlocked the test teardown. The worker now holds no session across the
  computation, and a regression test asserts the pool is empty at the moment
  the analysis begins.
* **A server error reached the browser as a CORS failure.** The catch-all error
  handler returns its 500 directly, and it was registered *outside* the CORS
  middleware — so that response carried no `Access-Control-Allow-Origin`. The
  browser then reported a CORS problem for what was really an unhandled
  exception, hiding the actual cause from whoever had to debug it. Found while
  running the browser journey against a broken database.
* **A foreign key disappeared from the analysis.** An id-shaped column whose
  values repeat — `Account ID` appearing 5,062 times across 260 accounts — fell
  past every categorical test into free text and was classified `descriptive`.
  That made it invisible to cross-sheet relationship detection, so a workbook
  with a perfectly good join key reported no relationships at all.
* **A joined lookup column produced a fabricated trend.** After a many-to-one
  join, `Credit Limit` repeats on every order, so the "90% increase in August"
  the trend engine found was the month's order mix, not any change in credit
  limits. Columns fanned out by a join are now averaged rather than summed and
  excluded from trends.
* **An analysis claimed to cover a whole workbook when it covered one sheet.**
  `combine_sheets` correctly refuses to stack sheets with different schemas, but
  the scope was reported as `__workbook__` whenever the file had more than one
  sheet — regardless of how many were actually analysed.
* **Four of six samples produced a report longer than the style promised.**
  Standard is documented as 5–15 pages and produced 16 or 17 on real datasets.
  The page-count test only ever ran against one small fixture, so it never saw
  it. The generator now fits the report to its declared range, and the
  all-samples journey asserts the range for every sample and every style.
* **SVG chart export silently dropped every CSS-driven colour.** Computed styles
  were read from a detached clone, where `getComputedStyle` returns nothing, so
  the inlining loop wrote no styles at all. Axis labels fell back to black —
  invisible against a dark background. The exported file *looked* fine because
  Recharts also writes presentation attributes for the marks themselves.
