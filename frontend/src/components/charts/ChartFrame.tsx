import { useState, type ReactNode } from 'react'
import type { Chart } from '../../lib/types'
import { clsx } from '../../lib/format'

interface Props {
  chart: Chart
  children: ReactNode
  table: ReactNode
  onDrilldown?: (dimension: string, value: string) => void
  compact?: boolean
}

/**
 * Shared chart container. Every chart states the question it answers, and the
 * table view is always one click away - which is also the relief that light-mode
 * low-contrast hues require.
 */
export function ChartFrame({ chart, children, table, compact = false }: Props) {
  const [showTable, setShowTable] = useState(false)
  const [showWhy, setShowWhy] = useState(false)

  return (
    <figure className="card flex h-full flex-col overflow-hidden">
      <figcaption className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-ink">{chart.title}</h3>
          <p className="mt-0.5 truncate text-xs text-muted" title={chart.question}>
            {chart.question}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => setShowWhy((open) => !open)}
            className="btn-ghost px-2 py-1 text-xs"
            aria-expanded={showWhy}
          >
            Why this chart
          </button>
          <button
            type="button"
            onClick={() => setShowTable((open) => !open)}
            className="btn-ghost px-2 py-1 text-xs"
            aria-pressed={showTable}
          >
            {showTable ? 'Chart' : 'Table'}
          </button>
        </div>
      </figcaption>

      {showWhy && (
        <div className="animate-fade-in border-b border-line bg-page px-4 py-3 text-xs text-subtle">
          <p>{chart.reason}</p>
          <p className="mt-1.5">
            <span className="font-medium text-ink">Calculation:</span>{' '}
            <span className="tnum">{chart.calculation}</span>
          </p>
          <p className="mt-1">
            <span className="font-medium text-ink">Columns:</span> {chart.columns.join(', ')}
          </p>
        </div>
      )}

      <div className={clsx('min-h-0 flex-1 px-2 pt-3', compact ? 'pb-1' : 'pb-2')}>
        {showTable ? (
          <div className="max-h-[320px] overflow-auto px-2">{table}</div>
        ) : (
          children
        )}
      </div>

      {chart.insight && !showTable && (
        <p className="border-t border-line px-4 py-2.5 text-xs text-subtle">{chart.insight}</p>
      )}
    </figure>
  )
}
