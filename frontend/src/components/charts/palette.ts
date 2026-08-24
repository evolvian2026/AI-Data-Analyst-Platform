/**
 * Chart colour roles.
 *
 * Hues are read from CSS custom properties so light and dark are declared once
 * in index.css. Categorical slots are assigned in fixed order and never cycled:
 * a ninth series folds into "Other" rather than inventing a colour.
 */

export const SERIES_SLOTS = 8

function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

export interface Palette {
  series: string[]
  grid: string
  axis: string
  ink: string
  muted: string
  surface: string
  sequential: [string, string, string]
  diverging: [string, string, string]
}

const LIGHT_FALLBACK = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100',
  '#e87ba4', '#008300', '#4a3aa7', '#e34948']

export function readPalette(): Palette {
  return {
    series: LIGHT_FALLBACK.map((fallback, index) => cssVar(`--series-${index + 1}`, fallback)),
    grid: cssVar('--grid', '#e1e0d9'),
    axis: cssVar('--axis', '#c3c2b7'),
    ink: `rgb(${cssVar('--ink', '11 11 11')})`,
    muted: `rgb(${cssVar('--muted', '137 135 129')})`,
    surface: `rgb(${cssVar('--surface', '252 252 251')})`,
    sequential: [
      cssVar('--seq-100', '#cde2fb'),
      cssVar('--seq-400', '#3987e5'),
      cssVar('--seq-700', '#0d366b'),
    ],
    diverging: [
      cssVar('--diverge-low', '#2a78d6'),
      cssVar('--diverge-mid', '#f0efec'),
      cssVar('--diverge-high', '#d03b3b'),
    ],
  }
}

/** Colour follows the entity, not its rank, so filtering never repaints series. */
export function seriesColor(palette: Palette, key: string, order: string[]): string {
  const index = order.indexOf(key)
  return palette.series[(index < 0 ? 0 : index) % SERIES_SLOTS]
}

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace('#', '')
  const full = clean.length === 3 ? clean.split('').map((c) => c + c).join('') : clean
  const value = parseInt(full, 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

function mix(from: string, to: string, ratio: number): string {
  const [r1, g1, b1] = hexToRgb(from)
  const [r2, g2, b2] = hexToRgb(to)
  const clamped = Math.max(0, Math.min(1, ratio))
  const channel = (a: number, b: number) => Math.round(a + (b - a) * clamped)
  return `rgb(${channel(r1, r2)} ${channel(g1, g2)} ${channel(b1, b2)})`
}

/** One hue, light to dark: magnitude only, never a rainbow. */
export function sequentialColor(palette: Palette, ratio: number): string {
  const [low, mid, high] = palette.sequential
  return ratio <= 0.5 ? mix(low, mid, ratio * 2) : mix(mid, high, (ratio - 0.5) * 2)
}

/** Two hues with a neutral midpoint: for signed values such as correlation. */
export function divergingColor(palette: Palette, value: number): string {
  const [low, mid, high] = palette.diverging
  const clamped = Math.max(-1, Math.min(1, value))
  return clamped >= 0 ? mix(mid, high, clamped) : mix(mid, low, -clamped)
}
