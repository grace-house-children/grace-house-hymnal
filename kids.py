#!/usr/bin/env python3
"""Grace House Kids — a one-page printable activity sheet.

The page lives at /{key}/kids/. It shows one US Letter sheet exactly as
it will print. The teacher taps any box on the sheet to shuffle it, and
presses Print when they like what they have. Everything on the sheet is
made in the visitor's browser, so the static build on GitHub Pages still
gives a fresh sheet every time, with nothing to rebuild.

    ┌──────────────────────────────────────────┐
    │ GRACE HOUSE KIDS          LOOK IT UP     │
    │ ACTIVITY SHEET            (coded verse)  │
    │ ________________________________________ │
    │ ________________________________________ │
    ├────────────────────┬─────────────────────┤
    │ HIDDEN PICTURE     │ WORD SEARCH         │
    ├────────────────────┼─────────────────────┤
    │ MAZE               │ DRAW IT             │
    ├────────────────────┴─────────────────────┤
    │ NEXT UP  (next event from events.txt)    │
    └──────────────────────────────────────────┘

Where things come from:
    Look it up   a random reference from verses.txt (the same list as the
                 front page's verse chip). Tap the box for another.
    Next up      the first event in events.txt that's today or later.
                 Worked out in the browser, so it stays current by itself.

server.py hands in the verses and events. This file never reads files
and never imports server.py.

How shuffling works: every box with a data-act name has a maker in
ACTIVITIES inside KIDS_JS. maker(body, rng, box) fills the box's body.
rng() gives a random number from 0 to 1 and is seeded, so the same seed
always makes the same puzzle. Makers marked PLACEHOLDER are still to be
built.
"""
from __future__ import annotations

import json
from html import escape

# Used only if verses.txt is missing or empty.
FALLBACK_VERSES = ["John 3:16", "Psalm 23:1", "Philippians 4:13"]


# ─────────────────────────────────────────────────────────────
# Styles (only on the kids page)

