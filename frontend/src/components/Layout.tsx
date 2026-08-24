import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'
import { useAnalysis } from '../context/AnalysisContext'
import { clsx } from '../lib/format'
import { ErrorState, Loading } from './Primitives'

const NAV = [
  { to: 'overview', label: 'Overview' },
  { to: 'story', label: 'Data Story' },
  { to: 'dashboard', label: 'Dashboard' },
  { to: 'insights', label: 'Insights' },
  { to: 'ask', label: 'Ask Your Data' },
  { to: 'quality', label: 'Data Quality' },
  { to: 'explore', label: 'Explore Data' },
  { to: 'reports', label: 'Reports' },
]

export function AppShell() {
  const { user, logout } = useAuth()
  const { theme, toggle } = useTheme()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-page">
      <header className="sticky top-0 z-40 border-b border-line bg-surface/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-4 px-4 sm:px-6">
          <button type="button" onClick={() => navigate('/app')}
            className="flex items-center gap-2 text-sm font-semibold text-ink">
            <span aria-hidden className="grid h-7 w-7 place-items-center rounded-lg bg-accent
                                        text-xs font-bold text-accent-ink">AI</span>
            AI Data Analyst
          </button>
          <div className="ml-auto flex items-center gap-1">
            <button type="button" onClick={toggle} className="btn-ghost px-2.5 py-1.5"
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
              <span aria-hidden>{theme === 'dark' ? '☀' : '☾'}</span>
            </button>
            {user && (
              <div className="flex items-center gap-2">
                <span className="hidden text-xs text-muted sm:inline">{user.email}</span>
                <button type="button" onClick={() => { logout(); navigate('/') }}
                  className="btn-ghost text-xs">Sign out</button>
              </div>
            )}
          </div>
        </div>
      </header>
      <Outlet />
    </div>
  )
}

export function AnalysisLayout() {
  const { session, analysis, loading, error, reload, sessionId } = useAnalysis()
  const navigate = useNavigate()

  if (loading) {
    return (
      <main className="mx-auto max-w-[1400px] px-4 py-10 sm:px-6">
        <Loading rows={4} label="Loading analysis" />
      </main>
    )
  }

  if (error || !analysis) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-14 sm:px-6">
        <ErrorState message={error ?? 'This analysis is not available.'} onRetry={reload} />
        <div className="mt-4 text-center">
          <button type="button" onClick={() => navigate('/app')} className="btn-secondary">
            Back to your datasets
          </button>
        </div>
      </main>
    )
  }

  return (
    <>
      <div className="border-b border-line bg-surface">
        <div className="mx-auto max-w-[1400px] px-4 sm:px-6">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-3">
            <h1 className="truncate text-sm font-semibold text-ink">
              {session?.name ?? analysis.session.name}
            </h1>
            <span className="tnum text-xs text-muted">
              {analysis.profile.row_count.toLocaleString()} rows ·{' '}
              {analysis.profile.column_count} columns
              {analysis.active_sheet !== '__workbook__' && ` · sheet ${analysis.active_sheet}`}
            </span>
          </div>
          <nav aria-label="Analysis sections"
            className="-mb-px flex gap-1 overflow-x-auto pt-2">
            {NAV.map((item) => (
              <NavLink key={item.to} to={`/app/${sessionId}/${item.to}`}
                className={({ isActive }) => clsx(
                  'whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
                  isActive
                    ? 'border-accent text-accent'
                    : 'border-transparent text-subtle hover:text-ink',
                )}>
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </div>
      <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </>
  )
}
