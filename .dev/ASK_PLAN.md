# Ask the Codebase — Plan

`SUBSTRATE_PLAN.md` built the substrate and stopped at K4, deliberately: a router, an
evidence contract and an inspector, with **no answer synthesis and no chat surface**.
The reasoning was that K1–K3 should be measurable before an agent was written on top
of them, and it paid — running the question set found three routing defects that no
amount of reasoning would have surfaced.

This is the feature K4 was groundwork for.

Decisions taken before writing this:

| Question | Answer |
|---|---|
| Where does the page live? | **Top-level `/app/chat`**, with a project selector. The KB is per-project, but the ask is for a nav entry beside Projects and Documents — so the page picks a project rather than living inside one |
| Stream tokens, or return the whole answer? | **Stream.** A grounded answer runs 5–20s; a spinner for that long reads as broken, and the evidence panel can populate while the model writes |
| Which model tier? | **Quality.** Measured in K4: the 1.2B fast tier answered `datastore` for four of five questions regardless of what was asked. Answers matter more than routing did |
| Persist messages, or keep them client-side? | **Persist from day one.** The thread sidebar is coming, and retrofitting persistence means redoing the message flow. One table, one migration |
| Agentic loop, re-querying until satisfied? | **No.** One retrieval pass, one answer. An agent that re-queries is a larger thing, and this should be measured before it is built |
| Reuse `DocMarkdown`? | **Extract a primitive.** It injects per-heading rewrite buttons, which a chat message must not have. Both render from one shared react-markdown config |

---

## What already exists

Worth stating precisely, because most of the hard part is done.

| Piece | Where | State |
|---|---|---|
| Router, validated against the KB | `app/knowledge/questions.py` | Done — `LLMQuestionPlanner` + `QuestionRouter.gather()` |
| Evidence with provenance | same | Done — `EvidenceBundle`, each item carrying `why` |
| Retrieval policy | `app/knowledge/policy.py` | Done — `QUESTION_ANSWERING`, prose labelled unverified |
| Code graph traversals | `app/memory/graph_store.py` | Done — callers, dependents, blast radius |
| SSE plumbing | `app/api/v1/jobs.py:118` | Exists — job logs stream, `?token=` auth because EventSource cannot set headers |
| Token counting | `app/llm/context_manager.py` | Exists — `count_text_tokens`, `trim_to_limit` |
| Context window | `MODEL_QUALITY_CONTEXT_WINDOW` | Exists — the denominator for the context wheel |
| Markdown rendering | `ui/src/app/components/docs/DocMarkdown.tsx` | Exists, needs a plain variant |

**Missing, and the whole of this plan:** answer synthesis, token streaming to a
browser, message persistence, and the page.

---

## Phase Q1 — Streaming from the model

**Why.** `chat_completion` already streams internally — it has to, so a cancelled job
stops the model rather than waiting for it — but it accumulates chunks and returns one
string. A chat surface needs the deltas.

**What.** `stream_completion()` in `app/llm/client.py`: an async generator yielding
content deltas, sharing the existing parameter assembly so local and hosted tiers,
reasoning models, and cancellation all behave identically to the non-streaming path.

**Measured by.** A script that prints tokens as they arrive from both a local and a
hosted tier, and a cancelled stream that stops the model rather than draining it.

**Risk.** Reasoning models stream thinking on a separate delta field. The existing
code already counts it separately; the generator must not yield it as answer text.

---

## Phase Q2 — The answer, and its citations

**Why.** This is the part K4 refused to build without measuring first.

**What.**

- `AskService`: question → `QuestionRouter.gather()` → prompt → stream.
- The prompt carries evidence **labelled by kind** — code with `file:line`, prose
  explicitly marked unverified. `SectionContext.render()` already does this.
- Multi-turn history, trimmed with the existing `trim_to_limit`.
- **Citations validated against the evidence actually retrieved.** The model is asked
  to cite `file:line`; a citation that does not appear in the bundle is stripped.

**The citation check is the point.** It is the same rule the router follows — the model
proposes, the knowledge base disposes. Without it, a chat that sounds grounded is
worse than one that obviously guesses, because the reader has no way to tell.

**Measured by.** The 20-question set answered end to end; every citation in every
answer resolves to a retrieved chunk; and the hand-scored "is this answerable from
what it retrieved" number that K4 exists to produce.

---

## Phase Q3 — Threads and messages

**What.** `chat_threads` (project, title, timestamps) and `chat_messages` (thread,
role, content, token count, evidence snapshot, citations). One migration.

Token counts are stored per message so the context wheel is answered from the database
rather than recomputed on every render.

**Measured by.** A reload preserves the conversation; clearing empties it; the thread
sidebar can be built later without touching the message flow.

---

## Phase Q4 — The page

**What.** `/app/chat`, nav entry `05`, three columns: existing app nav │ thread
sidebar (visual stub) │ chat column at ~760px.

**Empty state.** Input centred, greeting, and four suggested questions taken from
`scripts/questions.txt` — they are real questions that have been run against this
substrate, not invented placeholders. On first send the input docks to the bottom.

**Project selector** in the header, defaulting to the most recently analysed project,
deep-linkable as `?project=2`.

**Measured by.** It looks like the reference screenshots, and a project with no
knowledge base says so rather than failing.

---

## Phase Q5 — Messages and the composer

**Messages.** Assistant answers in markdown with highlighted code blocks and a copy
button; citations as `file:line` chips. User messages also markdown, so newlines and
lists survive. A streaming cursor while tokens arrive.

**Composer.** Textarea from one row to ~200px with its own scrollbar; Enter sends,
Shift+Enter newlines. Attachment button present and **disabled with a tooltip saying
why** — a dead control that looks live is worse than an honest one.

**Context wheel.** An SVG ring: system + evidence + history + what is being typed,
over `MODEL_QUALITY_CONTEXT_WINDOW`. Server counts are authoritative because they use
the pipeline's tokenizer; the client estimates live as you type. Amber at 75%, red at
90%, with the exact numbers on hover.

**Clear history**, behind the existing `ConfirmDelete`.

---

## Risks, stated plainly

- **The answer is only as good as K4 measured.** If the retrieved evidence does not
  contain what is needed, a better prompt will not save it. Q2's hand-scoring is the
  honest gate, and it may say "not yet".
- **Streaming plus cancellation is where the bugs are.** A closed browser tab must
  stop the model, or an abandoned question generates to completion and bills for it.
- **Token counts drift.** `count_text_tokens` approximates; the wheel should read as
  a guide, not a guarantee, and must never block sending.
- **Context exhaustion is silent.** Evidence is large. A long thread plus a large
  bundle can exceed the window mid-conversation; trimming must drop history rather
  than evidence, or answers lose their grounding first.
- **The project selector is a real dependency.** A chat with no KB has nothing to
  answer from, and that must be a clear message rather than an empty reply.

## Open questions

- Should each answer show a collapsible evidence panel? The bundle is already there
  and it is nearly free, but it competes with a clean reading surface.
- Should the wheel count the *next* turn's evidence, which is not known until the
  question is asked? Proposal: count history plus a running average of recent
  bundles, and label it an estimate.
- Non-streaming first, for roughly 40% less work? Proposal: no — the latency is the
  reason streaming exists, and retrofitting it touches every message component.
