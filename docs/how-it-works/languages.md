# Languages

## What is supported today

| Language | Provider | Extensions |
|---|---|---|
| **Python** | `python.py` | `.py`, `.pyi` |
| **TypeScript / JavaScript** | `typescript.py` | `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs` |
| **Go** | `go.py` | `.go` |
| **Java** | `java.py` | `.java` |

Anything else is still **read**: a file no provider claims is chunked on line windows
and embedded, so it is searchable and readable in the source viewer. What it does not
get is symbols, imports, calls, or framework-aware facts.

## What a provider does

A `LanguageProvider` is the only place in the codebase that knows anything language-
specific. It answers:

- **Which files are mine**, by extension.
- **What is declared here** — every symbol with its kind, its qualified name, and its
  line span. This is what makes a chunk a whole function instead of an arbitrary
  window, and what fills `graph_symbols`.
- **What does this file import**, resolved to repository paths where it can be.
- **What calls what**, where the callee is unambiguous.
- **What framework facts are visible** — a FastAPI decorator is a route, a Gin handler
  is a route, an `os.environ` read is an env var.
- **What to skip** — `node_modules`, `__pycache__`, `vendor`, and the rest.

Python's provider is the most complete, because it was first and because the product
was built in it. Go and Java extract symbols, imports and routes; TypeScript adds the
studio's own idioms.

## The rule

!!! note "No language-specific code outside `codelith/languages/`"
    Python's `ast`, file extensions, framework idioms — all of it lives behind
    `LanguageProvider`. Agents and the knowledge base speak the neutral vocabulary in
    `codelith/languages/taxonomy.py` and `codelith/knowledge/constants.py`.

    **Adding a language means adding one provider.** Not touching agents, not touching
    the schema, not touching the apps.

This is not a style preference. It is what keeps a thirteen-kind entity vocabulary
meaningful across four languages, and what makes the fifth cheap.

## Adding one

1. Write a provider in `codelith/languages/providers/`, implementing the interface.
2. Register it.
3. Run the conformance suite. `tests/unit/languages/conformance.py` is shared across
   providers: it asks every one of them the same questions and checks the shape of the
   answers, so a new provider is held to what the existing ones already do.

There is no step four. If you find yourself editing an agent, the agent is asking for
something the provider should be answering.

## Path handling

Paths inside the knowledge base are POSIX-style and repo-relative, always.

Backslashes are normalised to forward slashes wherever a path is compared, on every
platform — not because Windows needs it, but because being wrong there is silent: one
native path slipping past a filter means a whole vendored tree gets analysed, embedded,
and paid for, with nothing to show that the filter did not fire.
