import { useCallback, useEffect, useState } from 'react'
import { useAnalysis } from '../context/AnalysisContext'
import { api, ApiError } from '../lib/api'
import {
  Card, Empty, ErrorState, Loading, SectionHeading, SeverityBadge,
} from '../components/Primitives'
import { clsx } from '../lib/format'
import type { ComparableSession, Comparison, GroupMovement, KpiMovement } from '../lib/types'

/**
 * "What changed since last time?" - the first question anyone asks of a
 * re-uploaded workbook.
 *
 * The page leads with the caveats rather than burying them, because the most
 * common way to be wrong here is to compare a total across two periods of
 * different length and call the difference growth.
 */
export function ComparePage() {
  const { sessionId, analysis } = useAnalysis()
  const [candidates, setCandidates] = useState<ComparableSession[] | null>(null)
  const [selected, setSelected] = useState<string>('')
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.comparable(sessionId)
      .then((response) => {
        if (cancelled) return
        setCandidates(response.comparable)
        if (response.comparable.length) setSelected(response.comparable[0].id)
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof ApiError ? caught.message : 'Could not list earlier analyses.')
        }
      })
    return () => { cancelled = true }
  }, [sessionId])

  const compare = useCallback(async (previousId: string) => {
    setBusy(true)
    setError(null)
    try {
      setComparison(await api.compare(sessionId, previousId))
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not compare these analyses.')
      setComparison(null)
    } finally {
      setBusy(false)
    }
  }, [sessionId])

  useEffect(() => { if (selected) void compare(selected) }, [selected, compare])

  if (!analysis) return null
  if (!candidates) return <Loading rows={2} label="Looking for comparable analyses" />

  if (candidates.length === 0) {
    return (
      <Empty
        title="Nothing to compare against yet"
        description="Upload this dataset again after it has been refreshed - or upload another workbook with the same columns - and this page will show exactly what moved between the two."
      />
    )
  }

  return (
    <div className="space-y-6">
      <SectionHeading
        title="What changed"
        description="Compare this analysis with an earlier one of the same kind of dataset."
        action={
          <label className="flex items-center gap-2 text-xs text-subtle">
            Compare with
            <select value={selected} onChange={(event) => setSelected(event.target.value)}
              className="input w-auto py-1.5 text-xs" aria-label="Earlier analysis to compare with">
              {candidates.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name} · {new Date(candidate.created_at).toLocaleDateString()}
                  {candidate.identical_shape ? '' : ` · ${candidate.comparable_pct}% comparable`}
                </option>
              ))}
            </select>
          </label>
        }
      />

      {error && <ErrorState message={error} onRetry={() => void compare(selected)} />}
      {busy && <Loading rows={2} label="Comparing" />}

      {comparison && !busy && (
        <ComparisonBody comparison={comparison} />
      )}
    </div>
  )
}

