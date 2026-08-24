import { useMemo } from 'react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts'
import type { Chart } from '../../lib/types'
import { compact, formatValue } from '../../lib/format'
import { ChartFrame } from './ChartFrame'
import { divergingColor, readPalette, sequentialColor, type Palette } from './palette'

interface Props {
  chart: Chart
  height?: number
  onDrilldown?: (dimension: string, value: string) => void
}

const AXIS_STYLE = { fontSize: 11 }
const MARGIN = { top: 8, right: 16, bottom: 8, left: 4 }

function useValueFormatter(chart: Chart) {
  return useMemo(
    () => (value: number | string | null) =>
      formatValue(value, chart.value_format, chart.currency_symbol),
    [chart.value_format, chart.currency_symbol],
  )
}

function TooltipBox({
  title, rows,
}: { title: string; rows: { label: string; value: string; color?: string }[] }) {
  return (
    <div className="rounded-lg border border-line bg-raised px-3 py-2 shadow-lift">
      <p className="mb-1 text-xs font-semibold text-ink">{title}</p>
      {rows.map((row) => (
        <p key={row.label} className="flex items-center gap-2 text-xs text-subtle">
          {row.color && (
            <span
              className="inline-block h-2 w-2 shrink-0 rounded-sm"
              style={{ background: row.color }}
              aria-hidden
            />
          )}
          <span>{row.label}</span>
          <span className="tnum ml-auto font-medium text-ink">{row.value}</span>
        </p>
      ))}
    </div>
  )
}

