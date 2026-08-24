import { useEffect, useState } from 'react'
import { useAnalysis } from '../context/AnalysisContext'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { Card, SectionHeading } from '../components/Primitives'
import { clsx, titleCase } from '../lib/format'

type Style = 'executive' | 'standard' | 'detailed'

const SECTION_LABELS: Record<string, string> = {
  cover: 'Cover', toc: 'Table of contents', briefing: 'Executive briefing',
  executive_summary: 'Executive summary', kpis: 'KPI dashboard', quality: 'Data quality',
  story: 'Data story', trends: 'Major trends', drivers: 'Key drivers', winners: 'Winners',
  underperformers: 'Underperformers', anomalies: 'Anomalies', relationships: 'Relationships',
  risks: 'Risks', opportunities: 'Opportunities', recommendations: 'Recommendations',
  charts: 'Visual analysis', analytics: 'Detailed analytics', statistics: 'Statistical analysis',
  correlations: 'Correlations', appendix: 'Appendix',
}

export function ReportsPage() {
  const { sessionId, view, analysis, filters } = useAnalysis()
  const { user } = useAuth()
  const [styles, setStyles] = useState<{ key: string; label: string; pages: string; sections: string[] }[]>([])
  const [style, setStyle] = useState<Style>('standard')
  const [title, setTitle] = useState('')
  const [organization, setOrganization] = useState('')
  const [author, setAuthor] = useState('')
  const [dateRange, setDateRange] = useState('')
  const [audience, setAudience] = useState('manager')
  const [includeCharts, setIncludeCharts] = useState(true)
  const [excluded, setExcluded] = useState<string[]>([])
  const [logo, setLogo] = useState<string | null>(null)
  const [includeData, setIncludeData] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [shareLink, setShareLink] = useState<string | null>(null)

  useEffect(() => {
    api.reportStyles().then((response) => setStyles(response.styles)).catch(() => setStyles([]))
  }, [])

  useEffect(() => {
    if (analysis) setTitle(`${analysis.session.name} - Analytics Report`)
    if (user) {
      setOrganization(user.organization || '')
      setAuthor(user.full_name || user.email)
    }
  }, [analysis, user])

  if (!view || !analysis) return null

  const preset = styles.find((item) => item.key === style)
  const sections = (preset?.sections ?? []).filter((key) => key !== 'cover' && key !== 'toc')

  async function run(kind: 'pdf' | 'excel') {
    setBusy(kind)
    setError(null)
    try {
      if (kind === 'pdf') {
        await api.downloadPdf(sessionId, {
          style, title, organization, author, date_range: dateRange || null, audience,
          include_charts: includeCharts, logo_base64: logo,
          sections: sections.filter((key) => !excluded.includes(key)),
          filters,
        }, `${analysis!.session.name}-report.pdf`)
      } else {
        await api.downloadExcel(sessionId, {
          include_data: includeData, data_row_limit: 20000, filters,
        }, `${analysis!.session.name}-analysis.xlsx`)
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The export failed.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-6">
      <SectionHeading
        title="Reports"
        description="A professional PDF for sharing, or an Excel workbook containing the whole analysis."
      />

      {filters.length > 0 && (
        <p className="rounded-lg border border-accent/40 bg-accent/5 px-3 py-2 text-xs text-accent">
          The {filters.length} active filter(s) will be applied to the report, and the analysis will
          be recalculated for the filtered records.
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <h2 className="mb-4 text-sm font-semibold text-ink">PDF report</h2>

          <div className="mb-4">
            <span className="label">Report style</span>
            <div className="grid gap-2 sm:grid-cols-3">
              {styles.map((option) => (
                <button key={option.key} type="button"
                  onClick={() => setStyle(option.key as Style)}
                  className={clsx('rounded-lg border p-3 text-left transition-colors',
                    style === option.key
                      ? 'border-accent bg-accent/5' : 'border-line hover:border-accent/50')}>
                  <p className="text-sm font-medium text-ink">{option.label}</p>
                  <p className="text-xs text-muted">{option.pages}</p>
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted">
              The engine sizes the report to what it actually found, so a thin dataset does not
              produce padded pages.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="label">Report title</span>
              <input className="input" value={title}
                onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label className="block">
              <span className="label">Organization</span>
              <input className="input" value={organization}
                onChange={(event) => setOrganization(event.target.value)} />
            </label>
            <label className="block">
              <span className="label">Author</span>
              <input className="input" value={author}
                onChange={(event) => setAuthor(event.target.value)} />
            </label>
            <label className="block">
              <span className="label">Date range (optional)</span>
              <input className="input" value={dateRange} placeholder="Jan–Dec 2025"
                onChange={(event) => setDateRange(event.target.value)} />
            </label>
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="label">Audience</span>
              <select className="input" value={audience}
                onChange={(event) => setAudience(event.target.value)}>
                {Object.entries(analysis.audiences).map(([key, config]) => (
                  <option key={key} value={key}>{config.label}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="label">Logo (PNG or JPEG)</span>
              <input type="file" accept="image/png,image/jpeg" className="input py-1.5 text-xs"
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (!file) { setLogo(null); return }
                  const reader = new FileReader()
                  reader.onload = () => setLogo(String(reader.result))
                  reader.readAsDataURL(file)
                }} />
            </label>
          </div>

          <div className="mt-4">
            <span className="label">Sections to include</span>
            <div className="flex flex-wrap gap-1.5">
              {sections.map((key) => {
                const on = !excluded.includes(key)
                return (
                  <button key={key} type="button"
                    onClick={() => setExcluded((current) =>
                      on ? [...current, key] : current.filter((item) => item !== key))}
                    aria-pressed={on}
                    className={clsx('chip transition-colors',
                      on ? 'border-accent bg-accent/10 text-accent' : 'text-muted')}>
                    {SECTION_LABELS[key] ?? titleCase(key)}
                  </button>
                )
              })}
            </div>
          </div>

          <label className="mt-4 flex items-center gap-2 text-sm text-subtle">
            <input type="checkbox" checked={includeCharts} className="accent-[rgb(var(--accent))]"
              onChange={(event) => setIncludeCharts(event.target.checked)} />
            Include charts
          </label>

          <button type="button" className="btn-primary mt-5" disabled={busy !== null}
            onClick={() => void run('pdf')}>
            {busy === 'pdf' ? 'Generating…' : 'Download PDF report'}
          </button>
        </Card>

        <div className="space-y-6">
          <Card>
            <h2 className="mb-2 text-sm font-semibold text-ink">Excel analysis workbook</h2>
            <p className="text-xs leading-relaxed text-subtle">
              Executive summary, KPIs, the data story, every insight, data quality, statistics,
              correlations, outliers, segment analysis, aggregated data and the exact values behind
              each chart - one sheet each.
            </p>
            <label className="mt-3 flex items-center gap-2 text-sm text-subtle">
              <input type="checkbox" checked={includeData} className="accent-[rgb(var(--accent))]"
                onChange={(event) => setIncludeData(event.target.checked)} />
              Also include the underlying rows
            </label>
            <button type="button" className="btn-secondary mt-4 w-full" disabled={busy !== null}
              onClick={() => void run('excel')}>
              {busy === 'excel' ? 'Building…' : 'Download Excel analysis'}
            </button>
          </Card>

          <Card>
            <h2 className="mb-2 text-sm font-semibold text-ink">Share the findings</h2>
            <p className="text-xs leading-relaxed text-subtle">
              Creates a read-only link to the report. The underlying rows are never included.
            </p>
            <button type="button" className="btn-secondary mt-4 w-full"
              onClick={async () => {
                try {
                  const share = await api.share(sessionId, 72)
                  setShareLink(`${window.location.origin}${share.path}`)
                } catch (caught) {
                  setError(caught instanceof ApiError ? caught.message : 'Could not create a link.')
                }
              }}>
              Create a share link
            </button>
            {shareLink && (
              <div className="mt-3">
                <input readOnly value={shareLink} className="input text-xs"
                  onFocus={(event) => event.target.select()} aria-label="Share link" />
                <p className="mt-1 text-[11px] text-muted">Expires in 72 hours.</p>
              </div>
            )}
          </Card>

          <Card>
            <h2 className="mb-2 text-sm font-semibold text-ink">What goes in the report</h2>
            <p className="text-xs leading-relaxed text-subtle">
              Every figure is calculated by the analytics engine. Interpretations carry a confidence
              level, and each finding lists the columns, the calculation and the record count behind
              it.
            </p>
          </Card>
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded-lg border border-critical/40 bg-critical/5 px-3 py-2
                                   text-sm text-critical">{error}</p>
      )}
    </div>
  )
}
