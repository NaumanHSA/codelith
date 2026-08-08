"""
Rendering D2 to SVG.

A lateral move from `mermaid_render`, not a new class of dependency: that already
shells out to a Node binary (`mmdc`) and renders server-side.

The published `@terrastruct/d2` package is a WASM library, not a CLI — so this goes
through `scripts/d2render.mjs`. That turned out better than the static binary this
was first written against: WASM runs wherever Node does, with no per-platform
executable to vendor, and it installs into `node_modules` exactly like mermaid-cli
so a job never needs the network.

**SVG, not PNG.** Roughly ten times smaller inside a `data:` URI, crisp at any zoom,
and — the reason it matters here — a themeable document rather than baked pixels.
The mermaid path passes `--background white`, which is a latent bug for the dark
variant the studio has not built yet. An SVG inherits.

Licensing note: D2's core is MPL-2.0, which is fine for this project. The TALA
layout engine is proprietary and paid, so layout stays on `dagre` or `elk`.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Open-source layout engines. TALA is deliberately not an option — see the module
#: docstring.
_LAYOUTS = ("dagre", "elk")


#: The shim, and the package it needs. Both must be present.
_SHIM = _PROJECT_ROOT / "scripts" / "d2render.mjs"
_PACKAGE = _PROJECT_ROOT / "node_modules" / "@terrastruct" / "d2"


def d2_cli() -> str | None:
    """
    The `node` that can run the shim, or `None` if D2 is not usable here.

    Returns the interpreter rather than a `d2` executable because the package is a
    WASM library: there is no binary to find. Both the shim and the installed
    package are checked, since either alone renders nothing.
    """
    settings = get_settings()
    if configured := (getattr(settings, "D2_NODE_PATH", "") or "").strip():
        node = configured if Path(configured).exists() else None
    else:
        node = shutil.which("node")

    if not node or not _SHIM.exists() or not _PACKAGE.exists():
        return None
    return node


def rendering_available() -> bool:
    """Whether a diagram can actually be turned into an image right now."""
    return bool(get_settings().DIAGRAM_RENDER_SVG and d2_cli())


def validate(source: str) -> tuple[bool, str]:
    """
    Whether D2 accepts this source, using D2's own parser.

    The mermaid path had only a best-effort regex, which is why invalid diagrams
    reached readers. Here the compiler is the check. When the binary is absent this
    returns `True` — an unverifiable diagram is not a failed one, and refusing to
    emit anything without the renderer would make diagrams depend on it twice.
    """
    node = d2_cli()
    if not node:
        return True, "d2 not installed — not validated"

    settings = get_settings()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "diagram.d2"
        path.write_text(source, encoding="utf-8")
        try:
            result = subprocess.run(  # noqa: S603 — fixed shim, temp-file argument
                [node, str(_SHIM), str(path), "--check"],
                capture_output=True,
                text=True,
                timeout=settings.DIAGRAM_RENDER_TIMEOUT_SECONDS,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return False, f"d2 could not be run: {exc}"

    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout or "invalid d2").strip()[:400]


def render_svg(source: str, *, layout: str = "dagre") -> bytes | None:
    """
    D2 source to SVG bytes, or `None` if it could not be rendered.

    Never raises. A diagram is an enhancement to a page, and a page without one is
    worth far more than a failed job.
    """
    settings = get_settings()
    if not settings.DIAGRAM_RENDER_SVG:
        return None
    node = d2_cli()
    if not node:
        logger.info("d2_not_installed")
        return None
    if layout not in _LAYOUTS:
        layout = "dagre"

    with tempfile.TemporaryDirectory() as tmp:
        source_path = Path(tmp) / "diagram.d2"
        out_path = Path(tmp) / "diagram.svg"
        source_path.write_text(source, encoding="utf-8")

        try:
            result = subprocess.run(  # noqa: S603 — fixed shim, temp-file arguments
                [node, str(_SHIM), str(source_path), str(out_path), layout],
                capture_output=True,
                text=True,
                timeout=settings.DIAGRAM_RENDER_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "d2_render_timeout", seconds=settings.DIAGRAM_RENDER_TIMEOUT_SECONDS
            )
            return None
        except OSError as exc:
            logger.warning("d2_render_failed", error=str(exc))
            return None

        if result.returncode != 0 or not out_path.exists():
            logger.warning("d2_render_failed", stderr=(result.stderr or "")[:300])
            return None

        data = out_path.read_bytes()

    if len(data) > settings.DIAGRAM_MAX_SVG_BYTES:
        logger.warning("d2_render_too_large", bytes=len(data))
        return None
    return data


__all__ = ["render_svg", "validate", "rendering_available", "d2_cli"]
