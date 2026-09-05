"""
Turning a site tree into a directory of files.

One interface, so publishing does not care which generator produced the output and a
second one can land without the build pipeline learning anything new.

The built-in renderer does not render. It wraps `StaticSiteFormatter`, which already
produces the whole site as HTML in the studio's theme with no build step and no
network, and unpacks its archive into the build directory. Reimplementing the same
HTML here would mean two renderers to keep correct and a slow divergence between what
you download and what you publish; extracting a zip in memory costs nothing and makes
those two byte-identical by construction.

`version` is not decoration. It goes into the content hash, so changing what a
renderer emits invalidates every publication built by the old one instead of letting
them report themselves as current.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class BuildResult:
    """What a renderer wrote."""

    file_count: int
    bytes_total: int
    page_count: int


class Renderer(Protocol):
    """A way of turning a `SiteTree` into files on disk."""

    name: str
    version: str

    def available(self) -> tuple[bool, str]:
        """
        Whether this can run here, and why not if it cannot.

        Asked before a renderer is offered rather than after it is chosen. The studio
        lists what the server says it can do, the same way document types are offered
        from the evidence that supports them, so nobody picks a renderer that is
        going to fail at the build step.
        """
        ...

    def build(self, tree, out_dir: Path) -> BuildResult:
        """Write the site into `out_dir`, which exists and is empty."""
        ...


class BuiltinRenderer:
    """
    The studio's own theme, as static files.

    Always available: it is string formatting over markdown that is already in
    memory, with no external tool, no dependency beyond what the API already imports
    and no network at any point.
    """

    name = "builtin"
    #: Bump when the emitted HTML changes. See the module docstring.
    version = "1"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def build(self, tree, out_dir: Path) -> BuildResult:
        from codelith.apps.documentation.formatters.static_site import StaticSiteFormatter

        archive = StaticSiteFormatter().format_site_tree(tree)

        files = 0
        total = 0
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                # The archive is ours, but it is still an archive: a member named
                # `../x` would write outside the build directory, and the one place
                # that must never happen is the one serving files to a browser.
                target = (out_dir / info.filename).resolve()
                if out_dir.resolve() not in target.parents:
                    raise ValueError(f"Renderer produced a path outside the build: {info.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                data = zf.read(info)
                target.write_bytes(data)
                files += 1
                total += len(data)

        pages = sum(len(section.pages) for section in tree.sections)
        return BuildResult(file_count=files, bytes_total=total, page_count=pages)


#: Every renderer the product knows about. Ordered, because the first available one
#: is the default the studio pre-selects.
RENDERERS: dict[str, Renderer] = {
    BuiltinRenderer.name: BuiltinRenderer(),
}

DEFAULT_RENDERER = BuiltinRenderer.name


def get_renderer(name: str | None) -> Renderer:
    """The named renderer, or the default. Raises `KeyError` for a name we do not have."""
    return RENDERERS[name or DEFAULT_RENDERER]


def available_renderers() -> list[dict]:
    """What this machine can actually build, for the studio to offer."""
    out = []
    for name, renderer in RENDERERS.items():
        ok, reason = renderer.available()
        out.append(
            {"name": name, "version": renderer.version, "available": ok, "reason": reason}
        )
    return out


__all__ = [
    "DEFAULT_RENDERER",
    "RENDERERS",
    "BuildResult",
    "BuiltinRenderer",
    "Renderer",
    "available_renderers",
    "get_renderer",
]
