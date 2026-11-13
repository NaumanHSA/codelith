import { api } from '../../lib/api'
import { formatBytes } from '../../lib/format'
import { useAsync } from '../../lib/hooks'
import { Icon } from '../../lib/icons'
import { ErrorState, SkeletonPanel } from '../States'

/* ------------------------------------------------------------------ *
 * What each reading's kept files take on this machine. Content is
 * stored once and shared, so a codebase's figure counts what it uses,
 * and the codebases together can add up to more than the whole.
 * ------------------------------------------------------------------ */

export function KeptSource() {
  const data = useAsync(s => api.storage(s), [])
  if (data.loading) return <SkeletonPanel rows={3} />
  if (data.error) return <ErrorState message={data.error} onRetry={data.reload} compact />
  const d = data.data
  if (!d) return null
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-rule bg-panel p-5">
      <div className="flex flex-wrap items-start gap-3">
        <Icon name="hard-drive" size={18} className="mt-0.5 text-ink-dim" />
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold text-ink">Kept source</h2>
          <p className="mt-1 max-w-[75ch] text-[12.5px] leading-snug text-ink-mid">
            Every reading keeps its files, each distinct content stored once and compressed, so a re-reading costs only
            what changed.{' '}
            {d.keep_readings > 0
              ? `Only the newest ${d.keep_readings} reading(s) of each codebase keep theirs (KEEP_SOURCE_READINGS).`
              : 'Every reading keeps its files; set KEEP_SOURCE_READINGS to keep only the newest few.'}{' '}
            Deleting a codebase frees what only it used.
          </p>
        </div>
        <div className="text-right">
          <div className="font-head text-[20px] font-semibold text-ink">{formatBytes(d.stored_bytes)}</div>
          <div className="text-[12px] text-ink-dim">
            {d.blobs.toLocaleString()} contents, {formatBytes(d.bytes)} uncompressed
          </div>
        </div>
      </div>
      {d.codebases.length > 0 && (
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Codebase</th>
                <th className="text-right">Readings with files</th>
                <th className="text-right">Contents</th>
                <th className="text-right">Stored</th>
              </tr>
            </thead>
            <tbody>
              {d.codebases.map(c => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td className="text-right font-mono">{c.readings_with_files}</td>
                  <td className="text-right font-mono">{c.blobs.toLocaleString()}</td>
                  <td className="text-right font-mono">{formatBytes(c.stored_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
