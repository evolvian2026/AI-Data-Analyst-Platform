import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { ProcessingStatus } from '../components/ProcessingStatus'
import { ErrorState } from '../components/Primitives'
import type { Progress, SheetInfo } from '../lib/types'

const EMPTY: Progress = { stages: [], completed: 0, total: 12, percent: 0 }

export function ProcessingPage() {
  const { sessionId = '' } = useParams()
  const navigate = useNavigate()
  const [progress, setProgress] = useState<Progress>(EMPTY)
  const [sheets, setSheets] = useState<SheetInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const [filename, setFilename] = useState<string>()

  useEffect(() => {
    let active = true
    let timer: number

    async function poll() {
      try {
        const status = await api.status(sessionId)
        if (!active) return
        setProgress(status.progress ?? EMPTY)
        setSheets(status.sheets ?? [])
        if (status.status === 'completed') {
          navigate(`/app/${sessionId}/overview`, { replace: true })
          return
        }
        if (status.status === 'failed') {
          setError(status.error || 'The analysis failed.')
          return
        }
        timer = window.setTimeout(poll, 900)
      } catch (caught) {
        if (!active) return
        setError(caught instanceof ApiError ? caught.message : 'Lost contact with the server.')
      }
    }

    api.getSession(sessionId)
      .then((session) => { if (active) setFilename(session.original_filename) })
      .catch(() => { /* the progress panel still renders */ })
    void poll()

    return () => { active = true && false; window.clearTimeout(timer) }
  }, [sessionId, navigate])

  return (
    <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      {error ? (
        <>
          <ErrorState message={error} />
          <div className="mt-4 text-center">
            <button type="button" className="btn-secondary" onClick={() => navigate('/app')}>
              Back to your datasets
            </button>
          </div>
        </>
      ) : (
        <>
          <ProcessingStatus progress={progress} filename={filename} />
          {sheets.length > 1 && (
            <div className="card mt-4 p-4">
              <h2 className="mb-2 text-sm font-semibold text-ink">Sheets found</h2>
              <ul className="space-y-1 text-xs">
                {sheets.map((sheet) => (
                  <li key={sheet.name} className="flex items-center gap-2 text-subtle">
                    <span className="font-medium text-ink">{sheet.name}</span>
                    {sheet.is_analyzable ? (
                      <span className="tnum text-muted">
                        {sheet.rows.toLocaleString()} rows · {sheet.columns} columns
                      </span>
                    ) : (
                      <span className="text-muted">{sheet.reason}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </main>
  )
}
