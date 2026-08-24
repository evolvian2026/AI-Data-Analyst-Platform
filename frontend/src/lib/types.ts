/** Shapes returned by the analytics API. */

export interface User {
  id: string
  email: string
  full_name: string
  organization: string
  created_at: string
}

export interface SessionSummary {
  id: string
  name: string
  original_filename: string
  file_size: number
  status: 'pending' | 'processing' | 'completed' | 'failed'
  error: string
  created_at: string
  updated_at: string
  workbook_meta: WorkbookMeta
  progress: Progress
  config: Record<string, unknown>
  file_deleted: boolean
}

export interface WorkbookMeta {
  filename?: string
  file_size?: number
  sheet_count?: number
  analyzable_sheet_count?: number
  sheet_names?: string[]
  total_rows?: number
  total_columns?: number
  total_cells?: number
  uploaded_at?: string
  sheets?: SheetInfo[]
}

export interface SheetInfo {
  name: string
  rows: number
  columns: number
  cells: number
  header_row: number
  empty_columns_removed: number
  empty_rows_removed: number
  duplicate_headers_renamed: string[]
  unnamed_headers: number
  is_analyzable: boolean
  reason: string
}

export interface ProgressStage {
  key: string
  label: string
  done: boolean
  active: boolean
}

export interface Progress {
  stages: ProgressStage[]
  completed: number
  total: number
  percent: number
  elapsed_seconds?: number
}

export type Confidence = 'high' | 'medium' | 'low'

export interface ColumnProfile {
  name: string
  position: number
  dtype: string
  semantic_type: string
  role: string
  count: number
  missing: number
  missing_pct: number
  unique: number
  unique_pct: number
  is_constant: boolean
  sample_values: string[]
  top_values: { value: string; count: number; pct: number }[]
  numeric_stats: Record<string, number>
  temporal_stats: Record<string, string | number>
  currency_symbol: string
  aggregation?: string
  additive?: boolean
  non_negative?: boolean
  derived_from?: string
  confidence: number
  notes: string[]
}

export interface Profile {
  row_count: number
  column_count: number
  sampled: boolean
  sample_rows: number
  columns: ColumnProfile[]
  roles: Record<string, string[]>
  currency_symbol: string
  derived_columns?: DerivedColumn[]
}

export interface DerivedColumn {
  column: string
  operation: string
  sources: string[]
  formula: string
  match_ratio: number
  narrative: string
}

export interface QualityIssue {
  id: string
  type: string
  column: string | null
  severity: 'critical' | 'high' | 'medium' | 'low'
  title: string
  detail: string
  impact: string
  affected_records: number
  affected_pct: number
  groups?: { canonical: string; variants: string[] }[]
  findings?: { column: string; excerpt: string; reason: string }[]
}

export interface Quality {
  score: number
  grade: string
  explanation: string
  components: Record<string, number>
  weights: Record<string, number>
  metrics: Record<string, number | string | string[] | Record<string, number>>
  issues: QualityIssue[]
  recommendations: string[]
  injection_findings: { column: string; excerpt: string; reason: string }[]
}

export interface Kpi {
  key: string
  label: string
  value: number | null
  formatted: string
  aggregation: string
  source_columns: string[]
  calculation: string
  math: { formula: string; substitution?: string; result?: string }
  records_used: number
  semantic_type: string
  secondary: Record<string, string | number>
  description: string
  derived: boolean
  change: { direction: 'up' | 'down'; pct: number } | null
  priority_components: Record<string, number>
  priority_score: number
}

export interface Evidence {
  metric?: string
  value?: number | string | null
  formatted_value?: string
  comparison?: { label?: string; from?: number; to?: number; change_pct?: number | null }
  source_columns?: string[]
  calculation?: string
  math?: { formula?: string; substitution?: string; result?: string }
  records_used?: number
  periods?: number
  statistics?: Record<string, number | string | null>
  aggregation?: Record<string, unknown>[]
  anomaly_id?: string
}

