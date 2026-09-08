# Analysis

One reading of a repository, once per commit SHA. It takes no document type and must
not — the moment analysis knows what you intend to do with it, the apps stop being
interchangeable.

The graph is a LangGraph `StateGraph` in `codelith/workflows/analysis_workflow.py`. Ten
stages, in order.

## The ten stages

### 1. `repo_analyzer`

Clones or opens the source, walks it, and parses every file a
[language provider](languages.md) claims. Produces the file list, the symbol spans, and
the raw material everything downstream reads.

Skips the directories nobody means to analyse — `.git`, `node_modules`, `.venv`,
`__pycache__`, `dist`, `build` — and files over 500 KB.

**Writes:** the parsed codebase, in memory. **Model calls:** none.

### 2. `structured_extractor`

Finds the facts that are true whether or not a model reads the code: routes,
entrypoints, environment variables, datastores, dependencies, config files, CLI
commands, scheduled tasks, external APIs, infra resources, test suites.

Some of this is pattern work in a language provider (a FastAPI decorator is a route);
some is manifest reading (`pyproject.toml`, `package.json`); some is a fast-tier model
call for the parts that need judgement.

**Writes:** `kb_entities`. **Model tier:** fast.

### 3. `graph_builder`

Turns the parsed symbols and imports into [the code graph](code-graph.md): six tables
of files, modules, packages, symbols, imports and calls.

**Writes:** `graph_*`. **Model calls:** none.

### 4. `semantic_indexer`

Splits the source into [chunks](chunks-and-retrieval.md) and embeds them. Code is split
on symbol boundaries where the provider gave spans, and on line windows where it did
not. Prose — docstrings, markdown — is chunked separately and labelled, so nothing
downstream can mistake a README for evidence.

**Writes:** `code_chunks`, each with its vector. **Model tier:** embedding.

### 5. `module_summarizer`

A paragraph per module: what it is *for*, not what it contains. This is the stage that
costs, and the one with a ceiling.

**Writes:** `kb_modules.summary`. **Model tier:** fast, six concurrent.

!!! warning "It stops at 40 modules"
    `ANALYSIS_MAX_SUMMARISED_MODULES` defaults to 40. Beyond that, the largest modules
    are summarised and the rest are left with no prose — visible in the studio as a
    module with no paragraph. Raise it if you want full coverage; it costs one call per
    extra module.

### 6. `architecture_synthesizer`

Reads the whole picture and names the **components this system actually has**: not
`service` and `api`, but "Worker Face Tracking Engine" and "Controller Persistence".
Each component gets a type, a description, and the modules that make it up, plus the
relations between them.

This is what the knowledge graph groups by, and what [What changed](../apps.md#what-changed)
compares between two readings.

**Writes:** `knowledge_bases.architecture_json`. **Model tier:** quality.

### 7. `narrative_writer`

Twelve cross-cutting topics — architecture, request lifecycle, data model,
configuration, deployment, error handling, testing, observability, integrations, state
management, CLI usage, overview — each written from the modules it drew on, with those
modules recorded as provenance.

**Writes:** `kb_narratives`, with `source_refs_json`. **Model tier:** quality.

### 8. `site_planner`

Decides which document types this codebase can actually support, from evidence rather
than from a menu. A project with no HTTP routes is never offered an API reference.

**Writes:** `knowledge_bases.site_map_json`. **Model tier:** quality.

### 9. `question_seeder`

The suggested questions on the Ask page, derived from what was found. "Which service
handles diagram generation?" is a real question about a real module, not a template.

**Writes:** `knowledge_bases.suggested_questions_json`. **Model tier:** fast.

### 10. `kb_persister`

Marks the knowledge base ready and writes the aggregate statistics: module and entity
counts, role distribution, languages, embedding model and measured width.

**Writes:** `knowledge_bases.stats_json`, status. **Model calls:** none.

## What happens to the clone

It is deleted. The checkout is working material for the run; nothing needs it
afterwards, because [a file is rebuilt from stored chunks](chunks-and-retrieval.md#reading-a-file-back).

Removal happens in a `finally`, so a run that failed halfway releases the disk exactly
as one that succeeded does, and clones left by earlier versions are swept at startup.

A **folder** source is your own directory. It is passed straight through and never
registered for deletion, which is a structural guarantee rather than a check.

## Cancelling

Long work stays cancellable throughout. `JobCancelled` is never swallowed by a broad
`except` and never retried; a cancelled run leaves no half-built knowledge base looking
usable.

## Re-running

Analysing a commit that already has a ready knowledge base reuses it. Pass `force` to
rebuild. Analysing a *different* commit builds a second reading alongside the first,
which is the raw material for [What changed](../apps.md#what-changed).
