#!/usr/bin/env python3
"""Grace House Hymnal — a tiny local web server for a home church.

Reads plain-text hymns from ./hymns and serves them as a numbered
table of contents plus per-hymn pages, mobile-first, styled to match
the Grace House brand.

The entire site is served under a URL prefix (the "access key") loaded
from ./access-key.txt. Anyone without the key sees a 404 page. The QR
code has the key baked in — one scan = one tap = they're in.

Usage:
    python3 server.py           # serves on port 8000
    python3 server.py 8080      # or pick another port

Add a hymn: drop a file into ./hymns/ named NNN-slug.txt
where NNN is a 3-digit number and slug is any short name.

File format:
    Title of the hymn
    [Speed:4]          <- optional, musician auto-scroll speed
    [Key:G]            <- optional, original key (shown when transposing)
    <blank line>
    <optional short label alone on its own line, e.g. "1" or "C">
    Verse line 1
    Verse line 2
    <blank line separates blocks>
    <another optional label>
    More lines
    ...

Labels: any short string (up to 6 chars, no spaces) on its own line
at the start of a block. Examples: 1, 2, 3, C (chorus), B (bridge),
Cd (coda), †. The order of blocks in the file is the order shown.
Repeat a chorus by copy-pasting the C block between verses.

Song settings (optional, musician view only):
    [Speed:4]   Starting auto-scroll speed. Any number, decimals OK
                (e.g. 3.5). Songs without it start at DEFAULT_SPEED.
                The musician can nudge it with − / + on the page; when
                she does, the page shows "WAS 4" so she can tell you
                the new number to bake in.
    [Key:G]     The key the chords are written in (G, Bb, F#m, Em...).
                Only used to label the key while transposing. If it's
                missing, the first chord in the song is used as a guess.
Each goes on its own line, anywhere after the title. They never show
on either view. Capitalization and spaces don't matter ([speed: 4]).

Chords (optional, ChordPro-style, inline):
    Amazing [G]grace how [C]sweet the [G]sound
    That [G]saved a [Em]wretch like [D]me

Put a chord in square brackets right before the syllable it plays
on. Any characters except a closing bracket work inside (G, G7, Am,
F#m, Csus4, G/B, N.C., etc.).

On the PUBLIC hymnal (/hymn/N/), [X] markers are stripped out — the
congregation only sees the lyrics. On the MUSICIAN mirror
(/musician/hymn/N/), [X] markers render inline as pink brackets right
where they appear in the text, so the musician sees where each chord
change lands. You can convert songs to chorded format one at a time;
songs without markers just render as lyrics on both views.

Musician controls (bottom bar on /musician/hymn/N/):
    PLAY / PAUSE    8-second countdown, then auto-scroll. Pause any time.
    RESET           Stops, jumps to the top, restores the file's speed.
    SPEED − / +     Slower / faster, before or during scrolling.
    KEY − / + / ↺   Transpose chords down / up a half step; ↺ = original.
                    (Hidden on songs with no chords.)
    SIZE − / + / ↺  Text size; ↺ = default. Remembered between songs.
    ☀ / ☾           Normal look / dark mode. Remembered between songs.
The screen is kept awake while counting down and scrolling (needs the
https Tailscale Funnel URL; most phones/tablets from 2023 on support it).

Musician notes (optional, musician view only):
    Notes
    Capo 3 for original key
    Slower on verse 3

Add a block labeled "Notes" (or "Notes:") at the end of the hymn file.
Anything in that block renders as a small musician-only footer on
/musician/hymn/N/ — capo positions, key change reminders, tempo cues.
The public view skips it entirely.
"""
from __future__ import annotations

import http.server
import re
import secrets
import socket
import socketserver
import sys
import urllib.parse
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
HYMNS_DIR = HERE / "hymns"
QR_PATH = HERE / "qr-code.png"
KEY_PATH = HERE / "access-key.txt"
ZINE_PATH = HERE / "zine.txt"
DEFAULT_PORT = 8000

# Auto-scroll speed for songs with no [Speed:X] line. On screen, speed 1
# is about 5 pixels per second at 100% text size (it scales with text
# size, so the same number always feels the same).
DEFAULT_SPEED = 4

# [Speed:4] / [Key:G] on a line by themselves.
META_RE = re.compile(r"^\s*\[\s*(speed|key)\s*:\s*([^\]]*?)\s*\]\s*$", re.IGNORECASE)

# ─────────────────────────────────────────────────────────────
# Access key

def load_key() -> str:
    if not KEY_PATH.exists():
        key = "grace-" + secrets.token_urlsafe(6).lower().replace("_", "-")
        KEY_PATH.write_text(key + "\n", encoding="utf-8")
    key = KEY_PATH.read_text(encoding="utf-8").strip().split("\n", 1)[0].strip()
    key = re.sub(r"[^A-Za-z0-9_-]", "", key)
    if not key:
        key = "grace-" + secrets.token_urlsafe(6).lower().replace("_", "-")
        KEY_PATH.write_text(key + "\n", encoding="utf-8")
    return key


# ─────────────────────────────────────────────────────────────
# Hymn loading

def load_hymns():
    hymns = []
    for path in HYMNS_DIR.glob("*.txt"):
        m = re.match(r"(\d+)[-_ ](.+)\.txt$", path.name)
        if not m:
            continue
        number = int(m.group(1))
        title = ""
        try:
            with open(path, encoding="utf-8") as f:
                # First real line is the title (skip blanks and [Speed]/[Key]).
                for ln in f:
                    if ln.strip() and not META_RE.match(ln):
                        title = ln.strip()
                        break
        except OSError:
            continue
        if not title:
            title = path.stem
        hymns.append((number, title, path))
    hymns.sort(key=lambda h: h[0])
    return hymns


def parse_zine():
    """Return (title, [(heading, [body_lines]), ...]) from zine.txt,
    or None if the file doesn't exist / is empty.

    Format:
        Title of the page (line 1)

        Section heading
        Body line
        Body line

        Section heading
        - bullet
        - bullet
    """
    if not ZINE_PATH.exists():
        return None
    with open(ZINE_PATH, encoding="utf-8") as f:
        content = f.read()
    lines = content.rstrip().split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return None
    title = lines[0].strip()
    body = "\n".join(lines[1:]).strip()
    if not body:
        return (title, [])
    raw_sections = re.split(r"\n\s*\n", body)
    sections = []
    for block in raw_sections:
        block_lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not block_lines:
            continue
        heading = block_lines[0].strip()
        body_lines = [ln.rstrip() for ln in block_lines[1:]]
        sections.append((heading, body_lines))
    return (title, sections)


