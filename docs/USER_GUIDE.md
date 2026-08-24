# User guide

## Getting started

1. Create an account. Your datasets are visible only to you.
2. On the workspace, drag an Excel workbook onto the upload area — or load one
   of the five sample datasets to see the full analysis in about a minute.
3. Watch the twelve processing stages tick through. Analysis runs on the
   server, so a large workbook never loads into your browser.

**What uploads well.** `.xlsx` and `.xls`, up to 100 MB by default. Multiple
sheets, empty rows and columns, missing or duplicate headers and mixed types
are all handled. There is no schema to configure — the platform works out what
your columns mean from their values.

**Multi-sheet workbooks.** Sheets sharing a schema are stacked automatically.
On the Overview you can switch between *Analyze entire workbook* and any single
sheet, and the whole analysis re-runs for that scope.

---

## The eight sections

### Overview

The orientation page. It answers "what is in this file?" before it answers
anything else: a generated description of the dataset, the file's own facts,
the data quality and story strength scores, the metrics worth watching, the
shape of the leading measure over time, and the five most important findings.

### Data Story

The signature feature, and the place to start on an unfamiliar dataset.

Instead of a wall of charts, the findings are arranged into a narrative:
Executive Summary → The Big Picture → Major Trends → Key Drivers → Winners →
Underperformers → Anomalies → Relationships → Risks → Opportunities →
Recommendations → Next Questions. The order is decided by analytical
importance, not by the order the engines happened to run in.

* **Presentation** steps through one card at a time — headline, supporting
  number, chart, explanation, evidence, confidence, recommendation.
* **Document** shows the whole narrative as a readable report.
* **Audience** (Executive, Manager, Analyst, Researcher, Student, General)
  changes how much explanation you get. It never changes the findings or the
  numbers — an Analyst simply also sees the methodology, the statistics and the
  record counts.

### Dashboard

Every chart answers a different analytical question, and says which one under
its title. Two controls on each chart are worth knowing:

* **Why this chart** — why the engine selected it, the exact calculation, and
  the columns involved.
* **Table** — the underlying values, for when you need the number rather than
  the shape.

Click any bar or slice to drill into it. The panel shows that value's metrics
with its share and its difference from the dataset average, its breakdown by
every other dimension, its trend, its largest records and any related
anomalies — and only the analyses your dataset can actually support.

### Insights

Every finding, ranked. Each carries four labelled layers:

| Layer | What it is |
|---|---|
| **Fact** | Calculated directly from your data. |
| **Interpretation** | What the pattern may mean. |
| **Why it matters** | The consequence, when the data supports stating one. |
| **Recommendation** | What to investigate or consider next. |

Filter by type, bookmark what matters, and add notes for your team. Every card
has **Why am I seeing this insight?**, which opens the source columns, the
calculation, the values substituted into it, the record count and the
supporting rows.

On an anomaly, **Investigate anomaly** decomposes it: which dimension values
the deviation is concentrated in, whether it came from more records or larger
records, and how other measures moved over the same records.

### Ask Your Data

Ask in plain English:

* What are the most important findings?
* Show the top 10 products
* Which region is growing fastest?
* What caused the revenue spike?
* Compare 2024 and 2025
* Is marketing spend related to revenue?
* Find unusual records
* What should management know?

Every answer shows the calculation behind it, how many records it used, and a
confidence level. Where a chart or table helps, you get one.

Your question chooses a calculation from a fixed catalogue — no code is
generated or run — so the answers stay grounded in your data.

### Data Quality

What is wrong with the data, and more usefully what that does to the analysis.

The score is a weighted blend of completeness (34%), uniqueness (20%), validity
(20%), consistency (18%) and structure (8%), and the page explains which
dimension pulled it down.

Each issue states its **impact**. Not "Region has 8.4% missing values" but
"8.4% of records cannot be attributed to a Region value, so any breakdown by
Region understates or misclassifies that share of the data."

The column classification table shows how every column was interpreted —
detected type, role, whether it is summed or averaged, and why.

### Explore Data

The rows behind the analysis, with server-side paging, sorting and search.
Column headers show how each column was classified. Download the filtered rows
as CSV at any point.

### Reports

**PDF.** Choose Executive (2–5 pages), Standard (5–15) or Detailed (15+). Set
the title, organization, author, logo and date range, pick the sections, and
choose the audience. The engine sizes the report to what it actually found
rather than padding to a page count.

**Excel.** A 16-sheet analysis workbook: executive summary, KPIs, the data
story, every insight, data quality, statistics, correlations, outliers, segment
analysis, concentration, aggregated data and the exact values behind each
chart. Optionally the rows too.

**Share.** A read-only link to the findings. The underlying rows are never
included, and the link expires.

---

## Filters

Filters are generated from whichever dimensions your dataset actually has, and
sit in one row above the content. Applying one **recalculates the whole
analysis** — KPIs, charts, insights and the story — for the matching records,
not just the visuals. Reports generated with filters active describe the
filtered data.

---

## Reading a confidence level

| Level | Means |
|---|---|
| **High** | Calculated directly from your data. The number is what it says. |
| **Medium** | Strong analytical evidence, but the interpretation requires judgement — a half-period growth comparison, for example, where the split point is mechanical rather than tied to a known event. |
| **Low** | A possible explanation that needs further investigation. |

A low-confidence interpretation is never presented as a fact. Where a finding
points at a driver, it says the deviation *coincides with* or *is concentrated
in* a segment — the platform does not claim causation from a spreadsheet.

---

## Where the numbers come from

Every figure is calculated by the analytics engine from your uploaded file.
When an AI provider is configured it may only rephrase that narration, and any
figure it produces that does not match the calculated results causes the whole
response to be discarded in favour of the engine's own wording. Your
administrator can confirm which mode is active — it is reported at
`/api/system/config`.

---

## Your data

* Uploads are private to your account. No other user can reach them, even with
  the session id.
* Files are stored with restrictive permissions and deleted automatically after
  the retention window (72 hours by default). The analysis survives, so
  previously generated reports remain readable — but Explore Data will tell you
  the file is gone and ask you to upload it again.
* Delete a session at any time and its file goes with it.
* Spreadsheet content is treated strictly as data. If a cell contains text that
  reads like an instruction to an AI system, it is neutralised and reported to
  you as a data quality finding rather than acted on.
