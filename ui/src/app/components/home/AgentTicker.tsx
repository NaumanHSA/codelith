/* ------------------------------------------------------------------ *
 * Every agent that runs on this machine, scrolling past.
 *
 * From the landing page, and it earns its place here for the reason it
 * earned it there: the band above claims the work is done locally by a
 * lot of small agents, and a list of their names is the cheapest proof
 * of that a page can offer. It sits between the claim and the schematic
 * that shows the order they run in.
 *
 * The names are the agents' own `name` attributes, read out of the
 * source rather than remembered. The landing page's list had drifted —
 * it was written before the apps split and still carried the old
 * composition_* naming, and it had missed graph_builder, site_planner,
 * question_seeder, kb_loader, linker and reviser as they landed. That is
 * survivable on a marketing page and not inside the product, where the
 * count beside it is a claim about what the reader just installed.
 * ------------------------------------------------------------------ */

/** Analysis first, in the order the workflow runs them, then the documentation app. */
const AGENTS = [
  'repo_analyzer',
  'structured_extractor',
  'semantic_indexer',
  'module_summarizer',
  'architecture_synthesizer',
  'graph_builder',
  'narrative_writer',
  'site_planner',
  'question_seeder',
  'kb_persister',
  'kb_loader',
  'composition_strategy',
  'composition_planner',
  'composition_writer',
  'reviser',
  'linker',
  'diagram',
  'qa',
  'formatter',
  'publisher',
]

export default function AgentTicker() {
  return (
    <div className="mb-5 overflow-hidden border border-rule bg-term py-1.5">
      {/* Listed twice. The strip is translated by exactly half its width, so the
          second copy is under the cursor at the moment the first runs out. */}
      <div
        className="flex w-max gap-6 whitespace-nowrap"
        style={{ animation: 'ticker 38s linear infinite' }}
      >
        {[...AGENTS, ...AGENTS].map((a, i) => (
          <span key={i} className="tag flex items-center gap-2 text-term-dim">
            <span className="size-[4px] rotate-45 bg-hot" />
            {a}
          </span>
        ))}
      </div>
    </div>
  )
}