export interface Insight {
  id: string
  type: string
  type_label: string
  headline: string
  fact: string
  interpretation: string
  recommendation: string
  so_what: string
  confidence: Confidence
  confidence_reason: string
  evidence: Evidence
  priority: { score: number; components: Record<string, number> }
  next_questions: string[]
  chart_hint: Record<string, unknown> | null
  chart_id: string | null
  subject: string
  tags: string[]
  rank: number
}

export interface ChartSeries {
  key: string
  label: string
  type?: string
}

export interface Chart {
  id: string
  type: string
  title: string
  question: string
  reason: string
  columns: string[]
  calculation: string
  insight: string
  data: Record<string, string | number | null>[]
  x_key: string
  series: ChartSeries[]
  value_format: string
  currency_symbol: string
  drilldown: { type: string; dimension?: string; measure?: string | null } | null
  priority: number
  x_label?: string
  y_label?: string
  correlation?: number
  r_squared?: number
  mean?: number
  median?: number
  measure_format?: string
  matrix_columns?: string[]
  column_values?: string[]
  row_label?: string
  column_label?: string
}

export interface StoryCard {
  id: string
  section: string
  headline: string
  kpi: Kpi | null
  supporting_kpi?: { label: string; value: string; sub: string }
  chart_id: string | null
  explanation: string
  fact?: string
  so_what?: string
  evidence: Evidence
  confidence: Confidence
  confidence_reason?: string
  recommendation: string
  insight_ids: string[]
  type?: string
  type_label?: string
  priority_score?: number
  questions?: string[]
  recommendations?: Recommendation[]
  position: number
  total: number
}

export interface StorySection {
  key: string
  title: string
  purpose: string
  narrative: string
  insight_ids: string[]
  kpis: string[]
  questions?: string[]
  recommendations?: Recommendation[]
}

export interface Story {
  sections: StorySection[]
  cards: StoryCard[]
  card_count: number
  flow: { position: number; headline: string; section: string }[]
  audience?: string
  audiences?: Record<string, AudienceConfig>
  adapted_insights?: AdaptedInsight[]
  story_score?: StoryScore
}

export interface AudienceConfig {
  label: string
  depth: string
  description: string
}

export interface AdaptedInsight {
  id: string
  headline: string
  body: string
  recommendation: string
  confidence: Confidence
  type: string
  type_label: string
}

export interface Recommendation {
  id: string
  insight_id: string | null
  action: string
  priority: 'critical' | 'high' | 'medium' | 'low'
  priority_meaning: string
  rationale: string
  impact: string
  confidence: Confidence
  type: string
  type_label: string
  source_columns: string[]
  evidence: Evidence
  priority_score: number
}

export interface BriefingItem {
  insight_id: string
  headline: string
  detail: string
  confidence: Confidence
  type_label: string
}

export interface Briefing {
  status: 'Positive' | 'Neutral' | 'Concerning'
  status_reason: string
  wins: BriefingItem[]
  concerns: BriefingItem[]
  trends: BriefingItem[]
  opportunities: BriefingItem[]
  actions: { action: string; priority: string; impact: string; insight_id: string | null }[]
  key_numbers: { label: string; value: string; detail: string; derived: boolean }[]
  data_quality: { score: number | null; grade: string | null; headline: string }
  narrated?: AdaptedInsight[]
  reading_time_seconds: number
}

export interface StoryScore {
  score: number
  label: string
  components: Record<string, number>
  weights: Record<string, number>
  explanation: string
}

export interface AnomalyItem {
  id: string
  kind: 'record' | 'timeseries'
  column: string
  semantic_type: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  max_score: number
  headline: string
  method: string
  count?: number
  pct_of_records?: number
  period?: string
  deviation_pct?: number
  direction?: string
  bounds?: { lower: number | null; upper: number | null }
  examples?: Record<string, string | number | null>[]
  evidence: Record<string, unknown>
}

export interface Anomalies {
  total: number
  record_level: number
  timeseries_level: number
  affected_columns: string[]
  affected_records: number
  affected_pct: number
  highest_severity: string | null
  items: AnomalyItem[]
}

