"""Generate the symbol-explorer website for the regenerated 1D font.

Layout mirrors Slevinski's symbols browser:

  index.html         — parent grid. One cell per base (S100..S38b),
                       showing that base's "fill 0 / rot 0" glyph. Click a
                       cell to drill into the per-base detail page.
  S{base}.html       — one page per base. 16×16 grid of (fill × rotation)
                       cells, decorated and with rich hover previews.
  about.html         — explainer page describing the dedup categories.
  new.ttf, old.ttf   — copied alongside so @font-face works on file://.

Decoration:
  • orange fill  → glyph is a D4 transformation composite (hand dedup).
  • green border → glyph contains ≥1 approximately-circular sub-path.

Sticky header on every page has a "Use upstream OneD font" toggle whose
choice persists in localStorage so it survives navigation.

Usage:
    python -m signwriting_fonts.font_1d.site \\
        --new-ttf   fonts/SignWritingOneD-base.ttf \\
        --old-ttf   fonts/SuttonSignWritingOneD.ttf \\
        --duplicates signwriting_fonts/font_1d/duplicates.json \\
        --circles   signwriting_fonts/font_1d/circles.json \\
        --out-dir   assets/regen/symbols
"""

from __future__ import annotations

import argparse
import functools
import json
import shutil
from html import escape
from pathlib import Path

from fontTools.ttLib import TTFont


# ---------------------------------------------------------------------------
# Symkey ↔ codepoint helpers (mirror signwriting_fonts/font_1d/_symkey.py).
# Kept duplicated here so the generator stays self-contained and the JS we
# emit uses the same formula.
# ---------------------------------------------------------------------------

def _symkey_cp(sym: str) -> int:
    base = int(sym[1:4], 16)
    vh = int(sym[4], 16)
    vl = int(sym[5], 16)
    return 0x40000 + (base - 0x100) * 96 + vh * 16 + vl + 1


@functools.lru_cache(maxsize=None)
def _unicode_name(sym: str) -> str | None:
    """Return the official Unicode SignWriting name for a symkey, or None.
    The mapping is direct: U+1D800 + (base - 0x100). Same name for every
    variant of a base (the Unicode standard names the *base*, not the
    fill/rotation). Cached because site.py calls this for each of ~167k
    cell renders across all detail pages."""
    try:
        import unicodedata
        base = int(sym[1:4], 16)
        return unicodedata.name(chr(0x1D800 + base - 0x100))
    except (ValueError, OverflowError, IndexError):
        return None


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path and path.exists() else {}


# ---------------------------------------------------------------------------
# ISWA 2010 top-level categories.
#   https://www.signbank.org/iswa/
# Each entry is (anchor-id, display-title, hex-start, hex-end-inclusive).
# Boundaries are derived from the Unicode names assigned in the
# SignWriting block (U+1D800 + (base - 0x100)). Symbols outside any
# range get dumped at the end under a sentinel "Other" section.
# ---------------------------------------------------------------------------
ISWA_CATEGORIES = [
    ("hands",       "1. Hands",              0x100, 0x204),
    ("movement",    "2. Movement",           0x205, 0x2f4),
    ("dynamics",    "3. Dynamics & Timing",  0x2f5, 0x2fe),
    ("head",        "4. Head & Faces",       0x2ff, 0x36c),
    ("body",        "5. Body",               0x36d, 0x375),
    ("location",    "6. Detailed Location",  0x376, 0x386),
    ("punctuation", "7. Punctuation",        0x387, 0x38b),
]


def _category_for(base: int) -> tuple[str, str] | None:
    for anchor, title, lo, hi in ISWA_CATEGORIES:
        if lo <= base <= hi:
            return anchor, title
    return None


# ---------------------------------------------------------------------------
# Cell metadata
# ---------------------------------------------------------------------------

