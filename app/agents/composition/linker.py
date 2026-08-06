"""
Resolving cross-page links.

Writers are told to reference another page as `[[section/slug]]` and never to invent
a path. This stage turns those into real routes and checks every internal link and
heading anchor in the page.

**No LLM, on purpose.** A model cannot be trusted to construct a relative path it
has never seen, and it has no way to know which pages exist at write time — the site
is written a section at a time, over months. Getting a link wrong is also unusually
expensive: a documentation site with broken links reads as broken regardless of how
good its prose is, and nothing downstream can detect one.

An unresolvable reference degrades to plain text rather than shipping `[[foo]]` to a
reader, and is reported so the failure is visible rather than silent.

The route written is the studio's (`/app/projects/{id}/docs/{section}/{slug}`),
because the studio owns the reading experience. Exporting to MkDocs or Docusaurus
rewrites these to relative file paths — a mechanical transform on a link that is
already known to resolve, which is the whole point of doing it here.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.base import BaseAgent
from app.knowledge.sites import anchor_id, doc_key
from app.tracing.artifacts import save_artifact

#: `[[section/slug]]`, `[[slug]]`, or either with `|custom link text`.
_WIKI_LINK = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")

#: A markdown link pointing at a heading in the same page.
_ANCHOR_LINK = re.compile(r"\[([^\]]*)\]\(#([^)]+)\)")

#: A markdown link pointing into this site by address rather than by wiki syntax.
_PAGE_PATH = re.compile(r"\[([^\]]*)\]\(/app/projects/(\d+)/docs/([^)#]+)(#[^)]*)?\)")

#: Any markdown link at all, so the ones that are none of the above can be caught.
#: The lookbehind excludes `![alt](src)` — an image is an embed, not a reference, and
#: a rendered diagram arrives as a `data:` URI that must survive untouched.
_ANY_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]*)\)")

#: Hrefs that are legitimately addresses: a resolved page route, a heading anchor,
#: somewhere off this machine, or an embedded asset.
_REAL_HREF = re.compile(r"^(#|/app/projects/|https?://|mailto:|data:)")

#: A symbol or path — no whitespace, and not obviously a sentence.
_CODEISH = re.compile(r"^[\w./\\@:${}()\[\]-]+$")


class LinkerAgent(BaseAgent):
    name = "linker_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="Linker: resolving cross-page links",
            end_message="Linker: complete",
        ) as t:
            await self._update_step(self.name, "running")

            project = state["project"]
            docs: list[dict] = state.get("generated_docs") or []
            site_map: dict = state.get("site_map") or {}
            index = self._index(site_map)

            linked: list[dict] = []
            resolved = broken = anchors = demoted = 0
            report: list[dict] = []

            for doc in docs:
                content = doc.get("content_markdown") or ""
                if not content:
                    linked.append(doc)
                    continue

                content, outcome = self._link_one(content, project.id, index, doc)
                resolved += outcome["resolved"]
                broken += len(outcome["unresolved"]) + len(outcome["dead_anchors"])
                anchors += outcome["anchors"]
                demoted += len(outcome["source_links"])
                if outcome["unresolved"] or outcome["dead_anchors"] or outcome["source_links"]:
                    report.append({"page": doc_key(doc), **outcome})
                linked.append({**doc, "content_markdown": content})

            save_artifact(
                "linker.links",
                {
                    "resolved": resolved,
                    "broken": broken,
                    "anchors": anchors,
                    "source_links": demoted,
                    "problems": report,
                },
            )

            if broken or demoted:
                # Named, not counted: "3 broken links" is not actionable, and the
                # whole reason this stage is deterministic is that its failures can
                # be pointed at precisely.
                for entry in report:
                    for target in entry["unresolved"]:
                        await self._emit_log(
                            "warning",
                            f"{entry['page']}: no page matches [[{target}]]",
                        )
                    for anchor in entry["dead_anchors"]:
                        await self._emit_log(
                            "warning", f"{entry['page']}: no heading matches #{anchor}"
                        )
                    # Repaired rather than broken, so it is info: the reader sees a
                    # backticked path instead of a dead link. Still logged, because a
                    # page doing it twenty times is a prompt problem, not a typo.
                    for href in entry["source_links"]:
                        await self._emit_log(
                            "info",
                            f"{entry['page']}: link to source path '{href}' demoted to code",
                        )
            await self._emit_log(
                "info",
                f"Resolved {resolved} cross-page link(s), checked {anchors} anchor(s)",
                broken=broken,
                source_links=demoted,
            )

            t.outputs(
                resolved=resolved, broken=broken, anchors=anchors, source_links=demoted
            )
            await self._update_step(
                self.name, "completed",
                {
                    "resolved": resolved,
                    "broken": broken,
                    "anchors": anchors,
                    "source_links": demoted,
                },
            )

            # `generated_docs` is a reduced key, so returning it here would append a
            # second copy of every page. The rewritten text rides on its own key,
            # which `formatter` and `publisher` prefer when present.
            return {"linked_docs": linked, "link_report": report}

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _index(site_map: dict) -> dict[str, dict]:
        """
        Every addressable page, by full address *and* by bare slug.

        The bare slug is a convenience for the writer — `[[endpoints]]` is what a
        model naturally produces — but only when it is unambiguous across the site.
        A slug used in two sections resolves to neither, which is correct: guessing
        would silently link half the references to the wrong page.
        """
        by_address: dict[str, dict] = {}
        slug_counts: dict[str, int] = {}
        for section in site_map.get("sections") or []:
            for page in section.get("pages") or []:
                entry = {
                    "section_slug": section.get("slug"),
                    "slug": page.get("slug"),
                    "title": page.get("title") or page.get("slug"),
                }
                by_address[f"{entry['section_slug']}/{entry['slug']}"] = entry
                slug_counts[entry["slug"]] = slug_counts.get(entry["slug"], 0) + 1

        index = dict(by_address)
        for entry in by_address.values():
            if slug_counts.get(entry["slug"]) == 1:
                index[entry["slug"]] = entry
        return index

    def _link_one(
        self, content: str, project_id: int, index: dict[str, dict], doc: dict
    ) -> tuple[str, dict]:
        unresolved: list[str] = []
        resolved = 0
        self_address = doc.get("address")

        def replace(match: re.Match[str]) -> str:
            nonlocal resolved
            raw = match.group(1).strip()
            label = (match.group(2) or "").strip()
            entry = index.get(raw) or index.get(raw.strip("/"))
            if entry is None:
                unresolved.append(raw)
                # Plain text beats shipping `[[foo]]` to a reader.
                return label or raw
            address = f"{entry['section_slug']}/{entry['slug']}"
            if address == self_address:
                # A page referencing itself renders as a link that does nothing.
                # Not counted as resolved: nothing was linked.
                return label or entry["title"]
            resolved += 1
            route = f"/app/projects/{project_id}/docs/{address}"
            return f"[{label or entry['title']}]({route})"

        content = _WIKI_LINK.sub(replace, content)

        # The same rule for a route the model wrote out by hand rather than as a
        # reference — rarer, since the prompt forbids it, but just as dead.
        if self_address:
            content = _PAGE_PATH.sub(
                lambda m: m.group(0)
                if f"{m.group(3).rstrip('/')}" != self_address
                else m.group(1),
                content,
            )

        # Heading anchors within this page.
        headings = {anchor_id(h) for h in self._headings(content)}
        dead: list[str] = []
        for match in _ANCHOR_LINK.finditer(content):
            if match.group(2) not in headings:
                dead.append(match.group(2))
        if dead:
            content = _ANCHOR_LINK.sub(
                lambda m: m.group(1) if m.group(2) in dead else m.group(0), content
            )

        content, source_links = self._demote_source_links(content)

        return content, {
            "resolved": resolved,
            "unresolved": unresolved,
            "anchors": len(headings),
            "dead_anchors": dead,
            "source_links": source_links,
        }

    @staticmethod
    def _demote_source_links(content: str) -> tuple[str, list[str]]:
        """
        A markdown link to a source path is a dead link. Demote it to code.

        The prompt says to write a source file in backticks and never as a link, and
        C1 measured one page in four ignoring that: `architecture/data-model` shipped
        19 dead links out of 28, hrefs like `neurosurfer/tracing/config.py` and a few
        carrying a stray backtick inside them. Wiki references and anchors were both
        already checked; a plain relative-path link was checked by nothing, so it
        reached the reader.

        Runs last, after wiki links have become real routes — anything left whose href
        is not a route, an anchor or an external URL has no address to point at.
        `[`TracerConfig`](…)` becomes `` `TracerConfig` ``, which is what the writer
        was asked for in the first place.
        """
        demoted: list[str] = []

        def replace(match: re.Match[str]) -> str:
            text, href = match.group(1), match.group(2).strip()
            if not href or _REAL_HREF.match(href):
                return match.group(0)
            demoted.append(href.strip("`"))
            label = text.strip()
            if label.startswith("`") and label.endswith("`") and len(label) > 1:
                return label  # already code — just drop the link around it
            if label and _CODEISH.match(label):
                return f"`{label}`"
            # Prose link text: keep the words, lose the link, and name the file after
            # it so the reference is not simply lost.
            path = href.strip("`")
            return f"{label} (`{path}`)" if label else f"`{path}`"

        return _ANY_LINK.sub(replace, content), demoted

    @staticmethod
    def _headings(markdown: str) -> list[str]:
        out: list[str] = []
        in_fence = False
        for line in markdown.split("\n"):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
            if in_fence:
                continue
            if match := re.match(r"^(#{1,6})\s+(.*)$", line):
                out.append(match.group(2).strip())
        return out


__all__ = ["LinkerAgent"]
