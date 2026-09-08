# The code graph

Six tables in SQL, walked with a recursive CTE. No graph database, and none needed.

## The six tables

| Table | One row is | Key columns |
|---|---|---|
| `graph_files` | A file the reading covered | `path`, `language`, `loc`, symbol count |
| `graph_modules` | A module | `name`, `path` |
| `graph_packages` | A package grouping modules | `name` |
| `graph_symbols` | A declaration | `path`, `qname`, `name`, `kind`, `line`, `end_line`, `visibility` |
| `graph_imports` | One file importing another | source path, target path |
| `graph_calls` | One symbol calling another | caller, callee |

Every row is scoped by `kb_id` and `project_id`, so a re-analysis cannot mix two
readings into one answer.

## What it can answer

These are the questions **no embedding encodes**, which is why the graph exists
alongside retrieval.

**Who calls this?** `graph_calls`, by callee name.

**Who imports this file?** `graph_imports`, by target — one hop.

**What reaches this file, and how far away is it?** A recursive CTE over
`graph_imports`, returning each file with its distance in hops. This is the blast
radius, and distance is the useful part: the file one hop away breaks first.

**Does a test reach it?** The same walk, asking whether anything under a test path
appears in the set. A file nothing tests is a file a change to it is unverified by the
suite, and that is worth saying out loud.

**What does this file declare?** `graph_symbols`, by path — which is also the symbol
outline in the source viewer, and the table the
[lexical half of retrieval](chunks-and-retrieval.md#the-lexical-half) matches names
against.

## What it cannot answer, honestly

!!! warning "Call edges are resolved only where the callee is unambiguous"
    A method called through a variable, a callback passed as an argument, anything
    dispatched dynamically — those edges are not recorded, because recording a guess
    would be worse than recording nothing.

    So `find_callers` returning nothing is **not proof of no callers**, and it says so
    in its own output rather than letting a reader infer certainty that is not there.

Import edges are more complete than call edges, which is why blast radius is built on
imports.

## Reach, and what it is for

`reach_weight` ranks how much a file matters by how much depends on it: capped
transitive reach, plus five per written page that describes it. It lives in the base
rather than in an app, so ranking by reach never requires opening one.

A file is **high risk to edit** at a reach weight of 25 or more, or at 8 or more with no
test reaching it.

## Where you meet it

- **The studio**, under any file in the source viewer: what it imports, who imports it,
  what reaches it and how far, whether a test covers it, and which written pages
  describe it.
- **[`before_edit`](../mcp.md#before_edit)** over MCP, which assembles all of it into
  the answer an agent wants before it changes something.
- **[What changed](../apps.md#what-changed)**, which compares two readings.
