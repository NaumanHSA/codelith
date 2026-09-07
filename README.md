<p align="center">
  <img src="docs/assets/codelith-banner.png" alt="Codelith: local-first code intelligence" width="100%">
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/license-Apache%202.0-ff6b35?style=flat-square"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-ff6b35?style=flat-square">
  <a href="https://github.com/NaumanHSA/codelith/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/NaumanHSA/codelith/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="MCP: 8 tools" src="https://img.shields.io/badge/MCP-8%20tools-14120f?style=flat-square">
  <img alt="Runs offline" src="https://img.shields.io/badge/runs-fully%20offline-2f9e44?style=flat-square">
</p>

---

## 🧭 What this is

Your coding agent re-reads your repository from scratch every session, by grepping.

Codelith reads it **once**: every file, route, entrypoint, module boundary and
dependency. That reading becomes a **knowledge base**, pinned to the commit it was
taken from. Then it serves that reading back, to your editor over MCP, to a
question-answering app with checked citations, to a documentation writer, and to a
diff that tells you what moved between two commits.

**Analysis is the product. The apps are what it unlocks.**

Everything runs on your machine. The knowledge base is one SQLite file under
`~/.codelith`, and the models are whichever OpenAI-compatible endpoint you point it at
(LM Studio, Ollama, vLLM, llama.cpp, or a hosted API if you want one). There is no
database to run, no queue, no vector service, and no account anywhere.

<p align="center">
  <img src="docs/assets/architecture.png" alt="Sources are ingested, analysed once per commit into a knowledge base, and read by four apps and an MCP server." width="100%">
</p>

---

## 🚀 Quick start

### Docker: one container, one address

The image builds the studio, serves it from the API, creates the database and seeds an
account. Nothing else to install.

```bash
git clone https://github.com/NaumanHSA/codelith.git
cd codelith
docker compose up --build -d
```

Open **<http://localhost:8000>** and sign in with `admin@codelith.dev` / `admin1234`.

> ⚠️ **Your model stays on your machine.** A container's `localhost` is the container,
> so a model server running on your host is not reachable at the address that works
> everywhere else. Compose maps `host.docker.internal` for exactly this, and the studio
> says so at the field where you type a model endpoint, with a button that rewrites it
> for you. Point the tiers at `http://host.docker.internal:1234/v1` and it works.

`make docker` does the same thing and prints the address. `make docker-down` stops it;
the knowledge bases live in a named volume and survive.

### From source

Needs Python 3.11+ and, for the studio, Node ≥ 20.19.

```bash
git clone https://github.com/NaumanHSA/codelith.git
cd codelith
pip install -e ".[dev]"

python scripts/seed_dev.py     # the first account
make dev                       # API on :8000

# a second terminal
cd ui && pnpm install && pnpm dev    # studio on :5173
```

`.env` is optional. Every setting has a working default and `.env.example` documents
them. The database is a file under `~/.codelith` (or `CODELITH_HOME`), created on first
run, so there is no migrate step for a fresh install.

### From the command line

The CLI is a **client**: it talks to a running Codelith server, so start one of the
above first.

```bash
codelith login                          # remembers the token
codelith analyse .                      # or a GitHub URL, or a folder
codelith ask "how does auth work?"
codelith status                         # what has been analysed
codelith doctor                         # check the config before it fails deep
codelith mcp                            # serve the knowledge base over MCP
```

---

## ♻️ Read once, use many times

Analysis runs once per commit SHA and takes no document type. It must not, or the apps
stop being interchangeable. Everything below reads the stored knowledge base, and
**none of them re-open the repository**.

| App | What it does | What it reads |
|---|---|---|
| **Documentation** | Structured documents in Markdown, DOCX, MkDocs or Docusaurus. Document types are offered from an evidence-backed menu, so a project with no HTTP routes is never offered an API Reference | retrieval, narratives |
| **Ask the code** | Grounded question answering. Every citation is checked against the evidence actually retrieved, and one that does not resolve is stripped | retrieval, code graph |
| **What changed** | The difference between two readings of the same repository: modules added or rewritten, routes that came and went, and which written pages now describe code that is no longer there | modules, entities, written pages |
| **Before you edit** | What a change to a file or a symbol would touch: importers, transitive reach, call sites, whether a test covers it, and the pages that describe it. Also the `before_edit` MCP tool | code graph, entities, written pages |

Adding an app means one entry in `codelith/apps/registry.py` and one page, never a
change to analysis. That rule is a test rather than a convention:
`tests/unit/test_module_isolation.py` fails if the base imports an app, or if one app
imports another.

---

## 🔌 Use it from your editor (MCP)

Codelith has already read your repository: chunked, embedded, with an import graph,
pinned to a commit. Coding agents re-derive that by grepping, from scratch, every
session. The MCP server lets them ask instead.

```jsonc
// .mcp.json, for Claude Code, Cursor, and anything else speaking MCP
{
  "mcpServers": {
    "codelith": {
      "command": "codelith",
      "args": ["mcp"]
    }
  }
}
```