function DataTable({ chart }: { chart: Chart }) {
  const keys = useMemo(() => {
    const seen = new Set<string>([chart.x_key])
    chart.series.forEach((s) => seen.add(s.key))
    chart.data.slice(0, 1).forEach((row) => Object.keys(row).forEach((k) => seen.add(k)))
    return [...seen].filter((k) => k !== 'group')
  }, [chart])

  return (
    <table className="w-full text-left text-xs">
      <thead className="sticky top-0 bg-surface">
        <tr className="border-b border-line">
          {keys.map((key) => (
            <th key={key} className="py-2 pr-3 font-medium text-muted">{key}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {chart.data.slice(0, 200).map((row, index) => (
          <tr key={index} className="border-b border-line/60">
            {keys.map((key) => (
              <td key={key} className="tnum py-1.5 pr-3 text-subtle">
                {typeof row[key] === 'number'
                  ? formatValue(row[key] as number, chart.value_format, chart.currency_symbol)
                  : String(row[key] ?? '')}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function ChartRenderer({ chart, height = 260, onDrilldown }: Props) {
  const palette = useMemo(readPalette, [])
  const format = useValueFormatter(chart)
  const seriesKeys = chart.series.map((s) => s.key)
  const showLegend = chart.series.length >= 2

  const handleClick = (name: unknown) => {
    if (!onDrilldown || !chart.drilldown?.dimension || typeof name !== 'string') return
    onDrilldown(chart.drilldown.dimension, name)
  }

  const body = renderBody({ chart, palette, format, height, seriesKeys, showLegend, handleClick })

  return (
    <ChartFrame chart={chart} table={<DataTable chart={chart} />}>
      <div style={{ height }} className="w-full">
        {body}
      </div>
    </ChartFrame>
  )
}

interface BodyArgs {
  chart: Chart
  palette: Palette
  format: (value: number | string | null) => string
  height: number
  seriesKeys: string[]
  showLegend: boolean
  handleClick: (name: unknown) => void
}

function legendProps(palette: Palette) {
  return {
    wrapperStyle: { fontSize: 11, color: palette.muted, paddingTop: 4 },
    iconType: 'square' as const,
    iconSize: 9,
  }
}

function renderBody({ chart, palette, format, seriesKeys, showLegend, handleClick }: BodyArgs) {
  switch (chart.type) {
    case 'line':
    case 'area':
      return <TimeSeries {...{ chart, palette, format, showLegend }} />
    case 'bar':
    case 'histogram':
      return <VerticalBars {...{ chart, palette, format, handleClick }} />
    case 'horizontal_bar':
    case 'geographic':
      return <HorizontalBars {...{ chart, palette, format, handleClick }} />
    case 'stacked_bar':
      return <Stacked {...{ chart, palette, format, seriesKeys }} />
    case 'pareto':
      return <Pareto {...{ chart, palette, handleClick }} />
    case 'donut':
      return <Donut {...{ chart, palette, format, handleClick }} />
    case 'scatter':
      return <ScatterPlot {...{ chart, palette }} />
    case 'box':
      return <BoxPlot {...{ chart, palette, format }} />
    case 'heatmap':
      return <Heatmap {...{ chart, palette, format }} />
    case 'correlation_matrix':
      return <Matrix {...{ chart, palette }} />
    default:
      return <VerticalBars {...{ chart, palette, format, handleClick }} />
  }
}

/* --- individual forms ----------------------------------------------------- */

function TimeSeries({ chart, palette, format, showLegend }: {
  chart: Chart; palette: Palette; format: (v: number | string | null) => string; showLegend: boolean
}) {
  const Comp = chart.type === 'area' ? AreaChart : LineChart
  return (
    <ResponsiveContainer width="100%" height="100%">
      <Comp data={chart.data} margin={MARGIN}>
        <defs>
          <linearGradient id={`fill-${chart.id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={palette.series[0]} stopOpacity={0.28} />
            <stop offset="100%" stopColor={palette.series[0]} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke={palette.grid} />
        <XAxis dataKey={chart.x_key} tick={AXIS_STYLE} tickLine={false} axisLine={{ stroke: palette.axis }}
          minTickGap={24} />
        <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} width={56}
          tickFormatter={(v) => compact(v as number, chart.currency_symbol)} />
        <Tooltip
          cursor={{ stroke: palette.axis, strokeWidth: 1 }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipBox
                title={String(label)}
                rows={[
                  { label: chart.series[0]?.label ?? 'Value',
                    value: format(payload[0].value as number), color: palette.series[0] },
                  ...(payload[0].payload?.records !== undefined
                    ? [{ label: 'Records', value: String(payload[0].payload.records) }] : []),
                ]}
              />
            ) : null}
        />
        {showLegend && <Legend {...legendProps(palette)} />}
        {chart.type === 'area' ? (
          <Area isAnimationActive={false} type="monotone" dataKey="value" name={chart.series[0]?.label} stroke={palette.series[0]}
            strokeWidth={2} fill={`url(#fill-${chart.id})`} dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: palette.surface }} />
        ) : (
          <Line isAnimationActive={false} type="monotone" dataKey="value" name={chart.series[0]?.label} stroke={palette.series[0]}
            strokeWidth={2} dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: palette.surface }} />
        )}
      </Comp>
    </ResponsiveContainer>
  )
}

function VerticalBars({ chart, palette, format, handleClick }: {
  chart: Chart; palette: Palette; format: (v: number | string | null) => string
  handleClick: (name: unknown) => void
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={chart.data} margin={MARGIN}>
        <CartesianGrid vertical={false} stroke={palette.grid} />
        {/* With many bars, labelling every one turns the axis into a smear. */}
        <XAxis dataKey={chart.x_key} tick={AXIS_STYLE} tickLine={false}
          axisLine={{ stroke: palette.axis }}
          interval={chart.data.length > 12 ? Math.ceil(chart.data.length / 8) - 1 : 0}
          angle={chart.data.length > 6 ? -22 : 0}
          textAnchor={chart.data.length > 6 ? 'end' : 'middle'} height={chart.data.length > 6 ? 56 : 28} />
        <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} width={56}
          tickFormatter={(v) => compact(v as number, chart.currency_symbol)} />
        <Tooltip
          cursor={{ fill: palette.grid, fillOpacity: 0.4 }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipBox
                title={String(label)}
                rows={[
                  { label: chart.series[0]?.label ?? 'Value',
                    value: format(payload[0].value as number), color: palette.series[0] },
                  ...(payload[0].payload?.share != null
                    ? [{ label: 'Share', value: `${Number(payload[0].payload.share).toFixed(1)}%` }] : []),
                  ...(payload[0].payload?.records != null
                    ? [{ label: 'Records', value: Number(payload[0].payload.records).toLocaleString() }] : []),
                ]}
              />
            ) : null}
        />
        <Bar isAnimationActive={false} dataKey="value" name={chart.series[0]?.label} fill={palette.series[0]}
          radius={[4, 4, 0, 0]} maxBarSize={46}
          onClick={(entry: { name?: unknown }) => handleClick(entry?.name)}
          cursor={chart.drilldown?.dimension ? 'pointer' : 'default'} />
      </BarChart>
    </ResponsiveContainer>
  )
}

function HorizontalBars({ chart, palette, format, handleClick }: {
  chart: Chart; palette: Palette; format: (v: number | string | null) => string
  handleClick: (name: unknown) => void
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={chart.data} layout="vertical" margin={{ ...MARGIN, left: 12 }}>
        <CartesianGrid horizontal={false} stroke={palette.grid} />
        <XAxis type="number" tick={AXIS_STYLE} tickLine={false} axisLine={false}
          tickFormatter={(v) => compact(v as number, chart.currency_symbol)} />
        <YAxis type="category" dataKey={chart.x_key} tick={AXIS_STYLE} tickLine={false}
          axisLine={{ stroke: palette.axis }} width={110} />
        <Tooltip
          cursor={{ fill: palette.grid, fillOpacity: 0.4 }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipBox
                title={String(label)}
                rows={[
                  { label: chart.series[0]?.label ?? 'Value',
                    value: format(payload[0].value as number), color: palette.series[0] },
                  ...(payload[0].payload?.share != null
                    ? [{ label: 'Share', value: `${Number(payload[0].payload.share).toFixed(1)}%` }] : []),
                ]}
              />
            ) : null}
        />
        <Bar isAnimationActive={false} dataKey="value" name={chart.series[0]?.label} fill={palette.series[0]}
          radius={[0, 4, 4, 0]} maxBarSize={22}
          onClick={(entry: { name?: unknown }) => handleClick(entry?.name)}
          cursor={chart.drilldown?.dimension ? 'pointer' : 'default'} />
      </BarChart>
    </ResponsiveContainer>
  )
}

function Stacked({ chart, palette, format, seriesKeys }: {
  chart: Chart; palette: Palette; format: (v: number | string | null) => string; seriesKeys: string[]
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={chart.data} margin={MARGIN}>
        <CartesianGrid vertical={false} stroke={palette.grid} />
        <XAxis dataKey={chart.x_key} tick={AXIS_STYLE} tickLine={false}
          axisLine={{ stroke: palette.axis }} minTickGap={20} />
        <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} width={56}
          tickFormatter={(v) => compact(v as number, chart.currency_symbol)} />
        <Tooltip
          cursor={{ fill: palette.grid, fillOpacity: 0.4 }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipBox
                title={String(label)}
                rows={payload.map((entry) => ({
                  label: String(entry.name),
                  value: format(entry.value as number),
                  color: entry.color,
                }))}
              />
            ) : null}
        />
        <Legend {...legendProps(palette)} />
        {seriesKeys.map((key, index) => (
          <Bar isAnimationActive={false} key={key} dataKey={key} name={key} stackId="stack"
            fill={palette.series[index % palette.series.length]}
            stroke={palette.surface} strokeWidth={2} maxBarSize={44} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

function Pareto({ chart, palette, handleClick }: {
  chart: Chart; palette: Palette; handleClick: (name: unknown) => void
}) {
  // Share and cumulative share are both percentages of the same total, so they
  // share one axis; a second y-scale would invite a false visual comparison.
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={chart.data} margin={MARGIN}>
        <CartesianGrid vertical={false} stroke={palette.grid} />
        <XAxis dataKey={chart.x_key} tick={AXIS_STYLE} tickLine={false}
          axisLine={{ stroke: palette.axis }} interval={0}
          angle={chart.data.length > 6 ? -22 : 0}
          textAnchor={chart.data.length > 6 ? 'end' : 'middle'}
          height={chart.data.length > 6 ? 52 : 28} />
        <YAxis domain={[0, 100]} tick={AXIS_STYLE} tickLine={false} axisLine={false} width={44}
          tickFormatter={(v) => `${v}%`} />
        <Tooltip
          cursor={{ fill: palette.grid, fillOpacity: 0.4 }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipBox
                title={String(label)}
                rows={[
                  { label: 'Share', value: `${Number(payload[0]?.payload?.share ?? 0).toFixed(1)}%`,
                    color: palette.series[0] },
                  { label: 'Cumulative', value: `${Number(payload[0]?.payload?.cumulative ?? 0).toFixed(1)}%`,
                    color: palette.series[1] },
                  { label: 'Value', value: formatValue(payload[0]?.payload?.value as number,
                    chart.measure_format ?? '', chart.currency_symbol) },
                ]}
              />
            ) : null}
        />
        <Legend {...legendProps(palette)} />
        <Bar isAnimationActive={false} dataKey="share" name={chart.series[0]?.label ?? 'Share %'} fill={palette.series[0]}
          radius={[4, 4, 0, 0]} maxBarSize={40}
          onClick={(entry: { name?: unknown }) => handleClick(entry?.name)}
          cursor={chart.drilldown?.dimension ? 'pointer' : 'default'} />
        <Line isAnimationActive={false} type="monotone" dataKey="cumulative" name={chart.series[1]?.label ?? 'Cumulative %'}
          stroke={palette.series[1]} strokeWidth={2}
          dot={{ r: 3, strokeWidth: 2, stroke: palette.surface, fill: palette.series[1] }} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

function Donut({ chart, palette, format, handleClick }: {
  chart: Chart; palette: Palette; format: (v: number | string | null) => string
  handleClick: (name: unknown) => void
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart margin={MARGIN}>
        <Tooltip
          content={({ active, payload }) =>
            active && payload?.length ? (
              <TooltipBox
                title={String(payload[0].name)}
                rows={[
                  { label: chart.series[0]?.label ?? 'Value',
                    value: format(payload[0].value as number), color: payload[0].payload?.fill },
                  { label: 'Share', value: `${Number(payload[0].payload?.share ?? 0).toFixed(1)}%` },
                ]}
              />
            ) : null}
        />
        <Legend {...legendProps(palette)} />
        <Pie isAnimationActive={false} data={chart.data} dataKey="value" nameKey={chart.x_key} innerRadius="52%"
          outerRadius="80%" paddingAngle={2} strokeWidth={2} stroke={palette.surface}
          onClick={(entry: { name?: unknown }) => handleClick(entry?.name)}>
          {chart.data.map((row, index) => (
            <Cell key={String(row[chart.x_key])} fill={palette.series[index % palette.series.length]} />
          ))}
        </Pie>
      </PieChart>
    </ResponsiveContainer>
  )
}

function ScatterPlot({ chart, palette }: { chart: Chart; palette: Palette }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ScatterChart margin={{ ...MARGIN, bottom: 20 }}>
        <CartesianGrid stroke={palette.grid} />
        <XAxis type="number" dataKey="x" name={chart.x_label} tick={AXIS_STYLE} tickLine={false}
          axisLine={{ stroke: palette.axis }}
          tickFormatter={(v) => compact(v as number)}
          label={{ value: chart.x_label, position: 'insideBottom', offset: -12,
            style: { fontSize: 11, fill: palette.muted } }} />
        <YAxis type="number" dataKey="y" name={chart.y_label} tick={AXIS_STYLE} tickLine={false}
          axisLine={false} width={56} tickFormatter={(v) => compact(v as number)} />
        <ZAxis range={[36, 36]} />
        <Tooltip
          cursor={{ strokeDasharray: '3 3', stroke: palette.axis }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <TooltipBox
                title="Record"
                rows={[
                  { label: chart.x_label ?? 'x', value: compact(payload[0].value as number) },
                  { label: chart.y_label ?? 'y', value: compact(payload[1]?.value as number) },
                ]}
              />
            ) : null}
        />
        <Scatter isAnimationActive={false} data={chart.data} fill={palette.series[0]} fillOpacity={0.55} shape="circle" />
      </ScatterChart>
    </ResponsiveContainer>
  )
}

function BoxPlot({ chart, palette, format }: {
  chart: Chart; palette: Palette; format: (v: number | string | null) => string
}) {
  const rows = chart.data as unknown as {
    name: string; whisker_low: number; q1: number; median: number; q3: number
    whisker_high: number; outlier_count: number; records: number
  }[]
  const values = rows.flatMap((r) => [r.whisker_low, r.whisker_high])
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const scale = (v: number) => ((v - min) / span) * 100

  return (
    <div className="flex h-full flex-col justify-center gap-2.5 px-3">
      {rows.map((row) => (
        <div key={row.name} className="flex items-center gap-3 text-xs">
          <span className="w-24 shrink-0 truncate text-subtle" title={row.name}>{row.name}</span>
          <div className="relative h-5 flex-1 rounded bg-page">
            {/* whiskers */}
            <div className="absolute top-1/2 h-px -translate-y-1/2"
              style={{
                left: `${scale(row.whisker_low)}%`,
                width: `${scale(row.whisker_high) - scale(row.whisker_low)}%`,
                background: palette.axis,
              }} />
            {/* interquartile box */}
            <div className="absolute top-1/2 h-4 -translate-y-1/2 rounded"
              style={{
                left: `${scale(row.q1)}%`,
                width: `${Math.max(scale(row.q3) - scale(row.q1), 0.6)}%`,
                background: palette.series[0], opacity: 0.85,
              }}
              title={`Q1 ${format(row.q1)} – Q3 ${format(row.q3)}`} />
            {/* median */}
            <div className="absolute top-1/2 h-4 w-0.5 -translate-y-1/2"
              style={{ left: `${scale(row.median)}%`, background: palette.surface }} />
          </div>
          <span className="tnum w-20 shrink-0 text-right text-muted">{format(row.median)}</span>
        </div>
      ))}
      <p className="px-1 pt-1 text-[11px] text-muted">
        Bar spans the interquartile range; the light line is the median and the thin rule marks the
        whiskers.
      </p>
    </div>
  )
}

function Heatmap({ chart, palette, format }: {
  chart: Chart; palette: Palette; format: (v: number | string | null) => string
}) {
  const columns = chart.column_values ?? []
  const values = chart.data.flatMap((row) =>
    columns.map((c) => Number(row[c] ?? 0)).filter((v) => Number.isFinite(v)))
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 1)
  const span = max - min || 1

  return (
    <div className="h-full overflow-auto px-2">
      <table className="w-full border-separate" style={{ borderSpacing: 2 }}>
        <thead>
          <tr>
            <th className="sticky left-0 bg-surface" />
            {columns.map((column) => (
              <th key={column} className="px-1 pb-1 text-[10px] font-medium text-muted">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {chart.data.map((row) => (
            <tr key={String(row[chart.x_key])}>
              <th className="sticky left-0 bg-surface pr-2 text-right text-[11px] font-medium text-subtle">
                {String(row[chart.x_key])}
              </th>
              {columns.map((column) => {
                const value = Number(row[column] ?? 0)
                const ratio = (value - min) / span
                return (
                  <td key={column} className="rounded p-1 text-center text-[10px]"
                    style={{
                      background: sequentialColor(palette, ratio),
                      color: ratio > 0.55 ? '#fff' : palette.ink,
                    }}
                    title={`${String(row[chart.x_key])} · ${column}: ${format(value)}`}>
                    {format(value)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Matrix({ chart, palette }: { chart: Chart; palette: Palette }) {
  const columns = chart.matrix_columns ?? []
  return (
    <div className="h-full overflow-auto px-2">
      <table className="w-full border-separate" style={{ borderSpacing: 2 }}>
        <thead>
          <tr>
            <th className="sticky left-0 bg-surface" />
            {columns.map((column) => (
              <th key={column} className="px-1 pb-1 text-[10px] font-medium text-muted">
                <span className="block max-w-[64px] truncate" title={column}>{column}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {chart.data.map((row) => (
            <tr key={String(row.column)}>
              <th className="sticky left-0 bg-surface pr-2 text-right text-[11px] font-medium text-subtle">
                <span className="block max-w-[110px] truncate" title={String(row.column)}>
                  {String(row.column)}
                </span>
              </th>
              {columns.map((column) => {
                const value = row[column]
                const numeric = typeof value === 'number' ? value : null
                return (
                  <td key={column} className="rounded p-1 text-center text-[10px] tnum"
                    style={{
                      background: numeric === null ? palette.grid : divergingColor(palette, numeric),
                      color: numeric !== null && Math.abs(numeric) > 0.6 ? '#fff' : palette.ink,
                    }}
                    title={`${String(row.column)} vs ${column}: ${numeric?.toFixed(2) ?? 'n/a'}`}>
                    {numeric === null ? '–' : numeric.toFixed(2)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-1 pt-2 text-[11px] text-muted">
        Blue is a negative correlation, red positive and grey none. Correlation is association, not
        causation.
      </p>
    </div>
  )
}