def _cell_attrs(sym: str, dups, comps, circles
                ) -> tuple[str, dict[str, str]]:
    classes = ["cell"]
    attrs: dict[str, str] = {"data-sym": sym}
    name = _unicode_name(sym)
    if name:
        attrs["data-name"] = name
    is_dup = sym in dups
    if is_dup:
        e = dups[sym]
        classes.append("dup")
        attrs["data-dup-base"] = e["duplicate_of"]
        attrs["data-dup-transform"] = e["transform"]
    is_comp = sym in comps and not is_dup
    if is_comp:
        classes.append("comp")
        parts = comps[sym]["parts"]
        # Encode each part as "ref" or "ref:M" (transform suffix).
        encoded = ",".join(
            p["ref"] + (":" + p["transform"] if p.get("transform") else "")
            for p in parts
        )
        attrs["data-comp-parts"] = encoded
    if sym in circles and not is_dup:
        attrs["data-circles"] = str(circles[sym])
        classes.append("has-circle")
    return " ".join(classes), attrs


def _attr_str(attrs: dict[str, str]) -> str:
    return " ".join(f'{k}="{escape(v)}"' for k, v in attrs.items())


# ---------------------------------------------------------------------------
# Shared CSS + JS — emitted into a single style block per page.
# ---------------------------------------------------------------------------

_COMMON_CSS = """
@font-face {
  font-family: "SWNew";
  src: url("new.ttf") format("truetype");
}
@font-face {
  font-family: "SWOld";
  src: url("old.ttf") format("truetype");
}
:root {
  --bg: #ffffff;
  --fg: #1d1d1d;
  --muted: #888;
  --dup: #ffb96b;
  --comp: #b8e3a8;
  --circle: #2f9a2f;
}
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg);
  font: 14px/1.4 -apple-system, system-ui, sans-serif; }
header {
  position: sticky; top: 0; z-index: 100;
  background: rgba(255,255,255,0.96);
  backdrop-filter: blur(6px);
  border-bottom: 1px solid #e0e0e0;
  padding: 10px 24px;
  display: flex; align-items: center; gap: 16px;
}
header a.brand { color: #1d1d1d; text-decoration: none; font-weight: 600; }
header a.brand:hover { text-decoration: underline; }
header nav a { color: #555; margin-right: 12px; text-decoration: none; }
header nav a:hover { color: #000; text-decoration: underline; }
header label { display: flex; align-items: center; gap: 6px;
  font-size: 13px; user-select: none; cursor: pointer; }
header .legend { display: flex; gap: 14px; margin-left: auto;
  font-size: 12px; color: #555; }
header .legend span { display: inline-flex; align-items: center; gap: 4px; }
header .legend .sw {
  display: inline-block; width: 14px; height: 14px;
  border-radius: 3px; vertical-align: middle;
}
main { padding: 24px 24px 80px; max-width: 1280px; margin: 0 auto; }
.cell {
  position: relative;
  display: flex; align-items: center; justify-content: center;
  border: 1px solid transparent;
  border-radius: 2px;
  font-family: "SWNew", sans-serif;
  line-height: 1;
  color: #000;
  background: #f8f8f8;
  cursor: default;
}
body.old-font .cell { font-family: "SWOld", sans-serif; }
.cell.empty { background: transparent; color: transparent; }
.cell.dup     { background: var(--dup); }
.cell.comp    { background: var(--comp); }
.cell.dup.comp {
  background: linear-gradient(135deg, var(--dup) 50%, var(--comp) 50%);
}
.cell.has-circle { border-color: var(--circle); }
.cell:hover { outline: 2px solid #333; z-index: 5; }
#tip {
  position: fixed; pointer-events: none;
  background: #222; color: #fff;
  font: 12px/1.4 -apple-system, system-ui, sans-serif;
  padding: 10px 12px; border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.25);
  z-index: 200; max-width: 360px;
  display: none;
}
#tip .row { display: flex; align-items: center; gap: 8px;
  margin: 4px 0; flex-wrap: wrap; }
#tip .label { color: #ddd; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.04em; }
#tip .sym {
  font-family: "SWNew", sans-serif;
  font-size: 36px; line-height: 1;
  background: #fff; color: #000;
  border-radius: 4px; padding: 4px 8px;
  display: inline-block;
}
body.old-font #tip .sym { font-family: "SWOld", sans-serif; }
#tip .prim-svg {
  background: #fff; border-radius: 4px; padding: 4px;
  width: 40px; height: 40px;
}
#tip .name { font-family: ui-monospace, Menlo, monospace;
  font-size: 11px; color: #ccc; }
#tip .op { font-family: ui-monospace, Menlo, monospace;
  font-size: 13px; color: #fff; font-weight: 600; padding: 0 4px; }
#tip .chip { font: 11px ui-monospace, Menlo, monospace;
  background: #444; padding: 2px 6px; border-radius: 3px; }
"""

