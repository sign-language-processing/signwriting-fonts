"""Per-variant config for the three 1D fonts (OneD, Line, Fill).

All three are built from the same font-db cubic SVG sources via the same
extract → optimize → dedup → compositions → build_font pipeline. The
differences captured here:

- **SVG path filter** — font-db ships both ``sym-line`` (black outline) and
  ``sym-fill`` (white interior) inside one ``<g>``. OneD and Line keep
  ``sym-line``; Fill keeps ``sym-fill``.
- **Codepoint plane** — OneD uses plane-4 SignWriting Unicode (0x40001+).
  Line and Fill use PUA-A (0xF0001+) and PUA-B (0x100001+) to match the
  upstream Sutton fonts; this is what ``signwriting.symbol_line`` and
  ``signwriting.symbol_fill`` produce, so the built fonts drop into the
  signwriting visualizer.
- **Markers** — the plane-1 structural markers (SW A/B/L/M/R + SW 250-749)
  only ship with upstream OneD; Line and Fill have just the 37811 symbols.
- **Glyph placement** — OneD vertically centers each glyph around
  ``y=TARGET_Y_CENTER`` so single-line text stays visually aligned. Line
  and Fill use the descender layout the visualizer expects: top of the
  source SVG canvas sits at the baseline, glyphs extend below to roughly
  ``y = -natural_height * scale``.
"""

VARIANT_ONED = "oned"
VARIANT_LINE = "line"
VARIANT_FILL = "fill"
ALL_VARIANTS = (VARIANT_ONED, VARIANT_LINE, VARIANT_FILL)

SVG_CLASS_TO_KEEP = {
    VARIANT_ONED: "sym-line",
    VARIANT_LINE: "sym-line",
    VARIANT_FILL: "sym-fill",
}

CODEPOINT_PLANE = {
    VARIANT_ONED: 0x4,
    VARIANT_LINE: 0xF,
    VARIANT_FILL: 0x10,
}

FONT_NAMES = {
    VARIANT_ONED: "SuttonSignWritingOneD",
    VARIANT_LINE: "SuttonSignWritingLine",
    VARIANT_FILL: "SuttonSignWritingFill",
}

HAS_MARKERS = {
    VARIANT_ONED: True,
    VARIANT_LINE: False,
    VARIANT_FILL: False,
}
