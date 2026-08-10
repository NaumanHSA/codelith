import { lazy, Suspense, type ReactNode } from 'react'
import {
  BrowserRouter, Navigate, Route, Routes, useLocation,
} from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { RunningJobsProvider } from './running-jobs'
import { ErrorBoundary } from './components/ErrorBoundary'
import { SkeletonPanel } from './components/States'
import Shell from './components/layout/Shell'

import LandingPage from './pages/LandingPage'
import SignInPage from './pages/auth/SignInPage'
import RegisterPage from './pages/auth/RegisterPage'
import DashboardPage from './pages/app/DashboardPage'
import ProjectsPage from './pages/app/ProjectsPage'
import ProjectDetailPage from './pages/app/ProjectDetailPage'
import JobProgressPage from './pages/app/JobProgressPage'
import DocumentsPage from './pages/app/DocumentsPage'
import JobsPage from './pages/app/JobsPage'
import ComposePage from './pages/app/ComposePage'
import SettingsPage from './pages/app/SettingsPage'
import QualityPage from './pages/app/QualityPage'

// The Markdown stack is ~350 kB. Load it only when something is read.
const DocumentReaderPage = lazy(() => import('./pages/app/DocumentReaderPage'))
const DocsSitePage = lazy(() => import('./pages/app/DocsSitePage'))
const ChatPage = lazy(() => import('./pages/app/ChatPage'))

function BootScreen() {
  return (
    <div className="bp-grid flex h-screen items-center justify-center">
      <div className="flex items-center gap-2.5">
        <span className="anim-spin block size-3 rounded-full border-2 border-hot border-t-transparent" />
        <span className="tag text-ink-dim">restoring session</span>
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
              <Route path="/" element={<LandingPage />} />
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

              <Route
                path="/app"
                element={
                  <RequireAuth>
                    <Shell />
                  </RequireAuth>
                }
              >
                <Route index element={<DashboardPage />} />
                <Route path="projects" element={<ProjectsPage />} />
                <Route path="projects/:projectId" element={<ProjectDetailPage />} />
                <Route path="projects/:projectId/compose" element={<ComposePage />} />
                <Route path="projects/:projectId/jobs/:jobId" element={<JobProgressPage />} />
                <Route path="jobs" element={<JobsPage />} />
                <Route path="chat" element={<ChatPage />} />
                <Route path="projects/:projectId/quality" element={<QualityPage />} />
                {/*
                  The documentation site. Section and page are optional: no
                  section shows the coverage view, which is the whole map at a
                  glance rather than a 404.
                */}
                <Route
                  path="projects/:projectId/docs/:sectionSlug?/:pageSlug?"
                  element={
                    <Suspense
                      fallback={
                        <div className="mx-auto max-w-[1100px] p-5">
                          <SkeletonPanel rows={8} />
                        </div>
                      }
                    >
                      <DocsSitePage />
                    </Suspense>
                  }
                />
                <Route path="documents" element={<DocumentsPage />} />
                <Route
                  path="documents/:documentId"
                  element={
                    <Suspense
                      fallback={
                        <div className="mx-auto max-w-[1080px] p-5">
                          <SkeletonPanel rows={8} />
                        </div>
                      }
                    >
                      <DocumentReaderPage />
                    </Suspense>
                  }
                />
                <Route path="settings" element={<SettingsPage />} />
              </Route>

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </RunningJobsProvider>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