_DETAIL_CSS = """
.detail-grid {
  display: grid;
  grid-template-columns: 28px repeat(16, 44px);
  grid-auto-rows: 44px;
  gap: 1px;
  align-items: center;
}
.detail-grid .cell { width: 44px; height: 44px; font-size: 26px; }
.detail-grid .head, .detail-grid .row-label {
  text-align: center;
  font: 11px ui-monospace, Menlo, monospace;
  color: var(--muted);
}
.detail-grid .cell a { text-decoration: none; color: inherit;
  display: block; width: 100%; height: 100%;
  display: flex; align-items: center; justify-content: center; }
.base-nav { display: flex; gap: 8px; margin-bottom: 14px; align-items: center;
  font: 12px ui-monospace, Menlo, monospace; }
.base-nav a { color: #1f6feb; text-decoration: none; padding: 2px 8px;
  border: 1px solid #ddd; border-radius: 4px; }
.base-nav a:hover { background: #eef; }
.base-nav .here { color: #555; padding: 2px 8px; }
"""

_INDEX_CSS = """
.parent-grid {
  display: grid;
  grid-template-columns: repeat(16, 56px);
  gap: 4px;
}
.parent-grid .cell {
  width: 56px; height: 56px; font-size: 30px;
  border-radius: 4px;
}
.parent-grid .cell a { text-decoration: none; color: inherit;
  display: flex; align-items: center; justify-content: center;
  width: 100%; height: 100%; }
.parent-grid .label {
  font: 10px ui-monospace, Menlo, monospace; color: #888;
  text-align: center; margin-top: -2px;
}
.parent-cell-wrap {
  display: flex; flex-direction: column; align-items: center;
  gap: 2px;
}
.iswa-toc {
  display: flex; flex-wrap: wrap; gap: 6px 14px;
  margin: 0 0 22px 0; padding: 0; list-style: none;
  font-size: 13px;
}
.iswa-toc a {
  color: #444; text-decoration: none;
  padding: 3px 8px; border-radius: 12px;
  background: #eef1f4;
}
.iswa-toc a:hover { background: #d9dde3; color: #000; }
.iswa-section { margin: 26px 0 18px 0; }
.iswa-section h2 {
  font-size: 18px; margin: 0 0 4px 0; padding: 0;
  scroll-margin-top: 60px;
}
.iswa-section .sub {
  color: #888; font-size: 12px; margin: 0 0 10px 0;
  font: 12px ui-monospace, Menlo, monospace;
}
"""

_HEADER_HTML = """<header>
  <a class="brand" href="index.html">SignWriting 1D · symbol explorer</a>
  <nav>
    <a href="about.html">About</a>
  </nav>
  <label>
    <input type="checkbox" id="oldFontToggle">
    Use upstream OneD font
  </label>
  <div class="legend">
    <span><span class="sw" style="background:var(--dup)"></span>D4 dedup</span>
    <span><span class="sw" style="background:var(--comp)"></span>rule composition</span>
    <span><span class="sw" style="border:2px solid var(--circle); width:10px; height:10px"></span>contains a circle</span>
  </div>
</header>"""