def parse_hymn(path):
    """Return (title, [(label, [lines]), ...], meta).

    meta is a dict with optional "speed" and "key" strings taken from
    [Speed:X] / [Key:X] lines, which are removed before parsing.

    A block's first line is treated as its label when it is short
    (<= 6 chars, no spaces) AND there is content after it. Otherwise
    the block is auto-numbered from 1 and its lines are all body.
    """
    with open(path, encoding="utf-8") as f:
        content = f.read()
    meta: dict[str, str] = {}
    lines = []
    for ln in content.rstrip().split("\n"):
        mm = META_RE.match(ln)
        if mm:
            meta[mm.group(1).lower()] = mm.group(2).strip()
        else:
            lines.append(ln)
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return "", [], meta
    title = lines[0].strip()
    body = "\n".join(lines[1:]).strip()
    if not body:
        return title, [], meta
    raw_blocks = re.split(r"\n\s*\n", body)
    verses = []
    auto_num = 1
    for block in raw_blocks:
        block_lines = [ln.rstrip() for ln in block.split("\n")]
        while block_lines and not block_lines[0].strip():
            block_lines.pop(0)
        while block_lines and not block_lines[-1].strip():
            block_lines.pop()
        if not block_lines:
            continue
        first = block_lines[0].strip()
        is_label = (
            len(first) <= 6
            and " " not in first
            and len(block_lines) > 1
        )
        if is_label:
            label = first
            content_lines = [l for l in block_lines[1:] if l.strip()]
        else:
            label = str(auto_num)
            content_lines = [l for l in block_lines if l.strip()]
            auto_num += 1
        verses.append((label, content_lines))
    return title, verses, meta


