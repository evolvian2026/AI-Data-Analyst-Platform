import {
  createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode,
} from 'react'
import { useParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import type { ActiveFilter, Analysis, FeedbackVote, SessionSummary } from '../lib/types'

interface AnalysisValue {
  sessionId: string
  session: SessionSummary | null
  analysis: Analysis | null
  /** The analysis currently on screen: filtered when filters are active. */
  view: Analysis | null
  filters: ActiveFilter[]
  setFilters: (filters: ActiveFilter[]) => void
  filtering: boolean
  loading: boolean
  error: string | null
  reload: () => Promise<void>
  bookmarks: string[]
  notes: Record<string, string>
  toggleBookmark: (id: string) => void
  saveNote: (id: string, note: string) => void
  /** Rate a finding useful or not. Reorders the list; changes no value. */
  rateInsight: (id: string, vote: FeedbackVote | 'clear') => Promise<void>
}

const AnalysisContext = createContext<AnalysisValue | null>(null)

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const { sessionId = '' } = useParams()
  const [session, setSession] = useState<SessionSummary | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [filtered, setFiltered] = useState<Analysis | null>(null)
  const [filters, setFiltersState] = useState<ActiveFilter[]>([])
  const [filtering, setFiltering] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [bookmarks, setBookmarks] = useState<string[]>([])
  const [notes, setNotes] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    if (!sessionId) return
    setLoading(true)
    setError(null)
    try {
      const [summary, result] = await Promise.all([
        api.getSession(sessionId), api.analysis(sessionId),
      ])
      setSession(summary)
      setAnalysis(result)
      setBookmarks(result.session?.bookmarks ?? [])
      setNotes(result.session?.notes ?? {})
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not load this analysis.')
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => { void load() }, [load])

  const setFilters = useCallback(async (next: ActiveFilter[]) => {
    setFiltersState(next)
    if (next.length === 0) {
      setFiltered(null)
      return
    }
    setFiltering(true)
    try {
      setFiltered(await api.filter(sessionId, next))
      setError(null)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not apply those filters.')
      setFiltered(null)
    } finally {
      setFiltering(false)
    }
  }, [sessionId])

  const persist = useCallback(
    (payload: { bookmarks?: string[]; notes?: Record<string, string> }) => {
      void api.updateSession(sessionId, payload).catch(() => {
        /* the local state stays; the next save retries */
      })
    },
    [sessionId],
  )

  const toggleBookmark = useCallback((id: string) => {
    setBookmarks((current) => {
      const next = current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id]
      persist({ bookmarks: next })
      return next
    })
  }, [persist])

  const saveNote = useCallback((id: string, note: string) => {
    setNotes((current) => {
      const next = { ...current }
      if (note.trim()) next[id] = note.trim()
      else delete next[id]
      persist({ notes: next })
      return next
    })
  }, [persist])

  const rateInsight = useCallback(async (id: string, vote: FeedbackVote | 'clear') => {
    const response = await api.rateInsight(sessionId, id, vote)
    // The server returns the whole re-ordered list, so the ranking a reader
    // sees is always the one the server would serve on a reload.
    setAnalysis((current) => (current
      ? { ...current, insights: response.insights, top_insights: response.insights.slice(0, 5),
          feedback: response.feedback }
      : current))
  }, [sessionId])

  const value = useMemo<AnalysisValue>(() => ({
    sessionId, session, analysis, view: filtered ?? analysis, filters, setFilters,
    filtering, loading, error, reload: load, bookmarks, notes, toggleBookmark, saveNote,
    rateInsight,
  }), [sessionId, session, analysis, filtered, filters, setFilters, filtering, loading,
    error, load, bookmarks, notes, toggleBookmark, saveNote, rateInsight])

  return <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>
}

export function useAnalysis(): AnalysisValue {
  const value = useContext(AnalysisContext)
  if (!value) throw new Error('useAnalysis must be used inside AnalysisProvider')
  return value
}