_FONT_TOGGLE_JS = """
const toggle = document.getElementById("oldFontToggle");
const KEY = "sw-old-font";
if (localStorage.getItem(KEY) === "1") {
  toggle.checked = true;
  document.body.classList.add("old-font");
}
toggle.addEventListener("change", () => {
  document.body.classList.toggle("old-font", toggle.checked);
  localStorage.setItem(KEY, toggle.checked ? "1" : "0");
});

// Live-reload: when served via `make serve`, poll version.txt every 2s
// and hard-reload when it changes. No-op when opened via file://.
(function () {
  if (location.protocol === "file:") return;
  let last = null;
  setInterval(() => {
    fetch("version.txt?_=" + Date.now())
      .then(r => r.ok ? r.text() : null)
      .then(v => {
        if (v == null) return;
        if (last === null) { last = v; return; }
        if (v !== last) location.reload();
      })
      .catch(() => {});
  }, 2000);
})();
"""

# Detail-page tooltip JS. Builds rich HTML on hover, with a mini render
# of the dedup base via @font-face when the cell is a D4 duplicate.
_TIP_JS = """
function symkeyCp(sym) {
  const base = parseInt(sym.slice(1, 4), 16);
  const vh = parseInt(sym[4], 16);
  const vl = parseInt(sym[5], 16);
  return 0x40000 + (base - 0x100) * 96 + vh * 16 + vl + 1;
}
function renderMini(sym) {
  const cp = symkeyCp(sym);
  return `<div class="row">
    <span class="sym">${String.fromCodePoint(cp)}</span>
    <span class="name">${sym}</span>
  </div>`;
}
const tip = document.getElementById("tip");
function show(cell, ev) {
  const sym = cell.dataset.sym;
  if (!sym) return;
  const cp = symkeyCp(sym);
  let html = `<div class="row">
    <span class="sym">${String.fromCodePoint(cp)}</span>
    <span class="name">${sym} · U+${cp.toString(16).toUpperCase()}</span>
  </div>`;
  if (cell.dataset.dupBase) {
    html += `<div class="row"><span class="label">= ${cell.dataset.dupTransform} of</span></div>`;
    html += renderMini(cell.dataset.dupBase);
  }
  if (cell.dataset.compParts) {
    const parts = cell.dataset.compParts.split(",");
    html += `<div class="row"><span class="label">composed of ${parts.length} part${parts.length>1?"s":""}</span></div>`;
    for (const p of parts) {
      const [ref, xform] = p.split(":");
      const suffix = xform ? `<span class="op">(${xform})</span>` : "";
      html += renderMini(ref).replace('</div>', suffix + '</div>');
    }
  }
  if (cell.dataset.circles) {
    const n = parseInt(cell.dataset.circles, 10);
    html += `<div class="row"><span class="label">contains ${n} circle${n>1?"s":""}</span></div>`;
  }
  tip.innerHTML = html;
  tip.style.display = "block";
  position(ev);
}
function position(ev) {
  const r = tip.getBoundingClientRect();
  let x = ev.clientX + 16;
  let y = ev.clientY + 16;
  if (x + r.width > window.innerWidth - 8) x = ev.clientX - r.width - 16;
  if (y + r.height > window.innerHeight - 8) y = ev.clientY - r.height - 16;
  tip.style.left = Math.max(8, x) + "px";
  tip.style.top = Math.max(8, y) + "px";
}
function hide() { tip.style.display = "none"; }
document.querySelectorAll(".cell[data-sym]").forEach(c => {
  c.addEventListener("mouseenter", e => show(c, e));
  c.addEventListener("mousemove", position);
  c.addEventListener("mouseleave", hide);
});
"""


# ---------------------------------------------------------------------------
# Page emission
# ---------------------------------------------------------------------------

