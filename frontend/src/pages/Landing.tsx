import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'
import type { SampleDataset } from '../lib/types'

const WORKFLOW = ['Upload', 'Understand', 'Discover', 'Explain', 'Act']

const CAPABILITIES = [
  {
    title: 'It understands the dataset',
    body: 'Semantic types are inferred from the values, not the column names, so the same engine '
      + 'works on sales, HR, finance, students or survey data with no configuration.',
  },
  {
    title: 'It finds what matters',
    body: 'Every discovered pattern gets a priority score from its magnitude, unusualness, '
      + 'relevance, confidence, coverage and analytical importance - so a 32% revenue drop leads, '
      + 'not a 1.1% move in average order value.',
  },
  {
    title: 'It shows the evidence',
    body: 'Each finding carries the source columns, the calculation, the values used and the record '
      + 'count. Click "Why am I seeing this insight?" on anything.',
  },
  {
    title: 'It cannot make numbers up',
    body: 'The analytics engine is the source of truth. Narration is composed from calculated '
      + 'values, and any AI-generated figure that is not in the evidence is discarded.',
  },
]

export function LandingPage() {
  const { user } = useAuth()
  const { theme, toggle } = useTheme()
  const navigate = useNavigate()
  const [samples, setSamples] = useState<SampleDataset[]>([])

  useEffect(() => {
    api.samples().then((response) => setSamples(response.samples)).catch(() => setSamples([]))
  }, [])

  return (
    <div className="min-h-screen bg-page">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex h-14 max-w-6xl items-center px-4 sm:px-6">
          <span className="flex items-center gap-2 text-sm font-semibold text-ink">
            <span aria-hidden className="grid h-7 w-7 place-items-center rounded-lg bg-accent
                                        text-xs font-bold text-accent-ink">AI</span>
            AI Data Analyst
          </span>
          <div className="ml-auto flex items-center gap-2">
            <button type="button" onClick={toggle} className="btn-ghost px-2.5 py-1.5"
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
              <span aria-hidden>{theme === 'dark' ? '☀' : '☾'}</span>
            </button>
            <Link to={user ? '/app' : '/signin'} className="btn-primary text-sm">
              {user ? 'Open workspace' : 'Sign in'}
            </Link>
          </div>
        </div>
      </header>

      <main>
        <section className="mx-auto max-w-6xl px-4 pb-14 pt-16 sm:px-6 sm:pt-24">
          <p className="mb-4 text-xs font-semibold uppercase tracking-[0.16em] text-accent">
            Excel to data story
          </p>
          <h1 className="max-w-3xl text-4xl font-semibold leading-[1.1] tracking-tight text-ink
                         sm:text-5xl">
            Turn Any Excel File Into an AI Data Analyst
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-subtle">
            Upload your data. Discover what matters. Understand why it matters. Get a complete data
            story and professional report in minutes.
          </p>

          <ol className="mt-8 flex flex-wrap items-center gap-x-2 gap-y-2">
            {WORKFLOW.map((step, index) => (
              <li key={step} className="flex items-center gap-2">
                <span className="chip border-accent/40 text-accent">{step}</span>
                {index < WORKFLOW.length - 1 && (
                  <span aria-hidden className="text-muted">→</span>
                )}
              </li>
            ))}
          </ol>

          <div className="mt-9 flex flex-wrap gap-3">
            <Link to={user ? '/app' : '/signin'} className="btn-primary px-5 py-2.5">
              Upload a workbook
            </Link>
            <a href="#samples" className="btn-secondary px-5 py-2.5">Try a sample dataset</a>
          </div>
        </section>

        <section className="border-y border-line bg-surface">
          <div className="mx-auto grid max-w-6xl gap-6 px-4 py-14 sm:grid-cols-2 sm:px-6">
            {CAPABILITIES.map((capability) => (
              <div key={capability.title}>
                <h2 className="text-base font-semibold text-ink">{capability.title}</h2>
                <p className="mt-1.5 text-sm leading-relaxed text-subtle">{capability.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
          <h2 className="text-xl font-semibold tracking-tight text-ink">
            A traditional tool tells you the number. This tells you the story.
          </h2>
          <div className="mt-6 grid gap-4 md:grid-cols-3">
            {[
              { label: 'A dashboard says', text: 'Revenue = ₹12.5M', tone: 'text-muted' },
              { label: 'A better tool says', text: 'Revenue increased 18% compared with the previous period.', tone: 'text-subtle' },
              {
                label: 'This says',
                text: 'Revenue increased 18% compared with the previous period, primarily driven by '
                  + 'the North region and Product A. However, the growth is concentrated in two '
                  + 'categories, creating a potential concentration risk. Investigate whether the '
                  + 'same growth pattern exists in other regions.',
                tone: 'text-ink',
              },
            ].map((item, index) => (
              <div key={item.label}
                className={`card p-5 ${index === 2 ? 'border-accent/40' : ''}`}>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                  {item.label}
                </p>
                <p className={`text-sm leading-relaxed ${item.tone}`}>{item.text}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="samples" className="border-t border-line bg-surface">
          <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
            <h2 className="text-xl font-semibold tracking-tight text-ink">Sample datasets</h2>
            <p className="mt-1.5 max-w-2xl text-sm text-subtle">
              Each one exercises a different part of the engine. Sign in and load one to see the
              full analysis in about a minute.
            </p>
            <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {samples.map((sample) => (
                <button key={sample.key} type="button"
                  onClick={() => navigate(user ? `/app?sample=${sample.key}` : '/signin')}
                  className="card p-5 text-left transition-shadow hover:shadow-lift">
                  <h3 className="text-sm font-semibold text-ink">{sample.title}</h3>
                  <p className="mt-1.5 text-xs leading-relaxed text-subtle">{sample.description}</p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {sample.highlights.map((highlight) => (
                      <span key={highlight} className="chip text-[11px]">{highlight}</span>
                    ))}
                  </div>
                </button>
              ))}
              {samples.length === 0 && (
                <p className="text-sm text-muted">
                  Sample datasets load once the API is reachable.
                </p>
              )}
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-line py-8">
        <p className="mx-auto max-w-6xl px-4 text-xs text-muted sm:px-6">
          Uploaded workbooks are processed on the server, isolated per user and deleted on a
          retention schedule. Spreadsheet content is treated strictly as data.
        </p>
      </footer>
    </div>
  )
}
