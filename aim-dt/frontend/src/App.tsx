import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, SessionLoader } from './auth'
import { Layout } from './components/Layout'
import { AdminPage } from './pages/AdminPage'
import { AnalysisPage } from './pages/AnalysisPage'
import { ChangePasswordPage } from './pages/ChangePasswordPage'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'

export function App() {
  return (
    <SessionLoader>
      {(session) =>
        session.user && session.user.must_change_password ? (
          <ChangePasswordPage />
        ) : session.user ? (
          <AuthProvider user={session.user}>
            <Routes>
              <Route element={<Layout />}>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/analyses/:analysisId" element={<AnalysisPage />} />
                <Route path="/admin" element={session.user.role === 'admin' ? <AdminPage /> : <Navigate to="/" />} />
                <Route path="*" element={<Navigate to="/" />} />
              </Route>
            </Routes>
          </AuthProvider>
        ) : (
          <LoginPage />
        )
      }
    </SessionLoader>
  )
}
