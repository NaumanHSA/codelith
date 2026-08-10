"""
Revising prose that already exists.

The difference from the writer is the whole point of this agent: the writer is given
a heading and evidence and produces prose; the reviser is given *prose* and asked to
change it in a stated way. Handing the existing text back as an input is what makes
"tighten this" or "add an example here" mean anything — without it every instruction
becomes "write this section again, but differently", which loses everything the
reader wanted to keep.

Two things it must not do, both of which are silent:

* **Replace the page.** Only the addressed block is spliced; the rest of the page
  comes back exactly as it was. `app/knowledge/blocks.py` owns that.
* **Rename a heading for style.** Its text is the `anchor_id` other pages link to,
  so a reworded heading costs every link into it. It *may* rename one the revision
  has made inaccurate — dropping half of "Development and observability tips" leaves
  a title promising content that is gone, which is worse than a dead fragment link,
  and the linker degrades those to plain text anyway. When it does, the new anchor
  travels back on the step output: the studio is mid-conversation against the old
  id and its next turn would 404 without it.

Retrieval is the same machinery composition uses, aimed at the instruction rather
than at a plan: what the reader asked for is the best available query for what
evidence the revision needs.
"""

from __future__ import annotations

from typing import Any

from codelith.agents.base import BaseAgent
from codelith.config import get_settings
from codelith.core.cancellation import JobCancelled
from codelith.knowledge.blocks import block_body, find_blocks, replace_block
from codelith.knowledge.retrieval import SectionContextBuilder
from codelith.knowledge.sites import anchor_id
from codelith.llm.prompts.composition_prompts import SECTION_REVISE
from codelith.tracing.artifacts import save_artifact, save_input_artifact, save_text_artifact

#: Repeated from the writer rather than shared, because the two prompts are edited
#: for different reasons and a change to one is not automatically right for the other.
_LINK_RULES = (
    "  - To point at another page of this site, write `[[section-slug/page-slug]]`. "
    "Never a relative path or a URL.\n"
    "  - A source file or symbol goes in backticks and nothing else: `app/config.py`. "
    "Never `[[app/config.py]]` and never `[text](app/config.py)` — a source path is "
    "not a page and a markdown link to one is dead in the published page.\n"
)