def _page(title: str, body: str, *, extra_css: str = "",
          extra_js: str = "") -> str:
    """Wrap a body fragment in the shared shell (header + font toggle)."""
    head = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f'<title>{escape(title)}</title>\n'
        f'<style>\n{_COMMON_CSS}{extra_css}\n</style>\n'
        '</head>\n<body>\n'
    )
    foot = (
        f'\n<script>\n{_FONT_TOGGLE_JS}\n{extra_js}\n</script>\n'
        '</body>\n</html>\n'
    )
    return head + _HEADER_HTML + body + foot


def _write_index(out_dir: Path, by_base: dict, dups, comps, circles) -> None:
    """Parent grid: one cell per base showing the canonical S{base}00
    glyph, grouped into the seven ISWA 2010 top-level categories
    (https://www.signbank.org/iswa/). Each parent cell is styled and
    hovered exactly like its detail-page counterpart for S{base}00 — no
    family-level aggregation, so the parent grid honestly reflects
    whether the canonical variant is itself a D4 composite /
    circle-containing. Click the cell to drill into the 16×16 detail
    page."""
    bases = sorted(by_base.keys())
    grouped: dict[str, list[int]] = {}
    other: list[int] = []
    for base in bases:
        cat = _category_for(base)
        if cat is None:
            other.append(base)
        else:
            grouped.setdefault(cat[0], []).append(base)

    parts = ['<main>',
             '<p style="color:#555; max-width:760px;">'
             f'{len(bases)} base symbols organized by the seven '
             f'<a href="https://www.signbank.org/iswa/" target="_blank" '
             f'rel="noopener">ISWA 2010</a> categories. Each cell shows '
             f'the canonical S<i>xxx</i>00 variant, styled and hovered '
             f'as on its detail page. Click a cell to see the full 16×16 '
             f'fill × rotation grid.</p>']

    parts.append('<ul class="iswa-toc">')
    for anchor, title, lo, hi in ISWA_CATEGORIES:
        n = len(grouped.get(anchor, []))
        if n == 0:
            continue
        parts.append(f'<li><a href="#{anchor}">{escape(title)} ({n})</a></li>')
    parts.append('</ul>')

    def _cell(base: int) -> str:
        cells = {(f, r): cp for (f, r, cp) in by_base[base]}
        canonical_sym = f"S{base:03x}00"
        canonical_cp = cells.get((0, 0))
        if canonical_cp is None:
            if not cells:
                return ""
            (f0, r0), canonical_cp = next(iter(sorted(cells.items())))
            canonical_sym = f"S{base:03x}{f0:x}{r0:x}"
        classes, attrs = _cell_attrs(canonical_sym, dups, comps, circles)
        return (
            f'<div class="parent-cell-wrap">'
            f'<div class="{classes}" {_attr_str(attrs)} '
            f'style="width:56px;height:56px;font-size:30px">'
            f'<a href="S{base:03x}.html">{chr(canonical_cp)}</a></div>'
            f'<div class="label">S{base:03x}</div></div>'
        )

    for anchor, title, lo, hi in ISWA_CATEGORIES:
        sub = grouped.get(anchor, [])
        if not sub:
            continue
        parts.append(f'<section class="iswa-section" id="{anchor}">')
        parts.append(f'<h2>{escape(title)}</h2>')
        parts.append(
            f'<p class="sub">S{lo:03x}–S{hi:03x} · {len(sub)} symbols</p>'
        )
        parts.append('<div class="parent-grid">')
        for base in sub:
            parts.append(_cell(base))
        parts.append('</div>')
        parts.append('</section>')

    if other:
        parts.append('<section class="iswa-section" id="other">')
        parts.append(f'<h2>Other</h2>')
        parts.append(
            f'<p class="sub">{len(other)} symbols outside the ISWA 2010 '
            f'top-level categories</p>'
        )
        parts.append('<div class="parent-grid">')
        for base in other:
            parts.append(_cell(base))
        parts.append('</div>')
        parts.append('</section>')

    parts.append('<div id="tip"></div>')
    parts.append('</main>')
    body = "".join(parts)

    (out_dir / "index.html").write_text(
        _page("SignWriting 1D · symbol explorer", body,
              extra_css=_INDEX_CSS,
              extra_js=_TIP_JS)
    )


