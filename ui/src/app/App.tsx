import { lazy, Suspense, type ReactNode } from 'react'
import {
  BrowserRouter, Navigate, Route, Routes, useLocation, useParams,
} from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { RunningJobsProvider } from './running-jobs'
import { ErrorBoundary } from './components/ErrorBoundary'
import { SkeletonPanel } from './components/States'
import Shell from './components/layout/Shell'

import SignInPage from './pages/auth/SignInPage'
import RegisterPage from './pages/auth/RegisterPage'
import HomePage from './pages/app/HomePage'
import ProjectsPage from './pages/app/ProjectsPage'
import ProjectDetailPage from './pages/app/ProjectDetailPage'
import JobProgressPage from './pages/app/JobProgressPage'
import GraphPage from './pages/app/GraphPage'
import CodePage from './pages/app/CodePage'
import DriftPage from './pages/app/DriftPage'
import DocumentsPage from './pages/app/DocumentsPage'
import JobsPage from './pages/app/JobsPage'
import PublishedPage from './pages/app/PublishedPage'
import SettingsPage from './pages/app/SettingsPage'

/** `/compose` was retired into the documentation site. `replace` so Back does not
 *  bounce the reader off the page they just landed on. */
function ComposeRedirect() {
  const { projectId } = useParams()
  return <Navigate to={`/app/projects/${projectId}/docs`} replace />
}

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

              <Route
                path="/app"
                element={
                  <RequireAuth>
                    <Shell />
                  </RequireAuth>
                }
              >
                <Route index element={<HomePage />} />
                <Route path="projects" element={<ProjectsPage />} />
                <Route path="projects/:projectId" element={<ProjectDetailPage />} />
                {/* Compose was a second inventory of the same pages, with the
                    controls two screens below the fold. The site page is where
                    the docs already are, so writing happens there now. Kept as a
                    redirect: links, bookmarks and the app registry all pointed
                    here. */}
                <Route
                  path="projects/:projectId/compose"
                  element={<ComposeRedirect />}
                />
                <Route path="projects/:projectId/code" element={<CodePage />} />
                <Route path="projects/:projectId/graph" element={<GraphPage />} />
                <Route path="projects/:projectId/drift" element={<DriftPage />} />
                <Route path="projects/:projectId/jobs/:jobId" element={<JobProgressPage />} />
                <Route path="jobs" element={<JobsPage />} />
                <Route path="published" element={<PublishedPage />} />
                <Route path="chat" element={<ChatPage />} />
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
