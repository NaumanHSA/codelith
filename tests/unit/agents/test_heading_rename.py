"""
What a renamed heading costs, and that each cost is paid.

A revision may rename the heading its own edit made inaccurate — asked to drop the
observability half of "Development and observability tips", leaving that title over
what remains is worse than changing the anchor. But the heading text *is* the
address: `anchor_id` derives from it, and four separate things are keyed on it. Each
one is a way the rename can silently break something, and each has a case here.

1. The conversation. Every revision turn is a job row keyed on `config_json.anchor`,
   so a rename strands the transcript — measured before the fix: two turns orphaned
   by one rename, the panel showing an empty history for a section that had one.
2. The studio's open panel, mid-conversation against the old id. Covered by the
   agent returning `new_anchor` and the workflow carrying it out of the graph.
3. Same-page `](#fragment)` links, which the linker already degraded to plain text.
4. Cross-page `](/app/projects/N/docs/addr#fragment)` links, which it did *not* —
   the same-page check only ever sees one page at a time.

Plus the case where a rename is refused: renaming onto a heading the page already
has makes the anchor ambiguous, and `find_blocks` then refuses every later revision
of *either* section. The prose is still wanted, so the heading stays put.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codelith.apps.documentation.agents.linker import LinkerAgent
from codelith.apps.documentation.agents.reviser import ReviserAgent
from codelith.apps.documentation.services.revision_service import RevisionService
from codelith.knowledge.blocks import find_blocks, split_blocks

PAGE_MD = """Opening line.

## Development and observability tips

Tips about development, and about observability.

## Errors