def _write_detail(out_dir: Path, base: int, by_base, all_bases, idx_of,
                  dups, comps, circles) -> None:
    cells = {(f, r): cp for (f, r, cp) in by_base[base]}
    idx = idx_of[base]
    prev_b = all_bases[idx - 1] if idx > 0 else None
    next_b = all_bases[idx + 1] if idx + 1 < len(all_bases) else None

    parts = ['<main>',
             '<div class="base-nav">']
    parts.append('<a href="index.html">← all symbols</a>')
    if prev_b is not None:
        parts.append(f'<a href="S{prev_b:03x}.html">← S{prev_b:03x}</a>')
    parts.append(f'<span class="here">S{base:03x}</span>')
    if next_b is not None:
        parts.append(f'<a href="S{next_b:03x}.html">S{next_b:03x} →</a>')
    parts.append('</div>')

    parts.append('<div class="detail-grid">')
    parts.append('<div class="head"></div>')
    for r in range(16):
        parts.append(f'<div class="head">{r:x}</div>')
    for f in range(16):
        parts.append(f'<div class="row-label">{f:x}</div>')
        for r in range(16):
            cp = cells.get((f, r))
            if cp is None:
                parts.append('<div class="cell empty"></div>')
                continue
            sym = f"S{base:03x}{f:x}{r:x}"
            classes, attrs = _cell_attrs(sym, dups, comps, circles)
            parts.append(
                f'<div class="{classes}" {_attr_str(attrs)}>{chr(cp)}</div>'
            )
    parts.append('</div>')
    parts.append('<div id="tip"></div>')
    parts.append('</main>')
    body = "".join(parts)

    (out_dir / f"S{base:03x}.html").write_text(
        _page(f"S{base:03x} — SignWriting 1D", body,
              extra_css=_DETAIL_CSS,
              extra_js=_TIP_JS)
    )


def _example_cell(sym, dups, comps, circles, *, cp=None):
    """Render a hoverable example cell for the About page — identical
    styling to the detail-page grid (orange/green/border + tooltip)."""
    if cp is None:
        cp = _symkey_cp(sym)
    classes, attrs = _cell_attrs(sym, dups, comps, circles)
    return (
        f'<div class="{classes} example-cell" {_attr_str(attrs)}>'
        f'{chr(cp)}</div>'
    )