KIDS_CSS = r"""
/* The sheet is the printed page: 8.5 x 11 inches, with a half-inch
   margin inside it. margin: 0 on the page also keeps the browser from
   printing the web address (and the access key) on every sheet. */
@page { size: letter; margin: 0; }

/* Wide enough to show the sheet at full size on a computer. On a
   phone, KIDS_JS shrinks the preview to fit. */
main { max-width: calc(8.5in + 50px); }

/* ── Toolbar above the sheet ─────────────────────────────── */
.kids-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px 18px;
  margin: 24px 0 20px;
}
.kids-print {
  font-family: 'Big Shoulders Stencil Display', 'Impact', sans-serif;
  font-weight: 900;
  font-size: 26px;
  line-height: 1;
  letter-spacing: 1px;
  text-transform: uppercase;
  padding: 10px 20px 11px;
  background: #0a0a0a;
  color: #f2ede4;
  border: 3px solid #0a0a0a;
  border-radius: 0;
  box-shadow: 5px 5px 0 #f01a8b;
  cursor: pointer;
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
}
.kids-print:active { transform: translate(3px, 3px); box-shadow: 2px 2px 0 #f01a8b; }
.kids-print:focus-visible { outline: 3px solid #f01a8b; outline-offset: 4px; }
.kids-hint {
  font-family: 'Special Elite', 'Courier New', monospace;
  font-size: 13px;
}

/* ── The sheet ───────────────────────────────────────────── */
.sheet-wrap { position: relative; overflow: hidden; }   /* KIDS_JS sets the height */
.sheet {
  width: 8.5in;
  height: 11in;
  padding: 0.5in;
  transform-origin: 0 0;
  background: #ffffff;
  color: #0a0a0a;
  box-shadow: inset 0 0 0 1.5px #0a0a0a, 6px 6px 0 #0a0a0a;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  row-gap: 0.16in;
  font-family: 'Special Elite', 'Courier New', monospace;
  -webkit-print-color-adjust: exact;   /* print the black label chips */
  print-color-adjust: exact;
}

/* White paper, not dotted beige, so no beige halo on the sheet's text
   (or on the print button, which has its own solid background). */
.kids-print,
.sheet, .sheet * {
  -webkit-text-stroke-width: 0 !important;
  -webkit-text-stroke-color: transparent !important;
  paint-order: normal !important;
}

/* Header: title on the left, Look it up on the right */
.sh-head {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  column-gap: 0.3in;
  align-items: stretch;
}
.sh-title {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
}
.sh-brand {
  font-family: 'Big Shoulders Stencil Display', 'Impact', sans-serif;
  font-weight: 900;
  font-size: 34pt;
  line-height: 0.85;
  letter-spacing: -0.5px;
  text-transform: uppercase;
  white-space: nowrap;
}
.sh-kind {
  margin-top: 0.1in;
  padding: 2px 10px 4px;
  background: #0a0a0a;
  color: #ffffff;
  font-family: 'Big Shoulders Stencil Display', 'Impact', sans-serif;
  font-weight: 800;
  font-size: 15pt;
  line-height: 1;
  letter-spacing: 3px;
  text-transform: uppercase;
  transform: rotate(-1.5deg);
}

/* Two lines to copy the verse onto */
.sh-lines span {
  display: block;
  height: 0.36in;
  border-bottom: 1.5px solid #0a0a0a;
}

/* The four activity boxes */
.sh-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0.16in;
  min-height: 0;
}
.act {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: 0.12in 0.14in 0.14in;
  border: 2px solid #0a0a0a;
}
.act-label {
  align-self: flex-start;
  margin: 0 0 0.1in;
  padding: 3px 8px 4px;
  background: #0a0a0a;
  color: #ffffff;
  font-family: 'Big Shoulders Stencil Display', 'Impact', sans-serif;
  font-weight: 800;
  font-size: 13pt;
  line-height: 1;
  letter-spacing: 2px;
  text-transform: uppercase;
  transform: rotate(-1.5deg);
}
.act-body { position: relative; flex: 1; min-height: 0; }

/* Look it up */
.lookup-ref {
  margin: 0;
  font-family: 'Big Shoulders Stencil Text', 'Impact', sans-serif;
  font-weight: 800;
  font-size: 20pt;
  line-height: 1;
  text-transform: uppercase;
}
.lookup-note { margin: 4px 0 0; font-size: 9pt; color: #6b665d; }

/* Next up */
.sh-foot {
  display: flex;
  align-items: center;
  gap: 0.16in;
  padding-top: 0.1in;
  border-top: 2.5px solid #0a0a0a;
}
.sh-foot .act-label { margin: 0; flex-shrink: 0; }
.ev-text { min-width: 0; }
.ev-title {
  margin: 0;
  font-family: 'Big Shoulders Stencil Text', 'Impact', sans-serif;
  font-weight: 800;
  font-size: 15pt;
  line-height: 1.05;
  text-transform: uppercase;
}
.ev-more {
  margin: 3px 0 0;
  font-size: 10pt;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.ev-when { font-weight: 700; }

/* PLACEHOLDER look, until each activity is built */
.ph {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0.25in;
  border: 1.5px dashed #b5b0a6;
  text-align: center;
  color: #6b665d;
  font-size: 10.5pt;
  line-height: 1.4;
}
.ph b {
  font-family: 'Big Shoulders Stencil Text', 'Impact', sans-serif;
  font-weight: 800;
  font-size: 16pt;
  color: #0a0a0a;
  text-transform: uppercase;
}
.ph small { font-size: 9pt; }

/* ── On screen only: tap to shuffle ──────────────────────── */
@media screen {
  .act[data-act] { cursor: pointer; }
  .act[data-act]::after {
    content: "\21BB  shuffle";
    position: absolute;
    top: 6px;
    right: 6px;
    padding: 3px 7px 4px;
    background: #f01a8b;
    color: #0a0a0a;
    font-family: 'Special Elite', 'Courier New', monospace;
    font-size: 11px;
    line-height: 1;
    letter-spacing: 1px;
    text-transform: uppercase;
    opacity: 0;
    transition: opacity 0.15s;
    pointer-events: none;
  }
  .act[data-act]:focus-visible { outline: 3px solid #f01a8b; outline-offset: 3px; }
  .act[data-act]:focus-visible::after { opacity: 1; }
  .act.shuffled { animation: kids-flash 0.45s ease-out; }
}
@media screen and (hover: hover) {
  .act[data-act]:hover { outline: 3px dashed #f01a8b; outline-offset: 3px; }
  .act[data-act]:hover::after { opacity: 1; }
}
@media screen and (hover: none) {
  .act[data-act]::after { opacity: 0.9; }   /* phones: always show the hint */
}
@keyframes kids-flash { from { background: #fde3f0; } to { background: #ffffff; } }
@media (prefers-reduced-motion: reduce) {
  .act.shuffled { animation: none; }
}

/* ── Printing: only the sheet, full size, one page ───────── */
@media print {
  html, body {
    width: 8.5in !important;
    height: 11in !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
  }
  main { max-width: none !important; margin: 0 !important; padding: 0 !important; }
  main > :not(.sheet-wrap) { display: none !important; }
  .sheet-wrap { height: auto !important; overflow: visible !important; }
  .sheet { transform: none !important; box-shadow: none !important; }
}
"""


