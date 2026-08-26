# User guide

## Getting started

1. Create an account. Your datasets are visible only to you.
2. On the workspace, drag an Excel workbook onto the upload area — or load one
   of the six sample datasets to see the full analysis in about a minute.
   *SaaS Subscriptions* is the two-sheet one, so it is the one to load if you
   want to try combining sheets or the data-cleaning proposals.
3. Watch the twelve processing stages tick through. Analysis runs on the
   server, so a large workbook never loads into your browser.

**What uploads well.** `.xlsx` and `.xls`, up to 100 MB by default. Multiple
sheets, empty rows and columns, missing or duplicate headers and mixed types
are all handled. There is no schema to configure — the platform works out what
your columns mean from their values.

**Multi-sheet workbooks.** Sheets sharing a schema are stacked automatically.
On the Overview you can switch between *Analyze entire workbook* and any single
sheet, and the whole analysis re-runs for that scope. Sheets that do *not* share
a schema but do share a key can be **combined** instead — see Overview below.

---

## The ten sections

### Overview

The orientation page. It answers "what is in this file?" before it answers
anything else: a generated description of the dataset, the file's own facts,
the data quality and story strength scores, the metrics worth watching, the
shape of the leading measure over time, and the five most important findings.

Two things live here that are worth knowing about.

**Review how columns are read.** Working out what a column means from its values
is right most of the time and not all of the time — and when it is wrong, every
number downstream inherits the mistake. This panel shows what was decided about
each column, with the values behind the decision, and lets you correct the type,
the role and whether a measure is summed or averaged. Applying a correction
re-runs the whole analysis with that column read your way; clearing it returns
to the inferred classification. Only corrections your data can actually support
are offered — a column of region names is never offered as a measure, and the
panel says why.

**Combine sheets.** When two sheets share a key — orders and customers, invoices
and accounts — you can join them into a new analysis. The join is previewed
first: how many rows on each side find a match, how many an inner join would
drop, and how large the result will be. Two warnings matter:

* If the key repeats on *both* sheets, joining multiplies rows and every total
  calculated from the result is overstated. That join is refused rather than
  analysed.
* Columns coming from the lookup side repeat on every matching row. They are
  averaged rather than totalled and kept out of trends, because summing a
  customer's credit limit across their orders measures how often they ordered,
  not anything about the limit.

The join creates a **new** analysis. The originals are left exactly as they
were.

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

**Useful? ▲ ▼** teaches the ranking what you care about. An operations manager
does not want the data-quality findings a data steward lives for, and rating a
few findings shifts the order towards the kind you use. Three limits, stated so
you can trust it:

* It changes the **order only** — never a number, never a confidence level,
  never whether a finding reaches a report. A finding you downvote is still true.
* It is **bounded**: at most 8 points on a 100-point priority score, so a large,
  unusual, high-confidence finding cannot be voted off the front page.
* It is **explained**: any adjusted finding says why it moved.

Ratings are yours alone and follow the subject of a finding, so they still apply
after a re-analysis or on next month's upload of the same dataset.

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

**Follow-ups work.** Ask one question, then just say what to change:

> Which region has the highest revenue?
> *→ North has the highest total Revenue at 24.07M…*
>
> and by product?
> *→ Product A has the highest total Revenue at 24.57M…*

The second question inherits what the first established. Every answer begins by
stating how it was read — *"Understood as: the highest Product by Revenue
(carried over from your previous question: measure)"* — so if it inherited the
wrong thing you can see that immediately rather than trusting a number that
answers a question you did not ask. **Start a new thread** clears the context.

### Projection

A forecast is the one number on this platform that was never measured, so it
lives on its own page rather than mixed into pages that report what happened.

For each leading measure you get the method used, how many periods it was fitted
to, the projected values, and a 90% prediction interval around each of them. On
a chart a projection is always a **dashed line over a shaded band, starting at a
labelled boundary** — never a continuation of the solid measured line.

The more useful half of this page is often *Not projected*. A projection is
withheld entirely, with the reason stated, when the series is too short, varies
too much around its own average, or would produce an interval so wide it carries
no information. "We cannot tell you" is a real answer, and the platform gives it
rather than a confident-looking line.

Three methods, chosen by what the data supports:

| Method | Used when |
|---|---|
| Linear trend extrapolation | There is a statistically significant slope. |
| Recent level carried forward | There is not. Saying "about the same" is honest; extrapolating noise is not. |
| …with a seasonal pattern | Either of the above, when at least two full cycles show a repeating pattern strong enough to be worth modelling. |

Projected values never enter a KPI, a total, a share or a report figure.

### What Changed

Re-upload a refreshed workbook and this page tells you what moved since last
time. It finds earlier analyses of yours describing the same kind of dataset —
same columns in the same analytical roles, not merely the same filename — and
diffs them:

* which metrics moved, by how much, and which movements are material;
* whether data quality improved, and which issues were fixed or introduced;
* how segments shifted in rank and share, and whether the leader changed;
* trend directions that reversed;
* findings that appeared, no longer hold, or carried over.

**Read the caveats first.** They are at the top for a reason: the most common
way to be wrong here is to compare a total across two periods of different
length and call the difference growth. If the newer dataset covers more time,
the page says so and tells you to compare rates and shares instead.

Anything present in only one of the two analyses is reported as *added* or
*removed*, never quietly compared — and a metric whose aggregation changed
between runs is marked incomparable rather than differenced.

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

**Suggested corrections.** Where a problem has a fix the platform can propose,
it proposes it: inconsistently spelled categories, numbers stored as text,
duplicated rows. Each proposal shows the exact number of cells involved, real
before-and-after values from your own data, and an honest statement of the risk
— including when a fix discards data rather than repairing it.

Three things are always true here:

* **Nothing is applied until you accept it.** A proposal is a description, not
  an action. **Preview the effect** shows exactly what would change without
  changing anything.
* **Your uploaded file is never modified.** An accepted fix is stored as a
  recipe and replayed onto a copy of the data every time it is read.
* **It is completely reversible.** Clearing the fixes restores the original
  analysis exactly.

While fixes are applied, every page of the analysis carries a *cleaned data*
marker and this page shows precisely what each fix changed.

### Explore Data

The rows behind the analysis, with server-side paging, sorting and search.
Column headers show how each column was classified. Download the filtered rows
as CSV at any point.

### Reports

**PDF.** Choose Executive (2–5 pages), Standard (5–15) or Detailed (15+). Set
the title, organization, author, logo and date range, pick the sections, and
choose the audience. The engine sizes the report to what it actually found
rather than padding to a page count.

**Excel.** A 17-sheet analysis workbook: executive summary, KPIs, the data
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
response to be discarded in favour of the engine's own wording.

The single exception is the Projection page, and it is marked everywhere it
appears: a projected value is model output, not a measurement. Projections are
never included in a KPI, a total, a share or a report figure, and they are drawn
as a dashed line over a prediction interval so they cannot be mistaken for
measured values at a glance. Your
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
* Your administrator may also set a window for the **analyses** themselves,
  which still hold aggregates and sample values from your file. Where one is
  set, the workspace shows the date each analysis will be deleted; where none
  is, analyses are kept until you delete them.
* Delete a session at any time and its file goes with it.
* Spreadsheet content is treated strictly as data. If a cell contains text that
  reads like an instruction to an AI system, it is neutralised and reported to
  you as a data quality finding rather than acted on.
