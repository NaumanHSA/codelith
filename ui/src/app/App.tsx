import { type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { RunningJobsProvider } from './running-jobs'
import { ErrorBoundary } from './components/ErrorBoundary'
import Shell from './components/layout/Shell'

import SignInPage from './pages/auth/SignInPage'
import RegisterPage from './pages/auth/RegisterPage'

function BootScreen() {
  return (
    <div className="flex h-screen items-center justify-center bg-paper">
      <div className="flex items-center gap-2.5">
        <span className="anim-spin block size-3 rounded-full border-2 border-hot border-t-transparent" />
        <span className="text-[13px] text-ink-dim">Restoring your session…</span>
      </div>
    </div>
  )
}

/** Everything under /app requires a session. */
function RequireAuth({ children }: { children: ReactNode }) {
  const { user, booting } = useAuth()
  const location = useLocation()
  if (booting) return <BootScreen />
  if (!user) return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

/** Signed-in users should not sit on the sign-in form. */
function RedirectIfAuthed({ children }: { children: ReactNode }) {
  const { user, booting } = useAuth()
  if (booting) return <BootScreen />
  if (user) return <Navigate to="/app" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <RunningJobsProvider>
            <Routes>
              {/* There is no landing page. The application opens on the sign-in
                  form and then the studio, so the root is just the way in —
                  RequireAuth below sends a visitor without a session to /sign-in,
                  and one with a session straight to Home. */}
              <Route path="/" element={<Navigate to="/app" replace />} />
              <Route
                path="/sign-in"
                element={
                  <RedirectIfAuthed>
                    <SignInPage />
                  </RedirectIfAuthed>
                }
              />
              <Route
                path="/register"
                element={
                  <RedirectIfAuthed>
                    <RegisterPage />
                  </RedirectIfAuthed>
                }
              />

              {/* The studio. The shell keeps a tab per codebase, conversation and list,
                  and renders the pages itself (routes.tsx), one set per tab. */}
              <Route
                path="/app/*"
                element={
                  <RequireAuth>
                    <Shell />
                  </RequireAuth>
                }
              />

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </RunningJobsProvider>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
