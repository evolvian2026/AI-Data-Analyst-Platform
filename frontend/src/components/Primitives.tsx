import type { ReactNode } from 'react'
import { clsx } from '../lib/format'
import type { Confidence } from '../lib/types'

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx('card p-5', className)}>{children}</div>
}

export function SectionHeading({ title, description, action }: {
  title: string; description?: string; action?: ReactNode
}) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-ink">{title}</h2>
        {description && <p className="mt-1 max-w-2xl text-sm text-subtle">{description}</p>}
      </div>
      {action}
    </div>
  )
}

const CONFIDENCE_STYLE: Record<Confidence, string> = {
  high: 'border-good/40 text-good',
  medium: 'border-warning/50 text-warning',
  low: 'border-serious/50 text-serious',
}

const CONFIDENCE_ICON: Record<Confidence, string> = { high: '●', medium: '◐', low: '○' }

export function ConfidenceBadge({ level, reason }: { level: Confidence; reason?: string }) {
  return (
    <span className={clsx('chip', CONFIDENCE_STYLE[level])} title={reason}>
      <span aria-hidden>{CONFIDENCE_ICON[level]}</span>
      {level} confidence
    </span>
  )
}

const SEVERITY_STYLE: Record<string, string> = {
  critical: 'border-critical/50 text-critical',
  high: 'border-serious/50 text-serious',
  medium: 'border-warning/50 text-warning',
  low: 'border-line text-muted',
}

export function SeverityBadge({ level }: { level: string }) {
  return (
    <span className={clsx('chip capitalize', SEVERITY_STYLE[level] ?? SEVERITY_STYLE.low)}>
      {level}
    </span>
  )
}

export function Empty({ title, description, action }: {
  title: string; description: string; action?: ReactNode
}) {
  return (
    <div className="card flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <p className="text-sm font-semibold text-ink">{title}</p>
      <p className="max-w-md text-sm text-subtle">{description}</p>
      {action}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card border-critical/30 px-6 py-10 text-center">
      <p className="text-sm font-semibold text-critical">Something went wrong</p>
      <p className="mx-auto mt-2 max-w-lg text-sm text-subtle">{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn-secondary mt-4">Try again</button>
      )}
    </div>
  )
}

export function Loading({ rows = 3, label }: { rows?: number; label?: string }) {
  return (
    <div className="space-y-3" role="status" aria-live="polite">
      <span className="sr-only">{label ?? 'Loading'}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="skeleton h-24 w-full" />
      ))}
    </div>
  )
}

export function Meter({ value, max = 100, tone = 'accent' }: {
  value: number; max?: number; tone?: 'accent' | 'good' | 'warning' | 'critical'
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100))
  const tones = {
    accent: 'bg-accent', good: 'bg-good', warning: 'bg-warning', critical: 'bg-critical',
  }
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-line"
      role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <div className={clsx('h-full rounded-full transition-all', tones[tone])}
        style={{ width: `${pct}%` }} />
    </div>
  )
}

export function ScoreRing({ score, label, size = 92 }: {
  score: number; label: string; size?: number
}) {
  const radius = size / 2 - 7
  const circumference = 2 * Math.PI * radius
  const offset = circumference * (1 - Math.max(0, Math.min(100, score)) / 100)
  const tone = score >= 85 ? 'var(--good-c)' : score >= 65 ? 'var(--warn-c)' : 'var(--crit-c)'
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <style>{`.ring-${size}{--good-c:rgb(var(--good));--warn-c:rgb(var(--warning));--crit-c:rgb(var(--critical))}`}</style>
      <svg width={size} height={size} className={`ring-${size} -rotate-90`} aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none"
          stroke="rgb(var(--line))" strokeWidth={7} />
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={tone} strokeWidth={7}
          strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 600ms ease' }} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="tnum text-xl font-semibold text-ink">{Math.round(score)}</span>
        <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
      </div>
    </div>
  )
}

export function Toggle({ options, value, onChange, ariaLabel }: {
  options: { value: string; label: string }[]
  value: string
  onChange: (value: string) => void
  ariaLabel: string
}) {
  return (
    <div role="tablist" aria-label={ariaLabel}
      className="inline-flex rounded-lg border border-line bg-surface p-0.5">
      {options.map((option) => (
        <button key={option.value} type="button" role="tab"
          aria-selected={value === option.value}
          onClick={() => onChange(option.value)}
          className={clsx(
            'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
            value === option.value ? 'bg-accent text-accent-ink' : 'text-subtle hover:text-ink',
          )}>
          {option.label}
        </button>
      ))}
    </div>
  )
}
