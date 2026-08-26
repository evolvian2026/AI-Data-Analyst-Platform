import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAnalysis } from '../context/AnalysisContext'
import { api } from '../lib/api'
import { InsightCard } from '../components/InsightCard'
import { ChartRenderer } from '../components/charts/ChartRenderer'
import { FilterBar } from '../components/FilterBar'
import { Card, Empty, SectionHeading, SeverityBadge } from '../components/Primitives'
import { clsx } from '../lib/format'
import type { Investigation } from '../lib/types'

const TYPES = [
  { value: 'all', label: 'All' },
  { value: 'performance', label: 'Performance' },
  { value: 'trend', label: 'Trend' },
  { value: 'driver', label: 'Driver' },
  { value: 'anomaly', label: 'Anomaly' },
  { value: 'risk', label: 'Risk' },
  { value: 'opportunity', label: 'Opportunity' },
  { value: 'relationship', label: 'Relationship' },
  { value: 'distribution', label: 'Distribution' },
  { value: 'data_quality', label: 'Data Quality' },
]

export function InsightsPage() {
  const {
    sessionId, view, analysis, filters, setFilters, filtering, bookmarks, notes,
    toggleBookmark, saveNote, rateInsight,
  } = useAnalysis()
  const navigate = useNavigate()
  const [type, setType] = useState('all')
  const [onlyBookmarked, setOnlyBookmarked] = useState(false)
  const [withCharts, setWithCharts] = useState(true)
  const [investigation, setInvestigation] = useState<Investigation | null>(null)

  const insights = useMemo(() => {
    const all = view?.insights ?? []
    return all.filter((insight) => (
      (type === 'all' || insight.type === type)
      && (!onlyBookmarked || bookmarks.includes(insight.id))
    ))
  }, [view, type, onlyBookmarked, bookmarks])

  const counts = useMemo(() => {
    const map: Record<string, number> = {}
    ;(view?.insights ?? []).forEach((insight) => {
      map[insight.type] = (map[insight.type] ?? 0) + 1
    })
    return map
  }, [view])

  if (!view || !analysis) return null

  const chartFor = (id: string | null) =>
    (withCharts && id ? view.charts.find((chart) => chart.id === id) : undefined)

  return (
    <div className="space-y-6">
      <FilterBar definitions={analysis.filters} active={filters} onChange={setFilters}
        busy={filtering} summary={view.filter_summary ?? null} />

      {analysis.feedback?.active && (
        <p className="rounded-lg border border-line bg-surface px-3 py-2 text-xs text-subtle">
          <span className="font-medium text-ink">Ranking adapted to you. </span>
          {analysis.feedback.statement}
        </p>
      )}

      <SectionHeading
        title="Insights"
        description={`${view.insights.length} findings, ranked by priority. Every one carries the calculation and the records behind it.`}
        action={
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-subtle">
              <input type="checkbox" checked={withCharts} className="accent-[rgb(var(--accent))]"
                onChange={(event) => setWithCharts(event.target.checked)} />
              Show charts
            </label>
            <label className="flex items-center gap-1.5 text-xs text-subtle">
              <input type="checkbox" checked={onlyBookmarked} className="accent-[rgb(var(--accent))]"
                onChange={(event) => setOnlyBookmarked(event.target.checked)} />
              Bookmarked only
            </label>
          </div>
        }
      />

      <div className="flex flex-wrap gap-1.5">
        {TYPES.filter((option) => option.value === 'all' || counts[option.value]).map((option) => (
          <button key={option.value} type="button" onClick={() => setType(option.value)}
            className={clsx('chip transition-colors hover:border-accent',
              type === option.value && 'border-accent bg-accent/10 text-accent')}>
            {option.label}
            <span className="tnum text-muted">
              {option.value === 'all' ? view.insights.length : counts[option.value] ?? 0}
            </span>
          </button>
        ))}
      </div>

      {insights.length === 0 ? (
        <Empty title="Nothing matches these filters"
          description="Try a different insight type, or clear the bookmark filter." />
      ) : (
        <div className="space-y-4">
          {insights.map((insight) => {
            const chart = chartFor(insight.chart_id)
            return (
              <InsightCard key={insight.id} insight={insight} rank={insight.rank}
                bookmarked={bookmarks.includes(insight.id)} note={notes[insight.id]}
                onBookmark={toggleBookmark} onNote={saveNote}
                onRate={view.filtered ? undefined : (id, vote) => { void rateInsight(id, vote) }}
                onAsk={(question) =>
                  navigate(`/app/${sessionId}/ask?q=${encodeURIComponent(question)}`)}
                onInvestigate={async (anomalyId) => {
                  setInvestigation(await api.investigate(sessionId, anomalyId))
                }}
                chartSlot={chart ? <ChartRenderer chart={chart} height={220} /> : undefined}
              />
            )
          })}
        </div>
      )}

      {investigation && (
        <InvestigationModal investigation={investigation} onClose={() => setInvestigation(null)} />
      )}
    </div>
  )
}

