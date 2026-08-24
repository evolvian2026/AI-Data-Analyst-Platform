# Testing

160 tests covering the areas the product specification calls out. They run in
under a minute against real generated workbooks — no mocked dataframes — so a
passing suite means the pipeline genuinely works end to end.

```bash
cd backend
pytest                              # everything
pytest tests/test_security.py -v    # one area
pytest -k "insight or story"        # by name
pytest -x --lf                      # stop at the first failure, rerun last failures
```

```bash
cd frontend
npm run lint                        # TypeScript, strict mode
npm run build
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
| `test_security.py` | 35 | Prompt injection detection and neutralisation, data-block isolation, injection through workbook cells, question safety, formula injection, path traversal, authentication, account enumeration, cross-user isolation, malicious and oversized uploads, AI verification, security headers. |
| `test_api.py` | 24 | Registration and login, pipeline progress, the analysis payload, chart rationale, Ask Your Data, filters, drill-down, anomaly investigation, audience adaptation, data exploration, downloads, sharing, re-analysis, samples, deletion, retention. |

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
5–15, detailed 15+ — enforced by counting the pages of a real generated PDF.

---

## Fixtures

`tests/conftest.py` builds real workbooks:

| Fixture | What it is |
|---|---|
| `sales_frame` / `sales_workbook` | Two years of daily orders with a planted growth trend, regional concentration and a derived Profit column. |
| `sales_analysis` | The full pipeline result for that workbook, computed once per session. |
| `messy_frame` | Deliberately dirty: duplicate ids, inconsistent category spellings, currency stored as text, an unparseable number, a bad date, a constant column. |
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
