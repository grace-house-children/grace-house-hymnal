#!/usr/bin/env python3
"""Grace House Kids — a one-page printable activity sheet.

The page lives at /{key}/kids/. It shows one US Letter sheet exactly as
it will print. The teacher taps any box on the sheet to shuffle it, and
presses Print when they like what they have. Everything on the sheet is
made in the visitor's browser, so the static build on GitHub Pages still
gives a fresh sheet every time, with nothing to rebuild.

    ┌──────────────────────────────────────────┐
    │ GRACE HOUSE KIDS  [ACTIVITY SHEET]       │
    ├──────────────────────────────────────────┤
    │ LOOK IT UP  directions                   │
    │ (coded verse, with blanks to fill in)    │
    │ KEY (symbols and what they stand for)    │
    ├────────────────────┬─────────────────────┤
    │ HIDDEN PICTURE     │ WORD SEARCH         │
    ├────────────────────┼─────────────────────┤
    │ MAZE               │ DRAW IT             │
    ├────────────────────┴─────────────────────┤
    │ NEXT UP  (next event from events.txt)    │
    └──────────────────────────────────────────┘

Where things come from:
    Look it up   a random reference from verses.txt (the same list as the
                 front page's verse chip), written in a secret code of
                 little symbols, with a key underneath. Kids crack the
                 code, then look the verse up in a Bible.
                 Each shuffle picks a new verse and new symbols. The
                 answer shows above the sheet, on screen only.
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
  line-height: 1.5;
}
.kids-hint b { font-weight: normal; color: #f01a8b; }

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

/* Title row: GRACE HOUSE KIDS with the Activity Sheet chip beside it */
.sh-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.08in 0.22in;
}
.sh-brand {
  display: flex;
  align-items: center;
  font-family: 'Big Shoulders Stencil Display', 'Impact', sans-serif;
  font-weight: 900;
  font-size: 34pt;
  line-height: 0.85;
  letter-spacing: -0.5px;
  text-transform: uppercase;
  white-space: nowrap;
}
/* The 8-spoke wheel stands in for the O in HOUSE, same as the site's
   logo, but drawn heavier to match the solid letters. */
.sh-wheel {
  width: 0.77em;
  height: 0.77em;
  margin: 0 -0.02em 0 -0.04em;
  flex-shrink: 0;
}
/* Read aloud by screen readers, never shown */
.sh-sr {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
.sh-kind {
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

/* Look it up, full width: label and directions, then the coded
   reference, big enough to write in, then the key under it. */
.act-verse {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  column-gap: 0.14in;
  row-gap: 0.12in;
}
.act-verse .act-label { margin: 0; }
.act-verse .act-body {
  grid-column: 1 / -1;
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.16in;
}
.act-note { margin: 0; font-size: 9.5pt; line-height: 1.3; }

/* Code symbols: drawn in the text color, a few of them filled in */
.cs {
  display: block;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
  overflow: visible;
}
.cs .f { fill: currentColor; }

/* The coded reference. Words never split; a long one wraps whole. */
.code-msg {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  column-gap: 0.2in;
  row-gap: 0.12in;
}
.cw { display: flex; align-items: flex-end; }
.cc {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 0.31in;
}
.cc .cs { width: 0.24in; height: 0.24in; }
.cc i {                       /* the blank to write the letter on */
  display: block;
  width: 0.24in;
  height: 0.32in;
  border-bottom: 1.5px solid #0a0a0a;
}
.cp {                         /* a colon or dash, printed as is */
  width: 0.16in;
  text-align: center;
  font-family: 'Big Shoulders Stencil Text', 'Impact', sans-serif;
  font-weight: 800;
  font-size: 20pt;
  line-height: 1;
}

/* The key: each symbol over the letter or number it stands for */
.code-key {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.05in;
}
.code-key-label {
  margin-right: 0.06in;
  font-family: 'Big Shoulders Stencil Text', 'Impact', sans-serif;
  font-weight: 800;
  font-size: 11pt;
  letter-spacing: 1.5px;
  text-transform: uppercase;
}
.kp {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 0.3in;
  padding: 4px 0 3px;
  border: 1px solid #0a0a0a;
}
.kp .cs { width: 0.19in; height: 0.19in; }
.kp b {
  margin-top: 3px;
  font-family: 'Big Shoulders Stencil Text', 'Impact', sans-serif;
  font-weight: 800;
  font-size: 12.5pt;
  line-height: 1;
}
.kp-gap { width: 0.1in; }     /* between the letters and the numbers */

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

/* ── Printing: only the sheet, full size, one page ───────────
   Don't lock html/body to a height or hide their overflow here:
   Safari then prints from wherever the page was scrolled to, and the
   top of the sheet gets cut off. Instead the sheet is a hair shorter
   than the paper, so rounding can never spill a blank second page. */
@media print {
  html, body { margin: 0 !important; padding: 0 !important; }
  main { max-width: none !important; margin: 0 !important; padding: 0 !important; }
  main > :not(.sheet-wrap) { display: none !important; }
  .sheet-wrap { height: auto !important; overflow: visible !important; }
  .sheet {
    height: 10.98in;
    transform: none !important;
    box-shadow: none !important;
    break-inside: avoid;
    page-break-inside: avoid;
  }
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

  /* ── Look it up: the secret code ────────────────────────
     Every letter and number in the reference gets its own symbol,
     picked fresh on each shuffle. The key lists those plus a few
     decoy letters, so matching by count won't give the answer away. */
  var SHAPES = [
    '<circle cx="10" cy="10" r="7"/>',                                        // ring
    '<circle class="f" cx="10" cy="10" r="7"/>',                              // dot
    '<rect x="3.5" y="3.5" width="13" height="13"/>',                         // square
    '<rect class="f" x="3.5" y="3.5" width="13" height="13"/>',               // block
    '<path d="M10 3L17.5 16.5H2.5Z"/>',                                       // triangle
    '<path class="f" d="M10 3L17.5 16.5H2.5Z"/>',
    '<path d="M10 2.5L17.5 10L10 17.5L2.5 10Z"/>',                            // diamond
    '<path class="f" d="M10 2.5L17.5 10L10 17.5L2.5 10Z"/>',
    '<path d="M10 16.5C4.5 12.5 2.5 9.8 2.5 7.2C2.5 4.8 4.3 3.3 6.3 3.3C7.9 3.3 9.2 4.2 10 5.6C10.8 4.2 12.1 3.3 13.7 3.3C15.7 3.3 17.5 4.8 17.5 7.2C17.5 9.8 15.5 12.5 10 16.5Z"/>',
    '<path class="f" d="M10 16.5C4.5 12.5 2.5 9.8 2.5 7.2C2.5 4.8 4.3 3.3 6.3 3.3C7.9 3.3 9.2 4.2 10 5.6C10.8 4.2 12.1 3.3 13.7 3.3C15.7 3.3 17.5 4.8 17.5 7.2C17.5 9.8 15.5 12.5 10 16.5Z"/>',
    '<path d="M10 2.4L12.1 8L18 8.2L13.3 11.9L14.9 17.6L10 14.3L5.1 17.6L6.7 11.9L2 8.2L7.9 8Z"/>',
    '<path class="f" d="M10 2.4L12.1 8L18 8.2L13.3 11.9L14.9 17.6L10 14.3L5.1 17.6L6.7 11.9L2 8.2L7.9 8Z"/>',
    '<path d="M10 3V17M3 10H17"/>',                                           // plus
    '<path d="M4.5 4.5L15.5 15.5M15.5 4.5L4.5 15.5"/>',                       // x
    '<path class="f" d="M13 3.4A7.25 7.25 0 1 0 13 16.6A7 7 0 0 1 13 3.4Z"/>', // moon
    '<circle cx="10" cy="10" r="3.6"/><path d="M10 1.5V4.2M10 15.8V18.5M1.5 10H4.2M15.8 10H18.5M4 4L5.9 5.9M14.1 14.1L16 16M16 4L14.1 5.9M5.9 14.1L4 16"/>', // sun
    '<path d="M1.8 13.5C5 6 12.5 5 17.5 10C12.5 15 5 14 1.8 6.5"/>',          // fish
    '<path d="M10 17.5V3M4.5 8.5L10 3L15.5 8.5"/>',                           // arrow
    '<path class="f" d="M11.5 1.8L4.5 11H9.5L8 18.2L15.5 8.5H10.5Z"/>',       // lightning
    '<path d="M10 2.5C10 2.5 4.5 9 4.5 12.3A5.5 5.5 0 0 0 15.5 12.3C15.5 9 10 2.5 10 2.5Z"/>', // drop
    '<path d="M3 15.5V6L7 10L10 4L13 10L17 6V15.5Z"/>',                       // crown
    '<path d="M1.5 10.5Q4 5 6.5 10.5T11.5 10.5T16.5 10.5"/>'                  // wave
  ];
  var LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

  function shuffled(list, rng) {
    var a = list.slice();
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(rng() * (i + 1));
      var t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  }
  function symbol(shape) {
    return '<svg class="cs" viewBox="0 0 20 20" aria-hidden="true">' + shape + '</svg>';
  }

  function secretCode(ref, rng) {
    var text = ref.toUpperCase();
    var used = [];
    for (var i = 0; i < text.length; i++) {
      var ch = text.charAt(i);
      if (/[A-Z0-9]/.test(ch) && used.indexOf(ch) === -1) used.push(ch);
    }
    // Up to 4 decoy letters, fewer for long references so the key
    // stays on one row, and never more than there are symbols
    var decoys = Math.max(0, Math.min(4, 17 - used.length, SHAPES.length - used.length));
    var spare = LETTERS.split('').filter(function (c) { return used.indexOf(c) === -1; });
    var keyChars = used.concat(shuffled(spare, rng).slice(0, decoys));
    var shapes = shuffled(SHAPES, rng);
    var map = {};
    keyChars.forEach(function (c, n) { map[c] = shapes[n % shapes.length]; });

    // The message: a symbol and a blank for each letter or number
    var msg = text.split(/\s+/).filter(Boolean).map(function (word) {
      var cells = word.split('').map(function (c) {
        return map[c]
          ? '<span class="cc">' + symbol(map[c]) + '<i></i></span>'
          : '<span class="cp">' + esc(c) + '</span>';
      }).join('');
      return '<span class="cw">' + cells + '</span>';
    }).join('');

    // The key: letters A to Z, then numbers
    var letters = keyChars.filter(function (c) { return /[A-Z]/.test(c); }).sort();
    var digits = keyChars.filter(function (c) { return /[0-9]/.test(c); }).sort();
    function pair(c) { return '<span class="kp">' + symbol(map[c]) + '<b>' + c + '</b></span>'; }
    var key = letters.map(pair).join('') +
      (digits.length ? '<span class="kp-gap"></span>' + digits.map(pair).join('') : '');

    return '<div class="code-msg" role="img" aria-label="' + esc(ref) + ' in secret code">' + msg + '</div>' +
      '<div class="code-key"><span class="code-key-label">Key</span>' + key + '</div>';
  }

  /* ── The activities ─────────────────────────────────── */
  var ACTIVITIES = {
    verse: function (body, rng, box) {
      var list = VERSES.length ? VERSES : ['John 3:16'];
      var last = box.getAttribute('data-ref');
      var ref = pick(list, rng);
      for (var tries = 0; ref === last && tries < 20; tries++) ref = pick(list, rng);
      box.setAttribute('data-ref', ref);
      body.innerHTML = secretCode(ref, rng);
      // Only on screen, above the sheet: which verse this sheet has
      var answer = document.getElementById('kids-answer');
      if (answer) answer.textContent = ref;
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

  /* ── Printing ───────────────────────────────────────── */
  // Some browsers (Safari) print from the current scroll position, so
  // jump to the top while printing and come back afterward. Covers both
  // the Print button and Cmd+P / Ctrl+P.
  var savedY = null;
  function toTop() {
    if (savedY === null) savedY = window.scrollY;
    window.scrollTo(0, 0);
  }
  function comeBack() {
    if (savedY !== null) { window.scrollTo(0, savedY); savedY = null; }
  }
  window.addEventListener('beforeprint', toTop);
  window.addEventListener('afterprint', comeBack);
  document.getElementById('kids-print').onclick = function () { toTop(); window.print(); };
})();
"""


