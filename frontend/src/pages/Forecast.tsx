import { useEffect, useState } from 'react'
import { useAnalysis } from '../context/AnalysisContext'
import { api, ApiError } from '../lib/api'
import { ChartRenderer } from '../components/charts/ChartRenderer'
import { Card, ConfidenceBadge, Empty, ErrorState, Loading, SectionHeading } from '../components/Primitives'
import { clsx } from '../lib/format'
import type { Forecast } from '../lib/types'

/**
 * Projections, kept deliberately separate from every page that reports what
 * happened. A reader arrives here having chosen to look at a forecast, sees the
 * method and its assumptions before the numbers, and sees the measures that
 * could *not* be projected with the reason why - which is often the more useful
 * half of the page.
 */
export function ForecastPage() {
  const { sessionId, analysis } = useAnalysis()
  const [state, setState] = useState<{
    forecasts: Forecast[]; unavailable: { measure: string; reason: string }[]; policy: string
  } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    api.forecast(sessionId)
      .then((response) => { if (!cancelled) setState(response) })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof ApiError ? caught.message : 'Could not load projections.')
        }
      })
    return () => { cancelled = true }
  }, [sessionId])

  if (error) return <ErrorState message={error} />
  if (!state || !analysis) return <Loading rows={3} label="Preparing projections" />

  const available = state.forecasts.filter((f): f is Extract<Forecast, { available: true }> =>
    f.available)

  if (!analysis.time_column) {
    return (
      <Empty
        title="No time column, so nothing to project"
        description="A projection needs a date column to extend. This dataset has none, so the platform reports what the data shows rather than guessing at a shape it cannot see."
      />
    )
  }

  return (
    <div className="space-y-6">
      <SectionHeading
        title="Projection"
        description={state.policy}
      />

      {available.length === 0 ? (
        <Empty
          title="Nothing here can be projected honestly"
          description="Every measure was tested and none produced a projection worth showing. The reasons are listed below."
        />
      ) : (
        <div className="space-y-6">
          {available.map((forecast) => (
            <ForecastCard key={forecast.measure} forecast={forecast}
              chart={analysis.charts.find(
                (c) => c.projection?.measure === forecast.measure,
              )} />
          ))}
        </div>
      )}

      {state.unavailable.length > 0 && (
        <Card>
          <h3 className="text-sm font-semibold text-ink">Not projected</h3>
          <p className="mt-1 text-xs text-subtle">
            A refusal is a result. These measures were tested and withheld.
          </p>
          <ul className="mt-3 space-y-2.5">
            {state.unavailable.map((item) => (
              <li key={item.measure} className="border-l-2 border-line pl-3">
                <p className="text-sm font-medium text-ink">{item.measure}</p>
                <p className="mt-0.5 text-xs text-subtle">{item.reason}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}

function ForecastCard({ forecast, chart }: {
  forecast: Extract<Forecast, { available: true }>
  chart?: import('../lib/types').Chart
}) {
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-ink">
            {forecast.aggregation_label} {forecast.measure}
            <span className="ml-2 text-sm font-normal text-muted">
              next {forecast.horizon} {forecast.unit}
              {forecast.horizon > 1 ? 's' : ''}
            </span>
          </h3>
          <p className="mt-1 text-xs text-subtle">{forecast.basis}</p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <span className="chip border-line text-muted">{forecast.method_label}</span>
          <ConfidenceBadge level={forecast.confidence} />
        </div>
      </div>

      {chart && <ChartRenderer chart={chart} height={260} />}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] text-left text-sm">
          <caption className="sr-only">
            Projected {forecast.measure} with a {forecast.interval_pct}% prediction interval
          </caption>
          <thead>
            <tr className="border-b border-line text-xs text-muted">
              <th className="py-2 pr-3 font-medium capitalize">{forecast.unit}</th>
              <th className="py-2 pr-3 font-medium">Projected</th>
              <th className="py-2 font-medium">
                {forecast.interval_pct}% prediction interval
              </th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-line/60">
              <td className="py-1.5 pr-3 text-ink">{forecast.last_measured_period}</td>
              <td className="tnum py-1.5 pr-3 text-subtle">
                <span className="chip mr-1.5 border-line text-muted">measured</span>
              </td>
              <td className="py-1.5 text-xs text-muted">Last measured period</td>
            </tr>
            {forecast.points.map((point) => (
              <tr key={point.iso} className="border-b border-line/60">
                <td className="py-1.5 pr-3 text-ink">{point.label}</td>
                <td className="tnum py-1.5 pr-3 font-medium text-subtle">{point.formatted}</td>
                <td className="tnum py-1.5 text-xs text-muted">{point.formatted_range}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className={clsx('rounded-lg border px-3 py-2.5 text-xs',
        forecast.confidence === 'low'
          ? 'border-warning/40 bg-warning/5' : 'border-line bg-page')}>
        <p className="font-medium text-ink">{forecast.disclaimer}</p>
        <ul className="mt-1.5 list-disc space-y-1 pl-4 text-subtle">
          {forecast.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}
        </ul>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-muted">Measured periods</dt>
          <dd className="tnum text-ink">{forecast.measured_periods}</dd>
        </div>
        <div>
          <dt className="text-muted">Fit (R²)</dt>
          <dd className="tnum text-ink">
            {forecast.r_squared === null ? 'n/a' : forecast.r_squared.toFixed(2)}
          </dd>
        </div>
        <div>
          <dt className="text-muted">Volatility</dt>
          <dd className="tnum text-ink">{forecast.volatility_pct.toFixed(0)}%</dd>
        </div>
        <div>
          <dt className="text-muted">Seasonality</dt>
          <dd className="text-ink">{forecast.seasonal ? 'Modelled' : 'Not modelled'}</dd>
        </div>
      </dl>
    </Card>
  )
}
