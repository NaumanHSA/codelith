# Ask the Codebase — Scorecard

Twenty questions, scored against `neurosurfer` (project 2), quality tier on
`qwen/qwen3.5-9b` running locally. Question set in `scripts/questions.txt`.

Q7.0 left the subjective half open: *are the answers any good?* This is that pass,
done the only way it can be done honestly — by checking what each answer claims
against what the analysis extracted before any question was asked.

## Headline

| | gpt-5-mini | qwen3.5-9b, first run | qwen3.5-9b, now |
|---|---|---|---|
| blank answers | 0 | **5** | 0 |
| citations kept / stripped | 146 / 1 | 78 / 22 | **136 / 7** |
| answers citing nothing | — | 3 | **1** |
| hedged | 6 (30%) | 0 — *blanks do not hedge* | 5 (25%) |
| median | 28.0s | 14.8s | 17.5s |
| escalated | — | 5/20 | 5/20, 14 tool calls |

Half the latency of the hosted model, on hardware already paid for.

## Recall against extracted facts

Seven questions have a crisp ground truth: the routes, entrypoints, datastores,
external APIs and scheduled tasks were all extracted during analysis, before any
question existed. Recall is measurable there, and so is invention.

| Question | Recall | Verdict |
|---|---|---|
| what endpoints does it expose | **4/4** | Every route, with method, path and `file:line`. |
| where is the entry point | **3/3** | All three, each with the code that makes it one. |
| what external services does it talk to | **6/6** | Complete. |
| what database does it use | **2/2** | Chroma and SQLite, correctly distinguished by role. |
| where is data stored | 1/2 | Names Chroma, SQLite, and the MCP config file; misses the second extracted datastore by name. |
| what runs on a schedule | n/a — none exist | **Says so plainly.** The hardest kind of question to get right, and it did. |
| what environment variables does it need | 16/16 | Grouped by purpose, each with a location. |

Nothing invented, in any of the seven.

## What the scoring found

Scoring answers found four defects — three in the product, one in the scoring —
which is a better return than reading the code would have given.

**The model was better informed than the knowledge base.** Asked what environment
variables neurosurfer needs, it named `CONTEXT_WINDOW`, `SUPPORTS_VISION`, `NS_HOST`,
`NS_PORT` and `NS_LOG_LEVEL`. None were in the KB, so all five were flagged as
inventions. All five are real:

* `CONTEXT_WINDOW` / `SUPPORTS_VISION` — read via `env_int(...)` and
  `env_bool_opt(...)`, which the extractor did not recognise. **Fixed**: a project
  that reads more than two variables writes a wrapper, and then `os.getenv` never
  appears at the call sites again.
* `NS_*` — declared by a pydantic-settings class with `env_prefix="NS_"`, so no
  literal name appears in the source at all. **Not fixed** — see below.

**A test's variables were being answered as configuration.** `A`, `B`, `C` and `D`
from `tests/test_config.py:54-57` sat in the KB beside `OPENAI_API_KEY` with nothing
to tell them apart. `is_entrypoint` had excluded tests since run 1, with the reason
written down; nothing had applied it here. Fixed in all four language providers and
pushed into the conformance suite.

**Seventeen citations were invisible to the checker**, sitting in the first line
inside a code fence — where a model labels a sample with its source. Two of the three
answers that appeared to cite nothing had three and four of them.

**`mcp.json` was read as `mcp.js`.** Regex alternation is first-match-wins. A
correctly-cited file was reported to the reader as an invention.

## Where it is weakest

**`how is configuration loaded` — 3,696 characters, zero citations.** The one
remaining uncited answer. It describes `load_config()` accurately and shows the code,
but names it as `neurosurfer.config.load_config()` and leaves its fence unlabelled, so
there is nothing a reader can open. The prompt now asks for both; this one still did
neither.

**`how is it deployed` overstates its evidence.** It says deployment "uses a single
Python runtime container image". `docs/server/deployment.md:45` *recommends* an image
(`FROM python:3.12-slim`); the repository ships no Dockerfile — the CHANGELOG records
one being removed. Prose was read as a description of what is, rather than of what is
suggested. Exactly the failure the prompt's "blocks marked `unverified`" rule exists
to prevent, and the rule did not hold here.

**Escalation is the slow path and not obviously the better one.** The five questions
that escalated took 20–27s against a 17.5s median, and `what calls the tool registry`
spent all six tool calls and still hedged. Worth measuring whether the tools earn
their latency, per question, rather than assuming they do.

## Open

**Settings classes are invisible to env-var extraction.** pydantic-settings with
`env_prefix` declares a whole family of variables with no literal name anywhere —
`NS_HOST`, `NS_PORT`, `NS_LOG_LEVEL` are real and unfindable by any pattern over call
sites. This repository uses the same idiom in `app/config.py`, so document-anything
cannot currently document its own configuration. Recognising a settings class and
enumerating its fields is a real feature, not a regex.

**The env-helper fix is Python only.** Go, Java and TypeScript extract by regex rather
than AST, so the same detection there is a different and less safe job. The
conformance suite has the test seat ready.