# ─────────────────────────────────────────────────────────────
# Markup

# The Grace House wheel (8 spokes), drawn in the text color. Same shape
# as BRAND_LOGO in server.py, with heavier lines for the solid title.
# Rim and spokes share one line weight.
SHEET_WHEEL = (
    '<svg class="sh-wheel" viewBox="0 0 34 34" aria-hidden="true" '
    'fill="none" stroke="currentColor">'
    '<circle cx="17" cy="17" r="13.6" stroke-width="3"/>'
    '<line x1="17" y1="4" x2="17" y2="30" stroke-width="3"/>'
    '<line x1="4" y1="17" x2="30" y2="17" stroke-width="3"/>'
    '<line x1="7.81" y1="7.81" x2="26.19" y2="26.19" stroke-width="3"/>'
    '<line x1="26.19" y1="7.81" x2="7.81" y2="26.19" stroke-width="3"/>'
    '<circle cx="17" cy="17" r="3.4" fill="currentColor" stroke="none"/>'
    "</svg>"
)

def _act(name: str, title: str, note: str = "") -> str:
    """One shuffleable box: a label chip, optional directions beside it,
    and an empty body for its maker."""
    note_html = f'<p class="act-note">{escape(note)}</p>' if note else ""
    return (
        f'<section class="act act-{name}" data-act="{name}" role="button" tabindex="0" '
        f'aria-label="{escape(title)}. Tap to shuffle.">'
        f'<h2 class="act-label">{escape(title)}</h2>'
        f"{note_html}"
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
        '<span class="kids-hint">Tap any box to shuffle it.<br>'
        'This sheet\'s verse: <b id="kids-answer"></b></span>'
        "</div>\n"
        '<div id="sheet-wrap" class="sheet-wrap">\n'
        f'<div id="sheet" class="sheet" data-verses="{verse_data}" data-events="{event_data}">\n'
        '<header class="sh-head">'
        '<div class="sh-brand">'
        '<span class="sh-sr">Grace House Kids</span>'
        f'<span aria-hidden="true">Grace H</span>{SHEET_WHEEL}'
        '<span aria-hidden="true">use Kids</span>'
        "</div>"
        '<div class="sh-kind">Activity Sheet</div>'
        "</header>\n"
        f'{_act("verse", "Look it up", "Crack the code, then find the verse in a Bible.")}\n'
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