class ReviserAgent(BaseAgent):
    name = "reviser_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="Reviser: applying the requested change",
            end_message="Reviser: complete",
        ) as t:
            await self._update_step(self.name, "running")

            settings = get_settings()
            project = state["project"]
            page: dict = state["page"]
            anchor: str | None = state.get("anchor")
            instructions: str = state.get("instructions") or ""
            history: list[dict] = state.get("history") or []
            markdown: str = page.get("content_markdown") or ""

            builder = SectionContextBuilder(
                db=self.db,
                kb_id=state["kb_id"],
                project_id=project.id,
                token_budget=settings.COMPOSITION_SECTION_TOKEN_BUDGET,
            )

            # Whole page, or one of its sections.
            block = None
            if anchor:
                matches = find_blocks(markdown, anchor)
                if not matches:
                    return await self._give_up(
                        t, f"No section with anchor '{anchor}' on this page"
                    )
                if len(matches) > 1:
                    # `anchor_id` maps two identical headings to one id. Guessing
                    # would edit the wrong half of the page.
                    return await self._give_up(
                        t,
                        f"'{matches[0].title}' appears {len(matches)} times on this "
                        "page, so the instruction is ambiguous. Rename one heading "
                        "and try again.",
                    )
                block = matches[0]

            target = block.text if block else markdown
            section_name = block.title if block else page.get("title", "the page")

            # Aim retrieval at what the reader asked for, anchored on the files the
            # page was already written from so a small instruction cannot drag the
            # section onto unrelated code.
            context = await builder.build(
                {
                    "name": section_name,
                    "focus": instructions or section_name,
                    "key_files": page.get("source_files") or page.get("key_files") or [],
                },
                page.get("doc_type") or "architecture",
            )

            audience, tone = self._voice(state.get("strategy") or {}, page.get("doc_type"))
            messages = SECTION_REVISE.render(
                project_name=project.name,
                page_title=page.get("title", ""),
                page_intent=page.get("intent") or "part of this documentation",
                section_name=section_name,
                instructions=instructions or "(no instructions given — improve clarity)",
                history=self._history(history),
                current=target,
                neighbours=self._neighbours(state.get("site_map") or {}, page.get("address")),
                context=context.render(),
                audience=audience,
                tone=tone,
                max_subheadings=str(settings.SITE_MAX_SUBHEADINGS_PER_SECTION),
                link_rules=_LINK_RULES,
            )
            save_input_artifact("reviser.prompt", messages)

            try:
                revised = (await self._call_llm(messages, task_type="write") or "").strip()
            except JobCancelled:
                raise
            except Exception as exc:
                return await self._give_up(t, f"The revision call failed: {exc}")

            if not revised:
                return await self._give_up(t, "The model returned nothing")

            save_text_artifact("reviser.revised", revised)

            # Splice, or replace the whole page.
            try:
                content = replace_block(markdown, block, revised) if block else revised
            except ValueError as exc:
                return await self._give_up(t, str(exc))

            # A revision may rename its own heading — asked to drop half a
            # section's subject, leaving the old title promising content that is no
            # longer there is worse than a changed anchor. But the anchor *is* the
            # address, so the new one has to travel back: the panel is mid-conversation
            # against the old id and its next turn would 404 without this.
            new_anchor, new_title = anchor, None
            if anchor and block:
                first = revised.lstrip().split("\n", 1)[0]
                if first.startswith("#"):
                    new_title = first.lstrip("#").strip()
                    new_anchor = anchor_id(new_title)

                # A title of nothing but emoji or punctuation reduces to an empty
                # anchor, which is not an address: the conversation would be re-keyed
                # onto "" and every link into the section rewritten to a bare `#`.
                if new_anchor != anchor and not new_anchor:
                    await self._emit_log(
                        "warning",
                        f"Kept the heading “{block.title}”: “{new_title}” has no "
                        "addressable form.",
                    )
                    content = replace_block(
                        markdown,
                        block,
                        f"{'#' * block.level} {block.title}\n\n{block_body(revised)}",
                    )
                    new_anchor, new_title = anchor, None

                # A rename that lands on a heading the page already has makes the
                # anchor ambiguous, and every later revision of *either* section is
                # then refused as un-addressable. The prose is still wanted, so the
                # section keeps its old heading rather than the change being lost.
                if new_anchor != anchor and len(find_blocks(content, new_anchor)) > 1:
                    await self._emit_log(
                        "warning",
                        f"Kept the heading “{block.title}”: renaming it to "
                        f"“{new_title}” would collide with another heading on this page.",
                    )
                    content = replace_block(
                        markdown, block, f"{'#' * block.level} {block.title}\n\n{block_body(revised)}"
                    )
                    new_anchor, new_title = anchor, None

            save_artifact(
                "reviser.summary",
                {
                    "address": page.get("address"),
                    "anchor": anchor,
                    "new_anchor": new_anchor,
                    "section": section_name,
                    "instructions": instructions,
                    "words_before": len(target.split()),
                    "words_after": len(revised.split()),
                },
            )
            await self._emit_log(
                "info",
                f"Revised “{section_name}”"
                f" ({len(target.split())} → {len(revised.split())} words)",
                section=section_name, anchor=anchor,
            )

            t.outputs(section=section_name, anchor=anchor, words=len(revised.split()))
            await self._update_step(
                self.name,
                "completed",
                {
                    "section": section_name,
                    "anchor": anchor,
                    # Only when it moved, so the studio can tell "unchanged" from
                    # "renamed" without comparing strings itself. The title travels
                    # with it: `section` is what the heading *was*, and a panel that
                    # re-labels itself from that shows the old name over the new one.
                    **(
                        {"new_anchor": new_anchor, "new_title": new_title}
                        if new_anchor != anchor
                        else {}
                    ),
                    "words": len(revised.split()),
                },
            )

            # Shaped exactly like a composition result, so the linker and the
            # publisher downstream need to know nothing about revisions.
            return {
                # Carried out of the graph so the conversation can be re-keyed. Prior
                # turns are stored against the old anchor, and leaving them there
                # strands the history the next turn depends on.
                "new_anchor": new_anchor if new_anchor != anchor else None,
                "generated_docs": [
                    {
                        "doc_type": page.get("doc_type") or "architecture",
                        "title": page.get("title", ""),
                        "content_markdown": content,
                        # Read by the linker, which would otherwise see this page's
                        # own links to the old heading as dead and flatten them to
                        # text. The new anchor is known, so they are repointed.
                        **(
                            {"anchor_renames": {anchor: new_anchor}}
                            if new_anchor != anchor
                            else {}
                        ),
                        "page_id": page["id"],
                        "address": page.get("address"),
                        "section_slug": page.get("section_slug"),
                        "slug": page.get("slug"),
                        # Unchanged: a revision edits prose, it does not re-anchor the
                        # page. Overwriting these with the revision's retrieval would
                        # make staleness detection wrong for the whole page.
                        "source_files": page.get("source_files") or [],
                    }
                ]
            }

    async def _give_up(self, t, reason: str) -> dict[str, Any]:
        """Fail loudly and change nothing. A revision that cannot be made is not a
        reason to write something else over the page."""
        await self._emit_log("error", reason)
        t.outputs(error=reason)
        await self._update_step(self.name, "failed", {"error": reason})
        return {"generated_docs": [], "error": reason}

    @staticmethod
    def _history(history: list[dict]) -> str:
        """
        Earlier turns for this same section.

        The panel is scoped to one heading and cleared when the reader moves to
        another, so this is short by construction — and it is what lets "now make the
        second paragraph shorter" mean anything.
        """
        if not history:
            return ""
        lines = ["Earlier in this conversation, about this same section:"]
        for turn in history[-6:]:
            asked = (turn.get("instructions") or "").strip()
            if asked:
                lines.append(f"  - You were asked: {asked}")
        return "\n".join(lines) + "\n\n"

    @staticmethod
    def _neighbours(site_map: dict, address: str | None) -> str:
        """The other pages, so a revision can link rather than restate."""
        lines: list[str] = []
        for section in site_map.get("sections") or []:
            for page in section.get("pages") or []:
                other = f"{section.get('slug')}/{page.get('slug')}"
                if other == address:
                    continue
                lines.append(f"[[{other}]] {page.get('title')}")
        if not lines:
            return ""
        return (
            "Other pages of this site, to link to rather than restate: "
            + "; ".join(lines)
            + "\n\n"
        )

    @staticmethod
    def _voice(strategy: dict, doc_type: str | None) -> tuple[str, str]:
        for entry in strategy.get("audiences") or []:
            if entry.get("doc_type") == doc_type:
                return entry.get("audience", "developers"), entry.get("tone", "technical")
        return "developers", "technical"
