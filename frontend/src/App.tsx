import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import { ThemeProvider } from './context/ThemeContext'
import { AnalysisProvider } from './context/AnalysisContext'
import { AnalysisLayout, AppShell } from './components/Layout'
import { Loading } from './components/Primitives'
import { LandingPage } from './pages/Landing'
import { SignInPage } from './pages/SignIn'
import { WorkspacePage } from './pages/Workspace'
import { ProcessingPage } from './pages/Processing'
import { OverviewPage } from './pages/Overview'
import { DataStoryPage } from './pages/DataStory'
import { DashboardPage } from './pages/Dashboard'
import { InsightsPage } from './pages/Insights'
import { AskPage } from './pages/Ask'
import { QualityPage } from './pages/Quality'
import { ExplorePage } from './pages/Explore'
import { ReportsPage } from './pages/Reports'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16">
        <Loading rows={2} label="Checking your session" />
      </div>
    )
  }
  return user ? <>{children}</> : <Navigate to="/signin" replace />
}

export function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Router>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/signin" element={<SignInPage />} />
            <Route element={<AppShell />}>
              <Route path="/app" element={<RequireAuth><WorkspacePage /></RequireAuth>} />
              <Route path="/app/:sessionId/processing"
                element={<RequireAuth><ProcessingPage /></RequireAuth>} />
              <Route path="/app/:sessionId"
                element={<RequireAuth><AnalysisProvider><AnalysisLayout /></AnalysisProvider></RequireAuth>}>
                <Route index element={<Navigate to="overview" replace />} />
                <Route path="overview" element={<OverviewPage />} />
                <Route path="story" element={<DataStoryPage />} />
                <Route path="dashboard" element={<DashboardPage />} />
                <Route path="insights" element={<InsightsPage />} />
                <Route path="ask" element={<AskPage />} />
                <Route path="quality" element={<QualityPage />} />
                <Route path="explore" element={<ExplorePage />} />
                <Route path="reports" element={<ReportsPage />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Router>
      </AuthProvider>
    </ThemeProvider>
  )
}
