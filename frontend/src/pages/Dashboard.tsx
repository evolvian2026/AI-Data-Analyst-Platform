import { useState } from 'react'
import { useAnalysis } from '../context/AnalysisContext'
import { useNavigate } from 'react-router-dom'
import { ChartRenderer } from '../components/charts/ChartRenderer'
import { FilterBar } from '../components/FilterBar'
import { KpiCard } from '../components/KpiCard'
import { DrilldownPanel } from '../components/DrilldownPanel'
import { Empty, SectionHeading } from '../components/Primitives'

export function DashboardPage() {
  const { sessionId, view, analysis, filters, setFilters, filtering } = useAnalysis()
  const navigate = useNavigate()
  const [drilldown, setDrilldown] = useState<{ dimension: string; value: string } | null>(null)

  if (!view || !analysis) return null

  return (
    <div className="space-y-6">
      <FilterBar definitions={analysis.filters} active={filters} onChange={setFilters}
        busy={filtering} summary={view.filter_summary ?? null} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {view.kpis.primary.slice(0, 4).map((kpi) => (
          <KpiCard key={kpi.key} kpi={kpi} compactCard />
        ))}
      </div>

      <SectionHeading
        title="Dashboard"
        description="Each chart answers a different analytical question - click a bar or slice to drill into it."
      />

      {view.charts.length === 0 ? (
        <Empty title="No charts for this selection"
          description="The current filters leave too few records to plot. Clear a filter to see the charts again." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {view.charts.map((chart, index) => (
            <div key={chart.id}
              className={`min-w-0 ${index === 0 && chart.type !== 'donut' ? 'lg:col-span-2' : ''}`}>
              <ChartRenderer chart={chart} height={index === 0 ? 300 : 250}
                onDrilldown={(dimension, value) => setDrilldown({ dimension, value })} />
            </div>
          ))}
        </div>
      )}

      {drilldown && (
        <DrilldownPanel sessionId={sessionId} dimension={drilldown.dimension}
          value={drilldown.value} filters={filters} onClose={() => setDrilldown(null)}
          onAsk={(question) => navigate(`/app/${sessionId}/ask?q=${encodeURIComponent(question)}`)} />
      )}
    </div>
  )
}
