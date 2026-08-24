import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAnalysis } from '../context/AnalysisContext'
import { api } from '../lib/api'
import { ChartRenderer } from '../components/charts/ChartRenderer'
import { EvidencePanel } from '../components/EvidencePanel'
import { ConfidenceBadge, Card, ScoreRing, Toggle } from '../components/Primitives'
import { clsx } from '../lib/format'
import type { AdaptedInsight, Story } from '../lib/types'

/**
 * Story Mode: an executive presentation rather than a wall of charts. Cards are
 * ordered by analytical importance, and each carries its headline, a supporting
 * number, a chart, the evidence, a confidence level and a next step.
 */
export function DataStoryPage() {
  const { sessionId, view, analysis } = useAnalysis()
  const [audience, setAudience] = useState('manager')
  const [story, setStory] = useState<Story | null>(null)
  const [position, setPosition] = useState(0)
  const [mode, setMode] = useState<'presentation' | 'document'>('presentation')

  useEffect(() => {
    api.story(sessionId, audience).then(setStory).catch(() => setStory(null))
  }, [sessionId, audience])

  const cards = story?.cards ?? view?.story.cards ?? []
  const adapted = useMemo(() => {
    const map = new Map<string, AdaptedInsight>()
    story?.adapted_insights?.forEach((item) => map.set(item.id, item))
    return map
  }, [story])

  if (!view || !analysis) return null
  const card = cards[Math.min(position, cards.length - 1)]
  const chart = card?.chart_id ? view.charts.find((c) => c.id === card.chart_id) : undefined
  const audiences = analysis.audiences ?? {}

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Data Story</h1>
          <p className="mt-1 max-w-2xl text-sm text-subtle">
            The findings arranged in the order that makes them make sense - what is happening, what
            changed, what is driving it, and what to do next.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-muted">
            Audience
            <select value={audience} onChange={(event) => setAudience(event.target.value)}
              className="input w-auto py-1.5 text-xs">
              {Object.entries(audiences).map(([key, config]) => (
                <option key={key} value={key}>{config.label}</option>
              ))}
            </select>
          </label>
          {audiences[audience] && (
            <span className="hidden text-xs text-muted lg:inline">
              {audiences[audience].description}
            </span>
          )}
          <Toggle ariaLabel="Story view" value={mode}
            onChange={(value) => setMode(value as 'presentation' | 'document')}
            options={[
              { value: 'presentation', label: 'Presentation' },
              { value: 'document', label: 'Document' },
            ]} />
        </div>
      </header>


      {mode === 'presentation' && card && (
        <>
          <div className="flex items-center gap-3">
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-line">
              <div className="h-full rounded-full bg-accent transition-all"
                style={{ width: `${((position + 1) / cards.length) * 100}%` }} />
            </div>
            <span className="tnum shrink-0 text-xs text-muted">
              {position + 1} / {cards.length}
            </span>
          </div>

          <Card className="min-h-[340px]">
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <span className="chip border-accent/40 text-accent">
                {card.type_label ?? card.section.replace(/_/g, ' ')}
              </span>
              <ConfidenceBadge level={card.confidence} reason={card.confidence_reason} />
              {card.priority_score !== undefined && (
                <span className="tnum text-[11px] text-muted">
                  priority {card.priority_score.toFixed(0)}
                </span>
              )}
            </div>

            <h2 className="text-2xl font-semibold leading-tight tracking-tight text-ink">
              {card.headline}
            </h2>

            {card.supporting_kpi?.value && (
              <p className="mt-3 flex items-baseline gap-3">
                <span className="text-3xl font-semibold text-accent">
                  {card.supporting_kpi.value}
                </span>
                <span className="text-sm text-muted">{card.supporting_kpi.label}</span>
                {card.supporting_kpi.sub && (
                  <span className="text-sm font-medium text-subtle">{card.supporting_kpi.sub}</span>
                )}
              </p>
            )}

            <div className="mt-4 space-y-3 text-sm leading-relaxed">
              {card.fact && <p className="text-ink">{card.fact}</p>}
              <p className="text-subtle">
                {/* Summary and recommendation cards carry composed narrative;
                    only a card that represents one insight can be re-narrated
                    for the chosen audience. */}
                {(card.type && card.insight_ids.length === 1
                  ? adapted.get(card.insight_ids[0])?.body : null) ?? card.explanation}
              </p>
              {card.so_what && (
                <p className="text-subtle">
                  <span className="font-medium text-ink">Why it matters. </span>{card.so_what}
                </p>
              )}
            </div>

            {chart && (
              <div className="mt-5">
                <ChartRenderer chart={chart} height={240} />
              </div>
            )}

            {card.questions && card.questions.length > 0 && (
              <ul className="mt-5 flex flex-wrap gap-2">
                {card.questions.slice(0, 6).map((question) => (
                  <li key={question}>
                    <Link to={`/app/${sessionId}/ask?q=${encodeURIComponent(question)}`}
                      className="chip hover:border-accent hover:text-accent">{question}</Link>
                  </li>
                ))}
              </ul>
            )}

            {card.recommendations && card.recommendations.length > 0 && (
              <ol className="mt-5 space-y-2">
                {card.recommendations.slice(0, 5).map((recommendation) => (
                  <li key={recommendation.id} className="rounded-lg border border-line p-3 text-sm">
                    <span className={clsx('chip mr-2 capitalize',
                      recommendation.priority === 'critical' ? 'border-critical/50 text-critical'
                        : recommendation.priority === 'high' ? 'border-serious/50 text-serious'
                          : 'border-line text-muted')}>
                      {recommendation.priority}
                    </span>
                    <span className="text-subtle">{recommendation.action}</span>
                  </li>
                ))}
              </ol>
            )}

            {card.recommendation && (
              <p className="mt-5 rounded-lg border-l-2 border-accent bg-page px-3 py-2.5 text-sm
                            text-subtle">
                <span className="font-medium text-ink">Recommendation. </span>
                {card.recommendation}
              </p>
            )}

            <details className="mt-5">
              <summary className="cursor-pointer text-xs font-medium text-accent">
                Why am I seeing this?
              </summary>
              <div className="mt-2">
                <EvidencePanel evidence={card.evidence} confidence={card.confidence}
                  confidenceReason={card.confidence_reason} />
              </div>
            </details>
          </Card>

          <nav className="flex items-center justify-between gap-3">
            <button type="button" className="btn-secondary" disabled={position === 0}
              onClick={() => setPosition((current) => Math.max(0, current - 1))}>
              ← Previous
            </button>
            <Link to={`/app/${sessionId}/dashboard`} className="btn-ghost text-xs">
              View dashboard
            </Link>
            <button type="button" className="btn-primary"
              disabled={position >= cards.length - 1}
              onClick={() => setPosition((current) => Math.min(cards.length - 1, current + 1))}>
              Next →
            </button>
          </nav>

          <ol className="flex flex-wrap gap-1.5">
            {cards.map((item, index) => (
              <li key={item.id}>
                <button type="button" onClick={() => setPosition(index)}
                  aria-current={index === position}
                  className={clsx('rounded-md px-2 py-1 text-[11px] transition-colors',
                    index === position ? 'bg-accent text-accent-ink'
                      : 'text-muted hover:bg-page hover:text-ink')}>
                  {index + 1}. {item.headline.slice(0, 34)}
                  {item.headline.length > 34 ? '…' : ''}
                </button>
              </li>
            ))}
          </ol>
        </>
      )}

      {mode === 'document' && (
        <div className="space-y-6">
          <Card className="flex flex-wrap items-center gap-6">
            <ScoreRing score={view.story_score.score} label={view.story_score.label} />
            <div className="min-w-[240px] flex-1">
              <h2 className="text-sm font-semibold text-ink">Data story strength</h2>
              <p className="mt-1 text-sm text-subtle">{view.story_score.explanation}</p>
              <dl className="tnum mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
                {Object.entries(view.story_score.components).map(([key, value]) => (
                  <div key={key}>
                    <dt className="inline">{key.replace(/_/g, ' ')}: </dt>
                    <dd className="inline text-subtle">{value.toFixed(0)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </Card>

          {(story?.sections ?? view.story.sections).map((section) => (
            <section key={section.key}>
              <h2 className="text-lg font-semibold tracking-tight text-ink">{section.title}</h2>
              <p className="mt-0.5 text-xs text-muted">{section.purpose}</p>
              <p className="mt-2 text-sm leading-relaxed text-subtle">{section.narrative}</p>
              {section.questions && (
                <ul className="mt-3 flex flex-wrap gap-2">
                  {section.questions.map((question) => (
                    <li key={question}>
                      <Link to={`/app/${sessionId}/ask?q=${encodeURIComponent(question)}`}
                        className="chip hover:border-accent hover:text-accent">{question}</Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
