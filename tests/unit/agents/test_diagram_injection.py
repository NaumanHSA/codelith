"""
How a diagram reaches the reader.

A fenced ```mermaid block is only a picture if whatever displays the document renders
Mermaid — the studio's markdown pipeline does not, and a DOCX export certainly does
not, so generated diagrams arrived as a wall of `graph TD` text. The formatter now
embeds the rendered PNG and keeps the source beneath it.
"""

from __future__ import annotations

import base64

from app.agents.formatter import FormatterAgent

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")


def inject(diagrams: list[dict]) -> str:
    return FormatterAgent._inject_diagrams(FormatterAgent, "# Doc\n\nBody.", diagrams)


class TestRenderedDiagrams:
    def test_the_image_is_embedded(self) -> None:
        out = inject([{"name": "Request Flow", "content": "graph TD\n A-->B", "png_base64": _PNG}])
        assert f"![Request Flow](data:image/png;base64,{_PNG})" in out

    def test_the_source_is_kept_alongside_it(self) -> None:
        out = inject([{"name": "Request Flow", "content": "graph TD\n A-->B", "png_base64": _PNG}])
        assert "<details>" in out
        assert "```mermaid\ngraph TD\n A-->B\n```" in out

    def test_the_source_is_collapsed_so_the_picture_leads(self) -> None:
        out = inject([{"name": "Flow", "content": "graph TD\n A-->B", "png_base64": _PNG}])
        assert out.index("data:image/png") < out.index("```mermaid")


class TestUnrenderedDiagrams:
    def test_source_is_published_when_rendering_failed(self) -> None:
        """Better a code block than nothing — rendering is best-effort."""
        out = inject([{"name": "Flow", "content": "graph TD\n A-->B", "png_base64": None}])
        assert "```mermaid\ngraph TD\n A-->B\n```" in out
        assert "data:image/png" not in out

    def test_missing_key_is_treated_as_unrendered(self) -> None:
        out = inject([{"name": "Flow", "content": "graph TD\n A-->B"}])
        assert "```mermaid" in out


class TestRoutingByDocument:
    def test_diagrams_carry_the_document_they_belong_to(self) -> None:
        """
        Run 2 generated two diagrams for an API document and injected neither, because
        injection was hardcoded to `architecture`.
        """
        diagrams = [
            {"name": "A", "content": "graph TD\n A-->B", "doc_type": "api", "png_base64": None},
            {"name": "B", "content": "graph TD\n C-->D", "doc_type": "architecture"},
        ]
        mine = [d for d in diagrams if d.get("doc_type") == "api"]
        out = inject(mine)
        assert "A-->B" in out
        assert "C-->D" not in out


class TestRendererIsOptional:
    def test_disabling_rendering_returns_none(self, monkeypatch) -> None:
        from app.config import get_settings
        from app.tools import mermaid_render

        get_settings.cache_clear()
        monkeypatch.setenv("DIAGRAM_RENDER_PNG", "false")
        try:
            assert mermaid_render.render_png("graph TD\n A-->B") is None
        finally:
            get_settings.cache_clear()

    def test_a_missing_binary_is_not_fatal(self, monkeypatch) -> None:
        from app.config import get_settings
        from app.tools import mermaid_render

        get_settings.cache_clear()
        monkeypatch.setenv("MERMAID_CLI_PATH", "/nonexistent/mmdc")
        try:
            assert mermaid_render.render_png("graph TD\n A-->B") is None
        finally:
            get_settings.cache_clear()


class TestRenderingAvailability:
    """
    `DIAGRAM_RENDER_PNG=false` must mean "publish the source", not "publish nothing".

    The agent treats a missing PNG as a failed diagram and drops it, which is right
    when rendering is available and wrong when it is switched off — that combination
    silently produced zero diagrams instead of falling back.
    """

    def test_unavailable_when_rendering_is_disabled(self, monkeypatch) -> None:
        from app.config import get_settings
        from app.tools.mermaid_render import rendering_available

        get_settings.cache_clear()
        monkeypatch.setenv("DIAGRAM_RENDER_PNG", "false")
        try:
            assert rendering_available() is False
        finally:
            get_settings.cache_clear()

    def test_unavailable_when_the_binary_is_missing(self, monkeypatch) -> None:
        from app.config import get_settings
        from app.tools.mermaid_render import rendering_available

        get_settings.cache_clear()
        monkeypatch.setenv("MERMAID_CLI_PATH", "/nonexistent/mmdc")
        try:
            assert rendering_available() is False
        finally:
            get_settings.cache_clear()
