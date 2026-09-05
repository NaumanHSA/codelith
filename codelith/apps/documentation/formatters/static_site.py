"""
The site as static HTML, in our own theme.

MkDocs and Docusaurus hand a team a project to build. This hands them a folder they
can drop on any web server, or open with `file://`, and it looks like the studio,
which matters: the studio's reading surface is the product's own answer to "what
should generated documentation look like".

**The navigation mirrors the studio's**, because a published site and the page that
wrote it should not disagree about the shape of the document. Sections are tabs along
the top, the pages of the open section fill the left rail, and the headings of the
page you are reading fill the right one. A single flat list of every page in the site
is what this used to do, and it stops being navigable at about fifteen pages.

**Diagrams are written out as files.** They arrive in the markdown as
`data:image/svg+xml;base64,…`, and `markdown-it` refuses that URI: its link validator
allows `data:` for png, gif, jpeg and webp but not for svg, because an SVG data URI
can carry script. So the image silently rendered as its own literal source text, a
screenful of base64 in the middle of the page. Extracting each one to
`assets/diagrams/*.svg` sidesteps the validator, cuts the page weight enormously, and
is safe for the reason the validator exists: an SVG loaded through `<img src>` cannot
execute script, only an inlined or navigated one can.

Constraints that shaped it, all the same constraint the studio has: **no external
network at runtime.** No CDN stylesheet, no web font, no analytics. One stylesheet,
one small script for the theme toggle, one HTML file per page. A site produced here
works on an air-gapped machine, which is the claim the whole product rests on, and
`publishing/verify.py` asserts it against the built output every time.
"""

from __future__ import annotations

import base64
import hashlib
import html
import io
import re
import zipfile

from markdown_it import MarkdownIt

from codelith.apps.documentation.formatters.site_tree import (
    ExportPage,
    SiteTree,
    rewrite_links,
    slugify_filename,
)

#: The diagram-source blocks the studio folds under each diagram. They exist so an
#: author can check what was drawn; a published site has readers, not authors, and a
#: page of D2 source between two paragraphs is noise to every one of them.
_DIAGRAM_SOURCE = re.compile(
    r"<details>\s*<summary>\s*Diagram source\s*</summary>.*?</details>",
    re.S | re.I,
)

_ANCHOR_SAFE = re.compile(r"[^a-z0-9]+")


def _anchor(text: str) -> str:
    return _ANCHOR_SAFE.sub("-", text.lower()).strip("-") or "section"