Error text.
"""

PAGE = {
    "id": 7,
    "address": "guides/getting-started",
    "section_slug": "guides",
    "slug": "getting-started",
    "title": "Getting Started",
    "intent": "How to begin",
    "doc_type": "architecture",
    "content_markdown": PAGE_MD,
    "source_files": ["app/api.py"],
    "key_files": ["app/api.py"],
}

OLD_ANCHOR = "development-and-observability-tips"


class _Tracer:
    def outputs(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __call__(self, **kwargs):
        return self


@pytest.fixture
def agent(monkeypatch) -> ReviserAgent:
    """A reviser with everything outside its own logic stubbed out.

    Retrieval and tracing are not what these cases are about — the splice and the
    anchor bookkeeping either side of it are.
    """
    a = ReviserAgent(db=None, job_id=1)  # type: ignore[arg-type]

    async def _noop(*args, **kwargs):
        return None

    class _Context:
        def render(self):
            return "(evidence)"

    class _Builder:
        def __init__(self, **kwargs):
            pass

        async def build(self, *args, **kwargs):
            return _Context()

    a._emit_log = _noop  # type: ignore[method-assign]
    a._update_step = _noop  # type: ignore[method-assign]
    a._tracer = lambda: _Tracer()  # type: ignore[method-assign]
    monkeypatch.setattr("codelith.apps.documentation.agents.reviser.SectionContextBuilder", _Builder)
    monkeypatch.setattr("codelith.apps.documentation.agents.reviser.save_artifact", lambda *a, **k: None)
    monkeypatch.setattr("codelith.apps.documentation.agents.reviser.save_input_artifact", lambda *a, **k: None)
    monkeypatch.setattr("codelith.apps.documentation.agents.reviser.save_text_artifact", lambda *a, **k: None)
    return a


def _state(page_md: str = PAGE_MD, anchor: str = OLD_ANCHOR) -> dict:
    return {
        "project": SimpleNamespace(id=3, name="neurosurfer"),
        "page": {**PAGE, "content_markdown": page_md},
        "anchor": anchor,
        "instructions": "drop the observability part",
        "kb_id": 1,
        "history": [],
        "site_map": {},
        "strategy": {},
    }


def _answers(agent, text: str) -> None:
    async def _call(*args, **kwargs):
        return text

    agent._call_llm = _call  # type: ignore[method-assign]


class TestTheAgentReportsTheRename:
    """The new anchor has to leave the agent, or nothing downstream can react."""

    async def test_a_renamed_heading_comes_back_as_new_anchor(self, agent) -> None:
        _answers(agent, "## Development tips\n\nTips about development.")

        out = await agent.run(_state())

        assert out["new_anchor"] == "development-tips"
        assert "## Development tips" in out["generated_docs"][0]["content_markdown"]

    async def test_an_unchanged_heading_reports_no_move(self, agent) -> None:
        """`None`, not the same string — the task branches on truthiness, and
        re-keying a conversation onto the anchor it already has is a wasted write."""
        _answers(
            agent,
            "## Development and observability tips\n\nTighter, but the same subject.",
        )

        out = await agent.run(_state())

        assert out["new_anchor"] is None

    async def test_the_new_title_travels_with_the_new_anchor(self, agent, monkeypatch) -> None:
        """The panel re-labels itself from the step output. `section` is the name the
        heading had *before* this turn, so without a separate `new_title` the panel
        moves to the right anchor under the wrong name."""
        steps: dict = {}

        async def _capture(name, status, output=None):
            steps.update(output or {})

        agent._update_step = _capture  # type: ignore[method-assign]
        _answers(agent, "## Development tips\n\nTips about development.")

        await agent.run(_state())

        assert steps["section"] == "Development and observability tips"
        assert steps["new_title"] == "Development tips"
        assert steps["new_anchor"] == "development-tips"

    async def test_an_unchanged_heading_publishes_no_title_move(self, agent) -> None:
        steps: dict = {}

        async def _capture(name, status, output=None):
            steps.update(output or {})

        agent._update_step = _capture  # type: ignore[method-assign]
        _answers(agent, "## Development and observability tips\n\nTighter.")

        await agent.run(_state())

        assert "new_title" not in steps
        assert "new_anchor" not in steps

    async def test_the_rest_of_the_page_is_untouched_by_a_rename(self, agent) -> None:
        _answers(agent, "## Development tips\n\nTips about development.")

        content = (await agent.run(_state()))["generated_docs"][0]["content_markdown"]

        assert "Opening line." in content
        assert "## Errors" in content
        assert "Error text." in content

    async def test_the_renamed_section_is_addressable_for_the_next_turn(self, agent) -> None:
        """A conversation continues after a rename, so the new anchor must resolve
        to exactly one block in the page that was actually produced."""
        _answers(agent, "## Development tips\n\nTips about development.")

        out = await agent.run(_state())

        assert len(find_blocks(out["generated_docs"][0]["content_markdown"], out["new_anchor"])) == 1


class TestTheSectionStaysAddressable:
    """A rename is only safe if the section is still findable afterwards. Two ways a
    model breaks that while appearing to answer correctly."""

    async def test_a_heading_returned_at_the_wrong_level_is_corrected(self, agent) -> None:
        """Asked to rewrite a `##`, models sometimes answer with `###`. Spliced
        verbatim, the section leaves the page's structure: gone from the outline,
        no rewrite button, and unreachable to every later revision."""
        _answers(agent, "### Development tips\n\nTips about development.")

        out = await agent.run(_state())
        content = out["generated_docs"][0]["content_markdown"]

        assert "## Development tips" in content
        assert "### Development tips" not in content
        assert [b.title for b in split_blocks(content)] == ["Development tips", "Errors"]
        assert len(find_blocks(content, out["new_anchor"])) == 1

    async def test_a_deeper_heading_the_model_added_is_kept(self, agent) -> None:
        """Only the section's own heading is levelled. Sub-structure the writer
        chose inside it is its business."""
        _answers(agent, "## Development tips\n\n### Local setup\n\nSteps.")

        content = (await agent.run(_state()))["generated_docs"][0]["content_markdown"]

        assert "### Local setup" in content

    async def test_a_title_with_no_addressable_form_is_refused(self, agent) -> None:
        """`anchor_id('🚀')` is the empty string. Accepting it would re-key the
        conversation onto "" and rewrite every link into the section to a bare `#`."""
        _answers(agent, "## 🚀\n\nTips about development.")

        out = await agent.run(_state())
        content = out["generated_docs"][0]["content_markdown"]

        assert out["new_anchor"] is None
        assert "## Development and observability tips" in content
        assert "Tips about development." in content
        assert len(find_blocks(content, OLD_ANCHOR)) == 1


class TestARenameOntoAnExistingHeading:
    """`find_blocks` refuses an anchor matching two headings — deliberately, since
    guessing would edit the wrong half of the page. A rename that *creates* that
    collision would therefore lock both sections out of every future revision."""

    COLLIDING_MD = """## Errors