function InvestigationModal({ investigation, onClose }: {
  investigation: Investigation; onClose: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog" aria-modal="true" aria-label="Anomaly investigation" onClick={onClose}>
      <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto"
        onClick={(event) => event.stopPropagation()}>
        <Card>
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-ink">What may explain this anomaly?</h2>
              {investigation.anomaly && (
                <p className="mt-1 flex items-center gap-2 text-sm text-subtle">
                  <SeverityBadge level={investigation.anomaly.severity} />
                  {investigation.anomaly.headline}
                </p>
              )}
            </div>
            <button type="button" onClick={onClose} className="btn-ghost px-2 py-1"
              aria-label="Close">✕</button>
          </div>

          {!investigation.available ? (
            <p className="text-sm text-subtle">{investigation.reason}</p>
          ) : (
            <div className="space-y-5 text-sm">
              <ul className="space-y-2">
                {(investigation.explanations ?? []).map((explanation) => (
                  <li key={explanation} className="rounded-lg border-l-2 border-accent bg-page
                                                   px-3 py-2 text-subtle">
                    {explanation}
                  </li>
                ))}
              </ul>

              {(investigation.contributions ?? []).map((contribution) => (
                <section key={contribution.dimension}>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                    By {contribution.dimension}
                  </h3>
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-line text-muted">
                        <th className="py-1.5 pr-3 font-medium">{contribution.dimension}</th>
                        <th className="py-1.5 pr-3 font-medium">Amount</th>
                        <th className="py-1.5 pr-3 font-medium">Share here</th>
                        <th className="py-1.5 pr-3 font-medium">Share elsewhere</th>
                        <th className="py-1.5 font-medium">Shift</th>
                      </tr>
                    </thead>
                    <tbody>
                      {contribution.rows.map((row) => (
                        <tr key={row.value} className="border-b border-line/60">
                          <td className="py-1.5 pr-3 text-ink">{row.value}</td>
                          <td className="tnum py-1.5 pr-3 text-subtle">{row.formatted}</td>
                          <td className="tnum py-1.5 pr-3 text-subtle">{row.share_pct.toFixed(1)}%</td>
                          <td className="tnum py-1.5 pr-3 text-subtle">
                            {row.normal_share_pct.toFixed(1)}%
                          </td>
                          <td className={clsx('tnum py-1.5 font-medium',
                            row.share_shift_pct >= 0 ? 'text-good' : 'text-critical')}>
                            {row.share_shift_pct >= 0 ? '+' : ''}{row.share_shift_pct.toFixed(0)} pts
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              ))}

              {investigation.companion_measures && investigation.companion_measures.length > 0 && (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                    Other measures over the same records
                  </h3>
                  <ul className="space-y-1 text-subtle">
                    {investigation.companion_measures.map((measure) => (
                      <li key={measure.measure}>{measure.narrative}</li>
                    ))}
                  </ul>
                </section>
              )}

              <p className="rounded-lg border border-warning/40 bg-warning/5 px-3 py-2 text-xs
                            text-subtle">
                {investigation.caveat}
              </p>

              {investigation.next_questions && investigation.next_questions.length > 0 && (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                    Next questions
                  </h3>
                  <ul className="flex flex-wrap gap-2">
                    {investigation.next_questions.map((question) => (
                      <li key={question} className="chip">{question}</li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