export interface Investigation {
  available: boolean
  reason?: string
  anomaly_id?: string
  measure?: string
  context?: string
  records_examined?: number
  baseline_records?: number
  contributions?: {
    dimension: string
    rows: { value: string; amount: number; formatted: string; share_pct: number; normal_share_pct: number; share_shift_pct: number }[]
    top_value: string
    top_share_pct: number
    top_shift_pct: number
    concentrated: boolean
    narrative: string
  }[]
  volume_vs_value?: Record<string, number | string | null>
  companion_measures?: { measure: string; shift_pct: number; narrative: string }[]
  top_records?: { identifier: string; value: number; formatted: string; share_pct: number | null }[]
  explanations?: string[]
  caveat?: string
  next_questions?: string[]
  anomaly?: AnomalyItem
}

export interface CorrelationPair {
  x: string
  y: string
  pearson_r: number
  pearson_p: number
  spearman_r: number
  r_squared: number
  observations: number
  strength: string
  significant: boolean
  derived_pair: boolean
  narrative: string
}

export interface Correlations {
  available: boolean
  reason?: string
  columns: string[]
  matrix: Record<string, string | number | null>[]
  pairs: CorrelationPair[]
  meaningful: CorrelationPair[]
  caveat: string
  derived_columns?: DerivedColumn[]
}

export interface SegmentGroup {
  group: string
  value: number | null
  formatted_value: string
  total: number | null
  formatted_total: string
  mean: number | null
  formatted_mean: string
  median: number | null
  count: number
  share_pct: number | null
  cv_pct: number | null
  growth_pct: number | null
}

export interface Segment {
  dimension: string
  measure: string
  semantic_type: string
  aggregation: string
  aggregation_label: string
  shares_valid: boolean
  groups: SegmentGroup[]
  group_count: number
  total: number | null
  formatted_total: string
  best: SegmentGroup | null
  worst: SegmentGroup | null
  fastest_growing: SegmentGroup | null
  fastest_declining: SegmentGroup | null
  most_variable: SegmentGroup | null
  highest_average: SegmentGroup | null
  spread_pct: number | null
  has_growth: boolean
}

export interface Concentration {
  dimension: string
  measure: string
  group_count: number
  total: number
  formatted_total: string
  top_group: string
  top_group_formatted: string
  top1_pct: number
  top3_pct: number
  top5_pct: number
  top10_pct: number
  groups_for_80pct: number
  coverage_pct: number
  hhi: number
  is_risk: boolean
  severity: string
  pareto: { group: string; value: number; share_pct: number; cumulative_pct: number }[]
  narrative: string
}

export interface TrendPoint {
  label: string
  iso: string
  value: number | null
  records: number
}

export interface Trend {
  measure: string
  aggregation: string
  aggregation_label: string
  time_column: string
  frequency: string
  unit: string
  points: TrendPoint[]
  classification: {
    direction: string
    slope: number | null
    slope_pct_per_period: number | null
    r_squared: number | null
    p_value: number | null
    confidence: string
    volatility_pct: number | null
    periods: number
  }
  decomposition?: {
    record_change_pct: number | null
    value_change_pct: number | null
    average_change_pct: number | null
    driver: string
    narrative: string
  }
  seasonality: {
    detected: boolean
    peak: string
    peak_deviation_pct: number
    trough: string
    trough_deviation_pct: number
    strength_pct: number
    cycles_observed: number
    profile: { cycle: string; average: number; deviation_pct: number }[]
  } | null
  runs: Record<string, { periods: number; from: string; to: string; change_pct: number | null }>
  sudden_changes: {
    period: string
    previous_period: string
    value: number
    previous_value: number
    change_pct: number
    direction: string
    typical_movement_pct: number
  }[]
  comparisons: {
    type: string
    label: string
    current_label: string
    previous_label: string
    current: number
    previous: number
    change: number
    change_pct: number | null
  }[]
  first_period: string
  last_period: string
  first_value: number
  last_value: number
  total_change_pct: number | null
  total: number
  formatted_total: string
}

export interface FilterOption {
  value: string
  count: number
}

export interface FilterDefinition {
  column: string
  type: 'multi_select' | 'date_range' | 'numeric_range'
  label: string
  options?: FilterOption[]
  min?: number | string
  max?: number | string
}