# ─────────────────────────────────────────────────────────────
# Behavior

KIDS_JS = r"""
(function () {
  var sheet = document.getElementById('sheet');
  if (!sheet) return;
  var wrap = document.getElementById('sheet-wrap');

  function read(attr) {
    try { return JSON.parse(sheet.getAttribute(attr)) || []; } catch (e) { return []; }
  }
  var VERSES = read('data-verses');
  var EVENTS = read('data-events');   // [["2026-09-27", ["Fall potluck", ...]], ...] soonest first

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* Seeded random numbers (mulberry32): same seed, same puzzle. */
  function makeRng(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function newSeed() { return Math.floor(Math.random() * 4294967296); }
  function pick(list, rng) { return list[Math.floor(rng() * list.length)]; }

  /* PLACEHOLDER maker: shows what goes in the box, and counts shuffles
     so you can see tapping works. */
  function placeholder(name, what) {
    return function (body, rng, box) {
      var n = (+box.getAttribute('data-n') || 0) + 1;
      box.setAttribute('data-n', n);
      body.innerHTML =
        '<div class="ph"><b>' + name + '</b><span>' + what + '</span>' +
        '<small>Shuffle #' + n + '</small></div>';
    };
  }

  /* ── The activities ─────────────────────────────────── */
  var ACTIVITIES = {
    verse: function (body, rng, box) {
      var list = VERSES.length ? VERSES : ['John 3:16'];
      var last = box.getAttribute('data-ref');
      var ref = pick(list, rng);
      for (var tries = 0; ref === last && tries < 20; tries++) ref = pick(list, rng);
      box.setAttribute('data-ref', ref);
      // PLACEHOLDER: the reference will be written in secret code.
      body.innerHTML =
        '<p class="lookup-ref">' + esc(ref) + '</p>' +
        '<p class="lookup-note">Coming next: this will be in secret code.</p>';
    },
    picture: placeholder('Hidden picture',
      'Number clues around a grid. Shade the right squares to find the picture.'),
    words: placeholder('Word search',
      'A letter grid with a word bank underneath.'),
    maze: placeholder('Maze',
      'Stars, one-way arrows and jump circles, with a picture key for the rules.'),
    draw: placeholder('Draw it',
      'A drawing prompt and a big open box.')
  };

  function shuffle(box, flash) {
    var make = ACTIVITIES[box.getAttribute('data-act')];
    if (!make) return;
    var seed = newSeed();
    box.setAttribute('data-seed', seed);
    make(box.querySelector('.act-body'), makeRng(seed), box);
    if (flash) {
      box.classList.remove('shuffled');
      void box.offsetWidth;   // restart the flash
      box.classList.add('shuffled');
    }
  }

  var boxes = sheet.querySelectorAll('.act[data-act]');
  for (var i = 0; i < boxes.length; i++) {
    (function (box) {
      box.addEventListener('click', function () { shuffle(box, true); });
      box.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); shuffle(box, true); }
      });
      shuffle(box, false);
    })(boxes[i]);
  }

  /* ── Next up: the first event that's today or later ──── */
  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                'August', 'September', 'October', 'November', 'December'];
  var DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  // A short line with a number and am/pm, noon, or a colon: "10:30 AM", "6pm"
  var TIME_RE = /^(?=.*\d)(?=.*(a\.?m|p\.?m|noon|\d:\d\d)).{1,24}$/i;
  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function drawEvent() {
    var out = document.getElementById('sheet-event');
    var now = new Date();
    var today = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate());
    var next = null;
    for (var j = 0; j < EVENTS.length; j++) {
      if (EVENTS[j][0] >= today) { next = EVENTS[j]; break; }
    }
    if (!next) {
      out.innerHTML = '<p class="ev-title">See you next time at Grace House!</p>';
      return;
    }
    var p = next[0].split('-');
    var d = new Date(+p[0], +p[1] - 1, +p[2]);
    var when = (next[0] === today ? 'Today' : DAYS[d.getDay()]) + ', ' +
               MONTHS[d.getMonth()] + ' ' + d.getDate();
    var title = '', more = [];
    next[1].forEach(function (line) {
      line = line.replace(/^[-*]\s+/, '').trim();
      if (!line) return;
      if (TIME_RE.test(line)) when += ', ' + line;
      else if (!title) title = line;
      else more.push(line);
    });
    out.innerHTML =
      '<p class="ev-title">' + esc(title || 'Gathering at Grace House') + '</p>' +
      '<p class="ev-more"><span class="ev-when">' + esc(when) + '.</span> ' +
      esc(more.join(' ')) + '</p>';
  }
  drawEvent();

  /* ── Fit the preview to the screen (printing ignores this) ── */
  var SHADOW = 6;
  function fit() {
    var s = Math.min(1, (wrap.clientWidth - SHADOW) / sheet.offsetWidth);
    sheet.style.transform = s < 1 ? 'scale(' + s + ')' : '';
    wrap.style.height = Math.ceil(sheet.offsetHeight * s) + SHADOW + 'px';
  }
  fit();
  window.addEventListener('resize', fit);

  document.getElementById('kids-print').onclick = function () { window.print(); };
})();
"""


