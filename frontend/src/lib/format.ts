/** Display formatting that mirrors the server's own rules. */

export function compact(value: number | null | undefined, currency = ''): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'n/a'
  const sign = value < 0 ? '-' : ''
  const absolute = Math.abs(value)
  const units: [number, string][] = [[1e12, 'T'], [1e9, 'B'], [1e6, 'M'], [1e3, 'K']]
  for (const [threshold, suffix] of units) {
    if (absolute >= threshold) {
      return `${sign}${currency}${(absolute / threshold).toLocaleString(undefined, {
        maximumFractionDigits: 2,
      })}${suffix}`
    }
  }
  if (absolute >= 1000) return `${sign}${currency}${absolute.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
  if (absolute >= 1) return `${sign}${currency}${absolute.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
  if (absolute === 0) return `${currency}0`
  return `${sign}${currency}${absolute.toPrecision(3)}`
}

export function formatValue(
  value: number | string | null | undefined,
  semanticType = '',
  currency = '',
): string {
  if (value === null || value === undefined) return 'n/a'
  if (typeof value === 'string') return value
  if (!Number.isFinite(value)) return 'n/a'
  if (semanticType === 'percentage') return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`
  if (semanticType === 'currency') return compact(value, currency)
  if (semanticType === 'integer') return value.toLocaleString(undefined, { maximumFractionDigits: 0 })
  return compact(value)
}

export function formatDelta(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return 'n/a'
  if (pct >= 300) return `${(1 + pct / 100).toFixed(1)}x`
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

export function titleCase(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function clsx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}
