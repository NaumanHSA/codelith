"""
The site as static HTML, in our own theme.

MkDocs and Docusaurus hand a team a project to build. This hands them a folder they
can drop on any web server, or open with `file://`, and it looks like the studio —
which matters, because the studio's reading surface is the product's own answer to
"what should generated documentation look like".

Constraints that shaped it, all of them the same constraint the studio has: **no
external network at runtime.** No CDN stylesheet, no web font, no analytics. One
inline stylesheet, one HTML file per page, and nothing else. A site produced here
works on an air-gapped machine, which is the claim the whole product rests on.

Markdown is rendered with `markdown-it-py` (CommonMark plus tables), which is the
same flavour `react-markdown` + `remark-gfm` gives the studio.
"""

from __future__ import annotations

import html
import io
import zipfile

from markdown_it import MarkdownIt

from app.features.documentation.formatters.site_tree import ExportPage, SiteTree, rewrite_links, slugify_filename

#: The studio's tokens, inlined. Kept in one string so the two stay comparable —
#: if `ui/src/styles/theme.css` moves, this is the one place to follow it.
_CSS = """\
:root {
  --paper:#f4f3ef; --panel:#fff; --sunk:#eceae4; --ink:#14120f; --ink-mid:#55504a;
  --ink-dim:#8a847c; --rule:#dcd8d0; --hot:#ff6b35; --hot-ink:#c2400c;
  --hot-wash:#fff0e9; --code-bg:#14120f; --code-text:#ded5c8;
}
* { box-sizing: border-box; }
body {
  margin:0; background:var(--paper); color:var(--ink);
  font:14px/1.6 ui-monospace, "JetBrains Mono", SFMono-Regular, Menlo, monospace;
}
a { color:var(--hot-ink); }
.wrap { display:grid; grid-template-columns:230px minmax(0,1fr); min-height:100vh; }
nav.side {
  border-right:1px solid var(--rule); background:var(--panel); padding:16px 0;
  position:sticky; top:0; align-self:start; max-height:100vh; overflow-y:auto;
}
nav.side .brand { display:block; padding:0 14px 12px; font-weight:700; letter-spacing:-.01em; }
nav.side h2 {
  margin:14px 0 4px; padding:0 14px; font-size:10px; font-weight:600;
  letter-spacing:.12em; text-transform:uppercase; color:var(--ink-dim);
}
nav.side a {
  display:block; padding:5px 14px; font-size:12px; color:var(--ink-mid); text-decoration:none;
}
nav.side a:hover { background:var(--sunk); color:var(--ink); }
nav.side a.on { background:var(--hot-wash); color:var(--hot-ink); font-weight:600;
  box-shadow:inset 3px 0 0 var(--hot); }
main { padding:28px 34px 64px; max-width:900px; }
article { border:1px solid var(--rule); background:var(--panel); padding:22px 30px; }
h1 { font-size:22px; letter-spacing:-.02em; margin:0 0 6px; }
h2 { font-size:16px; margin:28px 0 10px; padding-bottom:6px; border-bottom:1px solid var(--rule); }
h3 { font-size:13.5px; margin:20px 0 8px; }
p, li { color:var(--ink-mid); }
code { background:var(--sunk); padding:1px 4px; font-size:12.5px; }
pre { background:var(--code-bg); color:var(--code-text); padding:14px; overflow-x:auto; }
pre code { background:none; color:inherit; padding:0; }
table { border-collapse:collapse; width:100%; font-size:12.5px; }
th, td { border:1px solid var(--rule); padding:6px 9px; text-align:left; }
th { background:var(--sunk); }
.meta { font-size:11px; color:var(--ink-dim); margin:0 0 18px; }
.foot { display:flex; justify-content:space-between; gap:12px; margin-top:22px; font-size:12px; }
.foot a { text-decoration:none; border:1px solid var(--rule); background:var(--panel);
  padding:9px 12px; flex:1; }
.foot a:hover { border-color:var(--ink); }
.foot .next { text-align:right; }
@media (max-width:820px) {
  .wrap { grid-template-columns:1fr; }
  nav.side { position:static; max-height:none; }
}
"""


