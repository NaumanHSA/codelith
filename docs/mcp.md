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

## The twelve tools

Call `list_codebases` first. Every other tool takes a `codebase_id`, and the ids are
not guessable.

| Tool | Answers |
|---|---|
| `list_codebases` | What has been analysed, with commit and size |
| **`before_edit`** | **What an edit would touch. Call this first** |
| **`review_changes`** | **Whether the change you just made fits. Call this before saying you are done** |
| `search_code` | Search the source, by meaning or by name |
| `read_file` | A file as the knowledge base holds it |
| `find_callers` | Who calls a symbol. **No embedding encodes this** |
| `find_dependents` | Which files import a file |
| `blast_radius` | Everything that transitively reaches a file, with distance |
| `list_facts` | Routes, datastores, env vars, entrypoints and the rest |
| `trace_flow` | How a request travels: from a route's or command's handler, function by function, to the data it reads or writes. With no argument, every way in |
| `how_to` | How a route, command, setting, model or test is added *here*: where they are declared, where they are registered, and the clearest example to copy. With `run`: what it needs, and how to install, run and test it |
| `qa_findings` | What QA found and nobody dismissed — security holes, leaks, error handling, code that will break, dependency problems, failing tests — each with its line, how sure it is and its fix; narrowed by `path`, `area` or `min_severity`. Also which areas QA has **never checked**, so an agent does not call them clean |

## `review_changes`

The other end of `before_edit`: after the edit. It reads the uncommitted change in the
repository (the codebase's own folder, or the directory the server runs in, or `path`)
against the commit the knowledge was read at, and answers in three sections:

- **Stop and look** — a deleted or renamed file something outside the change still
  imports; an import that makes a part depend on one in an earlier column (data reaching
  up into an entry point, a shared helper importing core logic); a new loop between parts
- **Check** — a new dependency between two parts that had none; a route, command or
  scheduled task removed; a file many others depend on that no test reaches
- **Notes** — what it adds (routes, settings, outside services), what it no longer uses,
  written pages that describe what it changed

Then what it touches file by file, the tests to run, and the pages to check. Open QA
findings in the changed files are said too: one whose rule no longer fires in the new
contents is **fixed**, one in a deleted file is gone, and one whose lines changed is to
be checked (a critical or high one under *Check*). `before_edit` lists a file's open
findings before the edit. No model
call. Each review is kept and shown on the codebase's **Review** page in the studio, so
you can read afterwards what your agent checked.

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

## `trace_flow` and `how_to`

`trace_flow("POST /orders")` answers "how does this work" with the calls the reading
recorded rather than a guess: the handler, each function it calls on the way, the file
and line of each, the part of the codebase it is in, and where the chain reaches data or
a service outside the code. It takes a route, a command, a handler's name or a file.

`how_to("route")` is the house style for the kind of change an agent is about to make.
An agent that adds a route the way the language usually does it, rather than the way this
codebase does it, writes code that works and does not fit; this says where the others
are declared, the file that registers them (a new file needs adding there too), and one
to copy.

Both are also in the instruction file `codelith agents-md` writes, so an agent that reads
`AGENTS.md` or `CLAUDE.md` first knows to call them.

## What agents could not find

Every call is recorded, and **Settings → Agents** lists the questions that came back
empty and the ones asked three times or more: a name the knowledge does not know, a part
analysis skipped, or a reading that is out of date. It is the to-do list for what the
reading is missing.

## What it will not do

- **Nothing writes.** Every tool is read-only.
- **Nothing leaves.** No network call beyond the model endpoint you configured.
- **Nothing is guessed.** `find_callers` returning empty says so explicitly, because
  call edges are resolved only where the callee is unambiguous and an empty result is
  not proof of no callers.

## When answers look stale

The knowledge base is pinned to a commit. If you have moved on since analysing, the
tools are describing the code as it was — accurately, and not as it is now.

So every answer ends with the commit it describes, and for a repository on this machine
how many commits have landed since: *(Read at c176f29d. The code has 3 newer commits
since; analyse it again for answers about the current code.)* `list_codebases` reports
the commit each reading is at.

To stop it going stale at all, read every commit: `codelith watch`, `codelith hook
install`, or **Read every commit** on the codebase page in the studio. A reading after a
small commit keeps everything that did not change, so it is cheap. The old reading stays,
which is what [What changed](apps.md#what-changed) compares.
