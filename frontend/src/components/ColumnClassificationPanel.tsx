import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { Card, Loading } from './Primitives'
import { clsx, titleCase } from '../lib/format'
import type { ColumnClassification, ColumnOverride } from '../lib/types'

/**
 * Correcting what the profiler decided about a column.
 *
 * Profiling infers meaning from values, which is right most of the time and not
 * all of the time - and when it is wrong, every number downstream inherits the
 * mistake. This panel makes the inference visible and correctable, while
 * offering only the classifications the data can actually support: a text
 * column is never offered as a measure, however much someone wants it to be.
 */
export function ColumnClassificationPanel({ sessionId, onApplied }: {
  sessionId: string
  onApplied: () => void
}) {
  const [columns, setColumns] = useState<ColumnClassification[] | null>(null)
  const [note, setNote] = useState('')
  const [draft, setDraft] = useState<Record<string, ColumnOverride>>({})
  const [saved, setSaved] = useState<Record<string, ColumnOverride>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const response = await api.columns(sessionId)
    setColumns(response.columns)
    setNote(response.note)
    setDraft(response.overrides)
    setSaved(response.overrides)
  }, [sessionId])

  useEffect(() => { void load() }, [load])

  const dirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(saved),
    [draft, saved],
  )

  const change = (name: string, field: keyof ColumnOverride, value: string) => {
    setDraft((current) => {
      const next = { ...current }
      const entry = { ...(next[name] ?? {}) }
      if (value) entry[field] = value
      else delete entry[field]
      if (Object.keys(entry).length) next[name] = entry
      else delete next[name]
      return next
    })
  }

  const apply = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.setColumns(sessionId, draft)
      setSaved(draft)
      onApplied()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not apply those corrections.')
    } finally {
      setBusy(false)
    }
  }

  if (!columns) return <Loading rows={2} label="Loading column classifications" />

  return (
    <Card className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-ink">How each column is being read</h3>
        <p className="mt-1 text-xs text-subtle">{note}</p>
      </div>

      {error && (
        <p className="rounded-lg border border-critical/40 bg-critical/5 px-3 py-2 text-xs
                      text-critical">{error}</p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-xs">
          <thead>
            <tr className="border-b border-line text-muted">
              <th className="py-2 pr-3 font-medium">Column</th>
              <th className="py-2 pr-3 font-medium">Example values</th>
              <th className="py-2 pr-3 font-medium">Type</th>
              <th className="py-2 pr-3 font-medium">Role</th>
              <th className="py-2 font-medium">Aggregation</th>
            </tr>
          </thead>
          <tbody>
            {columns.map((column) => {
              const override = draft[column.name] ?? {}
              const role = override.role ?? column.role
              const changed = Object.keys(override).length > 0
              return (
                <tr key={column.name}
                  className={clsx('border-b border-line/60',
                    changed && 'bg-accent/[0.04]')}>
                  <td className="py-2 pr-3 align-top">
                    <p className="font-medium text-ink">{column.name}</p>
                    {column.overridden.length > 0 && (
                      <span className="chip mt-1 border-accent/40 text-accent">corrected</span>
                    )}
                    {column.repeated_attribute && (
                      <span className="chip mt-1 border-line text-muted"
                        title="Joined from a lookup table, so this value repeats on every matching row">
                        repeated attribute
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-3 align-top text-muted">
                    <p className="max-w-[200px] truncate"
                      title={column.sample_values.join(', ')}>
                      {column.sample_values.slice(0, 3).join(', ') || '—'}
                    </p>
                    <p className="tnum mt-0.5 text-[10px]">
                      {column.unique.toLocaleString()} distinct ·{' '}
                      {column.missing_pct.toFixed(1)}% missing
                    </p>
                  </td>
                  <td className="py-2 pr-3 align-top">
                    <Select
                      label={`Type of ${column.name}`}
                      value={override.semantic_type ?? column.semantic_type}
                      options={column.options.semantic_types}
                      onChange={(value) => change(column.name, 'semantic_type',
                        value === column.semantic_type ? '' : value)}
                    />
                  </td>
                  <td className="py-2 pr-3 align-top">
                    <Select
                      label={`Role of ${column.name}`}
                      value={role}
                      options={column.options.roles}
                      onChange={(value) => change(column.name, 'role',
                        value === column.role ? '' : value)}
                    />
                    {column.options.blocked.length > 0 && (
                      <p className="mt-1 max-w-[220px] text-[10px] text-muted">
                        {column.options.blocked[0]}
                      </p>
                    )}
                  </td>
                  <td className="py-2 align-top">
                    {role === 'measure' ? (
                      <Select
                        label={`Aggregation of ${column.name}`}
                        value={override.aggregation ?? column.aggregation ?? 'sum'}
                        options={column.options.aggregations.length
                          ? column.options.aggregations : ['sum', 'mean']}
                        onChange={(value) => change(column.name, 'aggregation',
                          value === column.aggregation ? '' : value)}
                      />
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-3">
        <button type="button" className="btn-primary text-xs" disabled={!dirty || busy}
          onClick={() => void apply()}>
          {busy ? 'Re-analysing…' : 'Apply and re-analyse'}
        </button>
        <button type="button" className="btn-ghost text-xs" disabled={!dirty || busy}
          onClick={() => setDraft(saved)}>
          Discard changes
        </button>
        {Object.keys(saved).length > 0 && (
          <button type="button" className="btn-ghost text-xs" disabled={busy}
            onClick={() => { setDraft({}); }}>
            Clear all corrections
          </button>
        )}
        {dirty && (
          <span className="text-xs text-muted">
            Applying re-runs the whole analysis with these columns read your way.
          </span>
        )}
      </div>
    </Card>
  )
}

function Select({ label, value, options, onChange }: {
  label: string; value: string; options: string[]; onChange: (value: string) => void
}) {
  const choices = options.includes(value) ? options : [value, ...options]
  return (
    <select aria-label={label} value={value} className="input w-auto py-1 text-xs"
      onChange={(event) => onChange(event.target.value)}>
      {choices.map((option) => (
        <option key={option} value={option}>{titleCase(option)}</option>
      ))}
    </select>
  )
}