def _parse_speed(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if 0 < v <= 100 else None


# ─────────────────────────────────────────────────────────────
# Templates

CSS = r"""
@import url('https://fonts.googleapis.com/css2?family=Big+Shoulders+Stencil+Display:wght@700;800;900&family=Big+Shoulders+Stencil+Text:wght@500;700;800&family=Special+Elite&display=swap');

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: 'Special Elite', 'Courier New', monospace;
  background: #f2ede4;
  color: #0a0a0a;
  -webkit-font-smoothing: antialiased;
  -webkit-text-size-adjust: 100%;
  /* Beige halo (background-colored outline) on every text element, so
     the dotted background pattern never touches letter edges. Inherits
     from body into everything below; elements with their own colored
     background chips explicitly zero this out further down. */
  -webkit-text-stroke: 6px #f2ede4;
  paint-order: stroke fill;
  background-image:
    radial-gradient(circle at 12% 22%, rgba(0,0,0,0.5) 0.5px, transparent 1.5px),
    radial-gradient(circle at 34% 66%, rgba(0,0,0,0.4) 0.5px, transparent 1.5px),
    radial-gradient(circle at 68% 12%, rgba(0,0,0,0.45) 0.5px, transparent 1.4px),
    radial-gradient(circle at 84% 78%, rgba(0,0,0,0.35) 0.4px, transparent 1.3px),
    radial-gradient(circle at 52% 40%, rgba(0,0,0,0.3) 0.4px, transparent 1.2px),
    radial-gradient(circle at 8% 88%, rgba(0,0,0,0.4) 0.5px, transparent 1.4px),
    radial-gradient(circle at 92% 34%, rgba(0,0,0,0.3) 0.4px, transparent 1.2px),
    radial-gradient(circle at 44% 82%, rgba(0,0,0,0.35) 0.4px, transparent 1.3px);
  background-size: 40px 40px, 55px 55px, 47px 47px, 62px 62px, 33px 33px, 51px 51px, 44px 44px, 58px 58px;
}
main {
  max-width: calc(42rem * var(--fs, 1));
  margin: 0 auto;
  padding: 24px 22px 44px;
}
a { color: #f01a8b; text-decoration: none; }
a:hover { color: #b8106a; }

/* Logo mark */
.brand { padding: 8px 0 4px; }
.brand-line {
  font-family: 'Big Shoulders Stencil Display', 'Impact', sans-serif;
  font-weight: 900;
  font-size: 44px;
  line-height: 0.85;
  letter-spacing: -0.5px;
  color: transparent;
  -webkit-text-stroke: 1.5px #0a0a0a;
  display: flex;
  align-items: center;
}
.brand-line svg { margin: 0 -1px 0 -2px; flex-shrink: 0; }

/* Index title tag */
.title-tag {
  margin-top: 18px;
  display: inline-block;
  background: #0a0a0a;
  padding: 4px 14px 6px;
  transform: rotate(-1.5deg);
}
.title-tag h1 {
  margin: 0;
  font-family: 'Big Shoulders Stencil Display', 'Impact', sans-serif;
  font-weight: 800;
  color: #f2ede4;
  font-size: 36px;
  letter-spacing: 4px;
}
.meta-strip {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.count-tag {
  background: #f01a8b;
  color: #0a0a0a;
  padding: 2px 8px 3px;
  font-family: 'Special Elite', monospace;
  font-size: 11px;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  transform: rotate(1deg);
  display: inline-block;
}
.dash-rule {
  flex: 1;
  border-top: 2px dashed #0a0a0a;
  opacity: 0.4;
}
.hint {
  font-family: 'Special Elite', monospace;
  font-size: 10px;
  opacity: 0.55;
}

/* TOC */
ol.toc {
  list-style: none;
  padding: 0;
  margin: 22px 0 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
ol.toc li { border-bottom: 1.5px solid #0a0a0a; }
ol.toc li:last-child { border-bottom: none; }
ol.toc a {
  display: flex;
  align-items: baseline;
  gap: 14px;
  padding: 10px 6px;
  color: inherit;
}
ol.toc a:active { opacity: 0.6; }
ol.toc .num {
  font-family: 'Big Shoulders Stencil Display', 'Impact', sans-serif;
  font-weight: 900;
  color: #f01a8b;
  font-size: 38px;
  line-height: 0.85;
  min-width: 38px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
ol.toc .title {
  font-family: 'Big Shoulders Stencil Text', 'Impact', sans-serif;
  font-weight: 700;
  font-size: 20px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  line-height: 1.05;
}

/* Hymn page */
.hymn-nav-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0 12px;
}
.back-tag {
  font-family: 'Special Elite', monospace;
  font-size: 12px;
  background: #0a0a0a;
  color: #f2ede4 !important;
  padding: 3px 10px 4px;
  letter-spacing: 1px;
}
.song-num {
  font-family: 'Big Shoulders Stencil Display', 'Impact', sans-serif;
  font-weight: 900;
  font-size: 32px;
  line-height: 0.85;
  color: #f01a8b;
}
article {
  padding: 14px 0 4px;
  border-bottom: 3px solid #0a0a0a;
}
article h1 {
  margin: 0;
  font-family: 'Big Shoulders Stencil Display', 'Impact', sans-serif;
  font-weight: 900;
  font-size: 52px;
  line-height: 0.9;
  text-transform: uppercase;
  color: transparent;
  -webkit-text-stroke: 2px #0a0a0a;
}
.verses { padding-top: 6px; }
.verse {
  display: flex;
  gap: 14px;
  padding: 18px 2px 6px;
  align-items: flex-start;
}
.verse.chorus {
  border-left: 3px solid #f01a8b;
  margin-left: -8px;
  padding-left: 10px;
}
.verse.chorus .v-body { font-style: italic; }
/* --fs is the musician's text-size setting (1 = 100%). It's only ever
   set on musician pages, so the public view always renders at 1. */
.v-label {
  font-family: 'Big Shoulders Stencil Display', 'Impact', sans-serif;
  font-weight: 900;
  color: #f01a8b;
  font-size: calc(42px * var(--fs, 1));
  line-height: 0.8;
  min-width: calc(42px * var(--fs, 1));
  text-align: right;
  padding-top: 2px;
  text-transform: uppercase;
}
.v-body {
  flex: 1;
  font-family: 'Special Elite', 'Courier New', monospace;
  font-size: calc(15px * var(--fs, 1));
  line-height: 1.65;
  color: #0a0a0a;
  /* Beige halo is inherited from body — see the note there. */
}
.v-body .line { /* each lyric line; padding kicks in only on print */ }

/* Inline chord markers. On the musician view [G] stays in the text
   right where it was typed, just colored pink so it pops. On the
   public view chord tokens are stripped before rendering, so this
   class never appears in the DOM there. */
.v-body .chord {
  font-family: 'Big Shoulders Stencil Text', 'Impact', sans-serif;
  font-weight: 700;
  color: #f01a8b;
  letter-spacing: 0.5px;
  padding: 0 1px;
  white-space: nowrap;
}

/* Musician-only "Notes" block — capo, tempo, key change reminders. */
.notes {
  margin-top: 26px;
  padding-top: 18px;
  border-top: 2px dashed rgba(10, 10, 10, 0.35);
}
.notes-label {
  margin: 0 0 10px;
  font-family: 'Big Shoulders Stencil Text', 'Impact', sans-serif;
  font-weight: 800;
  font-size: 14px;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: #f01a8b;
}
.notes-body {
  font-family: 'Special Elite', 'Courier New', monospace;
  font-size: calc(13px * var(--fs, 1));
  line-height: 1.55;
  color: #0a0a0a;
  opacity: 0.9;
  /* Beige halo is inherited from body — see the note there. */
}
.notes-body p { margin: 0 0 6px; }
.notes-body p:last-child { margin-bottom: 0; }

/* Elements with their own colored background chips don't sit on the
   dotted beige, so the beige halo would just fatten them oddly.
   Zero it out on those. (Chips: HYMNAL title tag, "14 songs" count,
   the zine + foot chips, back-tag on hymn pages, the black NEXT arrow.) */
.title-tag h1,
.count-tag,
.zine-link,
.foot-link,
.back-tag,
.foot .nav-next {
  -webkit-text-stroke: 0;
}

/* Hide print-only elements on screen */
.print-slug { display: none; }

/* Footer nav */
.foot {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 8px;
  padding: 24px 0 0;
  margin-top: 24px;
  border-top: 3px solid #0a0a0a;
  font-family: 'Special Elite', monospace;
  font-size: 12px;
}
.foot a, .foot span { color: inherit; padding: 3px 10px; }
.foot .nav-prev { justify-self: start; }
.foot .home { justify-self: center; }
.foot .nav-next {
  justify-self: end;
  background: #0a0a0a;
  color: #f2ede4 !important;
  padding: 3px 10px 4px;
  letter-spacing: 1px;
}

/* Blank/404 */
.blank {
  text-align: center;
  padding: 6rem 1rem;
  color: rgba(0,0,0,0.55);
  font-family: 'Special Elite', monospace;
}
.blank h1 { font-weight: 500; font-size: 1.2rem; margin: 0 0 0.5rem; }
.blank p { font-size: 0.95rem; margin: 0; }

/* Zine link — pink chip floating top-right of the TOC page */
main { position: relative; }
.zine-link {
  position: absolute;
  top: 44px;
  right: 22px;
  font-family: 'Special Elite', 'Courier New', monospace;
  font-size: 11px;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: #0a0a0a !important;
  padding: 4px 10px 5px;
  background: #f01a8b;
  transform: rotate(2deg);
  display: inline-block;
  z-index: 2;
}

/* Zine page */
.zine-meta {
  font-family: 'Special Elite', monospace;
  font-size: 10px;
  opacity: 0.55;
  margin-top: 8px;
}
.zine-section {
  padding: 22px 0 20px;
  border-bottom: 2px solid #0a0a0a;
}
.zine-section:last-of-type { border-bottom: none; padding-bottom: 6px; }
.zine-heading {
  margin: 0 0 14px;
  font-family: 'Big Shoulders Stencil Display', 'Impact', sans-serif;
  font-weight: 900;
  font-size: 30px;
  line-height: 0.95;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: #0a0a0a;
}
.zine-body {
  font-family: 'Special Elite', 'Courier New', monospace;
  font-size: 14px;
  line-height: 1.6;
  color: #0a0a0a;
}
.zine-body p { margin: 0 0 12px; }
.zine-body p:last-child { margin-bottom: 0; }
.zine-body ul { margin: 0 0 12px; padding-left: 22px; }
.zine-body li { margin: 4px 0; padding-left: 4px; }
.zine-body li::marker { color: #f01a8b; }

/* Musician's booklet link at bottom of TOC */
.foot-actions {
  margin-top: 28px;
  padding-top: 16px;
  border-top: 1.5px dashed rgba(10,10,10,0.35);
  text-align: right;
}
.foot-link {
  font-family: 'Special Elite', monospace;
  font-size: 11px;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: #0a0a0a !important;
  padding: 4px 10px 5px;
  background: #f01a8b;
  display: inline-block;
  transform: rotate(-1deg);
}

/* QR page */
.qr-wrap { text-align: center; padding: 2rem 0; }
.qr-wrap img {
  max-width: 320px;
  width: 100%;
  height: auto;
  background: white;
  padding: 12px;
}
.qr-wrap p { font-family: 'Special Elite', monospace; font-size: 0.95rem; }
.qr-wrap code {
  font-family: 'Special Elite', monospace;
  font-size: 0.95rem;
  background: rgba(0,0,0,0.08);
  padding: 0.2rem 0.5rem;
  word-break: break-all;
}

/* ────────────────────────────────────────────────────────────
   MUSICIAN PLAYER — fixed control bar on /musician/hymn/N/
   ──────────────────────────────────────────────────────────── */
.player {
  position: fixed;
  left: 0; right: 0; bottom: 0;
  z-index: 50;
  background: #f2ede4;
  border-top: 3px solid #0a0a0a;
  padding: 8px 10px calc(8px + env(safe-area-inset-bottom));
  display: flex;
  flex-direction: column;
  gap: 6px;
  -webkit-text-stroke: 0;
}
.player [hidden] { display: none !important; }
.p-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px;
  width: 100%;
  max-width: 42rem;
  margin: 0 auto;
}
.p-group { display: flex; align-items: center; gap: 3px; }
.p-btn {
  font-family: 'Special Elite', 'Courier New', monospace;
  font-size: 13px;
  letter-spacing: 1px;
  height: 38px;
  min-width: 36px;
  padding: 0 9px;
  border: 2px solid #0a0a0a;
  border-radius: 0;
  background: transparent;
  color: #0a0a0a;
  cursor: pointer;
  touch-action: manipulation;          /* no double-tap zoom on + + + */
  -webkit-tap-highlight-color: transparent;
}
.p-btn:active { transform: translateY(1px); }
.p-btn:focus-visible { outline: 3px solid #f01a8b; outline-offset: 2px; }
.p-sq { width: 36px; padding: 0; font-size: 20px; line-height: 1; }
.p-main {
  min-width: 90px;
  background: #0a0a0a;
  color: #f2ede4;
}
.p-main.on {
  background: #f01a8b;
  border-color: #f01a8b;
  color: #0a0a0a;
}
.p-val {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 48px;
  line-height: 1;
  color: #0a0a0a;
}
.p-val small {
  font-family: 'Special Elite', monospace;
  font-size: 9px;
  letter-spacing: 1px;
  opacity: 0.65;
  white-space: nowrap;
}
.p-val b {
  font-family: 'Big Shoulders Stencil Text', 'Impact', sans-serif;
  font-weight: 800;
  font-size: 21px;
  margin-top: 2px;
  white-space: nowrap;
}
.p-val.changed b { color: #f01a8b; }
.p-theme {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  font-size: 18px;
}
.p-theme span { opacity: 0.3; }
html:not(.dark) .p-theme .t-sun,
html.dark .p-theme .t-moon { opacity: 1; color: #f01a8b; }
.player-spacer { height: 150px; }
@media (max-width: 400px) {
  .player { padding-left: 8px; padding-right: 8px; }
  .p-row { gap: 4px; }
  .p-btn { font-size: 12px; letter-spacing: 0.5px; padding: 0 7px; }
  .p-sq { width: 34px; min-width: 34px; padding: 0; }
  .p-main { min-width: 78px; }
  .p-val { min-width: 44px; }
  .p-val b { font-size: 19px; }
  .p-theme { padding: 0 6px; gap: 4px; }
}

/* 8-second countdown card */
.countdown {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.countdown[hidden] { display: none; }
.cd-box {
  background: #0a0a0a;
  color: #f2ede4;
  padding: 16px 30px 18px;
  text-align: center;
  transform: rotate(-1.5deg);
  box-shadow: 6px 6px 0 #f01a8b;
  -webkit-text-stroke: 0;
}
.cd-msg {
  font-family: 'Special Elite', monospace;
  font-size: 14px;
  letter-spacing: 2px;
  text-transform: uppercase;
}
.cd-num {
  font-family: 'Big Shoulders Stencil Display', 'Impact', sans-serif;
  font-weight: 900;
  font-size: 104px;
  line-height: 0.9;
  color: #f01a8b;
}
.cd-hint {
  font-family: 'Special Elite', monospace;
  font-size: 10px;
  letter-spacing: 1px;
  opacity: 0.6;
  text-transform: uppercase;
}

/* ────────────────────────────────────────────────────────────
   DARK MODE (musician pages only) — black page, white text,
   pink chords and labels stay pink.
   ──────────────────────────────────────────────────────────── */
html.dark body {
  background: #000000;
  background-image: none;
  color: #f5f5f5;
  -webkit-text-stroke: 0;   /* no dots, so no halo needed */
}
html.dark .brand-line { -webkit-text-stroke: 1.5px #f5f5f5; }
html.dark .brand svg circle,
html.dark .brand svg line { stroke: #f5f5f5; }
html.dark .brand svg circle[fill="#0a0a0a"] { fill: #f5f5f5; }
html.dark .title-tag { background: #f5f5f5; }
html.dark .title-tag h1 { color: #000000; }
html.dark .dash-rule { border-top-color: #f5f5f5; }
html.dark ol.toc li { border-bottom-color: #f5f5f5; }
html.dark .back-tag,
html.dark .foot .nav-next { background: #f5f5f5; color: #000000 !important; }
html.dark article { border-bottom-color: #f5f5f5; }
html.dark article h1 { -webkit-text-stroke: 2px #f5f5f5; }
html.dark .v-body,
html.dark .notes-body { color: #f5f5f5; }
html.dark .notes { border-top-color: rgba(245, 245, 245, 0.35); }
html.dark .foot { border-top-color: #f5f5f5; }
html.dark .foot-actions { border-top-color: rgba(245, 245, 245, 0.35); }
html.dark .player { background: #000000; border-top-color: #f5f5f5; }
html.dark .p-btn { border-color: #f5f5f5; color: #f5f5f5; }
html.dark .p-main { background: #f5f5f5; color: #000000; }
html.dark .p-main.on { background: #f01a8b; border-color: #f01a8b; color: #000000; }
html.dark .p-val { color: #f5f5f5; }
html.dark .cd-box { background: #f5f5f5; color: #000000; }

/* ────────────────────────────────────────────────────────────
   PRINT STYLES — for musicians who want to write chords above
   each lyric line. Kicks in only when Cmd+P / Print is used.
   ──────────────────────────────────────────────────────────── */
@media print {
  html, body {
    background: #ffffff !important;
    background-image: none !important;
    color: #000000 !important;
    /* Paper has no dot pattern — nix the halo so print stays crisp.
       Because the halo is now on body, resetting it here covers all
       inheriting descendants in one go. */
    -webkit-text-stroke: 0 !important;
  }
  main { max-width: none; padding: 0.55in 0.7in 0.55in 0.95in; }

  /* Hide screen chrome we don't want on paper */
  .brand, .title-tag, .meta-strip,
  .hymn-nav-top, .foot,
  .player, .player-spacer, .countdown { display: none !important; }

  /* Per-hymn title block */
  article {
    border-bottom: 2pt solid #000 !important;
    padding: 0 0 8pt !important;
    margin-bottom: 6pt;
  }
  article h1 {
    -webkit-text-stroke: 0 !important;
    color: #000 !important;
    font-family: 'Special Elite', 'Courier New', monospace !important;
    font-weight: 400;
    font-size: 22pt;
    line-height: 1.15;
    letter-spacing: 0.5pt;
  }
  .print-slug {
    display: block !important;
    font-family: 'Special Elite', monospace;
    font-size: 10pt;
    letter-spacing: 2pt;
    text-transform: uppercase;
    color: #000;
    margin-bottom: 4pt;
  }

  /* Verse blocks — keep each verse on one page if possible */
  .verse {
    display: flex;
    align-items: flex-start;
    gap: 14pt;
    padding: 4pt 0 6pt;
    break-inside: avoid-page;
    page-break-inside: avoid;
  }
  .verse.chorus {
    border-left: 2pt solid #000 !important;
    margin-left: -8pt;
    padding-left: 10pt;
  }
  .verse.chorus .v-body { font-style: italic; }

  .v-label {
    font-family: 'Special Elite', monospace !important;
    color: #000 !important;
    -webkit-text-stroke: 0 !important;
    font-weight: 700;
    font-size: 15pt;
    line-height: 1;
    min-width: 22pt;
    padding-top: 2pt;
    text-align: right;
  }
  .v-body {
    font-family: 'Special Elite', 'Courier New', monospace !important;
    font-size: 12pt !important;
    color: #000 !important;
    line-height: 1.2;
    /* Paper has no dot pattern — nix the halo so print stays crisp. */
    -webkit-text-stroke: 0 !important;
  }
  .notes-body {
    -webkit-text-stroke: 0 !important;
  }

  /* Tight lyric lines on paper (no more blank-space-for-handwriting;
     inline [X] chords, when present, print in black bracketed text). */
  .v-body .line {
    padding-top: 0;
    line-height: 1.35;
  }
  .v-body .chord {
    color: #000 !important;
    font-family: 'Special Elite', 'Courier New', monospace !important;
    font-weight: 700;
    letter-spacing: 0.3pt;
  }
}
"""

# The GRACE H⊕USE brand mark, rendered inline. The 8-spoke wheel
# replaces the O in HOUSE.
BRAND_LOGO = """<div class="brand">
  <div class="brand-line">GRACE</div>
  <div class="brand-line">
    <span>H</span>
    <svg width="34" height="34" viewBox="0 0 34 34" aria-label="wheel">
      <circle cx="17" cy="17" r="13" stroke="#0a0a0a" stroke-width="1.8" fill="none"/>
      <line x1="17" y1="4" x2="17" y2="30" stroke="#0a0a0a" stroke-width="1.5"/>
      <line x1="4" y1="17" x2="30" y2="17" stroke="#0a0a0a" stroke-width="1.5"/>
      <line x1="7.81" y1="7.81" x2="26.19" y2="26.19" stroke="#0a0a0a" stroke-width="1.5"/>
      <line x1="26.19" y1="7.81" x2="7.81" y2="26.19" stroke="#0a0a0a" stroke-width="1.5"/>
      <circle cx="17" cy="17" r="2.5" fill="#0a0a0a"/>
    </svg>
    <span>USE</span>
  </div>
</div>"""


# Runs in <head> on musician pages, before anything paints, so dark mode
# and text size are already applied (no white flash between songs).
MUSICIAN_HEAD_JS = (
    "<script>try{var d=document.documentElement;"
    "if(localStorage.getItem('gh-theme')==='dark'){d.classList.add('dark');"
    "var m=document.querySelector('meta[name=\"theme-color\"]');if(m)m.content='#000000';}"
    "var f=parseFloat(localStorage.getItem('gh-fs'));"
    "if(f>0)d.style.setProperty('--fs',f);}catch(e){}</script>\n"
)


# Musician control bar behavior. Plain string (not an f-string) so the
# JavaScript braces don't need escaping.
MUSICIAN_JS = r"""
(function () {
  var player = document.getElementById('player');
  if (!player) return;
  var root = document.documentElement;
  function $(id) { return document.getElementById(id); }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, String(v)); } catch (e) {} }
  function fmt(n) { return String(Math.round(n * 100) / 100); }

  /* ── Sun / moon ───────────────────────────────────────── */
  function setTheme(dark, remember) {
    root.classList.toggle('dark', dark);
    $('ctl-theme').setAttribute('aria-pressed', String(dark));
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', dark ? '#000000' : '#f2ede4');
    if (remember) save('gh-theme', dark ? 'dark' : 'light');
  }
  $('ctl-theme').onclick = function () { setTheme(!root.classList.contains('dark'), true); };
  setTheme(root.classList.contains('dark'), false);

  /* ── Text size ────────────────────────────────────────── */
  var fs = parseFloat(load('gh-fs')) || 1;
  function setFs(v) {
    fs = Math.min(2.5, Math.max(0.7, Math.round(v * 10) / 10));
    root.style.setProperty('--fs', fs);
    $('ctl-fs-val').textContent = Math.round(fs * 100) + '%';
    $('ctl-fs').classList.toggle('changed', fs !== 1);
    save('gh-fs', fs);
  }
  $('ctl-fs-dn').onclick = function () { setFs(fs - 0.1); };
  $('ctl-fs-up').onclick = function () { setFs(fs + 0.1); };
  $('ctl-fs-reset').onclick = function () { setFs(1); };
  setFs(fs);

  /* ── Screen wake lock ─────────────────────────────────── */
  var lock = null;
  function wake() {
    if (lock || !('wakeLock' in navigator)) return;
    navigator.wakeLock.request('screen').then(function (l) {
      lock = l;
      l.addEventListener('release', function () { lock = null; });
    }).catch(function () {});
  }
  function unwake() {
    if (lock) { lock.release().catch(function () {}); lock = null; }
  }

  /* ── Auto-scroll ──────────────────────────────────────── */
  var COUNTDOWN = 8;        // seconds before scrolling starts
  var PX_PER_UNIT = 5;      // speed 1 = 5 px/sec at 100% text size
  var fileSpeed = parseFloat(player.getAttribute('data-speed')) || 4;
  var speed = fileSpeed;
  var state = 'idle';       // idle | countdown | scrolling
  var pos = 0, lastY = 0, lastT = 0, raf = 0, timer = 0, left = 0;
  var playBtn = $('ctl-play'), overlay = $('countdown'), cdNum = $('cd-num');

  function setSpeed(v) {
    speed = Math.min(40, Math.max(0.25, Math.round(v * 100) / 100));
    var changed = Math.abs(speed - fileSpeed) > 0.001;
    $('ctl-speed-val').textContent = fmt(speed);
    $('ctl-speed-lbl').textContent = changed ? 'WAS ' + fmt(fileSpeed) : 'SPEED';
    $('ctl-speed').classList.toggle('changed', changed);
  }
  function setPlay() {
    var on = state !== 'idle';
    playBtn.textContent = on ? '\u275A\u275A PAUSE' : '\u25B6\uFE0E PLAY';
    playBtn.classList.toggle('on', on);
  }
  function atBottom() {
    return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
  }
  function start() {
    state = 'countdown';
    left = COUNTDOWN;
    cdNum.textContent = left;
    overlay.hidden = false;
    wake();
    setPlay();
    timer = setInterval(function () {
      left -= 1;
      if (left > 0) { cdNum.textContent = left; return; }
      clearInterval(timer);
      overlay.hidden = true;
      state = 'scrolling';
      pos = lastY = window.scrollY;
      lastT = 0;
      raf = requestAnimationFrame(tick);
    }, 1000);
  }
  function tick(t) {
    if (state !== 'scrolling') return;
    if (lastT) {
      var dt = Math.min(0.1, (t - lastT) / 1000);
      // If she dragged the page by hand, carry on from where she left it.
      if (Math.abs(window.scrollY - lastY) > 3) pos = window.scrollY;
      pos += speed * PX_PER_UNIT * fs * dt;
      window.scrollTo(0, pos);
      lastY = window.scrollY;
      if (atBottom()) { stop(); return; }
    }
    lastT = t;
    raf = requestAnimationFrame(tick);
  }
  function stop() {
    clearInterval(timer);
    cancelAnimationFrame(raf);
    overlay.hidden = true;
    state = 'idle';
    unwake();
    setPlay();
  }
  playBtn.onclick = function () { if (state === 'idle') start(); else stop(); };
  $('ctl-reset').onclick = function () { stop(); setSpeed(fileSpeed); window.scrollTo(0, 0); };
  $('ctl-speed-dn').onclick = function () { setSpeed(speed - 0.5); };
  $('ctl-speed-up').onclick = function () { setSpeed(speed + 0.5); };
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && state !== 'idle') wake();
  });
  setSpeed(speed);
  setPlay();

  /* ── Transpose ────────────────────────────────────────── */
  var chords = Array.prototype.slice.call(document.querySelectorAll('.v-body .chord[data-chord]'));
  if (!chords.length) { $('ctl-key-group').hidden = true; return; }

  var SHARP = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
  var FLAT  = ['C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B'];
  var PC = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  var FLAT_MAJOR = [5, 10, 3, 8, 1];      // F Bb Eb Ab Db
  var FLAT_MINOR = [2, 7, 0, 5, 10, 3];   // Dm Gm Cm Fm Bbm Ebm
  // Note letters at the start of a chord or after a slash: G, F#, Bb, G/B
  var NOTE_RE = /(^|[\/(\s])([A-G])([#b\u266F\u266D]?)/g;
  var KEY_RE = /^([A-G])([#b\u266F\u266D]?)(m(?!aj))?/;

  function pcOf(letter, acc) {
    var p = PC[letter];
    if (acc === '#' || acc === '\u266F') p += 1;
    else if (acc === 'b' || acc === '\u266D') p -= 1;
    return (p + 12) % 12;
  }

  // Original key: [Key:X] from the file, else the first chord.
  var keyText = player.getAttribute('data-key') || chords[0].getAttribute('data-chord') || '';
  var km = keyText.trim().match(KEY_RE);
  var origKey = km ? { pc: pcOf(km[1], km[2]), minor: !!km[3] } : null;
  var origLabel = km ? km[1] + km[2] + (km[3] ? 'm' : '') : '';
  var shift = 0;

  function useFlats(s) {
    if (!origKey) return s < 0;
    var pc = ((origKey.pc + s) % 12 + 12) % 12;
    return (origKey.minor ? FLAT_MINOR : FLAT_MAJOR).indexOf(pc) !== -1;
  }
  function keyName(s) {
    var pc = ((origKey.pc + s) % 12 + 12) % 12;
    return (useFlats(s) ? FLAT : SHARP)[pc] + (origKey.minor ? 'm' : '');
  }
  function moveChord(chord, s, flats) {
    var names = flats ? FLAT : SHARP;
    return chord.replace(NOTE_RE, function (m, pre, letter, acc) {
      return pre + names[((pcOf(letter, acc) + s) % 12 + 12) % 12];
    });
  }
  function setShift(s) {
    shift = Math.max(-11, Math.min(11, s));
    var flats = useFlats(shift);
    chords.forEach(function (el) {
      var orig = el.getAttribute('data-chord');
      el.textContent = '[' + (shift === 0 ? orig : moveChord(orig, shift, flats)) + ']';
    });
    var off = shift === 0 ? '' : (shift > 0 ? '+' : '\u2212') + Math.abs(shift);
    var name = origKey ? (shift === 0 ? origLabel : keyName(shift)) : '';
    $('ctl-key-val').textContent = name || off || '\u00B10';
    $('ctl-key-lbl').textContent = (name && off) ? 'KEY ' + off : 'KEY';
    $('ctl-key').classList.toggle('changed', shift !== 0);
  }
  $('ctl-key-dn').onclick = function () { setShift(shift - 1); };
  $('ctl-key-up').onclick = function () { setShift(shift + 1); };
  $('ctl-key-reset').onclick = function () { setShift(0); };
  setShift(0);
})();
"""


def render_player(speed: float, key: str) -> str:
    """The musician control bar + countdown card + script."""
    speed_txt = f"{speed:g}"
    return (
        '<div class="player-spacer"></div>\n'
        f'<div id="player" class="player" data-speed="{escape(speed_txt)}" data-key="{escape(key)}">\n'
        '<div class="p-row">'
        '<button id="ctl-play" class="p-btn p-main" type="button">&#9654;&#xFE0E; PLAY</button>'
        '<button id="ctl-reset" class="p-btn" type="button" aria-label="Reset song">&#8634; RESET</button>'
        '<div class="p-group">'
        '<button id="ctl-speed-dn" class="p-btn p-sq" type="button" aria-label="Slower">&minus;</button>'
        f'<span id="ctl-speed" class="p-val"><small id="ctl-speed-lbl">SPEED</small><b id="ctl-speed-val">{escape(speed_txt)}</b></span>'
        '<button id="ctl-speed-up" class="p-btn p-sq" type="button" aria-label="Faster">+</button>'
        '</div>'
        '<button id="ctl-theme" class="p-btn p-theme" type="button" aria-label="Switch normal / dark mode">'
        '<span class="t-sun">&#9728;&#xFE0E;</span><span class="t-moon">&#9790;&#xFE0E;</span></button>'
        '</div>\n'
        '<div class="p-row">'
        '<div class="p-group" id="ctl-key-group">'
        '<button id="ctl-key-dn" class="p-btn p-sq" type="button" aria-label="Key down a half step">&minus;</button>'
        '<span id="ctl-key" class="p-val"><small id="ctl-key-lbl">KEY</small><b id="ctl-key-val">&plusmn;0</b></span>'
        '<button id="ctl-key-up" class="p-btn p-sq" type="button" aria-label="Key up a half step">+</button>'
        '<button id="ctl-key-reset" class="p-btn p-sq" type="button" aria-label="Original key">&#8634;</button>'
        '</div>'
        '<div class="p-group">'
        '<button id="ctl-fs-dn" class="p-btn p-sq" type="button" aria-label="Smaller text">&minus;</button>'
        '<span id="ctl-fs" class="p-val"><small>SIZE</small><b id="ctl-fs-val">100%</b></span>'
        '<button id="ctl-fs-up" class="p-btn p-sq" type="button" aria-label="Bigger text">+</button>'
        '<button id="ctl-fs-reset" class="p-btn p-sq" type="button" aria-label="Default text size">&#8634;</button>'
        '</div>'
        '</div>\n'
        '</div>\n'
        '<div id="countdown" class="countdown" hidden aria-live="polite">'
        '<div class="cd-box">'
        '<div class="cd-msg">Scrolling begins in</div>'
        '<div id="cd-num" class="cd-num">8</div>'
        '<div class="cd-hint">tap pause to cancel</div>'
        '</div>'
        '</div>\n'
        f"<script>{MUSICIAN_JS}</script>"
    )


def page(title_text: str, body_html: str, key: str, musician: bool = False) -> str:
    base = f"/{key}/"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="theme-color" content="#f2ede4">\n'
        f'<base href="{escape(base)}">\n'
        f"<title>{escape(title_text)}</title>\n"
        '<link rel="stylesheet" href="style.css">\n'
        f"{MUSICIAN_HEAD_JS if musician else ''}"
        "</head>\n"
        "<body>\n"
        "<main>\n"
        f"{body_html}\n"
        "</main>\n"
        "</body>\n"
        "</html>\n"
    )


