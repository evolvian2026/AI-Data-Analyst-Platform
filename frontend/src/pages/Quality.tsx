import { useAnalysis } from '../context/AnalysisContext'
import { Card, ScoreRing, SectionHeading, SeverityBadge } from '../components/Primitives'
import { titleCase } from '../lib/format'

export function QualityPage() {
  const { view } = useAnalysis()
  if (!view) return null
  const quality = view.quality
  const derived = view.derived_columns ?? []

  return (
    <div className="space-y-8">
      <SectionHeading
        title="Data quality"
        description="What is wrong with the data, and - more usefully - what that does to the analysis."
      />

      <Card className="flex flex-wrap items-start gap-6">
        <ScoreRing score={quality.score} label={quality.grade} size={110} />
        <div className="min-w-[280px] flex-1">
          <p className="text-sm leading-relaxed text-subtle">{quality.explanation}</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {Object.entries(quality.components).map(([key, value]) => (
              <div key={key}>
                <p className="mb-1 flex items-baseline justify-between text-xs">
                  <span className="text-muted">{titleCase(key)}</span>
                  <span className="tnum font-medium text-ink">{value.toFixed(0)}</span>
                </p>
                <div className="h-1.5 overflow-hidden rounded-full bg-line">
                  <div className="h-full rounded-full bg-accent" style={{ width: `${value}%` }} />
                </div>
                <p className="mt-1 text-[10px] text-muted">
                  weight {(quality.weights[key] * 100).toFixed(0)}%
                </p>
              </div>
            ))}
          </div>
        </div>
      </Card>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-ink">Dataset measurements</h2>
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {[
            ['Rows', quality.metrics.rows],
            ['Columns', quality.metrics.columns],
            ['Missing cells', quality.metrics.missing_cells],
            ['Missing %', `${quality.metrics.missing_pct}%`],
            ['Duplicate rows', quality.metrics.duplicate_rows],
            ['Outliers', quality.metrics.outliers],
          ].map(([label, value]) => (
            <div key={String(label)} className="card p-3">
              <p className="text-[11px] text-muted">{String(label)}</p>
              <p className="tnum text-lg font-semibold text-ink">
                {typeof value === 'number' ? value.toLocaleString() : String(value)}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-ink">
          Issues and their impact on this analysis
        </h2>
        {quality.issues.length === 0 ? (
          <Card><p className="text-sm text-subtle">No material data quality problems were found.</p></Card>
        ) : (
          <ul className="space-y-3">
            {quality.issues.map((issue) => (
              <li key={issue.id}>
                <Card>
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <SeverityBadge level={issue.severity} />
                    {issue.column && <span className="chip">{issue.column}</span>}
                    <span className="chip">{titleCase(issue.type)}</span>
                    {issue.affected_records > 0 && (
                      <span className="tnum text-[11px] text-muted">
                        {issue.affected_records.toLocaleString()} records
                        {issue.affected_pct > 0 && ` (${issue.affected_pct}%)`}
                      </span>
                    )}
                  </div>
                  <h3 className="text-sm font-semibold text-ink">{issue.title}</h3>
                  <p className="mt-1 text-sm text-subtle">{issue.detail}</p>
                  <p className="mt-2 rounded-lg border-l-2 border-warning bg-page px-3 py-2 text-sm
                                text-subtle">
                    <span className="font-medium text-ink">Impact. </span>{issue.impact}
                  </p>
                  {issue.groups && issue.groups.length > 0 && (
                    <ul className="mt-2 flex flex-wrap gap-1.5">
                      {issue.groups.slice(0, 8).map((group) => (
                        <li key={group.canonical} className="chip text-[11px]">
                          {group.variants.join(' / ')}
                        </li>
                      ))}
                    </ul>
                  )}
                  {issue.findings && issue.findings.length > 0 && (
                    <ul className="mt-2 space-y-1 text-xs text-muted">
                      {issue.findings.map((finding) => (
                        <li key={finding.column}>
                          <span className="font-medium text-subtle">{finding.column}:</span>{' '}
                          {finding.excerpt}
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-ink">Recommendations</h2>
        <Card>
          <ol className="space-y-2 text-sm text-subtle">
            {quality.recommendations.map((recommendation, index) => (
              <li key={recommendation} className="flex gap-2">
                <span className="tnum shrink-0 text-muted">{index + 1}.</span>
                {recommendation}
              </li>
            ))}
          </ol>
        </Card>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-ink">Column classification</h2>
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-line bg-page text-muted">
                {['Column', 'Detected type', 'Role', 'Aggregation', 'Missing', 'Distinct', 'Notes']
                  .map((heading) => (
                    <th key={heading} className="px-3 py-2 font-medium">{heading}</th>
                  ))}
              </tr>
            </thead>
            <tbody>
              {view.profile.columns.map((column) => (
                <tr key={column.name} className="border-b border-line/60">
                  <td className="px-3 py-2 font-medium text-ink">{column.name}</td>
                  <td className="px-3 py-2 text-subtle">{column.semantic_type}</td>
                  <td className="px-3 py-2 text-subtle">{column.role}</td>
                  <td className="px-3 py-2 text-subtle">{column.aggregation || '–'}</td>
                  <td className="tnum px-3 py-2 text-subtle">{column.missing_pct.toFixed(1)}%</td>
                  <td className="tnum px-3 py-2 text-subtle">{column.unique.toLocaleString()}</td>
                  <td className="px-3 py-2 text-muted">
                    {[column.derived_from, ...column.notes].filter(Boolean).join(' ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </section>

      {derived.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold text-ink">Columns calculated from others</h2>
          <Card>
            <ul className="space-y-2 text-sm text-subtle">
              {derived.map((item) => <li key={item.column}>{item.narrative}</li>)}
            </ul>
          </Card>
        </section>
      )}
    </div>
  )
}
