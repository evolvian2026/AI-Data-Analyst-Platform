import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { Card, Loading } from './Primitives'
import { clsx } from '../lib/format'
import type { CleaningAudit, CleaningProposal } from '../lib/types'

/**
 * Propose and confirm.
 *
 * Every fix here is a proposal until someone accepts it: the panel states the
 * exact number of cells involved, shows real before/after values from this
 * dataset, and says plainly when a fix discards data. Accepting stores a recipe
 * replayed onto a copy - the uploaded workbook is never modified, and clearing
 * the recipe restores the original analysis exactly.
 */
export function CleaningPanel({ sessionId, audit, onApplied }: {
  sessionId: string
  audit: CleaningAudit | null
  onApplied: () => void
}) {
  const [proposals, setProposals] = useState<CleaningProposal[] | null>(null)
  const [policy, setPolicy] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [accepted, setAccepted] = useState<Set<string>>(new Set())
  const [preview, setPreview] = useState<CleaningAudit | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const response = await api.qualityFixes(sessionId)
    setProposals(response.proposals)
    setPolicy(response.policy)
    const already = new Set(response.applied.map((fix) => fix.id))
    setAccepted(already)
    setSelected(new Set(already))
  }, [sessionId])

  useEffect(() => { void load() }, [load])

  const chosen = useMemo(
    () => (proposals ?? []).filter((proposal) => selected.has(proposal.id)),
    [proposals, selected],
  )
  const dirty = useMemo(() => {
    if (selected.size !== accepted.size) return true
    return [...selected].some((id) => !accepted.has(id))
  }, [selected, accepted])

  const toggle = (id: string) => {
    setPreview(null)
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const runPreview = async () => {
    setBusy(true)
    setError(null)
    try {
      setPreview(await api.previewQualityFixes(sessionId, chosen))
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not preview those fixes.')
    } finally {
      setBusy(false)
    }
  }

  const apply = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.applyQualityFixes(sessionId, chosen)
      setAccepted(new Set(selected))
      setPreview(null)
      onApplied()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not apply those fixes.')
    } finally {
      setBusy(false)
    }
  }

  if (!proposals) return <Loading rows={2} label="Looking for fixable problems" />

  if (proposals.length === 0 && !audit) {
    return (
      <Card>
        <h3 className="text-sm font-semibold text-ink">Nothing to fix</h3>
        <p className="mt-1 text-xs text-subtle">
          No problem in this dataset has a correction the platform can propose safely.
        </p>
      </Card>
    )
  }

  return (
    <Card className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-ink">Suggested corrections</h3>
        <p className="mt-1 text-xs text-subtle">{policy}</p>
      </div>

      {audit && audit.applied_count > 0 && (
        <div className="rounded-lg border border-accent/40 bg-accent/5 px-3 py-2.5 text-xs">
          <p className="font-medium text-ink">
            This analysis is calculated from cleaned data
          </p>
          <ul className="tnum mt-1.5 space-y-0.5 text-subtle">
            {audit.steps.filter((step) => step.applied).map((step) => (
              <li key={step.id}>{step.note}</li>
            ))}
          </ul>
          <p className="mt-1.5 text-muted">
            {audit.rows_before.toLocaleString()} rows in the file,{' '}
            {audit.rows_after.toLocaleString()} analysed. The uploaded file itself is unchanged.
          </p>
        </div>
      )}

      {error && (
        <p className="rounded-lg border border-critical/40 bg-critical/5 px-3 py-2 text-xs
                      text-critical">{error}</p>
      )}

      <ul className="space-y-3">
        {proposals.map((proposal) => (
          <li key={proposal.id}>
            <label className={clsx(
              'flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors',
              selected.has(proposal.id) ? 'border-accent bg-accent/5' : 'border-line hover:border-accent/50',
            )}>
              <input type="checkbox" className="mt-0.5 accent-[rgb(var(--accent))]"
                aria-label={`Accept: ${proposal.title}`}
                checked={selected.has(proposal.id)}
                onChange={() => toggle(proposal.id)} />
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
                  {proposal.title}
                  {proposal.data_loss && (
                    <span className="chip border-warning/50 text-warning">discards data</span>
                  )}
                  {accepted.has(proposal.id) && (
                    <span className="chip border-good/40 text-good">applied</span>
                  )}
                </p>
                <p className="mt-1 text-xs text-subtle">{proposal.description}</p>
                {proposal.rationale && (
                  <p className="mt-1 text-xs text-muted">{proposal.rationale}</p>
                )}
                {proposal.examples.length > 0 && (
                  <table className="tnum mt-2 text-left text-[11px]">
                    <thead>
                      <tr className="text-muted">
                        <th className="pr-4 font-medium">Before</th>
                        <th className="font-medium">After</th>
                      </tr>
                    </thead>
                    <tbody>
                      {proposal.examples.map((example, index) => (
                        <tr key={index}>
                          <td className="pr-4 text-subtle">{example.before}</td>
                          <td className="text-ink">{example.after}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <p className="mt-1.5 text-[11px] text-muted">
                  <span className="font-medium">Risk:</span> {proposal.risk}
                </p>
              </div>
            </label>
          </li>
        ))}
      </ul>

      {preview && (
        <div className="rounded-lg border border-line bg-page px-3 py-2.5 text-xs">
          <p className="font-medium text-ink">What this would change</p>
          <ul className="tnum mt-1 space-y-0.5 text-subtle">
            {preview.steps.map((step) => <li key={step.id}>{step.note}</li>)}
          </ul>
          <p className="tnum mt-1.5 text-muted">
            {preview.rows_before.toLocaleString()} rows →{' '}
            {preview.rows_after.toLocaleString()} rows;{' '}
            {preview.cells_changed.toLocaleString()} cells changed. Nothing has been applied yet.
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-3">
        <button type="button" className="btn-secondary text-xs"
          disabled={busy || chosen.length === 0} onClick={() => void runPreview()}>
          Preview the effect
        </button>
        <button type="button" className="btn-primary text-xs" disabled={busy || !dirty}
          onClick={() => void apply()}>
          {busy ? 'Re-analysing…' : selected.size === 0
            ? 'Remove all fixes and re-analyse'
            : `Apply ${selected.size} fix${selected.size === 1 ? '' : 'es'} and re-analyse`}
        </button>
        {dirty && (
          <span className="text-xs text-muted">
            The uploaded file is not modified; removing a fix restores the original analysis.
          </span>
        )}
      </div>
    </Card>
  )
}