def render_toc(hymns, key: str, musician: bool = False) -> str:
    # Musician mirror lives at /{key}/musician/, so its hymn links carry
    # that prefix while the public TOC's links stay bare.
    hymn_prefix = "musician/hymn" if musician else "hymn"
    items = "\n".join(
        f'<li><a href="{hymn_prefix}/{n}">'
        f'<span class="num">{n}</span>'
        f'<span class="title">{escape(t)}</span>'
        f"</a></li>"
        for (n, t, _) in hymns
    )
    # Zine chip in the top-right, on BOTH views if zine.txt exists —
    # the musician gets to the zine the same way the congregation does.
    zine = parse_zine()
    top_right = ""
    if zine is not None:
        zine_title, _ = zine
        top_right = f'<a href="zine" class="zine-link">{escape(zine_title.upper())} →</a>'
    # The foot chip swaps between "Musicians →" (from hymnal) and "← Hymnal"
    # (from musicians), mirroring each other at the bottom of the TOC.
    if musician:
        title_word = "MUSICIANS"
        foot = (
            '<div class="foot-actions">'
            '<a href="." class="foot-link">← Hymnal</a>'
            "</div>"
        )
        page_title = "Musicians — Grace House Hymnal"
    else:
        title_word = "HYMNAL"
        foot = (
            '<div class="foot-actions">'
            '<a href="musician/" class="foot-link">Musicians →</a>'
            "</div>"
        )
        page_title = "Grace House Hymnal"
    body = (
        f"{top_right}\n"
        f"{BRAND_LOGO}\n"
        f'<div class="title-tag"><h1>{title_word}</h1></div>\n'
        '<div class="meta-strip">'
        f'<span class="count-tag">{len(hymns)} songs</span>'
        '<div class="dash-rule"></div>'
        '<span class="hint">↓ tap one</span>'
        "</div>\n"
        f'<ol class="toc">\n{items}\n</ol>\n'
        f"{foot}"
    )
    return page(page_title, body, key, musician=musician)