def _make_about_body(new_ttf, old_ttf, unopt_ttf,
                     dups, comps, circles) -> str:
    upstream_b = old_ttf.stat().st_size
    unopt_b = unopt_ttf.stat().st_size
    composed_b = new_ttf.stat().st_size
    kb = lambda b: f"{b/1024:,.0f} KB"

    def cell(sym): return _example_cell(sym, dups, comps, circles)

    return f"""<main style="max-width: 800px">
<h1>How the 1D font is built</h1>
<p>
The Sutton SignWriting OneD font ships with ~38,000 glyphs. Many hand
variants are rigid rotations or reflections of others — the regenerated
font encodes that structure directly via TrueType composite glyphs,
yielding a smaller font without losing any glyph.
</p>

<h2>File size impact</h2>
<table class="sizes">
<tr><th></th><th>Size</th><th>vs upstream</th></tr>
<tr><td>Upstream <code>SuttonSignWritingOneD.ttf</code></td>
    <td>{kb(upstream_b)}</td><td>—</td></tr>
<tr><td>Our build, <em>no</em> pointer dedup (every glyph as its own outline)</td>
    <td>{kb(unopt_b)}</td>
    <td>−{(1-unopt_b/upstream_b)*100:.0f}%</td></tr>
<tr><td>Our build with D4 hand-rotation composites</td>
    <td><b>{kb(composed_b)}</b></td>
    <td>−{(1-composed_b/upstream_b)*100:.0f}%</td></tr>
</table>
<p>
The "pointer operations vs duplicated SVGs" delta is the difference
between rows 2 and 3: <b>{kb(unopt_b - composed_b)} saved</b>
({(1-composed_b/unopt_b)*100:.0f}% smaller) from storing each rotated
hand as a single composite reference instead of its own outline.
</p>

<h2><span class="chip dup-chip">D4 transformations</span>
   &nbsp; hand rotations and reflections</h2>
<p>
SignWriting hand symbols (base range <code>S100</code>–<code>S204</code>)
follow a fixed pattern: the rot digit of an FSW symbol key determines
the rigid transform that takes the rot-0 (or rot-1) base hand onto this
rotation. Even rotations derive from rot 0; odd rotations derive from
rot 1 (the diagonal hand variant, drawn independently by the SignWriting
authors). Hover the examples to see the data.
</p>
<div class="ex">
  {cell("S10000")}
  <div class="txt"><b>S10000</b> &mdash; base hand, kept as outline.</div>
</div>
<div class="ex">
  {cell("S10002")}
  <div class="txt"><b>S10002</b> = R90 of S10000. Stored as a TrueType
  composite that references S10000 plus a 90° rotation matrix. Zero
  outline bytes.</div>
</div>
<div class="ex">
  {cell("S10008")}
  <div class="txt"><b>S10008</b> = M of S10000 (mirror). The mapping is
  deterministic — no IOU search, no fidelity threshold.</div>
</div>

<h2><span class="chip comp-chip">rule compositions</span>
   &nbsp; manual multi-part composites</h2>
<p>
Symbols that fit a manually-authored composition rule
(<code>rules.json</code>) are emitted as TrueType composite glyphs that
reference each part with an auto-derived offset. Eyebrows
(S30a–S310) are the first family wired: each "head + eyebrow" symbol
is composed of <code>S2ff00</code> plus a smaller eyebrow glyph.
</p>
<div class="ex">
  {cell("S30a00")}
  <div class="txt"><b>S30a00</b> = <code>S2ff00</code> + <code>S30a30</code>
    (head + both eyebrows side-by-side).</div>
</div>
<div class="ex">
  {cell("S30a30")}
  <div class="txt"><b>S30a30</b> = <code>S30a40</code> + <code>S30a50</code>
    (both eyebrow halves; no head).</div>
</div>
<div class="ex">
  {cell("S30a50")}
  <div class="txt"><b>S30a50</b> = M(<code>S30a40</code>) — mirror of
    the right eyebrow.</div>
</div>

<h2><span class="chip ellipse-chip">contains a circle</span>
   &nbsp; circular sub-paths</h2>
<p>
The green border marks every symbol with a sub-path that fits a circle
(lenient detection — within ~7% radius error and max 90° gap between
anchors). The build's stricter ellipse-replacement pass swaps only the
cleanest rings for synthetic kappa-Bezier ellipses; the indicator helps
spot under- and over-detection separately.
</p>
<div class="ex">
  {cell("S2ff00")}
  <div class="txt"><b>S2ff00</b> &mdash; the head ring, drawn as two
    concentric circular sub-paths.</div>
</div>
</main>
<div id="tip"></div>"""