Error text.

## Development and observability tips

Tips about development, and about observability.
"""

    async def test_the_old_heading_is_kept(self, agent) -> None:
        _answers(agent, "## Errors\n\nRewritten as an errors section.")

        out = await agent.run(_state(self.COLLIDING_MD))

        content = out["generated_docs"][0]["content_markdown"]
        assert [b.title for b in split_blocks(content)] == [
            "Errors",
            "Development and observability tips",
        ]
        assert out["new_anchor"] is None

    async def test_the_revised_prose_is_still_applied(self, agent) -> None:
        """Refusing the rename must not throw away the edit the reader asked for."""
        _answers(agent, "## Errors\n\nRewritten as an errors section.")

        content = (await agent.run(_state(self.COLLIDING_MD)))["generated_docs"][0][
            "content_markdown"
        ]

        assert "Rewritten as an errors section." in content
        # And not doubled: the heading line of the model's answer is dropped, not
        # stacked under the original.
        assert content.count("## Errors") == 1

    async def test_both_sections_remain_individually_addressable(self, agent) -> None:
        _answers(agent, "## Errors\n\nRewritten as an errors section.")

        content = (await agent.run(_state(self.COLLIDING_MD)))["generated_docs"][0][
            "content_markdown"
        ]

        assert len(find_blocks(content, "errors")) == 1
        assert len(find_blocks(content, OLD_ANCHOR)) == 1


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    """Just enough session for `rekey_anchor`, which does one select and one commit."""

    def __init__(self, rows):
        self.rows = rows
        self.committed = False

    async def execute(self, *args, **kwargs):
        return _FakeResult(self.rows)

    async def commit(self):
        self.committed = True


def _turn(job_id: int, anchor: str | None, address: str = "guides/getting-started"):
    return SimpleNamespace(
        id=job_id,
        project_id=3,
        job_type="revision",
        status="completed",
        config_json={
            "address": address,
            "anchor": anchor,
            "instructions": f"turn {job_id}",
        },
    )


class TestTheConversationFollowsTheHeading:
    """The transcript is a query over job rows keyed on the anchor, so a rename
    strands it — the panel reopens empty and the next turn is handed no history."""

    async def test_prior_turns_move_onto_the_new_anchor(self) -> None:
        rows = [_turn(1, OLD_ANCHOR), _turn(2, OLD_ANCHOR), _turn(3, OLD_ANCHOR)]
        db = _FakeDB(rows)

        moved = await RevisionService(db).rekey_anchor(rows[2], "development-tips")

        assert moved == 3
        assert {r.config_json["anchor"] for r in rows} == {"development-tips"}
        assert db.committed

    async def test_the_rename_is_recorded_on_each_turn(self) -> None:
        """`renamed_from` is what makes a re-keyed transcript explicable later —
        without it the rows claim to have always been about the new heading."""
        rows = [_turn(1, OLD_ANCHOR)]

        await RevisionService(_FakeDB(rows)).rekey_anchor(rows[0], "development-tips")

        assert rows[0].config_json["renamed_from"] == OLD_ANCHOR

    async def test_other_headings_are_left_alone(self) -> None:
        mine, theirs = _turn(1, OLD_ANCHOR), _turn(2, "errors")

        await RevisionService(_FakeDB([mine, theirs])).rekey_anchor(mine, "development-tips")

        assert theirs.config_json["anchor"] == "errors"

    async def test_the_same_heading_on_another_page_is_left_alone(self) -> None:
        """Anchors are page-local. Two pages can both have "Errors", and one being
        renamed says nothing about the other."""
        mine = _turn(1, OLD_ANCHOR)
        elsewhere = _turn(2, OLD_ANCHOR, address="reference/config")

        await RevisionService(_FakeDB([mine, elsewhere])).rekey_anchor(mine, "development-tips")

        assert elsewhere.config_json["anchor"] == OLD_ANCHOR

    async def test_a_whole_page_revision_has_nothing_to_rekey(self) -> None:
        """No anchor means the whole page was the target; there is no heading to
        follow, and matching every `anchor: None` turn would be wrong."""
        row = _turn(1, None)

        assert await RevisionService(_FakeDB([row])).rekey_anchor(row, "anything") == 0

    async def test_an_unchanged_anchor_is_a_no_op(self) -> None:
        row = _turn(1, OLD_ANCHOR)
        db = _FakeDB([row])

        assert await RevisionService(db).rekey_anchor(row, OLD_ANCHOR) == 0
        assert not db.committed


def _page(section: str, slug: str, md: str):
    return SimpleNamespace(section_slug=section, slug=slug, content_markdown=md)


class _SweepDB(_FakeDB):
    """`repoint_links` reaches the pages through repositories, which are patched in
    the test; the session itself only has to commit."""

    async def execute(self, *args, **kwargs):
        return _FakeResult([])


class TestLinksFromElsewhereInTheSite:
    """The linker only ever sees the pages a job is writing. A link from another page
    into the renamed heading is invisible to it, and would stay stale until that page
    happened to be rewritten — which may be never."""

    ROUTE = "/app/projects/7/docs/guides/getting-started"

    @pytest.fixture
    def sweep(self, monkeypatch):
        def _run(pages):
            db = _SweepDB([])
            monkeypatch.setattr(
                "codelith.apps.documentation.services.revision_service.DocSiteRepository",
                lambda _db: SimpleNamespace(
                    get_for_project=lambda pid: _async(SimpleNamespace(id=1))
                ),
            )
            monkeypatch.setattr(
                "codelith.apps.documentation.services.revision_service.DocPageRepository",
                lambda _db: SimpleNamespace(list_for_site=lambda sid: _async(pages)),
            )
            return db

        return _run

    async def test_a_link_into_the_renamed_heading_is_repointed(self, sweep) -> None:
        other = _page("reference", "config", f"See [tips]({self.ROUTE}#{OLD_ANCHOR}).")
        db = sweep([other])

        touched = await RevisionService(db).repoint_links(
            _turn(1, OLD_ANCHOR), OLD_ANCHOR, "development-tips"
        )

        assert touched == ["reference/config (1)"]
        assert f"[tips]({self.ROUTE}#development-tips)" in other.content_markdown

    async def test_a_bare_fragment_on_another_page_is_left_alone(self, sweep) -> None:
        """`](#anchor)` on another page addresses *that* page's heading. This rename
        says nothing about it, and rewriting it would break a working link."""
        other = _page("reference", "config", f"See [its own section](#{OLD_ANCHOR}).")
        db = sweep([other])

        touched = await RevisionService(db).repoint_links(
            _turn(1, OLD_ANCHOR), OLD_ANCHOR, "development-tips"
        )

        assert touched == []
        assert f"(#{OLD_ANCHOR})" in other.content_markdown
        assert not db.committed

    async def test_a_link_to_a_different_page_is_left_alone(self, sweep) -> None:
        other = _page(
            "reference",
            "config",
            f"See [elsewhere](/app/projects/7/docs/reference/other#{OLD_ANCHOR}).",
        )
        db = sweep([other])

        assert (
            await RevisionService(db).repoint_links(
                _turn(1, OLD_ANCHOR), OLD_ANCHOR, "development-tips"
            )
            == []
        )

    async def test_it_still_works_after_the_conversation_has_been_rekeyed(self, sweep) -> None:
        """The ordering hazard, caught in a live run: `rekey_anchor` moves this job's
        own `config_json.anchor` onto the new value, so a sweep that read the old
        anchor off the job afterwards saw old == new and silently repointed nothing.
        Here the job is in its post-re-key state and the sweep must still work."""
        rekeyed = _turn(1, "development-tips")  # as rekey_anchor leaves it
        rekeyed.config_json["renamed_from"] = OLD_ANCHOR
        other = _page("reference", "config", f"See [tips]({self.ROUTE}#{OLD_ANCHOR}).")
        db = sweep([other])

        touched = await RevisionService(db).repoint_links(
            rekeyed, OLD_ANCHOR, "development-tips"
        )

        assert touched == ["reference/config (1)"]

    async def test_the_revised_page_itself_is_skipped(self, sweep) -> None:
        """The linker already repointed it, in the content this sweep would be
        re-reading — doing it twice is at best wasted, at worst a double rewrite."""
        itself = _page(
            "guides", "getting-started", f"See [tips]({self.ROUTE}#{OLD_ANCHOR})."
        )
        db = sweep([itself])

        assert (
            await RevisionService(db).repoint_links(
                _turn(1, OLD_ANCHOR), OLD_ANCHOR, "development-tips"
            )
            == []
        )


async def _async(value):
    return value


@pytest.fixture
def linker() -> LinkerAgent:
    return LinkerAgent(db=None, job_id=1)  # type: ignore[arg-type]


class TestLinksIntoARenamedHeading:
    ROUTE = "/app/projects/7/docs/guides/getting-started"

    def test_a_same_page_fragment_degrades_to_text(self, linker) -> None:
        """Already the behaviour, and asserted here because the rename is what
        creates the dead fragment — this is the case that was thought to cover
        everything."""
        md = "## Development tips\n\nSee [the tips](#development-and-observability-tips)."

        out, report = linker._link_one(md, 7, {}, {"address": "guides/getting-started"})

        assert "(#development-and-observability-tips)" not in out
        assert "the tips" in out
        assert report["dead_anchors"] == [OLD_ANCHOR]

    def test_a_cross_page_fragment_is_checked_against_that_page(self, linker) -> None:
        md = f"See [the tips]({self.ROUTE}#{OLD_ANCHOR})."
        anchors = {"guides/getting-started": {"development-tips"}}

        out, report = linker._link_one(md, 7, {}, {"address": "reference/config"}, anchors)

        assert report["stale_fragments"] == [f"guides/getting-started#{OLD_ANCHOR}"]
        # The page is still the right page — only the scroll target has gone, so the
        # link is trimmed rather than demoted to plain text.
        assert f"[the tips]({self.ROUTE})" in out

    def test_a_live_cross_page_fragment_is_untouched(self, linker) -> None:
        md = f"See [the tips]({self.ROUTE}#development-tips)."
        anchors = {"guides/getting-started": {"development-tips"}}

        out, report = linker._link_one(md, 7, {}, {"address": "reference/config"}, anchors)

        assert out == md
        assert report["stale_fragments"] == []

    def test_a_page_whose_headings_are_unknown_is_not_judged(self, linker) -> None:
        """Absence of evidence is not evidence of a dead fragment. Stripping one
        because the target was not loaded would break working links."""
        md = f"See [the tips]({self.ROUTE}#{OLD_ANCHOR})."

        out, report = linker._link_one(md, 7, {}, {"address": "reference/config"}, {})

        assert out == md
        assert report["stale_fragments"] == []

    def test_a_self_link_is_still_flattened(self, linker) -> None:
        """The pre-existing rule, which the fragment check runs alongside and must
        not have displaced."""
        md = f"See [this page]({self.ROUTE})."
        anchors = {"guides/getting-started": {"development-tips"}}

        out, _ = linker._link_one(md, 7, {}, {"address": "guides/getting-started"}, anchors)

        assert out == "See this page."

    def test_the_pages_own_links_are_repointed_not_flattened(self, linker) -> None:
        """The rename is known exactly, so a link to the old anchor is moved rather
        than degraded — flattening it would throw away a repairable reference."""
        md = (
            "## Development tips\n\nSee [the tips](#development-and-observability-tips)."
        )
        doc = {
            "address": "guides/getting-started",
            "anchor_renames": {OLD_ANCHOR: "development-tips"},
        }

        out, report = linker._link_one(md, 7, {}, doc, {})

        assert "[the tips](#development-tips)" in out
        assert report["dead_anchors"] == []
        assert report["repointed"] == 1

    def test_a_full_route_into_the_renamed_heading_is_repointed(self, linker) -> None:
        md = f"See [the tips]({self.ROUTE}#{OLD_ANCHOR})."
        doc = {
            "address": "guides/getting-started",
            "anchor_renames": {OLD_ANCHOR: "development-tips"},
        }

        out, report = linker._link_one(md, 7, {}, doc, {})

        assert report["repointed"] == 1
        # Then flattened by the self-link rule, since it points at its own page.
        assert out == "See the tips."

    def test_an_image_is_never_touched(self, linker) -> None:
        """A rendered diagram arrives as a `data:` URI. Rewriting one destroys it."""
        md = "![diagram](data:image/png;base64,iVBORw0KGgo=)"

        out, _ = linker._link_one(md, 7, {}, {"address": "guides/getting-started"}, {})

        assert out == md