def render_zine_body(lines):
    """Render body lines. Consecutive lines starting with '- ' or '* '
    become a <ul>. Other lines are paragraphs."""
    parts = []
    bullets = []

    def flush_bullets():
        if bullets:
            items_html = "".join(f"<li>{escape(b)}</li>" for b in bullets)
            parts.append(f"<ul>{items_html}</ul>")
            bullets.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if (stripped.startswith("- ") or stripped.startswith("* ")):
            bullets.append(stripped[2:].strip())
        else:
            flush_bullets()
            parts.append(f"<p>{escape(stripped)}</p>")
    flush_bullets()
    return "\n".join(parts)


def render_zine_page(title, sections, key):
    if not sections:
        sections_html = '<p style="opacity:0.5;padding:2rem 0;">Nothing to say yet. Edit zine.txt to add sections.</p>'
    else:
        sections_html = "\n".join(
            f'<section class="zine-section">'
            f'<h2 class="zine-heading">{escape(h)}</h2>'
            f'<div class="zine-body">{render_zine_body(body_lines)}</div>'
            f'</section>'
            for h, body_lines in sections
        )
    # Last-updated date from zine.txt mtime
    updated = ""
    try:
        import datetime
        mtime = datetime.datetime.fromtimestamp(ZINE_PATH.stat().st_mtime)
        updated = mtime.strftime("Updated %b %-d, %Y")
    except Exception:
        pass
    body = (
        '<div class="hymn-nav-top">'
        '<a href="." class="back-tag">← HYMNAL</a>'
        '<span class="song-num">✦</span>'
        "</div>\n"
        f"{BRAND_LOGO}\n"
        f'<div class="title-tag"><h1>{escape(title.upper())}</h1></div>\n'
        '<div class="meta-strip">'
        f'<span class="count-tag">{escape(updated) if updated else "the zine"}</span>'
        '<div class="dash-rule"></div>'
        '<span class="hint">↓ read</span>'
        "</div>\n"
        f'<div class="zine-content">\n{sections_html}\n</div>'
    )
    return page(f"{title} — Grace House", body, key)


