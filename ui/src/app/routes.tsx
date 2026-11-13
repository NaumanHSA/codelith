import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes, useParams, useSearchParams, type Location } from 'react-router-dom'
import { SkeletonPanel } from './components/States'

import HomePage from './pages/app/HomePage'
import ProjectsPage from './pages/app/ProjectsPage'
import ProjectDetailPage from './pages/app/ProjectDetailPage'
import JobProgressPage from './pages/app/JobProgressPage'
import DriftPage from './pages/app/DriftPage'
import QAPage from './pages/app/QAPage'
import HistoryPage from './pages/app/HistoryPage'
import DocumentationPage from './pages/app/DocumentationPage'
import JobsPage from './pages/app/JobsPage'
import PublishedPage from './pages/app/PublishedPage'
import SettingsPage from './pages/app/SettingsPage'

/* ------------------------------------------------------------------ *
 * Everything under /app, as one set of routes each tab renders with its
 * own location. A tab that is not showing keeps its page mounted where it
 * left it; see `components/layout/tabState.ts`.
 * ------------------------------------------------------------------ */

/** `/compose` was retired into the documentation site. `replace` so Back does not
 *  bounce the reader off the page they just landed on. */
function ComposeRedirect() {
  const { projectId } = useParams()
  return <Navigate to={`/app/projects/${projectId}/docs`} replace />
}

/** The knowledge graph lives at `/graph`. It was briefly `/atlas`, and the code page
 *  folded into it, so both of those land here, keeping the file and line they named. */
function GraphRedirect() {
  const { projectId } = useParams()
  const [params] = useSearchParams()
  const keep = new URLSearchParams()
  for (const k of ['file', 'line']) {
    const v = params.get(k)
    if (v) keep.set(k, v)
  }
  const q = keep.toString()
  return <Navigate to={`/app/projects/${projectId}/graph${q ? `?${q}` : ''}`} replace />
}

// three.js is ~600 kB. Only the knowledge graph pays for it.
const AtlasPage = lazy(() => import('./pages/app/AtlasPage'))

// The Markdown stack is ~350 kB. Load it only when something is read.
const DocumentReaderPage = lazy(() => import('./pages/app/DocumentReaderPage'))
const DocsSitePage = lazy(() => import('./pages/app/DocsSitePage'))
const ChatPage = lazy(() => import('./pages/app/ChatPage'))
const ReviewPage = lazy(() => import('./pages/app/ReviewPage'))

function Lazy({ rows, children }: { rows: number; children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="w-full px-6 py-5">
          <SkeletonPanel rows={rows} />
        </div>
      }
    >
      {children}
    </Suspense>
  )
}

export function AppRoutes({ location }: { location: Partial<Location> & { pathname: string } }) {
  return (
    <Routes location={location}>
      <Route index element={<HomePage />} />
      <Route path="projects" element={<ProjectsPage />} />
      <Route path="projects/:projectId" element={<ProjectDetailPage />} />
      {/* Compose was a second inventory of the same pages. The site page is where the
          docs already are, so writing happens there now. Kept as a redirect: links,
          bookmarks and the app registry all pointed here. */}
      <Route path="projects/:projectId/compose" element={<ComposeRedirect />} />
      <Route
        path="projects/:projectId/graph"
        element={
          <Lazy rows={10}>
            <AtlasPage />
          </Lazy>
        }
      />
      <Route path="projects/:projectId/atlas" element={<GraphRedirect />} />
      <Route path="projects/:projectId/code" element={<GraphRedirect />} />
      <Route path="projects/:projectId/drift" element={<DriftPage />} />
      <Route path="projects/:projectId/qa" element={<QAPage />} />
      <Route path="projects/:projectId/history" element={<HistoryPage />} />
      <Route
        path="projects/:projectId/review"
        element={
          <Lazy rows={8}>
            <ReviewPage />
          </Lazy>
        }
      />
      <Route path="projects/:projectId/jobs/:jobId" element={<JobProgressPage />} />
      <Route path="jobs" element={<JobsPage />} />
      <Route path="published" element={<PublishedPage />} />
      <Route
        path="chat"
        element={
          <Lazy rows={6}>
            <ChatPage />
          </Lazy>
        }
      />
      {/* The documentation site. Section and page are optional: no section shows the
          coverage view, which is the whole map at a glance rather than a 404. */}
      <Route
        path="projects/:projectId/docs/:sectionSlug?/:pageSlug?"
        element={
          <Lazy rows={8}>
            <DocsSitePage />
          </Lazy>
        }
      />
      <Route path="documentation" element={<DocumentationPage />} />
      {/* Former names and lists, all now parts of Documentation. */}
      <Route path="library" element={<Navigate to="/app/documentation" replace />} />
      <Route path="documents" element={<Navigate to="/app/documentation?tab=documents" replace />} />
      {/* The knowledge graph is per codebase; a bare link goes to the list. */}
      <Route path="atlas" element={<Navigate to="/app/projects" replace />} />
      <Route
        path="documents/:documentId"
        element={
          <Lazy rows={8}>
            <DocumentReaderPage />
          </Lazy>
        }
      />
      <Route path="settings" element={<SettingsPage />} />
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  )
}
