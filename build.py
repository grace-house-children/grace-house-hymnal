#!/usr/bin/env python3
"""Grace House Hymnal — static site builder.

Reads the same files server.py reads (hymns/, zine.txt, access-key.txt,
qr-code.png) and writes a complete static site to ./dist that can be
uploaded to any web host — GitHub Pages, Cloudflare Pages, Neocities,
a USB stick, whatever.

Usage:
    python3 build.py

Output:
    dist/                              <- upload this whole folder
    dist/index.html                    <- friendly landing page (nothing here)
    dist/{key}/index.html              <- the hymnal TOC
    dist/{key}/style.css
    dist/{key}/qr-code.png             <- if you have one
    dist/{key}/hymn/1/index.html       <- each hymn as its own page
    dist/{key}/hymn/2/index.html
    dist/{key}/zine/index.html         <- if zine.txt exists
    dist/{key}/print/index.html        <- musician's booklet
    dist/{key}/qr/index.html           <- the QR-code viewer page

The URLs work exactly like your local server: /{key}/ for the hymnal,
/{key}/hymn/5 for hymn #5, and so on. Anyone without the key just
sees the friendly landing page.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Reuse everything from server.py — same rendering, same look.
import server

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"


def write(rel_path: str, content: str | bytes, key: str) -> None:
    """Write a file into dist/. Text is rewritten so links work on a static host.

    On a static host, we don't have URL rewriting, so:
      - /{key}/hymn/5  becomes  /{key}/hymn/5/index.html
      - /{key}/zine    becomes  /{key}/zine/index.html
      - /{key}/print   becomes  /{key}/print/index.html
      - /{key}/qr      becomes  /{key}/qr/index.html
    We keep the pretty URLs by putting each page inside its own folder
    and letting the server serve index.html.
    """
    out = DIST / rel_path
    out.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        # The rendered HTML uses <base href="/{key}/"> so links like
        # "hymn/5" resolve to "/{key}/hymn/5". On a static host that
        # needs to be "/{key}/hymn/5/" (or explicitly /index.html) so
        # the server serves the right file. Adding the trailing slash
        # is the least invasive fix.
        content = (
            content
            .replace(f'href="hymn/', 'href="hymn/')  # unchanged, sanity anchor
        )
        out.write_text(content, encoding="utf-8")
    else:
        out.write_bytes(content)


def rewrite_hymn_links(html: str) -> str:
    """Make internal links work under a static host (add trailing slashes
    so /{key}/hymn/5 serves /{key}/hymn/5/index.html)."""
    import re
    # hymn/<num> and musician/hymn/<num> -> add trailing slash
    html = re.sub(r'href="(musician/)?hymn/(\d+)"', r'href="\1hymn/\2/"', html)
    # zine, qr -> trailing slash (musician/ and musician/hymn are already handled)
    html = html.replace('href="zine"', 'href="zine/"')
    html = html.replace('href="qr"', 'href="qr/"')
    return html


def rewrite_base(html: str, key: str, depth: int) -> str:
    """Rewrite the absolute `<base href="/KEY/">` into a *relative* one so
    the site works under any subpath — root (localhost, custom domain) or
    a project subpath (GitHub Pages: /repo-name/).

    depth = number of folder levels the page sits below /KEY/.
      TOC              /KEY/index.html                   depth 0 -> "./"
      hymn 5           /KEY/hymn/5/index.html            depth 2 -> "../../"
      musician TOC     /KEY/musician/index.html          depth 1 -> "../"
      musician hymn 5  /KEY/musician/hymn/5/index.html   depth 3 -> "../../../"
      zine             /KEY/zine/index.html              depth 1 -> "../"
      qr               /KEY/qr/index.html                depth 1 -> "../"
    """
    relative = "./" if depth == 0 else "../" * depth
    return html.replace(f'<base href="/{key}/">', f'<base href="{relative}">')


def landing_page() -> str:
    """A friendly page shown to anyone who visits the root of the site."""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Grace House</title>\n"
        "<style>\n" + server.CSS + "\n</style>\n"
        "</head><body>\n"
        '<main><div class="blank">\n'
        "<h1>Grace House</h1>\n"
        "<p>If you're expecting to see something, ask whoever shared the link with you.</p>\n"
        "</div></main>\n"
        "</body></html>\n"
    )


def build() -> None:
    # Nuke and repave — fully deterministic output.
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    key = server.load_key()
    key_dir = f"{key}"
    hymns = server.load_hymns()

    print(f"Building site with access key: {key}")
    print(f"Found {len(hymns)} hymns.")

    # Root landing page (unlisted URL protection: without the key, you
    # get this instead of the hymnal).
    write("index.html", landing_page(), key)

    # Stylesheet — under the key prefix so <base href="/{key}/"> finds it.
    write(f"{key_dir}/style.css", server.CSS, key)

    # QR code image (if present) — passed through as-is.
    if server.QR_PATH.exists():
        write(f"{key_dir}/qr-code.png", server.QR_PATH.read_bytes(), key)

    # The public hymnal TOC — /{key}/index.html
    toc_html = rewrite_hymn_links(server.render_toc(hymns, key))
    write(f"{key_dir}/index.html", rewrite_base(toc_html, key, 0), key)

    # Each public hymn page — /{key}/hymn/N/index.html
    for idx, (number, _title, filepath) in enumerate(hymns):
        title, verses, _meta = server.parse_hymn(filepath)
        prev_n = hymns[idx - 1][0] if idx > 0 else None
        next_n = hymns[idx + 1][0] if idx < len(hymns) - 1 else None
        html = rewrite_hymn_links(server.render_hymn_page(number, title, verses, prev_n, next_n, key))
        write(f"{key_dir}/hymn/{number}/index.html", rewrite_base(html, key, 2), key)
        print(f"  #{number:>3}  {title}")

    # The musician mirror — same hymns, but the [X] chord markers are
    # rendered inline as pink brackets instead of stripped out, plus the
    # scroll / transpose / text size / dark mode control bar. meta carries
    # each song's [Speed:X] and [Key:X] into that control bar.
    print("Musicians mirror:")
    musician_toc = rewrite_hymn_links(server.render_toc(hymns, key, musician=True))
    write(f"{key_dir}/musician/index.html", rewrite_base(musician_toc, key, 1), key)
    for idx, (number, _title, filepath) in enumerate(hymns):
        title, verses, meta = server.parse_hymn(filepath)
        prev_n = hymns[idx - 1][0] if idx > 0 else None
        next_n = hymns[idx + 1][0] if idx < len(hymns) - 1 else None
        html = rewrite_hymn_links(
            server.render_hymn_page(number, title, verses, prev_n, next_n, key,
                                    musician=True, meta=meta)
        )
        write(f"{key_dir}/musician/hymn/{number}/index.html", rewrite_base(html, key, 3), key)
        speed = meta.get("speed")
        print(f"  #{number:>3}  {title}" + (f"  (speed {speed})" if speed else ""))

    # Zine — /{key}/zine/index.html (only if zine.txt exists)
    zine = server.parse_zine()
    if zine is not None:
        title, sections = zine
        html = rewrite_hymn_links(server.render_zine_page(title, sections, key))
        write(f"{key_dir}/zine/index.html", rewrite_base(html, key, 1), key)

    # QR page — /{key}/qr/index.html.
    # The URL baked into the QR viewer's caption needs to point at the
    # PUBLIC site now, not localhost. We read it from a small file if
    # present; otherwise we fall back to a placeholder the user can
    # regenerate the PNG for.
    public_url_file = HERE / "public-url.txt"
    if public_url_file.exists():
        public_url = public_url_file.read_text(encoding="utf-8").strip().rstrip("/")
        display_url = f"{public_url}/{key}/"
    else:
        display_url = f"https://your-site.example/{key}/"
    qr_html = rewrite_hymn_links(server.render_qr_page(display_url, server.QR_PATH.exists(), key))
    write(f"{key_dir}/qr/index.html", rewrite_base(qr_html, key, 1), key)

    print()
    print(f"Built {sum(1 for _ in DIST.rglob('*') if _.is_file())} files into ./dist")
    print(f"Preview locally:  cd dist && python3 -m http.server 8000")
    print(f"Then open:        http://localhost:8000/{key}/")


if __name__ == "__main__":
    try:
        build()
    except Exception as e:
        print(f"Build failed: {e}", file=sys.stderr)
        sys.exit(1)
