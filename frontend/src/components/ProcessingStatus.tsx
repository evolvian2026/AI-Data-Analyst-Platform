import type { Progress } from '../lib/types'
import { clsx } from '../lib/format'

/** Live pipeline progress: every stage of the workflow, ticked as it completes. */
export function ProcessingStatus({ progress, filename }: {
  progress: Progress; filename?: string
}) {
  const stages = progress.stages ?? []
  return (
    <div className="card p-6">
      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-ink">Analysing your data</h2>
          {filename && <p className="mt-0.5 text-sm text-muted">{filename}</p>}
        </div>
        <span className="tnum text-2xl font-semibold text-accent">{progress.percent ?? 0}%</span>
      </div>

      <div className="mb-6 h-1.5 w-full overflow-hidden rounded-full bg-line">
        <div className="h-full rounded-full bg-accent transition-all duration-500"
          style={{ width: `${progress.percent ?? 0}%` }} />
      </div>

      <ol className="grid gap-2 sm:grid-cols-2">
        {stages.map((stage) => (
          <li key={stage.key} className={clsx(
            'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors',
            stage.done ? 'text-ink' : stage.active ? 'bg-page text-ink' : 'text-muted',
          )}>
            <span aria-hidden className={clsx(
              'flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px]',
              stage.done ? 'bg-good text-white'
                : stage.active ? 'border-2 border-accent border-t-transparent animate-spin'
                  : 'border border-line',
            )}>
              {stage.done ? '✓' : ''}
            </span>
            {stage.label}
          </li>
        ))}
      </ol>

      {progress.elapsed_seconds !== undefined && (
        <p className="tnum mt-4 text-xs text-muted">
          Elapsed {progress.elapsed_seconds.toFixed(1)}s · processing happens on the server, so
          large workbooks never load in your browser.
        </p>
      )}
    </div>
  )
}
