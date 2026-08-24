import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ApiError } from '../lib/api'

export function SignInPage() {
  const { user, login, register, config } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'signin' | 'register'>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [organization, setOrganization] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/app" replace />

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'signin') await login(email, password)
      else await register({ email, password, full_name: fullName, organization })
      navigate('/app')
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Something went wrong. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-4 py-12">
      <div className="w-full max-w-sm">
        <Link to="/" className="mb-8 flex items-center justify-center gap-2 text-sm font-semibold">
          <span aria-hidden className="grid h-7 w-7 place-items-center rounded-lg bg-accent
                                      text-xs font-bold text-accent-ink">AI</span>
          AI Data Analyst
        </Link>

        <div className="card p-6">
          <h1 className="text-lg font-semibold text-ink">
            {mode === 'signin' ? 'Sign in' : 'Create your account'}
          </h1>
          <p className="mt-1 text-sm text-subtle">
            {mode === 'signin'
              ? 'Your datasets stay private to your account.'
              : 'Uploads are isolated per account and removed on a retention schedule.'}
          </p>

          <form onSubmit={submit} className="mt-5 space-y-4">
            {mode === 'register' && (
              <>
                <div>
                  <label htmlFor="name" className="label">Full name</label>
                  <input id="name" className="input" value={fullName} autoComplete="name"
                    onChange={(event) => setFullName(event.target.value)} />
                </div>
                <div>
                  <label htmlFor="org" className="label">Organization</label>
                  <input id="org" className="input" value={organization} autoComplete="organization"
                    onChange={(event) => setOrganization(event.target.value)} />
                </div>
              </>
            )}
            <div>
              <label htmlFor="email" className="label">Email</label>
              <input id="email" type="email" required className="input" value={email}
                autoComplete="email" onChange={(event) => setEmail(event.target.value)} />
            </div>
            <div>
              <label htmlFor="password" className="label">Password</label>
              <input id="password" type="password" required minLength={8} className="input"
                value={password}
                autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                onChange={(event) => setPassword(event.target.value)} />
              {mode === 'register' && (
                <p className="mt-1 text-[11px] text-muted">
                  At least 8 characters, mixing letters with numbers or symbols.
                </p>
              )}
            </div>

            {error && (
              <p role="alert" className="rounded-lg border border-critical/40 bg-critical/5 px-3
                                         py-2 text-xs text-critical">
                {error}
              </p>
            )}

            <button type="submit" disabled={busy} className="btn-primary w-full py-2.5">
              {busy ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Create account'}
            </button>
          </form>

          {config?.allow_registration !== false && (
            <p className="mt-4 text-center text-xs text-subtle">
              {mode === 'signin' ? 'No account yet?' : 'Already have an account?'}{' '}
              <button type="button" className="font-medium text-accent hover:underline"
                onClick={() => { setMode(mode === 'signin' ? 'register' : 'signin'); setError(null) }}>
                {mode === 'signin' ? 'Create one' : 'Sign in'}
              </button>
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
