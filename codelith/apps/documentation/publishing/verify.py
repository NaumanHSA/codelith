"""
Checking a build before it becomes the thing people read.

Three questions, asked of the files themselves rather than of the tree they came
from. A renderer that drops a page still produces a tree that says the page exists;
only the directory knows what was actually written.

**Does every internal link go somewhere?** A published site with dead links is worse
than an export, because an export is obviously a snapshot and a site looks live.

**Is every referenced asset present?** A stylesheet that 404s turns the site into
unstyled markdown, and the reader has no way to tell that from it being broken.

**Does anything reach outside this machine on its own?** This is the one that is not
a nicety. The product's whole claim is that nothing leaves the box, and a renderer
that quietly pulls a font or an icon set from a CDN breaks that claim in the published
output, where it is hardest to notice and most visible to whoever was sent the link.

The distinction that matters is between a *subresource* and a *link*. A stylesheet, a
script, an image or a font is fetched the moment the page opens, with no one asking:
that is what breaks the claim, and it fails the build. An `<a href>` fetches nothing
until a reader chooses to click it, and forbidding those would mean no published page
could cite a repository, an RFC or a vendor's documentation — which is most of what
technical writing does. The first version of this check did not draw that line, and
refused a real site for linking to its own GitHub repository in a sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

#: Anything the browser fetches without being asked: `src` on any element, and `href`
#: on a `<link>`. These are what can leave the machine on their own.
_SUBRESOURCE = re.compile(
    r"""src\s*=\s*["']([^"']+)["']"""
    r"""|<link\s[^>]*?href\s*=\s*["']([^"']+)["']""",
    re.I,
)

#: Somewhere a reader can go. Checked for existence when it is local, and left alone
#: when it is not: clicking is a decision, and a document that cannot cite a URL is
#: not a document.
_LINK = re.compile(r"""<a\s[^>]*?href\s*=\s*["']([^"']+)["']""", re.I)

#: `url(...)` inside a stylesheet, which is where a web font hides.
_CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)""", re.I)

#: Schemes that never leave the machine.
_LOCAL_SCHEMES = {"", "data", "mailto", "tel"}


@dataclass
class VerifyReport:
    links_checked: int = 0
    assets_checked: int = 0
    #: Links pointing off the machine. Counted, not refused: reported so a reader of
    #: the build record can see there are some.
    offsite_links: int = 0
    broken: list[str] = field(default_factory=list)
    external: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.broken and not self.external

    def as_dict(self) -> dict:
        return {
            "links": self.links_checked,
            "assets": self.assets_checked,
            "offsite_links": self.offsite_links,
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
            subresources = [a or b for a, b in _SUBRESOURCE.findall(text)]
            _check(root, path, subresources, report, kind="asset")
            _check(root, path, _LINK.findall(text), report, kind="link")
        elif suffix == ".css":
            text = path.read_text(encoding="utf-8", errors="replace")
            _check(root, path, _CSS_URL.findall(text), report, kind="asset")

    return report


def _check(
    root: Path, source: Path, refs: list[str], report: VerifyReport, *, kind: str
) -> None:
    for raw in refs:
        ref = raw.strip()
        if not ref or ref.startswith("#"):
            continue  # an in-page anchor, resolved by the browser

        parsed = urlparse(ref)
        scheme = parsed.scheme.lower()
        offsite = scheme not in _LOCAL_SCHEMES or bool(parsed.netloc)

        if offsite:
            if kind == "asset":
                # Fetched the moment the page opens. The claim, broken.
                report.external.append(f"{source.relative_to(root).as_posix()} -> {ref}")
            else:
                # A link. Nothing happens until somebody clicks it, and a page that
                # may not cite a URL is not documentation.
                report.offsite_links += 1
            continue
        if scheme:
            continue  # data:, mailto:, tel: — local, and nothing to resolve

        target = unquote(parsed.path)
        if not target:
            continue

        base = root if target.startswith("/") else source.parent
        resolved = (base / target.lstrip("/")).resolve()

        if kind == "asset":
            report.assets_checked += 1
        else:
            report.links_checked += 1

        if resolved.is_dir():
            resolved = resolved / "index.html"
        if not resolved.exists():
            report.broken.append(f"{source.relative_to(root).as_posix()} -> {ref}")


__all__ = ["VerifyReport", "verify_build"]
