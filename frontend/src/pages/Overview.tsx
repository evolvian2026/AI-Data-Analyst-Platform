import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAnalysis } from '../context/AnalysisContext'
import { api } from '../lib/api'
import { KpiCard } from '../components/KpiCard'
import { ChartRenderer } from '../components/charts/ChartRenderer'
import { FilterBar } from '../components/FilterBar'
import { InsightCard } from '../components/InsightCard'
import { Card, ScoreRing, SectionHeading } from '../components/Primitives'
import { ExecutiveBriefing } from '../components/ExecutiveBriefing'
import { formatBytes, formatDateTime } from '../lib/format'

export function OverviewPage() {
  const {
    sessionId, view, analysis, filters, setFilters, filtering, bookmarks, notes,
    toggleBookmark, saveNote, reload,
  } = useAnalysis()
  const [showAllKpis, setShowAllKpis] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [showBriefing, setShowBriefing] = useState(false)

  if (!view || !analysis) return null

  const meta = analysis.meta
  const kpis = showAllKpis ? view.kpis.all : view.kpis.primary
  const leadChart = view.charts[0]
  const sheets = (meta.sheets ?? []).filter((sheet) => sheet.is_analyzable)

  return (
    <div className="space-y-8">
      <FilterBar definitions={analysis.filters} active={filters} onChange={setFilters}
        busy={filtering} summary={view.filter_summary ?? null} />

      {/* --- dataset summary --------------------------------------------- */}
      <section>
        <Card>
          <div className="flex flex-wrap items-start gap-6">
            <div className="min-w-[260px] flex-1">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
                What this dataset contains
              </h2>
              <p className="mt-2 text-base leading-relaxed text-ink">{view.summary}</p>
              <dl className="tnum mt-4 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted">
                <div><dt className="inline">File: </dt><dd className="inline text-subtle">{meta.filename}</dd></div>
                <div><dt className="inline">Size: </dt><dd className="inline text-subtle">{formatBytes(meta.file_size ?? 0)}</dd></div>
                <div><dt className="inline">Sheets: </dt><dd className="inline text-subtle">{meta.sheet_count}</dd></div>
                <div><dt className="inline">Rows: </dt><dd className="inline text-subtle">{view.profile.row_count.toLocaleString()}</dd></div>
                <div><dt className="inline">Columns: </dt><dd className="inline text-subtle">{view.profile.column_count}</dd></div>
                <div><dt className="inline">Cells: </dt><dd className="inline text-subtle">{(meta.total_cells ?? 0).toLocaleString()}</dd></div>
                <div><dt className="inline">Uploaded: </dt><dd className="inline text-subtle">{formatDateTime(meta.uploaded_at)}</dd></div>
              </dl>
            </div>
            <div className="flex gap-6">
              <ScoreRing score={view.quality.score} label="quality" />
              <ScoreRing score={view.story_score.score} label="story" />
            </div>
          </div>

          {sheets.length > 1 && (
            <div className="mt-5 border-t border-line pt-4">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                Analysis scope
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" disabled={switching}
                  onClick={async () => {
                    setSwitching(true)
                    await api.reanalyze(sessionId, 'workbook')
                    window.setTimeout(async () => { await reload(); setSwitching(false) }, 1500)
                  }}
                  className={`chip ${analysis.scope === 'workbook' ? 'border-accent text-accent' : ''}`}>
                  Analyze entire workbook
                </button>
                {sheets.map((sheet) => (
                  <button key={sheet.name} type="button" disabled={switching}
                    onClick={async () => {
                      setSwitching(true)
                      await api.reanalyze(sessionId, 'sheet', sheet.name)
                      window.setTimeout(async () => { await reload(); setSwitching(false) }, 1500)
                    }}
                    className={`chip ${analysis.active_sheet === sheet.name
                      ? 'border-accent text-accent' : ''}`}>
                    {sheet.name}
                    <span className="tnum text-muted">{sheet.rows.toLocaleString()}</span>
                  </button>
                ))}
                {switching && <span className="text-xs text-muted">Re-analysing…</span>}
              </div>
            </div>
          )}

          {analysis.relationships.length > 0 && (
            <div className="mt-5 border-t border-line pt-4">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                Detected relationships between sheets
              </p>
              <ul className="space-y-1 text-xs text-subtle">
                {analysis.relationships.slice(0, 4).map((relationship) => (
                  <li key={`${relationship.left}-${relationship.right}-${relationship.key}`}>
                    {relationship.narrative}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </section>

      {/* --- KPIs --------------------------------------------------------- */}
      <section>
        <SectionHeading
          title="Key metrics"
          description={`The ${view.kpis.primary.length} metrics ranked most useful for this dataset, out of ${view.kpis.count} calculated.`}
          action={
            <button type="button" className="btn-secondary text-xs"
              onClick={() => setShowAllKpis((open) => !open)}>
              {showAllKpis ? 'Show top metrics' : 'View all metrics'}
            </button>
          }
        />
        <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {kpis.map((kpi) => <KpiCard key={kpi.key} kpi={kpi} />)}
        </div>
      </section>

      {/* --- headline chart ----------------------------------------------- */}
      {leadChart && (
        <section>
          <SectionHeading title="The shape of the data"
            description={leadChart.question} />
          <ChartRenderer chart={leadChart} height={280} />
        </section>
      )}

      {/* --- top insights -------------------------------------------------- */}
      <section>
        <SectionHeading
          title="Top 5 most important findings"
          description="Ranked by magnitude, unusualness, relevance, confidence, coverage and analytical importance."
          action={<Link to={`/app/${sessionId}/insights`} className="btn-secondary text-xs">
            All {view.insights.length} findings
          </Link>}
        />
        <div className="space-y-4">
          {view.insights.slice(0, 5).map((insight) => (
            <InsightCard key={insight.id} insight={insight} rank={insight.rank}
              bookmarked={bookmarks.includes(insight.id)} note={notes[insight.id]}
              onBookmark={toggleBookmark} onNote={saveNote} />
          ))}
        </div>
      </section>

      <section className="flex flex-wrap gap-3">
        <Link to={`/app/${sessionId}/story`} className="btn-primary">Read the Data Story</Link>
        <button type="button" className="btn-secondary" onClick={() => setShowBriefing(true)}>
          Generate Executive Briefing
        </button>
        <Link to={`/app/${sessionId}/ask`} className="btn-secondary">Ask your data a question</Link>
        <Link to={`/app/${sessionId}/reports`} className="btn-secondary">Generate a report</Link>
      </section>

      {showBriefing && (
        <ExecutiveBriefing sessionId={sessionId} onClose={() => setShowBriefing(false)} />
      )}
    </div>
  )
}
