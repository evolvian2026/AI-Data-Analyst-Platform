import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { formatBytes, formatDateTime } from '../lib/format'
import { Empty, ErrorState, Loading, SectionHeading } from '../components/Primitives'
import type { SampleDataset, SessionSummary } from '../lib/types'

const STATUS_STYLE: Record<string, string> = {
  completed: 'text-good', processing: 'text-accent', pending: 'text-muted', failed: 'text-critical',
}

export function WorkspacePage() {
  const navigate = useNavigate()
  const { config } = useAuth()
  const [params, setParams] = useSearchParams()
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null)
  const [samples, setSamples] = useState<SampleDataset[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try {
      const [list, sampleList] = await Promise.all([api.listSessions(), api.samples()])
      setSessions(list)
      setSamples(sampleList.samples)
      setError(null)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not load your datasets.')
      setSessions([])
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const start = useCallback((session: SessionSummary) => {
    navigate(session.status === 'completed'
      ? `/app/${session.id}/overview`
      : `/app/${session.id}/processing`)
  }, [navigate])

  const upload = useCallback(async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      start(await api.upload(file))
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The upload failed.')
    } finally {
      setBusy(false)
    }
  }, [start])

  const loadSample = useCallback(async (key: string) => {
    setBusy(true)
    setError(null)
    try {
      start(await api.loadSample(key))
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The sample could not be loaded.')
    } finally {
      setBusy(false)
    }
  }, [start])

  // Deep link from the landing page: /app?sample=sales
  useEffect(() => {
    const requested = params.get('sample')
    if (requested) {
      setParams({}, { replace: true })
      void loadSample(requested)
    }
  }, [params, setParams, loadSample])

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      <SectionHeading
        title="Your datasets"
        description="Upload an Excel workbook to start a new analysis session, or reopen a previous one."
      />

      <div
        onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          const file = event.dataTransfer.files?.[0]
          if (file) void upload(file)
        }}
        className={`card flex flex-col items-center justify-center gap-3 border-dashed px-6 py-12
                    text-center transition-colors ${dragging ? 'border-accent bg-accent/5' : ''}`}
      >
        <p className="text-sm font-medium text-ink">Drop an Excel workbook here</p>
        <p className="max-w-md text-xs text-subtle">
          .xlsx or .xls, up to {config?.max_upload_mb ?? 100} MB. Multiple sheets, empty rows,
          missing or duplicate headers and mixed types are all handled.
        </p>
        <input ref={fileInput} type="file" accept=".xlsx,.xls,.xlsm" className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void upload(file)
            event.target.value = ''
          }} />
        <button type="button" className="btn-primary" disabled={busy}
          onClick={() => fileInput.current?.click()}>
          {busy ? 'Uploading…' : 'Choose a file'}
        </button>
      </div>

      {error && <div className="mt-4"><ErrorState message={error} onRetry={load} /></div>}

      <section className="mt-10">
        <h2 className="mb-3 text-sm font-semibold text-ink">Or start with a sample</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {samples.map((sample) => (
            <button key={sample.key} type="button" disabled={busy}
              onClick={() => void loadSample(sample.key)}
              className="card p-4 text-left transition-shadow hover:shadow-lift disabled:opacity-60">
              <h3 className="text-sm font-semibold text-ink">{sample.title}</h3>
              <p className="mt-1 text-xs leading-relaxed text-subtle">{sample.description}</p>
            </button>
          ))}
        </div>
      </section>

      <section className="mt-10">
        <h2 className="mb-3 text-sm font-semibold text-ink">Analysis sessions</h2>
        {sessions === null && <Loading rows={2} label="Loading sessions" />}
        {sessions?.length === 0 && (
          <Empty title="No analyses yet"
            description="Upload a workbook or load a sample dataset to create your first analysis session." />
        )}
        <ul className="space-y-2">
          {sessions?.map((session) => (
            <li key={session.id}>
              <div className="card flex flex-wrap items-center gap-x-4 gap-y-2 p-4">
                <button type="button" onClick={() => start(session)}
                  className="min-w-0 flex-1 text-left">
                  <p className="truncate text-sm font-medium text-ink">{session.name}</p>
                  <p className="tnum mt-0.5 text-xs text-muted">
                    {session.original_filename} · {formatBytes(session.file_size)} ·{' '}
                    {formatDateTime(session.created_at)}
                    {session.workbook_meta?.total_rows
                      ? ` · ${session.workbook_meta.total_rows.toLocaleString()} rows`
                      : ''}
                  </p>
                </button>
                <span className={`text-xs font-medium capitalize ${STATUS_STYLE[session.status]}`}>
                  {session.status}
                </span>
                <button type="button" className="btn-secondary text-xs"
                  onClick={() => start(session)}>Open</button>
                <button type="button" className="btn-ghost text-xs text-critical"
                  onClick={async () => {
                    if (!window.confirm(`Delete "${session.name}"? This cannot be undone.`)) return
                    await api.deleteSession(session.id)
                    void load()
                  }}>Delete</button>
              </div>
              {session.status === 'failed' && session.error && (
                <p className="mt-1 px-4 text-xs text-critical">{session.error}</p>
              )}
            </li>
          ))}
        </ul>
      </section>
    </main>
  )
}
