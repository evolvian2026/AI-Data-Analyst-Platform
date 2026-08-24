import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { clsx } from '../lib/format'
import { Card, ConfidenceBadge, Loading } from './Primitives'
import type { Briefing, BriefingItem } from '../lib/types'

const STATUS_STYLE: Record<string, string> = {
  Positive: 'border-good/50 text-good',
  Neutral: 'border-warning/50 text-warning',
  Concerning: 'border-critical/50 text-critical',
}

const PRIORITY_STYLE: Record<string, string> = {
  critical: 'border-critical/50 text-critical',
  high: 'border-serious/50 text-serious',
  medium: 'border-warning/50 text-warning',
  low: 'border-line text-muted',
}

/**
 * The two-minute management summary: overall status with its reasoning, three
 * wins, concerns, trends and opportunities, the recommended actions and the
 * key numbers.
 */
export function ExecutiveBriefing({ sessionId, audience, onClose }: {
  sessionId: string; audience?: string; onClose: () => void
}) {
  const [briefing, setBriefing] = useState<Briefing | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    let active = true
    api.briefing(sessionId, audience ?? 'executive')
      .then((response) => { if (active) setBriefing(response) })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof ApiError ? caught.message : 'Could not build the briefing.')
        }
      })
    return () => { active = false }
  }, [sessionId, audience])

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40
                    p-4 py-10"
      role="dialog" aria-modal="true" aria-label="Executive briefing" onClick={onClose}>
      <div className="w-full max-w-3xl" onClick={(event) => event.stopPropagation()}>
        <Card>
          <header className="mb-5 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-xl font-semibold tracking-tight text-ink">Executive Briefing</h2>
              <p className="mt-0.5 text-xs text-muted">
                Everything management needs from this dataset, in about two minutes.
              </p>
            </div>
            <button type="button" onClick={onClose} className="btn-ghost px-2 py-1"
              aria-label="Close briefing">✕</button>
          </header>

          {!briefing && !error && <Loading rows={3} label="Building the briefing" />}
          {error && <p className="text-sm text-critical">{error}</p>}

          {briefing && (
            <div className="space-y-6">
              <section className="flex flex-wrap items-center gap-3">
                <span className={clsx('chip text-sm font-semibold',
                  STATUS_STYLE[briefing.status] ?? '')}>
                  Overall status: {briefing.status}
                </span>
                <p className="min-w-[240px] flex-1 text-sm text-subtle">
                  {briefing.status_reason}
                </p>
              </section>

              <Group title="3 biggest wins" items={briefing.wins}
                empty="No clearly positive movements were detected." />
              <Group title="3 biggest concerns" items={briefing.concerns}
                empty="No material risks or anomalies were detected." />
              <Group title="3 important trends" items={briefing.trends}
                empty="No statistically significant trends were detected." />
              <Group title="3 opportunities" items={briefing.opportunities}
                empty="No clear opportunities were identified in this dataset." />

              {briefing.actions.length > 0 && (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                    3 recommended actions
                  </h3>
                  <ol className="space-y-2">
                    {briefing.actions.map((action) => (
                      <li key={action.action}
                        className="rounded-lg border border-line p-3 text-sm">
                        <span className={clsx('chip mr-2 capitalize',
                          PRIORITY_STYLE[action.priority] ?? PRIORITY_STYLE.low)}>
                          {action.priority}
                        </span>
                        <span className="text-ink">{action.action}</span>
                        <p className="mt-1 text-xs text-subtle">{action.impact}</p>
                      </li>
                    ))}
                  </ol>
                </section>
              )}

              {briefing.key_numbers.length > 0 && (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                    Key numbers
                  </h3>
                  <div className="grid gap-2 sm:grid-cols-3">
                    {briefing.key_numbers.map((number) => (
                      <div key={number.label} className="rounded-lg border border-line p-3">
                        <p className="text-[11px] text-muted">{number.label}</p>
                        <p className="text-lg font-semibold text-ink">{number.value}</p>
                        {number.derived && (
                          <span className="chip mt-1 border-accent/40 px-1.5 py-0.5 text-[10px]
                                           text-accent">derived</span>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              <section className="border-t border-line pt-4">
                <p className="text-xs text-subtle">
                  <span className="font-medium text-ink">
                    Data quality {briefing.data_quality.score?.toFixed(0)}/100
                    {briefing.data_quality.grade && ` (${briefing.data_quality.grade})`}.
                  </span>{' '}
                  {briefing.data_quality.headline} This is the reliability ceiling for every
                  figure above.
                </p>
              </section>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

function Group({ title, items, empty }: {
  title: string; items: BriefingItem[]; empty: string
}) {
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {items.length === 0 ? (
        <p className="text-sm text-muted">{empty}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.insight_id} className="rounded-lg border border-line p-3">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <span className="chip text-[11px]">{item.type_label}</span>
                <ConfidenceBadge level={item.confidence} />
              </div>
              <p className="text-sm font-medium text-ink">{item.headline}</p>
              <p className="mt-0.5 text-xs text-subtle">{item.detail}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
