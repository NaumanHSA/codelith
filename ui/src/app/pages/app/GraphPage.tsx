import { Link, useParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import { PageHead, Panel } from '../../components/ui'
import KnowledgeGraph from '../../components/projects/KnowledgeGraph'

/* ------------------------------------------------------------------ *
 * The knowledge graph, given the screen.
 *
 * The same component as the panel on the codebase page, with the height
 * it needs. Forty cards in a 640px well is a graph you pan around
 * rather than one you read, and the fix for that is not smaller cards.
 * ------------------------------------------------------------------ */

export default function GraphPage() {
  const { projectId } = useParams()
  const id = Number(projectId)

  const project = useAsync(() => api.project(id), [id])
  const modules = useAsync(sig => api.modules(id, sig), [id])
  const files = useAsync(sig => api.files(id, sig), [id])

  if (!Number.isFinite(id)) return <ErrorState message="Not a project." />

  return (
    <div className="space-y-3">
      <PageHead
        index="05"
        title="Knowledge graph"
        sub={
          project.data ? (
            <Link to={`/app/projects/${id}`} className="text-hot-ink hover:underline">
              {project.data.name}
            </Link>
          ) : null
        }
      />

      {modules.loading && <SkeletonPanel rows={8} />}
      {modules.error && <ErrorState message={modules.error} />}

      {modules.data && !modules.data.available && (
        <EmptyState
          title="Nothing read yet"
          body="Analyse this codebase and its shape will be here."
          action={
            <Link to={`/app/projects/${id}`} className="text-hot-ink hover:underline">
              Back to the codebase
            </Link>
          }
        />
      )}

      {modules.data?.available && project.data && (
        <Panel title="Knowledge base">
          <KnowledgeGraph
            title={project.data.name}
            modules={modules.data}
            files={files.data}
            projectId={id}
            fullscreen
          />
        </Panel>
      )}
    </div>
  )
}
