import { useState } from 'react'
import type { Insight } from '../lib/types'
import { clsx } from '../lib/format'
import { ConfidenceBadge } from './Primitives'
import { EvidencePanel } from './EvidencePanel'

const TYPE_ACCENT: Record<string, string> = {
  performance: 'border-l-[color:var(--series-1)]',
  trend: 'border-l-[color:var(--series-3)]',
  driver: 'border-l-[color:var(--series-7)]',
  anomaly: 'border-l-[color:var(--series-2)]',
  risk: 'border-l-critical',
  opportunity: 'border-l-good',
  data_quality: 'border-l-warning',
  relationship: 'border-l-[color:var(--series-5)]',
  distribution: 'border-l-[color:var(--series-4)]',
}

interface Props {
  insight: Insight
  rank?: number
  bookmarked?: boolean
  note?: string
  onBookmark?: (id: string) => void
  onNote?: (id: string, note: string) => void
  onAsk?: (question: string) => void
  onInvestigate?: (anomalyId: string) => void
  chartSlot?: React.ReactNode
}

export function InsightCard({
  insight, rank, bookmarked, note, onBookmark, onNote, onAsk, onInvestigate, chartSlot,
}: Props) {
  const [showEvidence, setShowEvidence] = useState(false)
  const [editingNote, setEditingNote] = useState(false)
  const [draft, setDraft] = useState(note ?? '')
  const anomalyId = insight.evidence.anomaly_id

  return (
    <article className={clsx(
      'card border-l-4 p-5',
      TYPE_ACCENT[insight.type] ?? 'border-l-accent',
    )}>
      <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            {rank !== undefined && (
              <span className="tnum chip border-accent/40 px-2 py-0.5 text-accent">#{rank}</span>
            )}
            <span className="chip">{insight.type_label}</span>
            <ConfidenceBadge level={insight.confidence} reason={insight.confidence_reason} />
            <span className="tnum text-[11px] text-muted" title="Insight priority score">
              priority {insight.priority.score.toFixed(0)}
            </span>
          </div>
          <h3 className="text-base font-semibold leading-snug text-ink">{insight.headline}</h3>
        </div>
        {onBookmark && (
          <button type="button" onClick={() => onBookmark(insight.id)}
            aria-pressed={bookmarked}
            aria-label={bookmarked ? 'Remove bookmark' : 'Bookmark this insight'}
            className={clsx('btn-ghost px-2 py-1 text-sm',
              bookmarked && 'text-warning')}>
            {bookmarked ? '★' : '☆'}
          </button>
        )}
      </header>

      <dl className="space-y-2.5 text-sm">
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-muted">Fact</dt>
          <dd className="mt-0.5 text-ink">{insight.fact}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-muted">
            Interpretation
          </dt>
          <dd className="mt-0.5 text-subtle">{insight.interpretation}</dd>
        </div>
        {insight.so_what && (
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-muted">
              Why it matters
            </dt>
            <dd className="mt-0.5 text-subtle">{insight.so_what}</dd>
          </div>
        )}
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-muted">
            Recommendation
          </dt>
          <dd className="mt-0.5 text-subtle">{insight.recommendation}</dd>
        </div>
      </dl>

      {chartSlot && <div className="mt-4">{chartSlot}</div>}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => setShowEvidence((open) => !open)}
          className="btn-ghost px-2 py-1 text-xs" aria-expanded={showEvidence}>
          Why am I seeing this insight?
        </button>
        {anomalyId && onInvestigate && (
          <button type="button" onClick={() => onInvestigate(anomalyId)}
            className="btn-ghost px-2 py-1 text-xs">
            Investigate anomaly
          </button>
        )}
        {onNote && (
          <button type="button" onClick={() => setEditingNote((open) => !open)}
            className="btn-ghost px-2 py-1 text-xs">
            {note ? 'Edit note' : 'Add note'}
          </button>
        )}
      </div>

      {showEvidence && (
        <div className="mt-3 animate-fade-in">
          <EvidencePanel evidence={insight.evidence} confidence={insight.confidence}
            confidenceReason={insight.confidence_reason} />
        </div>
      )}

      {note && !editingNote && (
        <p className="mt-3 rounded-lg border-l-2 border-warning bg-page px-3 py-2 text-xs text-subtle">
          <span className="font-medium text-ink">Your note: </span>{note}
        </p>
      )}

      {editingNote && onNote && (
        <div className="mt-3 animate-fade-in space-y-2">
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)}
            rows={2} className="input resize-y" placeholder="Add context for your team…"
            aria-label="Note on this insight" />
          <div className="flex gap-2">
            <button type="button" className="btn-primary px-3 py-1.5 text-xs"
              onClick={() => { onNote(insight.id, draft); setEditingNote(false) }}>
              Save note
            </button>
            <button type="button" className="btn-ghost px-3 py-1.5 text-xs"
              onClick={() => { setDraft(note ?? ''); setEditingNote(false) }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {insight.next_questions.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
            What next?
          </p>
          <ul className="flex flex-wrap gap-2">
            {insight.next_questions.slice(0, 4).map((question) => (
              <li key={question}>
                {onAsk ? (
                  <button type="button" onClick={() => onAsk(question)}
                    className="chip hover:border-accent hover:text-accent">
                    {question}
                  </button>
                ) : (
                  <span className="chip">{question}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  )
}