class StaticSiteFormatter:
    """A ZIP of self-contained HTML — no build step, no network, no dependencies."""

    def __init__(self) -> None:
        self._md = MarkdownIt("commonmark").enable("table").enable("strikethrough")

    def format_site_tree(self, tree: SiteTree) -> bytes:
        written = [
            (section, [p for p in section.pages if p.content_markdown.strip()])
            for section in tree.sections
        ]
        written = [(s, pages) for s, pages in written if pages]
        order = [p for _, pages in written for p in pages]

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("assets/theme.css", _CSS)
            zf.writestr("index.html", self._index(tree, written))
            for i, page in enumerate(order):
                folder = slugify_filename(page.section_slug)
                zf.writestr(
                    f"{folder}/{slugify_filename(page.slug)}.html",
                    self._page(
                        tree, written, page,
                        prev=order[i - 1] if i else None,
                        next_=order[i + 1] if i + 1 < len(order) else None,
                    ),
                )
        return buf.getvalue()

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _page(self, tree, written, page: ExportPage, *, prev, next_) -> str:
        body = self._md.render(
            rewrite_links(page.content_markdown, from_page=page.address, suffix=".html")
        )
        meta = ""
        if page.commit_sha or page.source_files:
            files = f"{len(page.source_files)} file{'' if len(page.source_files) == 1 else 's'}"
            sha = f" at {html.escape(page.commit_sha[:7])}" if page.commit_sha else ""
            meta = f'<p class="meta">Written from {files}{sha}.</p>'

        foot = '<div class="foot">'
        foot += (
            f'<a href="{self._href(page, prev)}">← {html.escape(prev.title)}</a>'
            if prev
            else "<span></span>"
        )
        foot += (
            f'<a class="next" href="{self._href(page, next_)}">{html.escape(next_.title)} →</a>'
            if next_
            else "<span></span>"
        )
        foot += "</div>"

        return self._shell(
            tree, written, active=page.address, depth=1,
            main=f"<article><h1>{html.escape(page.title)}</h1>{meta}{body}</article>{foot}",
            title=f"{page.title} · {tree.title}",
        )

    def _index(self, tree: SiteTree, written) -> str:
        parts = [f"<article><h1>{html.escape(tree.title)}</h1>"]
        if tree.home_markdown:
            parts.append(self._md.render(tree.home_markdown))
        for section, pages in written:
            parts.append(f"<h2>{html.escape(section.title)}</h2><ul>")
            for page in pages:
                href = f"{slugify_filename(page.section_slug)}/{slugify_filename(page.slug)}.html"
                intent = f" — {html.escape(page.intent)}" if page.intent else ""
                parts.append(f'<li><a href="{href}">{html.escape(page.title)}</a>{intent}</li>')
            parts.append("</ul>")
        parts.append("</article>")
        return self._shell(
            tree, written, active=None, depth=0, main="".join(parts), title=tree.title
        )

    def _shell(self, tree, written, *, active, depth, main, title) -> str:
        up = "../" * depth
        nav = [f'<a class="brand" href="{up}index.html">{html.escape(tree.title)}</a>']
        if tree.version_label:
            nav.append(
                f'<h2>version</h2><a href="{up}index.html">'
                f"{html.escape(tree.version_label)}</a>"
            )
        for section, pages in written:
            nav.append(f"<h2>{html.escape(section.title)}</h2>")
            for page in pages:
                href = (
                    f"{up}{slugify_filename(page.section_slug)}/"
                    f"{slugify_filename(page.slug)}.html"
                )
                on = " class=\"on\"" if page.address == active else ""
                nav.append(f'<a href="{href}"{on}>{html.escape(page.title)}</a>')

        return (
            "<!doctype html>\n"
            '<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(title)}</title>"
            f'<link rel="stylesheet" href="{up}assets/theme.css"></head>'
            f'<body><div class="wrap"><nav class="side">{"".join(nav)}</nav>'
            f"<main>{main}</main></div></body></html>\n"
        )

    @staticmethod
    def _href(from_page: ExportPage, to: ExportPage) -> str:
        name = f"{slugify_filename(to.slug)}.html"
        if to.section_slug == from_page.section_slug:
            return name
        return f"../{slugify_filename(to.section_slug)}/{name}"


__all__ = ["StaticSiteFormatter"]
