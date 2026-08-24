import type { Confidence, Evidence } from '../lib/types'

/**
 * Insight traceability. Shows exactly what produced a finding: the source
 * columns, the calculation, the values substituted into it and how many records
 * were involved.
 */
export function EvidencePanel({ evidence, confidence, confidenceReason }: {
  evidence: Evidence; confidence?: Confidence; confidenceReason?: string
}) {
  const rows: { label: string; value: string }[] = []

  if (evidence.metric) rows.push({ label: 'Metric', value: evidence.metric })
  if (evidence.formatted_value) rows.push({ label: 'Value', value: evidence.formatted_value })
  if (evidence.source_columns?.length) {
    rows.push({ label: 'Source columns', value: evidence.source_columns.join(', ') })
  }
  if (evidence.calculation) rows.push({ label: 'Calculation', value: evidence.calculation })
  if (evidence.comparison?.label) {
    const change = evidence.comparison.change_pct
    rows.push({
      label: 'Comparison',
      value: `${evidence.comparison.label}${
        change !== null && change !== undefined ? ` (${change >= 0 ? '+' : ''}${change.toFixed(1)}%)` : ''
      }`,
    })
  }
  if (evidence.records_used !== undefined) {
    rows.push({ label: 'Records used', value: evidence.records_used.toLocaleString() })
  }
  if (evidence.periods !== undefined) {
    rows.push({ label: 'Periods analysed', value: String(evidence.periods) })
  }

  const statistics = Object.entries(evidence.statistics ?? {})
    .filter(([, value]) => value !== null && value !== undefined)
    .slice(0, 8)

  return (
    <div className="rounded-lg border border-line bg-page p-3.5 text-xs">
      <p className="mb-2 font-semibold text-ink">Evidence behind this finding</p>
      <dl className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {rows.map((row) => (
          <div key={row.label} className="flex gap-2">
            <dt className="shrink-0 text-muted">{row.label}:</dt>
            <dd className="tnum min-w-0 break-words text-subtle">{row.value}</dd>
          </div>
        ))}
      </dl>

      {evidence.math?.formula && (
        <div className="mt-3 rounded-md border border-line bg-surface p-2.5">
          <p className="mb-1 font-semibold text-ink">Show the math</p>
          <p className="tnum text-subtle">{evidence.math.formula}</p>
          {evidence.math.substitution && (
            <p className="tnum mt-1 text-subtle">= {evidence.math.substitution}</p>
          )}
          {evidence.math.result && (
            <p className="tnum mt-1 font-medium text-ink">= {evidence.math.result}</p>
          )}
        </div>
      )}

      {statistics.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 font-semibold text-ink">Statistics</p>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-subtle">
            {statistics.map(([key, value]) => (
              <li key={key} className="tnum">
                <span className="text-muted">{key.replace(/_/g, ' ')}:</span>{' '}
                {typeof value === 'number' ? value.toLocaleString(undefined, {
                  maximumSignificantDigits: 4,
                }) : String(value)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {confidence && (
        <p className="mt-3 border-t border-line pt-2 text-subtle">
          <span className="font-medium text-ink capitalize">{confidence} confidence.</span>{' '}
          {confidenceReason}
        </p>
      )}

      {evidence.aggregation && evidence.aggregation.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-accent">Supporting values</summary>
          <div className="mt-2 max-h-48 overflow-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-line">
                  {Object.keys(evidence.aggregation[0]).slice(0, 6).map((key) => (
                    <th key={key} className="py-1 pr-3 font-medium text-muted">
                      {key.replace(/_/g, ' ')}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {evidence.aggregation.slice(0, 25).map((row, index) => (
                  <tr key={index} className="border-b border-line/50">
                    {Object.keys(evidence.aggregation![0]).slice(0, 6).map((key) => (
                      <td key={key} className="tnum py-1 pr-3 text-subtle">
                        {typeof row[key] === 'number'
                          ? (row[key] as number).toLocaleString(undefined, { maximumFractionDigits: 2 })
                          : String(row[key] ?? '')}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  )
}