class StaticSiteFormatter:
    """A ZIP of self-contained HTML — no build step, no network, no dependencies."""

    def __init__(self) -> None:
        self._md = MarkdownIt("commonmark").enable("table").enable("strikethrough")

        # The refusal happens at parse time, not at render time: a rejected link is
        # never turned into an image token at all, so extracting one afterwards is
        # too late. Permitting it here lets the token pass below pull it out to a
        # file, and the URI itself never reaches the output. Should extraction fail,
        # what is emitted is an `<img src="data:image/svg+xml…">`, which is the safe
        # half of what the validator guards: an SVG in an `<img>` cannot script, only
        # one that is inlined or navigated to can.
        default = self._md.validateLink

        def allow_inline_svg(url: str) -> bool:
            return url.startswith("data:image/svg+xml;base64,") or default(url)

        self._md.validateLink = allow_inline_svg

    def format_site_tree(self, tree: SiteTree) -> bytes:
        written = [
            (section, [p for p in section.pages if p.content_markdown.strip()])
            for section in tree.sections
        ]
        written = [(s, pages) for s, pages in written if pages]
        order = [p for _, pages in written for p in pages]

        #: Filled as pages render, because a diagram is only discovered by reading one.
        assets: dict[str, bytes] = {}

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("assets/theme.css", _CSS)
            zf.writestr("assets/theme.js", _JS)

            pages_html: list[tuple[str, str]] = []
            for i, page in enumerate(order):
                folder = slugify_filename(page.section_slug)
                pages_html.append(
                    (
                        f"{folder}/{slugify_filename(page.slug)}.html",
                        self._page(
                            tree, written, page, assets,
                            prev=order[i - 1] if i else None,
                            next_=order[i + 1] if i + 1 < len(order) else None,
                        ),
                    )
                )

            zf.writestr("index.html", self._index(tree, written, assets))
            for name, body in pages_html:
                zf.writestr(name, body)
            for name, data in assets.items():
                zf.writestr(name, data)

        return buf.getvalue()

    # ── Markdown ──────────────────────────────────────────────────────────────

    def _render(self, markdown: str, *, assets: dict[str, bytes], depth: int):
        """
        Markdown to HTML, plus the headings the right rail needs.

        Done over the token stream rather than by patching the HTML afterwards,
        because both jobs here need to *change* tokens: headings gain an id so they
        can be linked, and images with a `data:` source are pulled out to files.
        """
        tokens = self._md.parse(markdown)
        headings: list[tuple[int, str, str]] = []

        for i, token in enumerate(tokens):
            if token.type == "heading_open" and token.tag in ("h2", "h3"):
                inline = tokens[i + 1] if i + 1 < len(tokens) else None
                text = (inline.content if inline else "").strip()
                slug = _anchor(text)
                token.attrSet("id", slug)
                headings.append((2 if token.tag == "h2" else 3, slug, text))

            if token.type == "inline" and token.children:
                for child in token.children:
                    if child.type == "image":
                        src = child.attrGet("src") or ""
                        if src.startswith("data:"):
                            child.attrSet("src", _extract(src, assets, depth))

        return self._md.renderer.render(tokens, self._md.options, {}), headings

    # ── Pages ─────────────────────────────────────────────────────────────────

    def _page(self, tree, written, page: ExportPage, assets, *, prev, next_) -> str:
        source = _DIAGRAM_SOURCE.sub("", page.content_markdown)
        body, headings = self._render(
            rewrite_links(source, from_page=page.address, suffix=".html", present=tree.addresses),
            assets=assets,
            depth=1,
        )

        meta = ""
        if page.commit_sha or page.source_files:
            files = f"{len(page.source_files)} file{'' if len(page.source_files) == 1 else 's'}"
            sha = f" at <code>{html.escape(page.commit_sha[:7])}</code>" if page.commit_sha else ""
            meta = f'<p class="meta">Written from {files}{sha}.</p>'

        lead = f'<p class="lead">{html.escape(page.intent)}</p>' if page.intent else ""

        nav = '<nav class="pager">'
        nav += (
            f'<a href="{self._href(page, prev)}"><span>Previous</span>{html.escape(prev.title)}</a>'
            if prev
            else "<span></span>"
        )
        nav += (
            f'<a class="next" href="{self._href(page, next_)}">'
            f"<span>Next</span>{html.escape(next_.title)}</a>"
            if next_
            else "<span></span>"
        )
        nav += "</nav>"

        return self._shell(
            tree,
            written,
            active=page.address,
            section=page.section_slug,
            depth=1,
            headings=headings,
            main=(
                f'<article class="doc"><h1>{html.escape(page.title)}</h1>'
                f"{lead}{meta}{body}</article>{nav}"
            ),
            title=f"{page.title} · {tree.title}",
        )

    def _index(self, tree: SiteTree, written, assets) -> str:
        """
        The front page: what this is, then where to go.

        The overview is the only place a reader learns what the codebase does before
        committing to a page, so it leads, and the section cards below are the map.
        """
        parts = [f'<article class="doc"><h1>{html.escape(tree.title)}</h1>']

        pages = sum(len(p) for _, p in written)
        parts.append(
            '<p class="lead">Documentation written from the code itself, '
            f"{pages} page{'' if pages == 1 else 's'} across "
            f"{len(written)} section{'' if len(written) == 1 else 's'}.</p>"
        )

        if tree.home_markdown:
            body, _ = self._render(tree.home_markdown, assets=assets, depth=0)
            parts.append(body)

        parts.append('<h2 id="sections">Sections</h2><div class="cards">')
        for section, section_pages in written:
            parts.append(
                f'<div class="card"><h3>{html.escape(section.title)}</h3><ul>'
            )
            for page in section_pages:
                href = f"{slugify_filename(page.section_slug)}/{slugify_filename(page.slug)}.html"
                parts.append(f'<li><a href="{href}">{html.escape(page.title)}</a></li>')
            parts.append("</ul></div>")
        parts.append("</div></article>")

        return self._shell(
            tree, written, active=None, section=None, depth=0,
            headings=[(2, "sections", "Sections")],
            main="".join(parts),
            title=tree.title,
        )

    # ── Chrome ────────────────────────────────────────────────────────────────

    def _shell(self, tree, written, *, active, section, depth, headings, main, title) -> str:
        up = "../" * depth

        # Sections are tabs. The open one decides what the left rail contains, which
        # is the whole reason this is not one flat list of every page in the site.
        tabs = [
            f'<a class="tab{" on" if active is None else ""}" href="{up}index.html">Overview</a>'
        ]
        for sec, pages in written:
            first = pages[0]
            href = f"{up}{slugify_filename(first.section_slug)}/{slugify_filename(first.slug)}.html"
            on = " on" if sec.slug == section else ""
            tabs.append(f'<a class="tab{on}" href="{href}">{html.escape(sec.title)}</a>')

        side = ""
        current = next((pages for sec, pages in written if sec.slug == section), None)
        if current:
            title_of = next(sec.title for sec, _ in written if sec.slug == section)
            side = f'<p class="rail-head">{html.escape(title_of)}</p><ul class="rail">'
            for page in current:
                href = (
                    f"{up}{slugify_filename(page.section_slug)}/"
                    f"{slugify_filename(page.slug)}.html"
                )
                on = ' class="on"' if page.address == active else ""
                side += f'<li><a href="{href}"{on}>{html.escape(page.title)}</a></li>'
            side += "</ul>"
        else:
            side = '<p class="rail-head">Contents</p><ul class="rail">'
            for sec, pages in written:
                first = pages[0]
                href = (
                    f"{up}{slugify_filename(first.section_slug)}/"
                    f"{slugify_filename(first.slug)}.html"
                )
                side += f'<li><a href="{href}">{html.escape(sec.title)}</a></li>'
            side += "</ul>"

        toc = ""
        if headings:
            toc = '<p class="rail-head">On this page</p><ul class="toc">'
            for level, slug, text in headings:
                toc += f'<li class="l{level}"><a href="#{slug}">{html.escape(text)}</a></li>'
            toc += "</ul>"

        version = (
            f'<span class="version">{html.escape(tree.version_label)}</span>'
            if tree.version_label
            else ""
        )

        return (
            "<!doctype html>\n"
            '<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(title)}</title>"
            f'<link rel="stylesheet" href="{up}assets/theme.css">'
            # Inline and first, so the stored theme is applied before the first paint.
            # A toggle that flashes the wrong theme on every navigation is worse than
            # no toggle.
            "<script>try{var t=localStorage.getItem('codelith-theme');"
            "if(t)document.documentElement.dataset.theme=t;}catch(e){}</script>"
            "</head><body>"
            '<header class="topbar"><div class="topbar-in">'
            f'<a class="brand" href="{up}index.html">{_LOGO}'
            f'<span class="brand-name">code<i>·</i>lith</span></a>'
            f'<span class="sep"></span><span class="site">{html.escape(tree.title)}</span>'
            f"{version}"
            '<button class="theme" type="button" aria-label="Switch between light and dark">'
            f"{_SUN}{_MOON}</button>"
            "</div></header>"
            f'<nav class="tabs"><div class="tabs-in">{"".join(tabs)}</div></nav>'
            '<div class="shell">'
            f'<aside class="left">{side}</aside>'
            f"<main>{main}</main>"
            f'<aside class="right">{toc}</aside>'
            "</div>"
            '<footer><div class="footer-in">'
            f"<span>{html.escape(tree.title)}</span>"
            '<span class="by">Written from the code by '
            '<strong>Codelith</strong>. Nothing here left the machine that built it.'
            "</span>"
            "</div></footer>"
            f'<script src="{up}assets/theme.js"></script>'
            "</body></html>\n"
        )

    @staticmethod
    def _href(from_page: ExportPage, to: ExportPage) -> str:
        name = f"{slugify_filename(to.slug)}.html"
        if to.section_slug == from_page.section_slug:
            return name
        return f"../{slugify_filename(to.section_slug)}/{name}"


