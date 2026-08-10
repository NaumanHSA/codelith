"""
Rendering Mermaid to PNG, locally.

Mermaid source in a fenced code block only becomes a picture if whatever displays the
document knows how to render it — and the studio's markdown pipeline does not, so
generated diagrams reached the reader as a wall of `graph TD` text. Exports are worse:
a DOCX or a MkDocs zip has no renderer at all.

So the pipeline renders the picture itself. `@mermaid-js/mermaid-cli` runs headless
Chrome through puppeteer, both installed locally — no network at job time, which is the
property the whole product rests on.

Rendering is best-effort by construction. A missing binary, a broken diagram or a slow
render returns `None`, and the caller falls back to publishing the source. A diagram is
an illustration; it must never be the reason a document fails.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import structlog

from codelith.config import get_settings

logger = structlog.get_logger(__name__)

#: Repo root — `node_modules/.bin/mmdc` is installed by the root package.json.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

#: Puppeteer needs --no-sandbox in most container and CI environments.
_PUPPETEER_CONFIG = '{"args":["--no-sandbox","--disable-setuid-sandbox"]}'


def mermaid_cli() -> str | None:
    """Locate `mmdc`: configured path, then the local install, then PATH."""
    settings = get_settings()
    if configured := (settings.MERMAID_CLI_PATH or "").strip():
        return configured if Path(configured).exists() else None

    local = _PROJECT_ROOT / "node_modules" / ".bin" / "mmdc"
    if local.exists():
        return str(local)
    return shutil.which("mmdc")


def rendering_available() -> bool:
    """
    Whether PNG rendering is switched on *and* possible.

    Callers need this distinction: a diagram that cannot be rendered because rendering
    is off is not a broken diagram, and treating it as one drops the diagram entirely
    instead of publishing its source.
    """
    return bool(get_settings().DIAGRAM_RENDER_PNG and mermaid_cli())


def render_png(diagram: str, *, scale: int = 2, background: str = "white") -> bytes | None:
    """
    Render Mermaid source to PNG bytes, or `None` if it cannot be rendered.

    Never raises: every failure path — no binary, bad syntax, timeout — degrades to
    `None` so the caller can publish the source instead.
    """
    settings = get_settings()
    if not settings.DIAGRAM_RENDER_PNG:
        return None

    binary = mermaid_cli()
    if not binary:
        logger.warning(
            "mermaid_cli_missing",
            hint="run `npm install` in the repo root, or set MERMAID_CLI_PATH",
        )
        return None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "diagram.mmd"
        target = tmp_path / "diagram.png"
        config = tmp_path / "puppeteer.json"
        source.write_text(diagram, encoding="utf-8")
        config.write_text(_PUPPETEER_CONFIG, encoding="utf-8")

        try:
            result = subprocess.run(  # noqa: S603 — fixed binary, temp-file arguments
                [
                    binary,
                    "--input", str(source),
                    "--output", str(target),
                    "--backgroundColor", background,
                    "--scale", str(scale),
                    "--puppeteerConfigFile", str(config),
                ],
                capture_output=True,
                timeout=settings.DIAGRAM_RENDER_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "mermaid_render_timeout", seconds=settings.DIAGRAM_RENDER_TIMEOUT_SECONDS
            )
            return None
        except OSError as exc:
            logger.warning("mermaid_render_failed", error=str(exc))
            return None

        if result.returncode != 0 or not target.exists():
            logger.warning(
                "mermaid_render_rejected",
                returncode=result.returncode,
                stderr=result.stderr.decode("utf-8", "replace")[-400:],
            )
            return None

        data = target.read_bytes()

    if not data:
        return None
    if len(data) > settings.DIAGRAM_MAX_PNG_BYTES:
        # Embedded as a data URI, an oversized image bloats every copy of the document.
        logger.warning("mermaid_render_too_large", bytes=len(data))
        return None
    return data


__all__ = ["mermaid_cli", "render_png", "rendering_available"]
