#!/usr/bin/env python3
"""Grace House — static site builder.

Reads the same files server.py reads (hymns/, zine.txt, quote.txt,
events.txt) and writes a complete static site to ./dist that can be
uploaded to any web host — GitHub Pages, Cloudflare Pages, Neocities, a
USB stick, whatever.

Usage:
    python3 build.py

The access key:
    On GitHub, the key comes from the HYMNAL_KEY repository secret
    (Settings → Secrets and variables → Actions). On your own computer
    it comes from access-key.txt, which .gitignore keeps out of the repo.
    If GitHub has neither, the build stops instead of inventing a random
    key — the live site stays as it was.

Output:
    dist/                                <- upload this whole folder
    dist/index.html                      <- friendly landing page (nothing here)
    dist/{key}/index.html                <- front page: quote + section buttons
    dist/{key}/style.css
    dist/{key}/hymnal/index.html         <- the hymnal TOC
    dist/{key}/hymn/1/index.html         <- each hymn as its own page
    dist/{key}/musician/index.html       <- musician mirror TOC
    dist/{key}/musician/hymn/1/index.html
    dist/{key}/zine/index.html           <- the zine (or "coming soon")
    dist/{key}/events/index.html         <- calendar + events (or "coming soon")
    dist/{key}/who-we-are/index.html     <- "coming soon" pages for sections
    dist/{key}/tracts/index.html            that aren't built yet
    dist/{key}/kids/index.html
    dist/{key}/qr/index.html             <- QR code for the front page

The URLs work exactly like your local server. Anyone without the key
just sees the friendly landing page.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

# Reuse everything from server.py — same rendering, same look.
import server

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"


def write(rel_path: str, content: str | bytes) -> None:
    out = DIST / rel_path
    out.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        out.write_text(content, encoding="utf-8")
    else:
        out.write_bytes(content)


def rewrite_hymn_links(html: str) -> str:
    """Make internal links work under a static host (add trailing slashes
    so /{key}/hymn/5 serves /{key}/hymn/5/index.html)."""
    # hymn/<num> and musician/hymn/<num> -> add trailing slash
    html = re.sub(r'href="(musician/)?hymn/(\d+)"', r'href="\1hymn/\2/"', html)
    # zine, qr -> trailing slash (everything else is already written with one)
    html = html.replace('href="zine"', 'href="zine/"')
    html = html.replace('href="qr"', 'href="qr/"')
    return html


def rewrite_base(html: str, key: str, depth: int) -> str:
    """Rewrite the absolute `<base href="/KEY/">` into a *relative* one so
    the site works under any subpath — root (localhost, custom domain) or
    a project subpath (GitHub Pages: /repo-name/).

    depth = number of folder levels the page sits below /KEY/.
      front page       /KEY/index.html                   depth 0 -> "./"
      hymnal TOC       /KEY/hymnal/index.html            depth 1 -> "../"
      hymn 5           /KEY/hymn/5/index.html            depth 2 -> "../../"
      musician TOC     /KEY/musician/index.html          depth 1 -> "../"
      musician hymn 5  /KEY/musician/hymn/5/index.html   depth 3 -> "../../../"
      zine, qr, and each section page                    depth 1 -> "../"
    """
    relative = "./" if depth == 0 else "../" * depth
    return html.replace(f'<base href="/{key}/">', f'<base href="{relative}">')


def page_out(rel_path: str, html: str, key: str, depth: int) -> None:
    write(rel_path, rewrite_base(rewrite_hymn_links(html), key, depth))


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


def get_key() -> str:
    on_github = os.environ.get("GITHUB_ACTIONS") == "true"
    has_secret = bool(os.environ.get("HYMNAL_KEY", "").strip())
    if on_github and not has_secret:
        if not server.KEY_PATH.exists():
            raise RuntimeError(
                "No access key. Add a repository secret named HYMNAL_KEY "
                "(Settings → Secrets and variables → Actions)."
            )
        # Still works, but the key is sitting in the repo.
        print("::warning::Using access-key.txt from the repo. Add the HYMNAL_KEY "
              "secret and delete access-key.txt from GitHub.")
    elif on_github and server.KEY_PATH.exists():
        print("::warning::access-key.txt is still in the repo. The HYMNAL_KEY "
              "secret is being used instead; delete access-key.txt from GitHub.")
    return server.load_key()


def build() -> None:
    key = get_key()

    # Nuke and repave — fully deterministic output.
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    hymns = server.load_hymns()
    # Never print the key itself: GitHub build logs are public on a public repo.
    print(f"Building site ({len(hymns)} hymns).")

    # Root landing page (without the key, you get this instead of the site).
    write("index.html", landing_page())

    # Stylesheet — under the key prefix so <base href="/{key}/"> finds it.
    write(f"{key}/style.css", server.CSS)

    # Front page — /{key}/index.html
    page_out(f"{key}/index.html", server.render_home(key), key, 0)

    # Hymnal TOC — /{key}/hymnal/index.html
    page_out(f"{key}/hymnal/index.html", server.render_toc(hymns, key), key, 1)

    # Each public hymn page — /{key}/hymn/N/index.html
    for idx, (number, _title, filepath) in enumerate(hymns):
        title, verses, _meta = server.parse_hymn(filepath)
        prev_n = hymns[idx - 1][0] if idx > 0 else None
        next_n = hymns[idx + 1][0] if idx < len(hymns) - 1 else None
        html = server.render_hymn_page(number, title, verses, prev_n, next_n, key)
        page_out(f"{key}/hymn/{number}/index.html", html, key, 2)
        print(f"  #{number:>3}  {title}")

    # The musician mirror — chords inline, plus the scroll / transpose /
    # text size / dark mode control bar. meta carries each song's
    # [Speed:X] and [Key:X] into that control bar.
    print("Musicians mirror:")
    page_out(f"{key}/musician/index.html", server.render_toc(hymns, key, musician=True), key, 1)
    for idx, (number, _title, filepath) in enumerate(hymns):
        title, verses, meta = server.parse_hymn(filepath)
        prev_n = hymns[idx - 1][0] if idx > 0 else None
        next_n = hymns[idx + 1][0] if idx < len(hymns) - 1 else None
        html = server.render_hymn_page(number, title, verses, prev_n, next_n, key,
                                       musician=True, meta=meta)
        page_out(f"{key}/musician/hymn/{number}/index.html", html, key, 3)
        speed = meta.get("speed")
        print(f"  #{number:>3}  {title}" + (f"  (speed {speed})" if speed else ""))

    # Zine — /{key}/zine/index.html
    zine = server.parse_zine()
    if zine is not None:
        title, sections = zine
        page_out(f"{key}/zine/index.html", server.render_zine_page(title, sections, key), key, 1)

    # Events — /{key}/events/index.html. Every event goes in; visitors'
    # browsers pick the month and hide the ones that are over, so this
    # page never needs a rebuild just because time passed.
    if server.section_ready("events"):
        page_out(f"{key}/events/index.html", server.render_events_page(key), key, 1)
        events, problems = server.parse_events()
        print(f"Events: {len(events)} in events.txt")
        on_github = os.environ.get("GITHUB_ACTIONS") == "true"
        for msg in problems:
            print(f"::warning::events.txt: {msg}" if on_github else f"  ! events.txt: {msg}")

    # "Coming soon" for every front-page section without a real page yet.
    print("Sections:")
    for slug, title, _sub in server.SECTIONS:
        ready = server.section_ready(slug)
        if not ready:
            page_out(f"{key}/{slug}/index.html", server.render_coming_soon(slug, key), key, 1)
        print(f"  {title:<16} {'live' if ready else 'coming soon'}")

    # QR page — /{key}/qr/index.html (draws the code from its own address).
    page_out(f"{key}/qr/index.html", server.render_qr_page(key), key, 1)

    print()
    print(f"Built {sum(1 for p in DIST.rglob('*') if p.is_file())} files into ./dist")
    print("Preview locally:  cd dist && python3 -m http.server 8000")
    print("Then open http://localhost:8000/ followed by your key and a slash.")


if __name__ == "__main__":
    try:
        build()
    except Exception as e:
        print(f"Build failed: {e}", file=sys.stderr)
        sys.exit(1)
