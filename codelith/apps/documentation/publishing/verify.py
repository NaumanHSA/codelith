"""
Checking a build before it becomes the thing people read.

Three questions, asked of the files themselves rather than of the tree they came
from. A renderer that drops a page still produces a tree that says the page exists;
only the directory knows what was actually written.

**Does every internal link go somewhere?** A published site with dead links is worse
than an export, because an export is obviously a snapshot and a site looks live.

**Is every referenced asset present?** A stylesheet that 404s turns the site into
unstyled markdown, and the reader has no way to tell that from it being broken.

**Does anything reach outside this machine?** This is the one that is not a nicety.
The product's whole claim is that nothing leaves the box, and a renderer that quietly
pulls a font or an icon set from a CDN breaks that claim in the published output,
where it is hardest to notice and most visible to whoever was sent the link. So it is
asserted against the built HTML, every time, and it fails the build.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

#: `href` and `src` on any element. Deliberately not an HTML parser: the check runs
#: over our own output, and a regex that over-matches costs a false failure while a
#: parser that under-matches costs a shipped external request.
_REF = re.compile(r"""(?:href|src)\s*=\s*["']([^"']+)["']""", re.I)

#: `url(...)` inside a stylesheet, which is where a web font hides.
_CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)""", re.I)

#: Schemes that never leave the machine.
_LOCAL_SCHEMES = {"", "data", "mailto", "tel"}


@dataclass
class VerifyReport:
    links_checked: int = 0
    assets_checked: int = 0
    broken: list[str] = field(default_factory=list)
    external: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.broken and not self.external

    def as_dict(self) -> dict:
        return {
            "links": self.links_checked,
            "assets": self.assets_checked,
            # Capped: a systematically broken build would otherwise write thousands
            # of near-identical strings into a JSON column nobody reads past the top.
            "broken": self.broken[:50],
            "external": self.external[:50],
            "broken_total": len(self.broken),
            "external_total": len(self.external),
        }


def verify_build(root: Path) -> VerifyReport:
    """Walk every HTML and CSS file in a build and report what it found."""
    report = VerifyReport()
    root = root.resolve()

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in {".html", ".htm"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            _check(root, path, _REF.findall(text), report, is_asset=False)
        elif suffix == ".css":
            text = path.read_text(encoding="utf-8", errors="replace")
            _check(root, path, _CSS_URL.findall(text), report, is_asset=True)

    return report


def _check(root: Path, source: Path, refs: list[str], report: VerifyReport, *, is_asset: bool) -> None:
    for raw in refs:
        ref = raw.strip()
        if not ref or ref.startswith("#"):
            continue  # an in-page anchor, resolved by the browser

        parsed = urlparse(ref)
        scheme = parsed.scheme.lower()

        if scheme not in _LOCAL_SCHEMES:
            # http, https, //cdn..., anything with a host. The claim, broken.
            report.external.append(f"{source.relative_to(root).as_posix()} -> {ref}")
            continue
        if parsed.netloc:
            # Protocol-relative: no scheme, but still a host.
            report.external.append(f"{source.relative_to(root).as_posix()} -> {ref}")
            continue
        if scheme:
            continue  # data:, mailto:, tel: — local, and nothing to resolve

        target = unquote(parsed.path)
        if not target:
            continue

        base = root if target.startswith("/") else source.parent
        resolved = (base / target.lstrip("/")).resolve()

        if is_asset:
            report.assets_checked += 1
        else:
            report.links_checked += 1

        if resolved.is_dir():
            resolved = resolved / "index.html"
        if not resolved.exists():
            report.broken.append(f"{source.relative_to(root).as_posix()} -> {ref}")


__all__ = ["VerifyReport", "verify_build"]