CHORD_RE = re.compile(r'\[([^\]]+)\]')


def _render_line(line: str, show_chords: bool) -> str:
    """Render one lyric line as HTML.

    show_chords=False: [X] markers are STRIPPED and the line is rendered
    as plain text. This is the public/congregation view.

    show_chords=True: [X] markers are rendered INLINE as pink bracketed
    labels right where they appear in the text — [G]word stays [G]word,
    the chord doesn't float above. This is the musician view. Each chord
    also carries its original text in data-chord so the transpose
    buttons can always work from the written chord.
    """
    if not show_chords:
        return f'<div class="line">{escape(CHORD_RE.sub("", line))}</div>'
    if '[' not in line:
        return f'<div class="line">{escape(line)}</div>'
    # Build inline HTML: escape text runs, wrap chord tokens in <span class="chord">[X]</span>.
    parts = CHORD_RE.split(line)  # alternates: text, chord, text, chord, ...
    out = escape(parts[0])
    for i in range(1, len(parts), 2):
        chord = parts[i]
        following = parts[i + 1] if i + 1 < len(parts) else ""
        out += (
            f'<span class="chord" data-chord="{escape(chord)}">[{escape(chord)}]</span>'
            f'{escape(following)}'
        )
    return f'<div class="line has-chords">{out}</div>'


