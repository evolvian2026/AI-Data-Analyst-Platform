import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { Card, Loading } from './Primitives'
import { clsx } from '../lib/format'
import type { JoinReport, Relationship } from '../lib/types'

const HOW = [
  { value: 'inner', label: 'Only matching rows (inner)' },
  { value: 'left', label: 'Keep all left rows (left)' },
  { value: 'right', label: 'Keep all right rows (right)' },
  { value: 'outer', label: 'Keep everything (outer)' },
]

/**
 * Acting on a detected relationship between sheets.
 *
 * A join is previewed before it is run, because the two things that make a
 * join wrong - rows silently dropped for want of a match, and rows silently
 * multiplied by a repeating key - are both invisible in the result. The
 * preview states both, and the fan-out case is refused rather than analysed.
 */
export function JoinPanel({ sessionId, relationships }: {
  sessionId: string; relationships: Relationship[]
}) {
  const navigate = useNavigate()
  const [sheets, setSheets] = useState<string[]>([])
  const [spec, setSpec] = useState({ left: '', right: '', key: '', how: 'inner' })
  const [report, setReport] = useState<JoinReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    api.joins(sessionId).then((response) => {
      setSheets(response.sheets)
      const first = response.relationships[0]
      if (first) setSpec({ left: first.left, right: first.right, key: first.key, how: 'inner' })
      setLoaded(true)
    }).catch(() => setLoaded(true))
  }, [sessionId])

  const preview = useCallback(async (next: typeof spec) => {
    if (!next.left || !next.right || !next.key) return
    setError(null)
    try {
      setReport(await api.previewJoin(sessionId, next))
    } catch (caught) {
      setReport(null)
      setError(caught instanceof ApiError ? caught.message : 'Could not preview that join.')
    }
  }, [sessionId])

  useEffect(() => { void preview(spec) }, [spec, preview])

  const update = (patch: Partial<typeof spec>) => setSpec((current) => ({ ...current, ...patch }))

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      const created = await api.createJoin(sessionId, spec)
      navigate(`/app/${created.id}/processing`)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not create that join.')
      setBusy(false)
    }
  }

  if (!loaded) return <Loading rows={1} label="Loading sheet relationships" />

  return (
    <Card className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-ink">Combine two sheets</h3>
        <p className="mt-1 text-xs text-subtle">
          Joining creates a new analysis; this one is left exactly as it is.
        </p>
      </div>

      {relationships.length > 0 && (
        <ul className="space-y-1.5">
          {relationships.slice(0, 4).map((relationship) => (
            <li key={`${relationship.left}-${relationship.right}-${relationship.key}`}>
              <button type="button"
                onClick={() => update({ left: relationship.left, right: relationship.right,
                  key: relationship.key })}
                className={clsx('w-full rounded-lg border px-3 py-2 text-left text-xs',
                  spec.left === relationship.left && spec.right === relationship.right
                    && spec.key === relationship.key
                    ? 'border-accent bg-accent/5' : 'border-line hover:border-accent')}>
                <span className="text-subtle">{relationship.narrative}</span>
                {relationship.join_ready && (
                  <span className="chip ml-2 border-good/40 text-good">ready to join</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="Left sheet">
          <select className="input py-1.5 text-xs" value={spec.left}
            onChange={(event) => update({ left: event.target.value })}>
            <option value="">Choose…</option>
            {sheets.map((sheet) => <option key={sheet} value={sheet}>{sheet}</option>)}
          </select>
        </Field>
        <Field label="Right sheet">
          <select className="input py-1.5 text-xs" value={spec.right}
            onChange={(event) => update({ right: event.target.value })}>
            <option value="">Choose…</option>
            {sheets.map((sheet) => <option key={sheet} value={sheet}>{sheet}</option>)}
          </select>
        </Field>
        <Field label="Matching column">
          <input className="input py-1.5 text-xs" value={spec.key}
            placeholder="Customer ID"
            onChange={(event) => update({ key: event.target.value })} />
        </Field>
        <Field label="Rows to keep">
          <select className="input py-1.5 text-xs" value={spec.how}
            onChange={(event) => update({ how: event.target.value })}>
            {HOW.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </Field>
      </div>

      {error && (
        <p className="rounded-lg border border-critical/40 bg-critical/5 px-3 py-2 text-xs
                      text-critical">{error}</p>
      )}

      {report && (
        <div className="rounded-lg border border-line bg-page px-3 py-2.5 text-xs">
          <p className="font-medium text-ink">{report.narrative}</p>
          <dl className="tnum mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-muted sm:grid-cols-4">
            <div>
              <dt>Matched in {report.left}</dt>
              <dd className="text-ink">
                {report.matched_rows_left.toLocaleString()} / {report.rows_left.toLocaleString()}
                {' '}({report.coverage_left_pct}%)
              </dd>
            </div>
            <div>
              <dt>Matched in {report.right}</dt>
              <dd className="text-ink">
                {report.matched_rows_right.toLocaleString()} / {report.rows_right.toLocaleString()}
                {' '}({report.coverage_right_pct}%)
              </dd>
            </div>
            <div>
              <dt>Relationship</dt>
              <dd className="text-ink">{report.cardinality}</dd>
            </div>
            <div>
              <dt>Result size</dt>
              <dd className="text-ink">~{report.estimated_rows.toLocaleString()} rows</dd>
            </div>
          </dl>
          {report.warnings.length > 0 && (
            <ul className="mt-2 space-y-1">
              {report.warnings.map((warning) => (
                <li key={warning} className={clsx('flex gap-2',
                  report.safe ? 'text-subtle' : 'text-warning')}>
                  <span aria-hidden>!</span>{warning}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button type="button" className="btn-primary text-xs" disabled={busy || !report?.safe}
          onClick={() => void run()}>
          {busy ? 'Creating…' : 'Join and analyse'}
        </button>
        {report && !report.safe && (
          <span className="text-xs text-warning">
            This join is refused: every total calculated from the result would be overstated.
          </span>
        )}
      </div>
    </Card>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-muted">
        {label}
      </span>
      {children}
    </label>
  )
}