# ─────────────────────────────────────────────────────────────
# Markup

def _act(name: str, title: str) -> str:
    """One shuffleable box: a label chip and an empty body for its maker."""
    return (
        f'<section class="act act-{name}" data-act="{name}" role="button" tabindex="0" '
        f'aria-label="{escape(title)}. Tap to shuffle.">'
        f'<h2 class="act-label">{escape(title)}</h2>'
        '<div class="act-body"></div>'
        "</section>"
    )


def render_kids_sheet(verses: list[str], events) -> str:
    """The toolbar, the printable sheet, and its own CSS and JS.

    verses: ["John 3:16", ...]              from server.load_verses()
    events: [(date, [detail lines]), ...]   from server.parse_events()[0]
    """
    verse_data = escape(json.dumps(verses or FALLBACK_VERSES, ensure_ascii=False))
    event_data = escape(json.dumps(
        [[when.isoformat(), list(lines)] for when, lines in events],
        ensure_ascii=False,
    ))
    return (
        f"<style>{KIDS_CSS}</style>\n"
        '<div class="kids-bar">'
        '<button id="kids-print" class="kids-print" type="button">Print this sheet</button>'
        '<span class="kids-hint">Tap any box to shuffle it.</span>'
        "</div>\n"
        '<div id="sheet-wrap" class="sheet-wrap">\n'
        f'<div id="sheet" class="sheet" data-verses="{verse_data}" data-events="{event_data}">\n'
        '<header class="sh-head">'
        '<div class="sh-title">'
        '<div class="sh-brand">Grace House Kids</div>'
        '<div class="sh-kind">Activity Sheet</div>'
        "</div>"
        f'{_act("verse", "Look it up")}'
        "</header>\n"
        '<div class="sh-lines" aria-hidden="true"><span></span><span></span></div>\n'
        '<div class="sh-grid">\n'
        f'{_act("picture", "Hidden picture")}\n'
        f'{_act("words", "Word search")}\n'
        f'{_act("maze", "Maze")}\n'
        f'{_act("draw", "Draw it")}\n'
        "</div>\n"
        '<footer class="sh-foot">'
        '<h2 class="act-label">Next up</h2>'
        '<div id="sheet-event" class="ev-text"></div>'
        "</footer>\n"
        "</div>\n"
        "</div>\n"
        f"<script>{KIDS_JS}</script>"
    )
