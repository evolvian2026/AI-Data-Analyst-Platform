import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAnalysis } from '../context/AnalysisContext'
import { api, ApiError } from '../lib/api'
import { ChartRenderer } from '../components/charts/ChartRenderer'
import { FilterBar } from '../components/FilterBar'
import { ConfidenceBadge, Card, SectionHeading } from '../components/Primitives'
import type { AskAnswer } from '../lib/types'

interface Entry {
  question: string
  answer: AskAnswer | null
  error?: string
}

export function AskPage() {
  const { sessionId, view, analysis, filters, setFilters, filtering } = useAnalysis()
  const [params, setParams] = useSearchParams()
  const [question, setQuestion] = useState('')
  const [entries, setEntries] = useState<Entry[]>([])
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.askSuggestions(sessionId)
      .then((response) => setSuggestions(response.questions))
      .catch(() => setSuggestions([]))
  }, [sessionId])

  const submit = useCallback(async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    setBusy(true)
    setEntries((current) => [...current, { question: trimmed, answer: null }])
    setQuestion('')
    try {
      const answer = await api.ask(sessionId, trimmed, filters)
      setEntries((current) => current.map((entry, index) =>
        index === current.length - 1 ? { ...entry, answer } : entry))
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : 'The question could not be answered.'
      setEntries((current) => current.map((entry, index) =>
        index === current.length - 1 ? { ...entry, error: message } : entry))
    } finally {
      setBusy(false)
      window.setTimeout(() => bottom.current?.scrollIntoView({ behavior: 'smooth' }), 60)
    }
  }, [sessionId, filters, busy])

  // Questions arriving from an insight card or the story.
  useEffect(() => {
    const incoming = params.get('q')
    if (incoming) {
      setParams({}, { replace: true })
      void submit(incoming)
    }
  }, [params, setParams, submit])

  if (!view || !analysis) return null

  return (
    <div className="space-y-6">
      <FilterBar definitions={analysis.filters} active={filters} onChange={setFilters}
        busy={filtering} summary={view.filter_summary ?? null} />

      <SectionHeading
        title="Ask your data"
        description="Questions are mapped to a validated calculation - no code is generated or executed, and every answer shows the maths behind it."
      />

      {entries.length === 0 && (
        <Card>
          <p className="mb-3 text-sm font-medium text-ink">Try one of these</p>
          <ul className="flex flex-wrap gap-2">
            {suggestions.map((suggestion) => (
              <li key={suggestion}>
                <button type="button" onClick={() => void submit(suggestion)}
                  className="chip hover:border-accent hover:text-accent">{suggestion}</button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="space-y-5">
        {entries.map((entry, index) => (
          <div key={index} className="space-y-3">
            <p className="ml-auto w-fit max-w-[80%] rounded-2xl rounded-br-sm bg-accent px-4
                          py-2.5 text-sm text-accent-ink">
              {entry.question}
            </p>

            {!entry.answer && !entry.error && (
              <div className="skeleton h-20 w-full max-w-[85%]" />
            )}

            {entry.error && (
              <p className="max-w-[85%] rounded-2xl rounded-bl-sm border border-critical/40
                            bg-critical/5 px-4 py-3 text-sm text-critical">
                {entry.error}
              </p>
            )}

            {entry.answer && <AnswerBlock answer={entry.answer} />}
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <form className="sticky bottom-4 flex gap-2" onSubmit={(event: FormEvent) => {
        event.preventDefault()
        void submit(question)
      }}>
        <input value={question} onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask a question about this dataset…" aria-label="Your question"
          className="input shadow-lift" disabled={busy} />
        <button type="submit" className="btn-primary shrink-0" disabled={busy || !question.trim()}>
          {busy ? 'Thinking…' : 'Ask'}
        </button>
      </form>
    </div>
  )
}

function AnswerBlock({ answer }: { answer: AskAnswer }) {
  return (
    <div className="max-w-[92%] space-y-3">
      <Card>
        <p className="text-sm leading-relaxed text-ink">{answer.answer}</p>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <ConfidenceBadge level={answer.confidence} />
          <span className="chip">{answer.intent.replace(/_/g, ' ')}</span>
          {answer.applied_filter && (
            <span className="chip border-accent/40 text-accent">
              filtered to {answer.applied_filter.column} = {answer.applied_filter.value}
            </span>
          )}
          <span className="tnum text-[11px] text-muted">
            {answer.records_used.toLocaleString()} records
          </span>
        </div>

        {answer.calculation && (
          <p className="tnum mt-2 rounded-lg bg-page px-3 py-2 text-xs text-subtle">
            <span className="font-medium text-ink">Calculation: </span>{answer.calculation}
          </p>
        )}

        {answer.caveat && (
          <p className="mt-2 text-xs text-muted">{answer.caveat}</p>
        )}

        {answer.suggestions && answer.suggestions.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-2">
            {answer.suggestions.map((suggestion) => (
              <li key={suggestion} className="chip">{suggestion}</li>
            ))}
          </ul>
        )}
      </Card>

      {answer.chart && <ChartRenderer chart={answer.chart} height={240} />}

      {answer.table.length > 0 && (
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-line bg-page">
                {Object.keys(answer.table[0]).map((key) => (
                  <th key={key} className="px-3 py-2 font-medium text-muted">
                    {key.replace(/_/g, ' ')}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {answer.table.slice(0, 25).map((row, index) => (
                <tr key={index} className="border-b border-line/60">
                  {Object.keys(answer.table[0]).map((key) => (
                    <td key={key} className="tnum px-3 py-1.5 text-subtle">
                      {typeof row[key] === 'number'
                        ? (row[key] as number).toLocaleString(undefined, { maximumFractionDigits: 2 })
                        : String(row[key] ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
