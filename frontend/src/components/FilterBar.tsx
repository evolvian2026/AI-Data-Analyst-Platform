import { useMemo, useState } from 'react'
import type { ActiveFilter, FilterDefinition } from '../lib/types'
import { clsx } from '../lib/format'

interface Props {
  definitions: FilterDefinition[]
  active: ActiveFilter[]
  onChange: (filters: ActiveFilter[]) => void
  busy?: boolean
  summary?: { records: number; total_records: number; pct_of_total: number } | null
}

/**
 * Filters are generated from whichever dimensions the dataset actually has, and
 * sit in one row above the charts so the reader always knows what is in scope.
 */
export function FilterBar({ definitions, active, onChange, busy, summary }: Props) {
  const [open, setOpen] = useState<string | null>(null)

  const byColumn = useMemo(
    () => Object.fromEntries(active.map((filter) => [filter.column, filter])),
    [active],
  )

  const setFilter = (next: ActiveFilter | null, column: string) => {
    const rest = active.filter((filter) => filter.column !== column)
    onChange(next ? [...rest, next] : rest)
  }

  const toggleValue = (definition: FilterDefinition, value: string) => {
    const current = byColumn[definition.column]?.values ?? []
    const values = current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value]
    setFilter(
      values.length ? { column: definition.column, type: 'multi_select', values } : null,
      definition.column,
    )
  }

  if (definitions.length === 0) return null

  return (
    <div className="mb-5 flex flex-wrap items-center gap-2">
      {definitions.slice(0, 10).map((definition) => {
        const current = byColumn[definition.column]
        const count = current?.values?.length ?? 0
        const isRange = definition.type !== 'multi_select'
        const label = isRange && current
          ? `${definition.label}: ${current.from ?? current.min ?? ''}–${current.to ?? current.max ?? ''}`
          : definition.label

        return (
          <div key={definition.column} className="relative">
            <button type="button"
              onClick={() => setOpen(open === definition.column ? null : definition.column)}
              aria-expanded={open === definition.column}
              className={clsx('chip transition-colors hover:border-accent hover:text-accent',
                (count > 0 || (isRange && current)) && 'border-accent bg-accent/10 text-accent')}>
              {label}
              {count > 0 && <span className="tnum">· {count}</span>}
              <span aria-hidden className="text-[10px]">▾</span>
            </button>

            {open === definition.column && (
              <div className="absolute left-0 top-full z-30 mt-1.5 w-64 animate-fade-in rounded-xl
                              border border-line bg-raised p-2 shadow-lift">
                {definition.type === 'multi_select' && (
                  <div className="max-h-64 overflow-auto">
                    {(definition.options ?? []).slice(0, 200).map((option) => {
                      const checked = current?.values?.includes(option.value) ?? false
                      return (
                        <label key={option.value}
                          className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5
                                     text-xs hover:bg-page">
                          <input type="checkbox" checked={checked}
                            onChange={() => toggleValue(definition, option.value)}
                            className="h-3.5 w-3.5 accent-[rgb(var(--accent))]" />
                          <span className="min-w-0 flex-1 truncate text-ink">{option.value}</span>
                          <span className="tnum text-muted">{option.count.toLocaleString()}</span>
                        </label>
                      )
                    })}
                  </div>
                )}

                {definition.type === 'date_range' && (
                  <div className="space-y-2 p-1">
                    <label className="block text-xs text-muted">
                      From
                      <input type="date" className="input mt-1"
                        value={current?.from?.slice(0, 10) ?? ''}
                        onChange={(event) => setFilter({
                          column: definition.column, type: 'date_range',
                          from: event.target.value || undefined, to: current?.to,
                        }, definition.column)} />
                    </label>
                    <label className="block text-xs text-muted">
                      To
                      <input type="date" className="input mt-1"
                        value={current?.to?.slice(0, 10) ?? ''}
                        onChange={(event) => setFilter({
                          column: definition.column, type: 'date_range',
                          from: current?.from, to: event.target.value || undefined,
                        }, definition.column)} />
                    </label>
                    <p className="text-[11px] text-muted">
                      Available {String(definition.min).slice(0, 10)} to{' '}
                      {String(definition.max).slice(0, 10)}
                    </p>
                  </div>
                )}

                {definition.type === 'numeric_range' && (
                  <div className="space-y-2 p-1">
                    <div className="flex gap-2">
                      <label className="flex-1 text-xs text-muted">
                        Min
                        <input type="number" className="input mt-1"
                          value={current?.min ?? ''}
                          placeholder={String(definition.min)}
                          onChange={(event) => setFilter({
                            column: definition.column, type: 'numeric_range',
                            min: event.target.value === '' ? undefined : Number(event.target.value),
                            max: current?.max,
                          }, definition.column)} />
                      </label>
                      <label className="flex-1 text-xs text-muted">
                        Max
                        <input type="number" className="input mt-1"
                          value={current?.max ?? ''}
                          placeholder={String(definition.max)}
                          onChange={(event) => setFilter({
                            column: definition.column, type: 'numeric_range',
                            min: current?.min,
                            max: event.target.value === '' ? undefined : Number(event.target.value),
                          }, definition.column)} />
                      </label>
                    </div>
                  </div>
                )}

                <div className="mt-2 flex justify-between border-t border-line pt-2">
                  <button type="button" className="btn-ghost px-2 py-1 text-xs"
                    onClick={() => setFilter(null, definition.column)}>
                    Clear
                  </button>
                  <button type="button" className="btn-ghost px-2 py-1 text-xs"
                    onClick={() => setOpen(null)}>
                    Done
                  </button>
                </div>
              </div>
            )}
          </div>
        )
      })}

      {active.length > 0 && (
        <button type="button" onClick={() => onChange([])} className="btn-ghost px-2 py-1 text-xs">
          Clear all
        </button>
      )}

      {busy && <span className="text-xs text-muted">Recalculating…</span>}

      {summary && !busy && (
        <span className="tnum ml-auto text-xs text-muted">
          {summary.records.toLocaleString()} of {summary.total_records.toLocaleString()} records
          ({summary.pct_of_total.toFixed(1)}%)
        </span>
      )}
    </div>
  )
}