_ABOUT_CSS = """
main { max-width: 800px; }
main h1 { font-size: 22px; margin-top: 24px; }
main h2 { font-size: 16px; margin-top: 28px; border-bottom: 1px solid #eee;
  padding-bottom: 4px; }
.ex {
  background: #f6f6f6;
  border-radius: 6px;
  padding: 14px 18px;
  margin: 14px 0;
  display: flex; align-items: center; gap: 18px;
}
.example-cell {
  width: 64px; height: 64px;
  font-size: 36px;
  border-radius: 4px;
  background: #fff;
  border: 1px solid #ddd;
}
.example-cell.dup     { background: var(--dup); }
.example-cell.comp    { background: var(--comp); }
.example-cell.dup.comp {
  background: linear-gradient(135deg, var(--dup) 50%, var(--comp) 50%);
}
.example-cell.has-circle { border: 2px solid var(--circle); }
.example-cell:hover { outline: 2px solid #333; z-index: 5; }
.ex .txt { flex: 1; font-size: 14px; }
.chip { display: inline-block; padding: 1px 6px; border-radius: 3px;
  font: 11px ui-monospace, Menlo, monospace; vertical-align: middle; }
.chip.dup-chip     { background: var(--dup); }
.chip.comp-chip    { background: var(--comp); }
.chip.ellipse-chip { border: 2px solid var(--circle); padding: 0 4px; }
table.sizes { border-collapse: collapse; width: 100%; margin: 12px 0; }
table.sizes th, table.sizes td { padding: 6px 10px; border-bottom: 1px solid #eee;
  text-align: left; font-size: 14px; }
table.sizes th { color: #666; font-weight: 600; }
table.sizes td:nth-child(2), table.sizes td:nth-child(3) {
  font-family: ui-monospace, Menlo, monospace; }
"""


def build_site(args) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cmap = TTFont(args.new_ttf).getBestCmap()
    by_base: dict[int, list[tuple[int, int, int]]] = {}
    for cp, glyph in cmap.items():
        if not (glyph.startswith("S") and len(glyph) == 6):
            continue
        try:
            b = int(glyph[1:4], 16)
            f = int(glyph[4], 16)
            r = int(glyph[5], 16)
        except ValueError:
            continue
        by_base.setdefault(b, []).append((f, r, cp))
    for v in by_base.values():
        v.sort()

    duplicates = _load_json(args.duplicates)
    circles = _load_json(args.circles)
    comps = _load_json(args.compositions)
    dups = {k: v for k, v in duplicates.items() if not k.startswith("_")}
    circles_map = circles if isinstance(circles, dict) else {}

    # Pages
    _write_index(out_dir, by_base, dups, comps, circles_map)

    bases = sorted(by_base.keys())
    idx_of = {b: i for i, b in enumerate(bases)}
    for base in bases:
        _write_detail(out_dir, base, by_base, bases, idx_of,
                      dups, comps, circles_map)

    about_body = _make_about_body(
        args.new_ttf, args.old_ttf, args.unopt_ttf,
        dups, comps, circles_map,
    )
    (out_dir / "about.html").write_text(
        _page("About — SignWriting 1D", about_body,
              extra_css=_ABOUT_CSS,
              extra_js=_TIP_JS)
    )

    shutil.copy(args.new_ttf, out_dir / "new.ttf")
    shutil.copy(args.old_ttf, out_dir / "old.ttf")

    # Version stamp for live-reload polling in `make serve`.
    import time
    (out_dir / "version.txt").write_text(str(int(time.time())))

    print(f"Wrote site to {out_dir}/")
    print(f"  bases (detail pages):    {len(bases):,}")
    print(f"  D4-dedup glyphs:         {len(dups):,}")
    print(f"  rule compositions:       {len(comps):,}")
    print(f"  symbols with circles:    {len(circles_map):,}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new-ttf", type=Path, required=True)
    parser.add_argument("--old-ttf", type=Path, required=True)
    parser.add_argument("--unopt-ttf", type=Path, required=True,
                        help="no-dedup font; used for size-saving stats")
    parser.add_argument("--duplicates", type=Path, required=True)
    parser.add_argument("--compositions", type=Path, required=True)
    parser.add_argument("--circles", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    build_site(args)


if __name__ == "__main__":
    main()
