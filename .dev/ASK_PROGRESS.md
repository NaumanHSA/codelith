# Ask the Codebase — Progress

Execution tracker for [ASK_PLAN.md](ASK_PLAN.md). Update the status column as work
lands; keep notes on anything that contradicted the plan.

Legend: ⬜ not started · 🟨 in progress · ✅ done · ⛔ blocked · ⏭️ deferred

## Summary

| Phase | Scope | Status |
|---|---|---|
| Q1 | Streaming from the model | ✅ |
| Q2 | The answer, and its citations | ✅ |
| Q3 | Threads and messages | ✅ |
| Q4 | The page | ✅ |
| Q5 | Messages and the composer | ✅ |
| Q6 | Tests and verification | ✅ |
| Q7 | Escalate to a loop when one pass is not enough | ⬜ |

Everything K1–K9 landed before this is in [SUBSTRATE_PLAN.md](SUBSTRATE_PLAN.md).
K4 built the retrieval half of this feature and deliberately stopped short of
answering; this tracker is the other half.

---

## Phase Q1 — Streaming from the model ✅

| # | Task | Status | Notes |
|---|---|---|---|
| Q1.1 | `stream_completion()` in `app/llm/client.py` — async generator of content deltas | ✅ | `_completion_params` extracted and shared |
| Q1.2 | Reasoning deltas counted, never yielded as answer text | ✅ | |
| Q1.3 | Cancellation mid-stream closes the upstream request | ✅ | The check runs after the yield, as in `chat_completion`, so the chunk in flight is delivered — a test asserted otherwise and was wrong |
| Q1.4 | Verify against both a local and a hosted tier | ✅ | quality (gpt-5-mini) 59 chunks, first token 3.76s; fast (lfm2.5-1.2b) 59 chunks, 2.88s; cancellation aborted after 3 |

---

## Phase Q2 — The answer, and its citations ✅

| # | Task | Status | Notes |
|---|---|---|---|
| Q2.1 | `ANSWER_QUESTION` prompt in `app/llm/prompts/` | ✅ | Evidence labelled by kind; prose explicitly unverified |
| Q2.2 | `AskService` — question → `gather()` → prompt → stream | ✅ | No agentic loop: one retrieval pass, one answer |
| Q2.3 | Multi-turn history, trimmed | ✅ | Drop history before evidence — see the risk in the plan |
| Q2.4 | Citation extraction from the answer | ✅ | `file:line` and bare paths |
| Q2.5 | **Citations validated against the retrieved bundle** | ✅ | An unretrieved citation is stripped. Same rule as the router: the model proposes, the KB disposes |
| Q2.6 | Streaming endpoint `POST /projects/{id}/chat/stream` | ✅ | Events: `token`, `evidence`, `usage`, `done`, `error`. `?token=` auth like job logs |
| Q2.7 | A project with no usable KB returns a clear message | ✅ | Not an empty answer |
| Q2.8 | Run the 20-question set end to end | ⬜ | Exit criterion: every citation resolves; hand-score answerability |

---

## Phase Q3 — Threads and messages ✅

| # | Task | Status | Notes |
|---|---|---|---|
| Q3.1 | Migration: `chat_threads`, `chat_messages` | ✅ | Head is `c3f6a2d84b17` |
| Q3.2 | Models + service | ✅ | Token count stored per message so the wheel is a query, not a recomputation |
| Q3.3 | Evidence snapshot stored with the assistant message | ✅ | What it was answered from, at the time |
| Q3.4 | `GET .../chat/thread` — load a conversation | ✅ | |
| Q3.5 | `DELETE` — clear a thread | ✅ | Backs the clear-history button |
| Q3.6 | Reload preserves the conversation | ✅ | Exit criterion for Q3 |

---

## Phase Q4 — The page ✅

| # | Task | Status | Notes |
|---|---|---|---|
| Q4.1 | Route `/app/chat` + nav entry `05` | ✅ | `Shell.tsx` nav array |
| Q4.2 | Two-column layout; thread sidebar deferred | ⏭️ | The chat column is centred at 760px with the app nav beside it. A third column holding one stub felt like scaffolding on screen rather than a feature — Q3 stores what it needs | Persistence exists (Q3) but the sidebar is not wired this pass |
| Q4.3 | Project selector, defaulting to the most recently analysed | ✅ | Deep-linkable `?project=2` |
| Q4.4 | Empty state: centred input, greeting, suggested questions | ✅ | Questions from `scripts/questions.txt` — real ones, already run |
| Q4.5 | Input docks to the bottom after the first message | ✅ | The reference behaviour in the screenshots |
| Q4.6 | A project with no KB says so, with a link to analyse it | ✅ | |

---

## Phase Q5 — Messages and the composer ✅