function ComparisonBody({ comparison }: { comparison: Comparison }) {
  return (
    <div className="space-y-6">
      <Card>
        <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <span className="chip border-line">{comparison.previous_label}</span>
          <span aria-hidden>→</span>
          <span className="chip border-accent/40 text-accent">{comparison.current_label}</span>
          <span className="tnum ml-auto">{comparison.comparable_pct}% comparable</span>
        </div>
        <ul className="space-y-1.5 text-sm text-ink">
          {comparison.headline.map((line) => (
            <li key={line} className="flex gap-2">
              <span aria-hidden className="text-muted">·</span>
              {line}
            </li>
          ))}
        </ul>
      </Card>

      {comparison.caveats.length > 0 && (
        <Card className="border-warning/40">
          <h3 className="text-sm font-semibold text-ink">Read these first</h3>
          <ul className="mt-2 space-y-1.5 text-xs text-subtle">
            {comparison.caveats.map((caveat) => (
              <li key={caveat} className="flex gap-2">
                <span aria-hidden className="text-warning">!</span>
                {caveat}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <h3 className="mb-3 text-sm font-semibold text-ink">Metrics</h3>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead>
              <tr className="border-b border-line text-xs text-muted">
                <th className="py-2 pr-3 font-medium">Metric</th>
                <th className="py-2 pr-3 text-right font-medium">Before</th>
                <th className="py-2 pr-3 text-right font-medium">After</th>
                <th className="py-2 pr-3 text-right font-medium">Change</th>
                <th className="py-2 font-medium">Note</th>
              </tr>
            </thead>
            <tbody>
              {comparison.kpis.map((metric) => <MetricRow key={metric.key} metric={metric} />)}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h3 className="mb-2 text-sm font-semibold text-ink">Data quality</h3>
          <p className="tnum text-2xl font-semibold text-ink">
            {comparison.quality.score_after?.toFixed(0) ?? '—'}
            <span className="ml-1 text-sm font-normal text-muted">
              / 100 ({comparison.quality.grade_after})
            </span>
          </p>
          {comparison.quality.score_delta !== null && (
            <p className={clsx('tnum mt-1 text-sm',
              comparison.quality.score_delta > 0 ? 'text-good'
                : comparison.quality.score_delta < 0 ? 'text-critical' : 'text-muted')}>
              {comparison.quality.score_delta > 0 ? '+' : ''}
              {comparison.quality.score_delta.toFixed(1)} points since{' '}
              {comparison.previous_label}
            </p>
          )}
          <dl className="mt-3 space-y-2 text-xs">
            <div>
              <dt className="text-muted">Resolved ({comparison.quality.resolved.length})</dt>
              <dd className="mt-0.5 space-y-1">
                {comparison.quality.resolved.length === 0
                  ? <span className="text-subtle">Nothing was fixed.</span>
                  : comparison.quality.resolved.map((issue) => (
                    <p key={issue.id} className="flex items-center gap-2 text-subtle">
                      <SeverityBadge level={issue.severity} />{issue.title}
                    </p>
                  ))}
              </dd>
            </div>
            <div>
              <dt className="text-muted">Introduced ({comparison.quality.introduced.length})</dt>
              <dd className="mt-0.5 space-y-1">
                {comparison.quality.introduced.length === 0
                  ? <span className="text-subtle">No new problems.</span>
                  : comparison.quality.introduced.map((issue) => (
                    <p key={issue.id} className="flex items-center gap-2 text-subtle">
                      <SeverityBadge level={issue.severity} />{issue.title}
                    </p>
                  ))}
              </dd>
            </div>
          </dl>
        </Card>

        <Card>
          <h3 className="mb-2 text-sm font-semibold text-ink">Coverage and schema</h3>
          <dl className="space-y-2 text-xs">
            <div className="flex justify-between gap-3">
              <dt className="text-muted">Records</dt>
              <dd className="tnum text-ink">
                {comparison.coverage.rows_before.toLocaleString()} →{' '}
                {comparison.coverage.rows_after.toLocaleString()}
              </dd>
            </div>
            {comparison.coverage.time_column && (
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Period covered</dt>
                <dd className="tnum text-right text-ink">
                  {comparison.coverage.period_after.from.slice(0, 10)} to{' '}
                  {comparison.coverage.period_after.to.slice(0, 10)}
                </dd>
              </div>
            )}
            <div>
              <dt className="text-muted">Columns added</dt>
              <dd className="text-ink">
                {comparison.schema.added.join(', ') || 'None'}
              </dd>
            </div>
            <div>
              <dt className="text-muted">Columns removed</dt>
              <dd className="text-ink">
                {comparison.schema.removed.join(', ') || 'None'}
              </dd>
            </div>
            {comparison.schema.reclassified.length > 0 && (
              <div>
                <dt className="text-muted">Classified differently</dt>
                <dd className="space-y-0.5 text-ink">
                  {comparison.schema.reclassified.map((item) => (
                    <p key={item.column}>
                      {item.column}: <span className="text-subtle">{item.changes.join('; ')}</span>
                    </p>
                  ))}
                </dd>
              </div>
            )}
          </dl>
        </Card>
      </div>

      {comparison.segments.length > 0 && (
        <Card>
          <h3 className="mb-3 text-sm font-semibold text-ink">Segments</h3>
          <div className="space-y-5">
            {comparison.segments.map((segment) => (
              <section key={`${segment.dimension}-${segment.measure}`}>
                <p className="mb-2 text-xs text-subtle">
                  {segment.leader_changed && (
                    <span className="chip mr-2 border-warning/50 text-warning">leader changed</span>
                  )}
                  {segment.narrative}
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[480px] text-left text-xs">
                    <thead>
                      <tr className="border-b border-line text-muted">
                        <th className="py-1.5 pr-3 font-medium">{segment.dimension}</th>
                        <th className="py-1.5 pr-3 font-medium">Rank</th>
                        <th className="py-1.5 pr-3 text-right font-medium">
                          {segment.aggregation_label} before
                        </th>
                        <th className="py-1.5 pr-3 text-right font-medium">
                          {segment.aggregation_label} after
                        </th>
                        {segment.shares_valid && (
                          <th className="py-1.5 text-right font-medium">Share shift</th>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {segment.groups.map((group) => (
                        <GroupRow key={group.group} group={group}
                          showShare={segment.shares_valid} />
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </div>
        </Card>
      )}

      {comparison.trends.length > 0 && (
        <Card>
          <h3 className="mb-2 text-sm font-semibold text-ink">Trend directions</h3>
          <ul className="space-y-1.5 text-xs">
            {comparison.trends.map((trend) => (
              <li key={trend.measure} className="flex items-center gap-2 text-subtle">
                {trend.reversed && (
                  <span className="chip border-warning/50 text-warning">reversed</span>
                )}
                {trend.narrative}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <InsightColumn title="New findings" tone="accent"
          empty="Nothing new appeared."
          items={comparison.insights.new} />
        <InsightColumn title="No longer hold" tone="muted"
          empty="Every earlier finding still holds."
          items={comparison.insights.resolved} />
        <InsightColumn title="Still true" tone="muted"
          empty="No findings carried over."
          items={comparison.insights.persisting} />
      </div>

      <p className="text-xs text-muted">{comparison.method}</p>
    </div>
  )
}

function MetricRow({ metric }: { metric: KpiMovement }) {
  const tone = metric.direction === 'up' ? 'text-good'
    : metric.direction === 'down' ? 'text-critical' : 'text-muted'
  return (
    <tr className={clsx('border-b border-line/60', metric.is_primary && 'font-medium')}>
      <td className="py-1.5 pr-3 text-ink">
        {metric.label}
        {metric.status !== 'changed' && (
          <span className="chip ml-2 border-line text-muted">{metric.status}</span>
        )}
      </td>
      <td className="tnum py-1.5 pr-3 text-right text-subtle">{metric.formatted_before}</td>
      <td className="tnum py-1.5 pr-3 text-right text-ink">{metric.formatted_after}</td>
      <td className={clsx('tnum py-1.5 pr-3 text-right', tone)}>
        {metric.change_pct === null
          ? (metric.formatted_delta || '—')
          : `${metric.change_pct > 0 ? '+' : ''}${metric.change_pct.toFixed(1)}%`}
      </td>
      <td className="py-1.5 text-xs text-muted">{metric.note}</td>
    </tr>
  )
}

function GroupRow({ group, showShare }: { group: GroupMovement; showShare: boolean }) {
  const rankDelta = group.rank_delta ?? null
  return (
    <tr className="border-b border-line/60">
      <td className="py-1.5 pr-3 text-ink">{group.group}</td>
      <td className="tnum py-1.5 pr-3 text-subtle">
        {group.rank_before ?? '—'} → {group.rank_after ?? '—'}
        {!!rankDelta && (
          <span className={clsx('ml-1', rankDelta > 0 ? 'text-good' : 'text-critical')}>
            {rankDelta > 0 ? '▲' : '▼'}
          </span>
        )}
      </td>
      <td className="tnum py-1.5 pr-3 text-right text-subtle">{group.formatted_before}</td>
      <td className="tnum py-1.5 pr-3 text-right text-ink">{group.formatted_after}</td>
      {showShare && (
        <td className={clsx('tnum py-1.5 text-right',
          (group.share_delta ?? 0) > 0 ? 'text-good'
            : (group.share_delta ?? 0) < 0 ? 'text-critical' : 'text-muted')}>
          {group.share_delta === null ? '—'
            : `${group.share_delta > 0 ? '+' : ''}${group.share_delta.toFixed(1)} pts`}
        </td>
      )}
    </tr>
  )
}

function InsightColumn({ title, items, empty, tone }: {
  title: string
  items: { id: string; headline: string; type_label: string }[]
  empty: string
  tone: 'accent' | 'muted'
}) {
  return (
    <Card>
      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-ink">
        {title}
        <span className={clsx('tnum chip',
          tone === 'accent' ? 'border-accent/40 text-accent' : 'border-line text-muted')}>
          {items.length}
        </span>
      </h3>
      {items.length === 0 ? (
        <p className="text-xs text-subtle">{empty}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((insight) => (
            <li key={insight.id} className="border-l-2 border-line pl-3">
              <p className="text-[11px] uppercase tracking-wide text-muted">
                {insight.type_label}
              </p>
              <p className="text-xs text-subtle">{insight.headline}</p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
