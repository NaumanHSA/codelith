# The knowledge base

One SQLite file under `~/.codelith`. This page is what is in it.

A knowledge base belongs to a project and is **keyed by the commit SHA** it read. That
key is what makes a reading reproducible, makes re-analysis cheap, and makes comparing
two readings meaningful.

## Modules

The unit a person thinks in: a package or a directory of code.

| Column | What it holds |
|---|---|
| `path`, `name` | Repo-relative path, and the dotted name a person would say |
| `kind` | What the provider called it — package, file |
| `role` | One of thirteen fixed words (below) |
| `language` | The provider that claimed it |
| `file_count`, `loc` | Size |
| `is_test` | Kept and flagged rather than dropped |
| `summary` | A paragraph: what it is for. Empty past the summarising ceiling |
| `files_json`, `symbols_json` | What is inside it |

### Roles

`api` · `service` · `data_access` · `model` · `schema` · `worker` · `ui` · `cli` ·
`config` · `infra` · `test` · `utility` · `unknown`

A **closed vocabulary, identical in every codebase**, which is exactly what makes it
useful to the apps: a documentation writer asks for the `api` modules and that means
the same thing in every repository.

It is assigned by evidence, strongest first: the entities a module contains (a module
with routes is `api`), then its own directory name, then its ancestors, then filename
hints.

!!! note "Roles are not what the graph shows you"
    Because they are the same thirteen words everywhere, they make a poor label for a
    person browsing. The knowledge graph groups by the **components the architecture
    pass named for your codebase** instead, and falls back to the role only for a
    module no component claimed. See [Analysis](analysis.md#6-architecture_synthesizer).

## Entities

Facts extracted from the code. Thirteen kinds:

| Kind | What it is |
|---|---|
| `route` | An HTTP endpoint, with method and path |
| `entrypoint` | A way the program starts |
| `service` | A component the code names |
| `dependency` | A third-party package |
| `env_var` | An environment variable the code reads |
| `config_file` | A file that configures something |
| `datastore` | A database, cache or queue it talks to |
| `external_api` | A service it calls out to |
| `cli_command` | A command it exposes |
| `scheduled_task` | Cron, a watchdog, a periodic job |
| `event` | Something emitted or subscribed to |
| `infra_resource` | A Dockerfile, a manifest, a workflow |
| `test_suite` | A body of tests |

Each carries `source_path`, so a claim can be traced to the file it came from.

!!! tip "An empty result is a real answer"
    A project with no `route` entities has no HTTP surface. That is information, and
    the apps use it: the documentation planner will not offer an API reference, and
    `list_facts` over MCP says so rather than returning nothing ambiguously.

## Narratives

Twelve cross-cutting topics, each a piece of prose written from the analysis:
`overview`, `architecture`, `request_lifecycle`, `data_model`, `configuration`,
`deployment`, `error_handling`, `testing`, `observability`, `integrations`,
`state_management`, `cli_usage`.

Each stores `source_refs_json` — the modules it was written from. That provenance is
what lets a reader check a paragraph rather than trust it, and it is empty for anything
written before the recording writer existed. Empty is the honest answer there: guessing
after the fact would be a citation nobody could check.

## The architecture map

`architecture_json` on the knowledge base holds the components the analysis named for
this codebase, their types, descriptions, the modules in each, and the relations
between them.

This is the one part that says what a change *means*. A module growing by 200 lines is
a fact; a service appearing is a decision somebody made.

## Chunks

`code_chunks` — the source, split and embedded. Covered in
[Chunks and retrieval](chunks-and-retrieval.md).

## The code graph

Six `graph_*` tables. Covered in [The code graph](code-graph.md).

## Statistics

`stats_json` records what the reading found: module and entity counts, the distribution
of roles, entity kinds, the languages seen, the narratives written, how many modules
were summarised, and the **embedding model with its measured width**.

That last pair is not decoration. It is what refuses to read a knowledge base with the
wrong embedding model, and it is why there is no width to configure.

## Generations

Analysing a project at a new commit creates a new knowledge base rather than replacing
the old one. The most recent ready one is what the apps read; the previous ones stay,
which is what [What changed](../apps.md#what-changed) compares.

Everything is scoped by `kb_id`, so a re-analysis can never mix old and new source into
one answer.