def _verse_block_html(label: str, lines: list[str], show_chords: bool = False) -> str:
    is_chorus = label.upper() == "C"
    chorus_cls = " chorus" if is_chorus else ""
    body_html = "\n".join(_render_line(ln, show_chords) for ln in lines)
    return (
        f'<section class="verse{chorus_cls}">'
        f'<span class="v-label">{escape(label)}</span>'
        f'<div class="v-body">{body_html}</div>'
        f'</section>'
    )


def render_hymn_page(number, title, verses, prev_n, next_n, key: str,
                     musician: bool = False, meta: dict | None = None) -> str:
    meta = meta or {}
    # Split off an optional Notes block (any block whose label is "Notes"
    # or "Notes:" case-insensitively). Notes render ONLY on the musician
    # view — capo positions, key change reminders, tempo cues, whatever
    # the musician needs. The public never sees them.
    regular_verses = []
    notes_lines: list[str] = []
    for label, lines in verses:
        if label.strip().lower().rstrip(":").strip() in ("notes", "note"):
            notes_lines = lines
        else:
            regular_verses.append((label, lines))

    verse_html = "\n".join(
        _verse_block_html(label, lines, show_chords=musician)
        for label, lines in regular_verses
    )

    notes_html = ""
    if musician and notes_lines:
        # Notes are prose, not lyrics — strip any [X] tokens and render
        # each non-empty line as its own paragraph.
        rendered = "\n".join(
            f"<p>{escape(CHORD_RE.sub('', ln).strip())}</p>"
            for ln in notes_lines
            if ln.strip()
        )
        notes_html = (
            '<section class="notes">'
            '<h3 class="notes-label">Notes</h3>'
            f'<div class="notes-body">{rendered}</div>'
            '</section>\n'
        )

    player_html = ""
    if musician:
        speed = _parse_speed(meta.get("speed")) or DEFAULT_SPEED
        player_html = render_player(speed, meta.get("key", ""))

    # Links stay bare on public pages, prefixed with "musician/" on the mirror,
    # so the base href /{key}/ resolves them into the right subtree either way.
    hymn_prefix = "musician/hymn" if musician else "hymn"
    home_href = "musician/" if musician else "."
    back_label = "← MUSICIANS" if musician else "← ALL HYMNS"
    prev_link = (
        f'<a class="nav-prev" href="{hymn_prefix}/{prev_n}">← PREV</a>'
        if prev_n else '<span></span>'
    )
    next_link = (
        f'<a class="nav-next" href="{hymn_prefix}/{next_n}">NEXT →</a>'
        if next_n else '<span></span>'
    )
    body = (
        '<div class="hymn-nav-top">'
        f'<a href="{home_href}" class="back-tag">{back_label}</a>'
        f'<span class="song-num">#{number}</span>'
        "</div>\n"
        "<article>\n"
        f'<span class="print-slug">Song #{number}</span>'
        f"<h1>{escape(title)}</h1>\n"
        "</article>\n"
        f'<div class="verses">\n{verse_html}\n</div>\n'
        f'{notes_html}'
        '<nav class="foot">\n'
        f"{prev_link}\n"
        f'<a class="home" href="{home_href}">INDEX</a>\n'
        f"{next_link}\n"
        "</nav>\n"
        f"{player_html}"
    )
    title_suffix = " — Musicians" if musician else ""
    return page(f"{title}{title_suffix} — Grace House Hymnal", body, key, musician=musician)