def _extract(data_uri: str, assets: dict[str, bytes], depth: int) -> str:
    """
    A `data:` image, written out as a file and referenced by path.

    Named by the digest of its own bytes, so a diagram repeated across pages is
    stored once. Falls back to leaving the URI alone if it cannot be decoded: a
    diagram that fails to extract should degrade to the old behaviour, not take the
    build down.
    """
    match = re.match(r"data:image/([a-zA-Z0-9.+-]+);base64,(.*)$", data_uri, re.S)
    if not match:
        return data_uri
    kind, payload = match.group(1), match.group(2)
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception:
        return data_uri

    ext = {"svg+xml": "svg", "png": "png", "jpeg": "jpg", "gif": "gif", "webp": "webp"}.get(
        kind, "bin"
    )
    name = f"assets/diagrams/{hashlib.sha256(raw).hexdigest()[:16]}.{ext}"
    assets[name] = raw
    return f"{'../' * depth}{name}"


_LOGO = (
    '<svg class="mark" width="20" height="20" viewBox="0 0 150 150" fill="none" aria-hidden="true">'
    '<path fill="currentColor" d="m52.6 142.8c-1.4-0.6-12.6-4.8-20.2-7.4-2.8-1.1-5.2-4.3-5.2-8.4v-92.6'
    "c0-5.5 3.6-10.5 8.1-11.7l58.7-15.3c1.4-0.4 3.4-0.4 4.8-0.1l14.4 4.6 0.3 0.1-56.4 16.2c-5.3 1.4-10 "
    '6.7-10 13.5v93.1c0 4.5 2 7.2 5.5 8z"/>'
    '<path fill="currentColor" d="m114.6 124.3-56.4 16.1c-4.2 1-8-1.5-8-6v-92.4c0-5 3.7-9.7 8-11.1l56.4'
    '-15.9c4.6-1.4 8 1.3 8 6.1v91.9c0.1 5.4-3.4 10.2-8 11.3z"/>'
    '<path fill="var(--bg)" d="m74.8 62.3-14.4 17.4c-0.7 0.9-1.1 1.8-1 2.8s0.3 1.8 1.1 2.3l14.5 10.4v-8.1'
    'l-8.7-6.3 8.6-10.3v-8.2h-0.1z"/>'
    '<polygon fill="var(--bg)" points="77.9 97 83.6 95.4 93.1 54.2 87.1 55.9"/>'
    '<path fill="var(--bg)" d="m111 66.6-14.9-10.3v8.4l8.7 6.3-8.7 10.2v8.2l15-17.4c1.7-1.8 1.8-4.4-0.1-5.4z"/>'
    "</svg>"
)

