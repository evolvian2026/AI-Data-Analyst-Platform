import { useState } from 'react'
import type { Kpi } from '../lib/types'
import { clsx } from '../lib/format'

/**
 * A stat tile. "Show the math" is one click away because a KPI without its
 * calculation is a number the reader has to take on trust.
 */
export function KpiCard({ kpi, compactCard = false }: { kpi: Kpi; compactCard?: boolean }) {
  const [showMath, setShowMath] = useState(false)
  const direction = kpi.change?.direction

  return (
    <div className="card flex flex-col gap-2 p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium leading-snug text-muted" title={kpi.description}>
          {kpi.label}
        </p>
        {kpi.derived && (
          <span className="chip shrink-0 border-accent/40 px-1.5 py-0.5 text-[10px] text-accent">
            derived
          </span>
        )}
      </div>

      <p className="text-2xl font-semibold leading-none tracking-tight text-ink">
        {kpi.formatted}
      </p>

      {kpi.change && (
        <p className={clsx('flex items-center gap-1 text-xs font-medium',
          direction === 'up' ? 'text-good' : 'text-critical')}>
          <span aria-hidden>{direction === 'up' ? '▲' : '▼'}</span>
          {kpi.change.pct >= 0 ? '+' : ''}{kpi.change.pct.toFixed(1)}%
          <span className="font-normal text-muted">
            vs {String(kpi.secondary.previous_period ?? 'previous period')}
          </span>
        </p>
      )}

      {!compactCard && (
        <>
          <button type="button" onClick={() => setShowMath((open) => !open)}
            className="mt-auto self-start text-[11px] font-medium text-accent hover:underline"
            aria-expanded={showMath}>
            {showMath ? 'Hide the math' : 'Show the math'}
          </button>

          {showMath && (
            <dl className="animate-fade-in space-y-1 rounded-lg bg-page p-2.5 text-[11px] text-subtle">
              <div>
                <dt className="font-medium text-ink">Formula</dt>
                <dd className="tnum">{kpi.math.formula}</dd>
              </div>
              {kpi.math.substitution && (
                <div>
                  <dt className="font-medium text-ink">Values used</dt>
                  <dd className="tnum">{kpi.math.substitution}</dd>
                </div>
              )}
              <div>
                <dt className="font-medium text-ink">Result</dt>
                <dd className="tnum">{kpi.math.result ?? kpi.formatted}</dd>
              </div>
              <div>
                <dt className="font-medium text-ink">Records used</dt>
                <dd className="tnum">{kpi.records_used.toLocaleString()}</dd>
              </div>
              {kpi.source_columns.length > 0 && (
                <div>
                  <dt className="font-medium text-ink">Source columns</dt>
                  <dd>{kpi.source_columns.join(', ')}</dd>
                </div>
              )}
            </dl>
          )}
        </>
      )}
    </div>
  )
}
