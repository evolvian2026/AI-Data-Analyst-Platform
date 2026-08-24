import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { formatDelta } from '../lib/format'
import { Loading } from './Primitives'
import type { ActiveFilter, DrilldownResult } from '../lib/types'

/**
 * Drill-down. Only the analyses that this dataset can actually support are
 * shown - no empty "customers" panel when there is no customer column.
 */
export function DrilldownPanel({ sessionId, dimension, value, filters, onClose, onAsk }: {
  sessionId: string
  dimension: string
  value: string
  filters: ActiveFilter[]
  onClose: () => void
  onAsk?: (question: string) => void
}) {
  const [result, setResult] = useState<DrilldownResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Escape closes the panel: it overlays the page, so it needs a keyboard exit.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    let active = true
    setResult(null)
    setError(null)
    api.drilldown(sessionId, dimension, value, filters)
      .then((response) => { if (active) setResult(response) })
      .catch((caught) => {
        if (active) setError(caught instanceof ApiError ? caught.message : 'Could not drill down.')
      })
    return () => { active = false }
  }, [sessionId, dimension, value, filters])

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" onClick={onClose} aria-hidden />
      <aside className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l
                        border-line bg-surface shadow-lift"
        role="dialog" aria-modal="true" aria-label={`Details for ${dimension} ${value}`}>
      <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-wide text-muted">{dimension}</p>
          <h2 className="truncate text-lg font-semibold text-ink">{value}</h2>
          {result && (
            <p className="tnum mt-0.5 text-xs text-muted">
              {result.records.toLocaleString()} records ·{' '}
              {result.share_of_records_pct.toFixed(1)}% of the dataset
            </p>
          )}
        </div>
        <button type="button" onClick={onClose} className="btn-ghost px-2 py-1"
          aria-label="Close details">✕</button>
      </header>

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5">
        {!result && !error && <Loading rows={3} label="Loading details" />}
        {error && <p className="text-sm text-critical">{error}</p>}

        {result && (
          <>
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                Metrics
              </h3>
              <div className="grid gap-2 sm:grid-cols-2">
                {result.metrics.map((metric) => (
                  <div key={metric.measure} className="rounded-lg border border-line p-3">
                    <p className="text-xs text-muted">{metric.measure}</p>
                    <p className="text-lg font-semibold text-ink">{metric.formatted}</p>
                    <p className="tnum text-[11px] text-muted">
                      {/* For an averaged measure the headline already is the
                          average, so repeating it says nothing. */}
                      {metric.aggregation === 'sum' && `avg ${metric.formatted_average}`}
                      {metric.aggregation === 'sum' && metric.share_pct !== null && ' · '}
                      {metric.share_pct !== null && `${metric.share_pct.toFixed(1)}% of total`}
                      {metric.aggregation !== 'sum' && metric.share_pct === null
                        && `${metric.records.toLocaleString()} records`}
                    </p>
                    {metric.vs_dataset_pct !== null && (
                      <p className={`text-[11px] font-medium ${
                        metric.vs_dataset_pct >= 0 ? 'text-good' : 'text-critical'}`}>
                        {formatDelta(metric.vs_dataset_pct)} vs dataset average
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </section>

            {result.trend && (
              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                  {result.trend.measure} over time
                </h3>
                <Sparkline points={result.trend.points} />
              </section>
            )}

            {result.breakdowns.map((breakdown) => (
              <section key={breakdown.dimension}>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                  {breakdown.measure} by {breakdown.dimension}
                </h3>
                <ul className="space-y-1">
                  {breakdown.rows.map((row) => (
                    <li key={row.name} className="flex items-center gap-2 text-xs">
                      <span className="w-28 shrink-0 truncate text-subtle" title={row.name}>
                        {row.name}
                      </span>
                      <span className="h-2 flex-1 overflow-hidden rounded-full bg-page">
                        <span className="block h-full rounded-full bg-accent"
                          style={{ width: `${row.share_pct ?? 0}%` }} />
                      </span>
                      <span className="tnum w-20 shrink-0 text-right text-ink">{row.formatted}</span>
                    </li>
                  ))}
                </ul>
              </section>
            ))}

            {result.top_records.length > 0 && (
              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                  Largest records
                </h3>
                <ul className="space-y-1 text-xs">
                  {result.top_records.map((record) => (
                    <li key={record.identifier} className="flex justify-between gap-3">
                      <span className="truncate text-subtle">{record.identifier}</span>
                      <span className="tnum shrink-0 text-ink">{record.formatted}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {result.related_anomalies.length > 0 && (
              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                  Related anomalies
                </h3>
                <ul className="space-y-1 text-xs text-subtle">
                  {result.related_anomalies.map((anomaly) => (
                    <li key={anomaly.id}>{anomaly.headline}</li>
                  ))}
                </ul>
              </section>
            )}

            {onAsk && (
              <button type="button" className="btn-secondary w-full text-xs"
                onClick={() => onAsk(`What is driving ${value} in ${dimension}?`)}>
                Ask about {value}
              </button>
            )}
          </>
        )}
      </div>
      </aside>
    </>
  )
}

function Sparkline({ points }: { points: { name: string; value: number }[] }) {
  if (points.length < 2) return <p className="text-xs text-muted">Not enough periods to plot.</p>
  const values = points.map((point) => point.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const path = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * 100
      const y = 100 - ((point.value - min) / span) * 100
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')

  return (
    <div>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-16 w-full"
        role="img" aria-label="Trend over time">
        <path d={path} fill="none" stroke="rgb(var(--accent))" strokeWidth={2}
          vectorEffect="non-scaling-stroke" />
      </svg>
      <p className="tnum mt-1 flex justify-between text-[11px] text-muted">
        <span>{points[0].name}</span>
        <span>{points[points.length - 1].name}</span>
      </p>
    </div>
  )
}
