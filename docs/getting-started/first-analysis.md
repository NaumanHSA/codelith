# Your first analysis

Analysis is the thing you run first and the thing everything else reads. This page is
what happens when you do.

## Point it at something

Three kinds of source, and analysis treats them identically once they are on disk:

- **A Git repository.** Public or private, any branch. Shallow-cloned into `./repos/`
  and removed when the job ends.
- **A folder.** Read where it sits. Never copied, and never deleted.
- **An archive.** A zip or tarball, uploaded through the studio.

From the studio: **Codebases → Add a codebase**. From the command line:

```bash
codelith analyse https://github.com/NaumanHSA/watchtower.git
codelith analyse .
```

## What you get

A **knowledge base**, keyed by the commit SHA it read. Analysing the same commit twice
reuses the first reading unless you force it; analysing a new commit builds a second
one alongside, which is what makes [What changed](../apps.md#what-changed) possible.

Watchtower, a small FastAPI service, produces roughly this:

| | |
|---|---|
| Modules | 14, each with a role and a paragraph of prose |
| Entities | 150 — routes, entrypoints, env vars, datastores |
| Chunks | 324, embedded for retrieval |
| Symbols | 674, with file and line |
| Imports | 101 edges |
| Calls | 241 edges |
| Narratives | 12 topics, each with the modules it was written from |

## How long it takes

Most of it is model calls, so it depends on your models rather than on Codelith.

The stages that cost are module summarising (one call per module, up to
`ANALYSIS_MAX_SUMMARISED_MODULES`, six at a time), architecture synthesis (one large
call), and narrative writing (one per topic, twelve by default). Parsing, graph
building and embedding are fast by comparison.

For scale: Watchtower's 67 analysable files take a couple of minutes against a local
1.2B model for the fast tier and a hosted model for quality. A 400-file repository
takes several.

!!! note "Big repositories stop summarising at 40 modules"
    `ANALYSIS_MAX_SUMMARISED_MODULES` defaults to **40**. A repository with more modules
    than that gets the largest ones summarised and the rest left with no prose — which
    is why a 65-module project shows 40 summaries.

    Raise it if you want full coverage. It costs one model call per extra module.

## Watching it

The studio shows each stage as it runs, with the name the pipeline uses internally, so
what you see on screen matches what you would find in a trace. From the CLI, `codelith
analyse` follows the job and narrates the same stages.

If tracing is on, every stage writes its inputs and outputs to `./runs/{job_id}/`.
That is the place to look when an answer seems wrong: it shows what the model was
actually given.

## When it is done

The codebase page opens on the knowledge graph: the project at the centre, its
components around it, and modules, files and symbols underneath as you open them.

From there:

- **[Ask the code](../apps.md#ask-the-code)** — questions answered from the analysis, with
  every citation checked.
- **[Documentation](../apps.md#documentation)** — pages written from the same reading.
- **[Source](../how-it-works/chunks-and-retrieval.md#reading-a-file-back)** — every file
  the reading covered, rebuilt from stored chunks.
- **[MCP](../mcp.md)** — the same knowledge base, inside your editor.

## Analysing it again

Analyse the same repository at a later commit and you get a second reading. Two
readings is what [What changed](../apps.md#what-changed) compares: modules that grew or
were rewritten, entities that came and went, and which written pages now describe code
that moved.

One reading is a photograph. Two are a difference.