Or, in Claude Code:

```bash
claude mcp add codelith -- codelith mcp
```

The server speaks JSON-RPC on stdin and stdout, which is what an editor launches. It
writes nothing to stdout but the protocol, because a stray line of prose there is a
parse error on the client. That is why `codelith mcp` prints no banner.

Eight tools. Call `list_codebases` first: every other one takes a `codebase_id`, and
the ids are not guessable.

| Tool | Answers |
|---|---|
| `list_codebases` | What has been analysed, with commit and size |
| **`before_edit`** | **What an edit would touch. Call this first** |
| `search_code` | Semantic search over the source |
| `read_file` | A file as the knowledge base holds it |
| `find_callers` | Who calls a symbol. **No embedding encodes this** |
| `find_dependents` | Which files import a file |
| `blast_radius` | Everything that transitively reaches a file, with distance |
| `list_facts` | Routes, datastores, env vars, entrypoints and the rest |

`before_edit` is the one that changes what this is for. The others answer questions
about a codebase; that one is called *before* changing it. Give it a path or a symbol
and it comes back with what depends on it, whether anything tests it, and what has
already been written about it:

```
codelith/llm/client.py, high risk to edit. 3 file(s) import it directly,
11 reach it within 3 hops, nothing tests it, 2 written page(s) describe it.

Breaks first (nearest first):
  1 hop(s)  codelith/agents/base.py
  2 hops(s) codelith/workflows/analysis_workflow.py
  ...

No test file reaches this. A change here is unverified by the suite.

Written pages that describe it (they will need re-writing):
  reference/llm-client, The LLM client
```

No model call and four indexed queries, which is the point: a check an agent skips
under time pressure is a check that does not exist. The failure it prevents is not a
wrong edit but a confidently narrow one, correct in the file and broken for four
callers nobody looked for.

Read-only, and local. Nothing writes, and nothing is sent anywhere Codelith does not
already talk to.

---

## 🤖 Models

Three tiers, each pointed wherever you like. The provider decides only whether an API
key is sent.

| Tier | Used for | A reasonable local choice |
|---|---|---|
| **quality** | writing, review, validation, architecture, planning | a 7-14B instruct model |
| **fast** | classification, extraction, diagrams, summarising | a 1-3B instruct model |
| **embedding** | indexing and retrieval | any embedding model |

Configure them in the studio under **Settings → Models**, or in `.env`:

```bash
MODEL_QUALITY_PROVIDER=local          # local | openai
MODEL_QUALITY=qwen/qwen3.5-9b
MODEL_QUALITY_BASE_URL=http://localhost:1234/v1
MODEL_QUALITY_CONTEXT_WINDOW=21000
# ...and the same four for MODEL_FAST_* and MODEL_EMBEDDING_*
```

**There is no embedding-width setting, and there should not be.** The width is a
property of the model, so Codelith measures it on the first call and records it on the
knowledge base along with the model name. Open a knowledge base with a different
embedding model and it refuses to read it and tells you to re-analyse, rather than
silently comparing vectors that do not mean the same thing. Any model works, and you
never have to tell it a number.

Which tier handles which task is decided in `codelith/llm/router.py`, not by the
caller.

---

## 📚 What it can read

**Languages.** Python, TypeScript/JavaScript, Go, Java. Each is one provider under
`codelith/languages/providers/`, and no language-specific code exists anywhere else, so
adding a language means adding a provider rather than touching agents or schema.

**Sources.** A public or private Git repository (any branch), a folder on disk, or an
uploaded zip/tarball.

**Documentation output.** Markdown, DOCX, HTML, MkDocs or Docusaurus.

---

## 🛠️ Development

```bash
make test          # full suite, about 30 seconds, starts nothing
make test-unit     # unit only
make lint          # ruff
make typecheck     # mypy

cd ui && pnpm build    # typecheck, two render checks, then the bundle
```

The integration tests use a temporary SQLite file. There are no services to bring up
for any of it.

The rules a newcomer is most likely to break, and the tests that catch them, are in
[CONTRIBUTING.md](CONTRIBUTING.md). The short version: the base may not import an app,
apps may not import each other, colours live only in `ui/src/styles/theme.css`,
language-specific code lives only in `codelith/languages/`, and database access goes
through `codelith/db/repositories/`.

---

## 📦 Installing

**From source.** The path above. This is the supported one today.

**Docker.** `docker compose up --build`, also above.

**PyPI.** Not published yet. The release workflow is built and wired to trusted
publishing; firing it is a maintainer decision, and this README will say so when it
happens rather than before.

---

## 🤝 Contributing

Issues and pull requests are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md),
which covers the layout, the invariants enforced by tests, and how to run everything.

- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security policy](SECURITY.md). Please do not open a public issue for a vulnerability
- [Changelog](CHANGELOG.md)

## 📄 License

[Apache-2.0](LICENSE). Permissive, with an explicit patent grant, which is what a tool
that ends up inside other people's build pipelines should carry.