| # | Task | Status | Notes |
|---|---|---|---|
| Q5.1 | Extract a plain `Markdown` primitive | ✅ | Shared by `DocMarkdown` and chat; chat must not get heading rewrite buttons |
| Q5.2 | Assistant message: markdown, code blocks, copy button | ✅ | |
| Q5.3 | User message: markdown too, so newlines and lists survive | ✅ | Explicitly asked for |
| Q5.4 | Streaming cursor while tokens arrive | ✅ | |
| Q5.5 | Citations as `file:line` chips | ✅ | Only ones that survived Q2.5 |
| Q5.6 | Composer: 1 row → ~200px, own scrollbar | ✅ | Enter sends, Shift+Enter newline |
| Q5.7 | Attachment button, disabled, with a tooltip saying why | ✅ | A dead control that looks live is worse than an honest one |
| Q5.8 | Context wheel — SVG ring, amber 75%, red 90% | ✅ | Server counts authoritative; client estimates while typing |
| Q5.9 | Clear history behind `ConfirmDelete` | ✅ | |
| Q5.10 | Stop-generating button while streaming | ✅ | Falls out of Q1.3 |

---

## Phase Q6 — Tests and verification ✅

| # | Task | Status | Notes |
|---|---|---|---|
| Q6.1 | Citation validation: an invented `file:line` is stripped | ✅ | The load-bearing one |
| Q6.2 | History trimming drops history before evidence | ✅ | |
| Q6.3 | Token accounting matches the pipeline's tokenizer | ✅ | |
| Q6.4 | SSE contract: every event shape, including `error` | ✅ | |
| Q6.5 | Thread persistence and clearing | ✅ | |
| Q6.6 | UI typecheck + production build | ✅ | |
| Q6.7 | Full suite green | ✅ | 854 passing, up from 810 | |
| Q6.8 | Verify each new test fails without its fix | ✅ | Standing practice in this repo |

---

## Phase Q7 — Escalate to a loop when one pass is not enough ⬜

| # | Task | Status | Notes |
|---|---|---|---|
| Q7.0 | **Score the 20-question set by hand** | ⬜ | The gate. Sort failures into "needed to look further" and "looked in the right place and answered badly" — a loop fixes only the first |
| Q7.1 | Tool schemas over the KB | ⬜ | search_code, read_file, find_callers, find_dependents, blast_radius, list_facts. Every backing function already exists |
| Q7.2 | Tool-calling turn in `AskService` | ⬜ | Evidence still pre-loaded, tools offered alongside. Calling one *is* the escalation signal |
| Q7.3 | Step budget and a hard stop | ⬜ | Six calls |
| Q7.4 | Tool results join the evidence pool | ⬜ | Citations checked against pre-loaded plus fetched |
| Q7.5 | Fall back to one-shot when tools are unsupported | ⬜ | Automatic, not a crash |
| Q7.6 | Stream the loop to the reader | ⬜ | "Reading loop.py...", "Finding callers of run()..." |
| Q7.7 | Latency unchanged on easy questions | ⬜ | If a simple question starts costing four turns, escalation fires too eagerly |
| Q7.8 | Tests, including that escalation is *rare* | ⬜ | A loop that always fires is a slower one-shot |

---

## Deferred, deliberately

| Item | Why |
|---|---|
| Thread history sidebar (wired) | Asked to leave for later; the sidebar ships as a visual stub and Q3 stores what it will need |
| Attachments | Stub only, this pass |
| Agentic re-querying | Promoted to Q7, gated on Q7.0 |
| Answer regeneration / edit-and-resend | Not asked for; cheap to add on top of Q3 |

## Notes and contradictions

**Q3 was built before Q2.6, against the plan's order.** The endpoint needs to
persist what it streams, so building it before the tables meant building it twice.

**Two citation bugs, both found by running rather than reasoning.**

1. The pattern required backticks. A real answer wrote every citation as plain prose
   — `neurosurfer/vectorstores/chroma.py:13-105` — so all of them were correct and
   none was checked. Depending on a model to format its output for a safety check is
   depending on it not to make the mistake the check exists to catch. Bare paths now
   match too, and a resolved citation is normalised into backticks so the studio can
   render every verified reference the same way.
2. Only evidence *titles* were scanned for known paths. A code block is titled with
   its path, but an entity is titled `datastore: Chroma` and carries the path in its
   body — so citations to files the evidence had just named were stripped as
   inventions. Measured: two of three "inventions" in one answer were this. Bodies
   are scanned now, and the same answer went from 4 kept / 3 stripped to 6 kept /
   0 stripped.

**Latency worth knowing before Q5.** Retrieval runs 8-12s before the first token,
because the router makes a quality-tier call and then embeds. The `evidence` event
fires as soon as retrieval finishes, so the UI has something true to show during the
wait — but the wait is real and the design should assume it.
