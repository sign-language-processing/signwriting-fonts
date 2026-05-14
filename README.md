# SignWriting Fonts

## Development setup

```bash
brew install fontforge harfbuzz
pip install .[dev]
```

## SuttonSignWritingOneD.ttf

The SignWriting One-Dimensional font is a font that can be used to display SignWriting in a single line of text.
Created by Stephen Slevinski, it is available for download [here](https://github.com/sutton-signwriting/font-ttf),
and mirrored in this repository at [fonts/SignWritingOneD.ttf](fonts/SignWritingOneD.ttf).

![Example of the SuttonSignWritingOneD font](assets/SuttonSignWritingOneD-example.png)

### Regenerating a 1D font from font-db sources (issue #1)

The Sutton TTFs are built by FontForge from cubic-Bezier SVG sources; the cubic
curves are approximated as quadratics during TTF generation, which introduces
shape drift. To stay closer to the source we rebuild the 1D font from
[`@sutton-signwriting/font-db`][fontdb]'s cubic SVGs directly.

```bash
make fonts/SignWritingOneD.ttf
```

The pipeline:

1. **`signwriting_fonts/font_1d/extract.py`** reads `fonts/iswa2010.db` (the
   font-db SQLite blob, fetched by the Makefile) and writes one SVG per symbol
   into `fonts/1d/svg/`. The `sym-fill` (white-interior) path is dropped — 1D
   glyphs are monochrome.
2. **`signwriting_fonts/font_1d/optimize.py`** detects circular sub-paths via
   LSQ circle fit (robust to one outlier) and replaces them with a 4-segment
   cubic-Bezier ellipse (~0.027 % radius error). This both shrinks the path
   data and removes hand-traced wobble.
3. **`signwriting_fonts/font_1d/build_font.py`** is a FontForge Python script
   that creates one glyph per SVG, maps each to its plane-4 SWU codepoint, and
   emits a base TTF.
4. **`signwriting_fonts/font_1d/generate_vtp.py`** emits a minimal VTP, and
   `volt2ttf` combines that with the base TTF.

To extend the symbol set, edit `DEFAULT_SYMBOLS` in `extract.py` (or pass
`--symbols` on the CLI). A small subset is used by default for fast iteration.

[fontdb]: https://github.com/sutton-signwriting/font-db

## SuttonSignWritingTwoD.ttf

The SignWriting Two-Dimensional font is a font that can be used to display SignWriting in a two-dimensional grid.
This is designed for use cases where TTF fonts are supported, but SVG images are not, such as video captioning.

Created by this project, it is available for download at [fonts/SuttonSignWritingTwoD.ttf](fonts/SuttonSignWritingTwoD.ttf).

![Example of the SuttonSignWritingTwoD font](assets/SuttonSignWritingTwoD-example.png)

### Recreating the Font

```bash
make fonts/SuttonSignWritingTwoD.ttf
```

### How was it created?

To draw SignWriting in a two-dimensional grid, [font-ttf](https://github.com/sutton-signwriting/font-ttf) provides 
two additional fonts - `SuttonSignWritingFill` and `SuttonSignWritingLine`. 
These fonts are used to draw the fill and line of each glyph, respectively.

1. [TODO] The Glyphs in `SuttonSignWritingFill` and `SuttonSignWritingLine` were extracted and combined into a single two-tone TTF font.
2. [TODO: LRB] Non-visual glyphs (such as Boxes, and Positions) were removed from the font.
3. [TODO] The font was optimized by only including a single copy of each base hand shape, 
   and using rotations and mirroring to draw the other hand shapes.
4. [TODO] Using ligatures, an `M` box defines the size of the grid, and an anchor point.
   The anchor point is used to position the glyphs in the grid.
5. [TODO] All glyphs (grouped in 4 groups due to TTF limitations) combine with two positional glyphs to create an 
   Orthogonal translation of the glyph in the grid.