_SUN = (
    '<svg class="sun" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/>'
    '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4'
    'M17.7 6.3l1.4-1.4"/></svg>'
)
_MOON = (
    '<svg class="moon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/></svg>'
)

#: Remembers the choice, and nothing else. No analytics, no beacons, no network.
_JS = """(function () {
  var root = document.documentElement;
  var key = 'codelith-theme';
  function current() {
    if (root.dataset.theme) return root.dataset.theme;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  }
  var button = document.querySelector('.theme');
  if (!button) return;
  button.addEventListener('click', function () {
    var next = current() === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem(key, next); } catch (e) {}
  });
})();
"""

_CSS = """/* Codelith published documentation.
   Two palettes over one set of tokens, so the toggle swaps values rather than rules.
   No web font: the stacks below are what the reader already has. */
:root {
  --bg: #f4f3ef;
  --panel: #ffffff;
  --sunk: #eceae4;
  --ink: #14120f;
  --ink-mid: #55504a;
  --ink-dim: #8a847c;
  --rule: #dcd8d0;
  --hot: #ff6b35;
  --hot-ink: #c2400c;
  --hot-wash: #fff0e9;
  --code-bg: #f1efe9;
  --shadow: 0 1px 2px rgba(20, 18, 15, 0.05);
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
:root[data-theme='dark'] {
  --bg: #14120f;
  --panel: #1c1a16;
  --sunk: #211e1a;
  --ink: #f2efe9;
  --ink-mid: #b8b1a6;
  --ink-dim: #8a847c;
  --rule: #322e28;
  --hot: #ff7a49;
  --hot-ink: #ff9166;
  --hot-wash: #2a1d16;
  --code-bg: #211e1a;
  --shadow: none;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme='light']) {
    --bg: #14120f;
    --panel: #1c1a16;
    --sunk: #211e1a;
    --ink: #f2efe9;
    --ink-mid: #b8b1a6;
    --ink-dim: #8a847c;
    --rule: #322e28;
    --hot: #ff7a49;
    --hot-ink: #ff9166;
    --hot-wash: #2a1d16;
    --code-bg: #211e1a;
    --shadow: none;
  }
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 108px; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--sans);
  font-size: 15px;
  line-height: 1.7;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--hot-ink); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── Top bar ─────────────────────────────────────────────────────────── */
.topbar {
  position: sticky; top: 0; z-index: 20;
  background: var(--panel);
  border-bottom: 1px solid var(--rule);
}
.topbar-in {
  max-width: 1440px; margin: 0 auto;
  display: flex; align-items: center; gap: 12px;
  padding: 10px 24px;
}
.brand { display: flex; align-items: center; gap: 8px; color: var(--hot); }
.brand:hover { text-decoration: none; }
.brand-name {
  font-family: var(--mono); font-size: 14px; font-weight: 700;
  letter-spacing: -0.03em; color: var(--ink);
}
.brand-name i { color: var(--hot); font-style: normal; }
.sep { width: 1px; height: 18px; background: var(--rule); }
.site {
  font-family: var(--mono); font-size: 12.5px; color: var(--ink-mid);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.version {
  font-family: var(--mono); font-size: 10px; letter-spacing: .08em;
  text-transform: uppercase; color: var(--hot-ink);
  border: 1px solid var(--hot); border-radius: 3px; padding: 2px 6px;
}
.theme {
  margin-left: auto; display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; cursor: pointer;
  background: transparent; color: var(--ink-mid);
  border: 1px solid var(--rule); border-radius: 4px;
}
.theme:hover { color: var(--ink); border-color: var(--ink-dim); }
.theme .moon { display: none; }
:root[data-theme='dark'] .theme .sun { display: none; }
:root[data-theme='dark'] .theme .moon { display: inline; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme='light']) .theme .sun { display: none; }
  :root:not([data-theme='light']) .theme .moon { display: inline; }
}

/* ── Section tabs ────────────────────────────────────────────────────── */
.tabs {
  position: sticky; top: 51px; z-index: 19;
  background: var(--panel); border-bottom: 1px solid var(--rule);
}
.tabs-in {
  max-width: 1440px; margin: 0 auto; padding: 0 24px;
  display: flex; gap: 22px; overflow-x: auto; scrollbar-width: none;
}
.tabs-in::-webkit-scrollbar { display: none; }
.tab {
  padding: 11px 0; white-space: nowrap;
  font-size: 13px; color: var(--ink-mid);
  border-bottom: 2px solid transparent;
}
.tab:hover { color: var(--ink); text-decoration: none; }
.tab.on { color: var(--ink); font-weight: 600; border-bottom-color: var(--hot); }

/* ── Three columns ───────────────────────────────────────────────────── */
.shell {
  max-width: 1440px; margin: 0 auto; padding: 0 24px;
  display: grid; grid-template-columns: 232px minmax(0, 1fr) 200px; gap: 40px;
  align-items: start;
}
.left, .right { position: sticky; top: 104px; padding: 26px 0; max-height: calc(100vh - 104px); overflow-y: auto; }
.rail-head {
  margin: 0 0 10px; font-family: var(--mono); font-size: 10px;
  letter-spacing: .12em; text-transform: uppercase; color: var(--ink-dim);
}
.rail, .toc { list-style: none; margin: 0; padding: 0; }
.rail li { margin: 0 0 2px; }
.rail a {
  display: block; padding: 5px 10px; border-radius: 4px;
  font-size: 13.5px; color: var(--ink-mid); border-left: 2px solid transparent;
}
.rail a:hover { background: var(--sunk); color: var(--ink); text-decoration: none; }
.rail a.on {
  color: var(--hot-ink); background: var(--hot-wash);
  border-left-color: var(--hot); font-weight: 600;
}
.toc li { margin: 0 0 1px; }
.toc a {
  display: block; padding: 3px 0 3px 10px;
  border-left: 2px solid var(--rule);
  font-size: 12.5px; color: var(--ink-dim); line-height: 1.45;
}
.toc a:hover { color: var(--hot-ink); border-left-color: var(--hot); text-decoration: none; }
.toc .l3 a { padding-left: 22px; font-size: 12px; }

main { min-width: 0; padding: 30px 0 56px; }

/* ── The page ────────────────────────────────────────────────────────── */
.doc {
  background: var(--panel); border: 1px solid var(--rule); border-radius: 6px;
  padding: 34px 40px 40px; box-shadow: var(--shadow);
}
.doc h1 {
  margin: 0 0 6px; font-family: var(--mono);
  font-size: 27px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.15;
}
.doc h2 {
  margin: 40px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--rule);
  font-family: var(--mono); font-size: 18px; font-weight: 700; letter-spacing: -0.02em;
}
.doc h3 { margin: 28px 0 8px; font-family: var(--mono); font-size: 14.5px; font-weight: 700; }
.doc h4 { margin: 22px 0 6px; font-size: 13.5px; font-weight: 700; color: var(--ink-mid); }
.doc p { margin: 0 0 15px; color: var(--ink-mid); }
.doc li { color: var(--ink-mid); margin: 0 0 5px; }
.doc strong { color: var(--ink); font-weight: 600; }
.lead { font-size: 14.5px; color: var(--ink-dim) !important; margin-bottom: 18px !important; }
.meta {
  font-family: var(--mono); font-size: 11px; color: var(--ink-dim) !important;
  border-left: 2px solid var(--rule); padding-left: 10px; margin-bottom: 22px !important;
}
.doc code {
  font-family: var(--mono); font-size: 0.87em;
  background: var(--code-bg); border: 1px solid var(--rule); border-radius: 3px;
  padding: 1px 5px; color: var(--ink);
}
.doc pre {
  background: var(--code-bg); border: 1px solid var(--rule); border-radius: 5px;
  padding: 14px 16px; overflow-x: auto; margin: 0 0 18px;
}
.doc pre code { background: none; border: 0; padding: 0; font-size: 12.5px; line-height: 1.6; }
.doc img { max-width: 100%; height: auto; display: block; margin: 18px auto; }
.doc table { width: 100%; border-collapse: collapse; margin: 0 0 18px; font-size: 13.5px; }
.doc th, .doc td { border: 1px solid var(--rule); padding: 7px 10px; text-align: left; }
.doc th { background: var(--sunk); font-weight: 600; }
.doc blockquote {
  margin: 0 0 18px; padding: 2px 16px;
  border-left: 3px solid var(--hot); background: var(--hot-wash);
  border-radius: 0 4px 4px 0;
}
.doc hr { border: 0; border-top: 1px solid var(--rule); margin: 30px 0; }

/* ── Section cards on the front page ─────────────────────────────────── */
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 14px; }
.card { border: 1px solid var(--rule); border-radius: 5px; padding: 14px 16px; background: var(--bg); }
.card h3 { margin: 0 0 8px; font-family: var(--mono); font-size: 13px; }
.card ul { list-style: none; margin: 0; padding: 0; }
.card li { margin: 0 0 4px; font-size: 13px; }

/* ── Pager ───────────────────────────────────────────────────────────── */
.pager { display: flex; justify-content: space-between; gap: 14px; margin-top: 22px; }
.pager a {
  display: block; min-width: 0; padding: 12px 16px; border-radius: 5px;
  background: var(--panel); border: 1px solid var(--rule);
  font-size: 13.5px; font-weight: 600; color: var(--ink);
}
.pager a:hover { border-color: var(--hot); text-decoration: none; }
.pager a.next { text-align: right; }
.pager span {
  display: block; font-family: var(--mono); font-size: 10px;
  letter-spacing: .1em; text-transform: uppercase; color: var(--ink-dim);
  font-weight: 400; margin-bottom: 2px;
}

/* ── Footer ──────────────────────────────────────────────────────────── */
footer { border-top: 1px solid var(--rule); background: var(--panel); margin-top: 20px; }
.footer-in {
  max-width: 1440px; margin: 0 auto; padding: 20px 24px;
  display: flex; flex-wrap: wrap; gap: 6px 18px; align-items: baseline;
  font-family: var(--mono); font-size: 11px; color: var(--ink-dim);
}
.footer-in .by { margin-left: auto; }
.footer-in strong { color: var(--hot-ink); }

@media (max-width: 1180px) {
  .shell { grid-template-columns: 220px minmax(0, 1fr); }
  .right { display: none; }
}
@media (max-width: 820px) {
  .shell { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .left { position: static; max-height: none; padding: 18px 0 0; }
  .doc { padding: 22px 20px 26px; }
  .site { display: none; }
}
"""


__all__ = ["StaticSiteFormatter"]