export interface ActiveFilter {
  column: string
  type: 'multi_select' | 'date_range' | 'numeric_range'
  values?: string[]
  min?: number
  max?: number
  from?: string
  to?: string
}

export interface Relationship {
  left: string
  right: string
  key: string
  overlap_values: number
  coverage_left_pct: number
  coverage_right_pct: number
  cardinality: string
  narrative: string
  join_ready: boolean
}

export interface Analysis {
  summary: string
  profile: Profile
  derived_columns: DerivedColumn[]
  ranked_measures: string[]
  time_column: string | null
  quality: Quality
  kpis: { primary: Kpi[]; all: Kpi[]; count: number; currency_symbol: string }
  statistics: {
    columns: Record<string, Record<string, number | Record<string, number>>>
    categorical: Record<string, { value: string; count: number; pct: number }[]>
  }
  distributions: {
    columns: {
      column: string
      semantic_type: string
      stats: Record<string, number | Record<string, number>>
      box: Record<string, number>
      histogram: { bin: string; start: number; end: number; count: number }[]
    }[]
    interpretations: { column: string; shape: string; skewness: number; gap_pct: number; narrative: string }[]
  }
  trends: Trend[]
  anomalies: Anomalies
  investigations: Investigation[]
  correlations: Correlations
  segments: Segment[]
  concentration: Concentration[]
  insights: Insight[]
  top_insights: Insight[]
  charts: Chart[]
  recommendations: Recommendation[]
  story: Story
  briefing: Briefing
  story_score: StoryScore
  filters: FilterDefinition[]
  next_questions: string[]
  audiences: Record<string, AudienceConfig>
  meta: WorkbookMeta
  sheets: SheetInfo[]
  active_sheet: string
  scope: string
  analyzable_sheets: string[]
  relationships: Relationship[]
  progress: Progress
  session: {
    id: string
    name: string
    notes: Record<string, string>
    bookmarks: string[]
    config: Record<string, unknown>
    file_deleted: boolean
  }
  filtered?: boolean
  filter_summary?: {
    records: number
    total_records: number
    pct_of_total: number
    filters: ActiveFilter[]
  }
}

export interface AskAnswer {
  question: string
  intent: string
  answer: string
  calculation: string
  table: Record<string, string | number | null>[]
  chart: Chart | null
  confidence: Confidence
  supported: boolean
  records_used: number
  caveat: string
  suggestions?: string[]
  plan: Record<string, unknown>
  applied_filter: { column: string; value: string; records: number } | null
  insight_ids?: string[]
  anomaly_id?: string
  next_questions?: string[]
}

export interface DrilldownResult {
  dimension: string
  value: string
  records: number
  share_of_records_pct: number
  metrics: {
    measure: string
    aggregation: string
    value: number
    formatted: string
    average: number
    formatted_average: string
    records: number
    share_pct: number | null
    vs_dataset_pct: number | null
  }[]
  breakdowns: {
    dimension: string
    measure: string
    rows: { name: string; value: number; formatted: string; share_pct: number | null }[]
  }[]
  trend: { points: { name: string; value: number; records: number }[]; measure: string } | null
  top_records: { identifier: string; value: number; formatted: string }[]
  related_anomalies: { id: string; headline: string; column: string; severity: string }[]
  available_analyses: {
    measures: string[]
    dimensions: string[]
    time: boolean
    identifiers: string[]
  }
}

export interface DataPage {
  columns: { name: string; semantic_type?: string; role?: string; aggregation?: string }[]
  rows: Record<string, string | number | null>[]
  total: number
  offset: number
  limit: number
}

export interface SampleDataset {
  key: string
  title: string
  description: string
  highlights: string[]
  filename: string
}

export interface SystemConfig {
  app_name: string
  environment: string
  max_upload_mb: number
  max_rows_analyzed: number
  max_charts: number
  max_primary_kpis: number
  file_retention_hours: number
  allow_registration: boolean
  accepted_formats: string[]
  pipeline_stages: { key: string; label: string }[]
  audiences: Record<string, AudienceConfig>
  ai: {
    configured_provider: string
    active_provider: string
    model: string | null
    raw_rows_shared: boolean
    narration_mode: string
  }
}