def render_qr_page(url: str, have_png: bool, key: str) -> str:
    if have_png:
        img = '<img src="qr-code.png" alt="QR code">'
    else:
        img = "<p><em>qr-code.png not found.</em></p>"
    body = (
        '<div class="hymn-nav-top">'
        '<a href="." class="back-tag">← ALL HYMNS</a>'
        '<span class="song-num">QR</span>'
        "</div>\n"
        '<div class="qr-wrap">\n'
        f"{img}\n"
        f"<p>Points to <code>{escape(url)}</code></p>\n"
        "</div>"
    )
    return page("QR — Grace House Hymnal", body, key)


def render_blank() -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Not found</title>\n"
        "<style>\n" + CSS + "\n</style>\n"
        "</head><body>\n"
        '<main><div class="blank">\n'
        "<h1>Nothing here.</h1>\n"
        "<p>If you're expecting to see something, ask whoever shared the link with you.</p>\n"
        "</div></main>\n"
        "</body></html>\n"
    )


# ─────────────────────────────────────────────────────────────
# Server

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "Hymnal/1.2"

    def log_message(self, fmt, *args):
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str):
        self.send_response(301)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _blank(self):
        self._send(render_blank().encode("utf-8"), "text/html; charset=utf-8", 404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        key = load_key()
        prefix = f"/{key}"

        if path == prefix:
            self._redirect(prefix + "/")
            return
        if not path.startswith(prefix + "/"):
            self._blank()
            return

        inner = path[len(prefix):]

        if inner == "/style.css":
            self._send(CSS.encode("utf-8"), "text/css; charset=utf-8")
            return
        if inner == "/qr-code.png":
            if QR_PATH.exists():
                self._send(QR_PATH.read_bytes(), "image/png")
            else:
                self._send(b"QR not found", "text/plain; charset=utf-8", 404)
            return
        if inner == "/qr":
            port = self.server.server_address[1]
            url = f"http://localhost:{port}{prefix}/"
            self._send(
                render_qr_page(url, QR_PATH.exists(), key).encode("utf-8"),
                "text/html; charset=utf-8",
            )
            return
        if inner == "/":
            hymns = load_hymns()
            self._send(
                render_toc(hymns, key).encode("utf-8"),
                "text/html; charset=utf-8",
            )
            return
        if inner == "/musician" or inner == "/musician/":
            hymns = load_hymns()
            self._send(
                render_toc(hymns, key, musician=True).encode("utf-8"),
                "text/html; charset=utf-8",
            )
            return
        if inner == "/zine":
            zine = parse_zine()
            if zine is None:
                self._blank()
                return
            title, sections = zine
            self._send(
                render_zine_page(title, sections, key).encode("utf-8"),
                "text/html; charset=utf-8",
            )
            return
        # /hymn/N (public) and /musician/hymn/N (musician mirror) share
        # everything except the show_chords flag and their link prefixes.
        m = re.match(r"^(/musician)?/hymn/(\d+)$", inner)
        if m:
            musician = m.group(1) is not None
            wanted = int(m.group(2))
            hymns = load_hymns()
            idx = next((i for i, (n, _, _) in enumerate(hymns) if n == wanted), None)
            if idx is None:
                self._blank()
                return
            number, title, filepath = hymns[idx]
            title, verses, meta = parse_hymn(filepath)
            prev_n = hymns[idx - 1][0] if idx > 0 else None
            next_n = hymns[idx + 1][0] if idx < len(hymns) - 1 else None
            self._send(
                render_hymn_page(number, title, verses, prev_n, next_n, key,
                                 musician=musician, meta=meta).encode("utf-8"),
                "text/html; charset=utf-8",
            )
            return
        self._blank()


class ReuseTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Bad port: {sys.argv[1]}")
            sys.exit(2)

    if not HYMNS_DIR.exists():
        HYMNS_DIR.mkdir()

    key = load_key()

    bar = "─" * 62
    print()
    print(bar)
    print("  Grace House Hymnal is running")
    print(bar)
    print(f"  Hymnal            :  http://localhost:{port}/{key}/")
    print(f"  Musicians mirror  :  http://localhost:{port}/{key}/musician/")
    print(f"  QR code viewer    :  http://localhost:{port}/{key}/qr")
    print()
    print(f"  Access key        :  {key}")
    print(f"  (edit access-key.txt to change; then regenerate QR)")
    print()
    print(f"  Phones reach this via your Tailscale Funnel URL.")
    print(f"  Make sure Tailscale + Funnel are running.")
    print()
    print(f"  Hymns are loaded from ./hymns  (see SETUP for format)")
    print(f"  Press Ctrl+C to stop.")
    print(bar)
    print()

    try:
        with ReuseTCPServer(("0.0.0.0", port), Handler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    except OSError as e:
        print(f"\nCouldn't start server: {e}")
        print(f"Another program may be using port {port}.")
        print(f"Try:  python3 server.py 8080")
        sys.exit(1)


if __name__ == "__main__":
    main()
