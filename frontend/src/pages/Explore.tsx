import { useCallback, useEffect, useState } from 'react'
import { useAnalysis } from '../context/AnalysisContext'
import { api, ApiError } from '../lib/api'
import { FilterBar } from '../components/FilterBar'
import { Card, ErrorState, Loading, SectionHeading } from '../components/Primitives'
import { clsx } from '../lib/format'
import type { DataPage } from '../lib/types'

const PAGE_SIZE = 50

export function ExplorePage() {
  const { sessionId, view, analysis, filters, setFilters, filtering } = useAnalysis()
  const [page, setPage] = useState<DataPage | null>(null)
  const [offset, setOffset] = useState(0)
  const [sortBy, setSortBy] = useState<string | null>(null)
  const [sortDesc, setSortDesc] = useState(true)
  const [search, setSearch] = useState('')
  const [pending, setPending] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setPage(await api.data(sessionId, {
        limit: PAGE_SIZE, offset, sort_by: sortBy, sort_desc: sortDesc,
        search: search || null, filters,
      }))
      setError(null)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not load the rows.')
      setPage(null)
    } finally {
      setLoading(false)
    }
  }, [sessionId, offset, sortBy, sortDesc, search, filters])

  useEffect(() => { void load() }, [load])

  if (!view || !analysis) return null

  const total = page?.total ?? 0
  const lastOffset = Math.max(0, Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE)

  return (
    <div className="space-y-5">
      <FilterBar definitions={analysis.filters} active={filters}
        onChange={(next) => { setOffset(0); setFilters(next) }}
        busy={filtering} summary={view.filter_summary ?? null} />

      <SectionHeading
        title="Explore data"
        description="The rows behind the analysis. Paging, sorting and search all run on the server, so nothing large is loaded into the browser."
        action={
          <button type="button" className="btn-secondary text-xs"
            onClick={() => api.downloadData(sessionId,
              { filters, data_row_limit: 100000 },
              `${view.session?.name ?? 'data'}.csv`)}>
            Download filtered data
          </button>
        }
      />

      <form className="flex gap-2" onSubmit={(event) => {
        event.preventDefault()
        setOffset(0)
        setSearch(pending)
      }}>
        <input value={pending} onChange={(event) => setPending(event.target.value)}
          placeholder="Search across all columns…" aria-label="Search rows" className="input" />
        <button type="submit" className="btn-secondary shrink-0">Search</button>
        {search && (
          <button type="button" className="btn-ghost shrink-0"
            onClick={() => { setPending(''); setSearch(''); setOffset(0) }}>Clear</button>
        )}
      </form>

      {error && <ErrorState message={error} onRetry={load} />}

      {loading && !page && <Loading rows={4} label="Loading rows" />}

      {page && (
        <>
          <Card className="overflow-x-auto p-0">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-line bg-page">
                  {page.columns.map((column) => (
                    <th key={column.name} className="whitespace-nowrap px-3 py-2 font-medium">
                      <button type="button"
                        onClick={() => {
                          if (sortBy === column.name) setSortDesc((current) => !current)
                          else { setSortBy(column.name); setSortDesc(true) }
                          setOffset(0)
                        }}
                        className={clsx('flex items-center gap-1 hover:text-ink',
                          sortBy === column.name ? 'text-accent' : 'text-muted')}>
                        {column.name}
                        {sortBy === column.name && (
                          <span aria-hidden>{sortDesc ? '▾' : '▴'}</span>
                        )}
                      </button>
                      <span className="block text-[10px] font-normal text-muted">
                        {column.semantic_type}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {page.rows.map((row, index) => (
                  <tr key={index} className="border-b border-line/60 hover:bg-page">
                    {page.columns.map((column) => (
                      <td key={column.name} className="tnum whitespace-nowrap px-3 py-1.5 text-subtle">
                        {row[column.name] === null || row[column.name] === undefined
                          ? <span className="text-muted">–</span>
                          : typeof row[column.name] === 'number'
                            ? (row[column.name] as number).toLocaleString(undefined,
                              { maximumFractionDigits: 4 })
                            : String(row[column.name])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="tnum text-xs text-muted">
              Rows {total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of{' '}
              {total.toLocaleString()}
            </p>
            <div className="flex gap-2">
              <button type="button" className="btn-secondary text-xs" disabled={offset === 0}
                onClick={() => setOffset(0)}>First</button>
              <button type="button" className="btn-secondary text-xs" disabled={offset === 0}
                onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}>
                Previous
              </button>
              <button type="button" className="btn-secondary text-xs"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset((current) => current + PAGE_SIZE)}>Next</button>
              <button type="button" className="btn-secondary text-xs"
                disabled={offset >= lastOffset} onClick={() => setOffset(lastOffset)}>Last</button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
