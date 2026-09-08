# MCP

Codelith has already read your repository — chunked, embedded, with an import graph,
pinned to a commit. Coding agents re-derive that by grepping, from scratch, every
session. The MCP server lets them ask instead.

It is **not an app**. It adds nothing of its own; it is a second transport over the
same base.

## Setup

```jsonc
// .mcp.json — Claude Code, Cursor, and anything else speaking MCP
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
writes nothing to stdout but the protocol — a stray line of prose there is a parse
error on the client, which is why `codelith mcp` prints no banner.

## The eight tools

Call `list_codebases` first. Every other tool takes a `codebase_id`, and the ids are
not guessable.

| Tool | Answers |
|---|---|
| `list_codebases` | What has been analysed, with commit and size |
| **`before_edit`** | **What an edit would touch. Call this first** |
| `search_code` | Search the source, by meaning or by name |
| `read_file` | A file as the knowledge base holds it |
| `find_callers` | Who calls a symbol. **No embedding encodes this** |
| `find_dependents` | Which files import a file |
| `blast_radius` | Everything that transitively reaches a file, with distance |
| `list_facts` | Routes, datastores, env vars, entrypoints and the rest |

## `before_edit`

The one that changes what this is for. The others answer questions *about* a codebase;
this one is called *before* changing it.

Give it a path or a symbol:

```
codelith/llm/client.py — high risk to edit — 3 file(s) import it directly,
11 reach it within 3 hops, nothing tests it, 2 written page(s) describe it.

Breaks first (nearest first):
  1 hop(s)  codelith/agents/base.py
  2 hops(s) codelith/workflows/analysis_workflow.py
  ...

No test file reaches this. A change here is unverified by the suite.

Written pages that describe it (they will need re-writing):
  reference/llm-client — The LLM client
```

No model call and four indexed queries. A check an agent skips under time pressure is a
check that does not exist.

## What it will not do

- **Nothing writes.** Every tool is read-only.
- **Nothing leaves.** No network call beyond the model endpoint you configured.
- **Nothing is guessed.** `find_callers` returning empty says so explicitly, because
  call edges are resolved only where the callee is unambiguous and an empty result is
  not proof of no callers.

## When answers look stale

The knowledge base is pinned to a commit. If you have moved on since analysing, the
tools are describing the code as it was — accurately, and not as it is now.

`list_codebases` reports the commit each reading is at. Re-analyse to catch up, and the
old reading stays, which is what [What changed](apps.md#what-changed) compares.
