"""Extract per-symbol SVGs from font-db's iswa2010.db.

Writes one .svg file per symbol key into the output directory. The SVGs use the
original cubic-Bezier source paths (font-db is just a SQLite wrapper around the
same SVG glyphs that Slevinski's signwriting_2010_fonts/source/svg_line.zip ships).

font-db ships both `<path class="sym-line">` (black outline) and
`<path class="sym-fill">` (white interior) for each symbol; we keep one and
strip the other. `--variant line` drives the OneD and Line builds (sym-line
only — a monochrome outline; the sym-fill interior would render as black
ink and hide the ring it sits in). `--variant fill` keeps the sym-fill
paths for the Fill build.

Output naming: <symkey>.svg, e.g. S2ff00.svg.
"""

import argparse
import re
import sqlite3
from pathlib import Path

from signwriting_fonts.font_1d.variants import (
    SVG_CLASS_TO_KEEP, VARIANT_LINE, VARIANT_FILL,
)

# Matches a `<path ... class="$cls" ... />` element so we can drop it.
# font-db emits self-closing tags here, so the match runs up to the first
# `/>`. `[^>]*?` (lazy, no `>`) keeps the match within a single element;
# `[^/]*` (the older pattern) would break on any attribute value with a
# `/`.
def _drop_path_pattern(svg_class: str) -> re.Pattern[str]:
    return re.compile(
        rf'<path\b[^>]*?\bclass="{re.escape(svg_class)}"[^>]*?/>')

# Hand-picked dev subset — pass `--symbols dev` on the CLI to use it instead
# of extracting all ~37k symbols. Covers the cases we currently optimise plus
# a couple of base hand-shapes for sanity-checking.
DEV_SYMBOLS = [
    "S10000",   # plain hand, base for many rotations/reflections
    "S10001",   # 22.5° rotation of S10000 — candidate for transform-based dedup
    "S17600",   # circle (face/contact) — ellipse-fit candidate
    "S20310",   # contact symbol
    "S21e00",   # two-dot variant — ellipse-fit candidate
    "S26b02",
    "S2ff00",   # large circle — ellipse-fit candidate
    "S33100",
]

# iswa2010.db schema:
#   symbol(id int, symkey text, width int, height int, svg text)
# svg holds the body: <g transform="..."><path class="sym-line" d=".."/>...</g>


def extract(db_path: Path, out_dir: Path, symbols: list[str] | None,
            variant: str = VARIANT_LINE) -> int:
    """Extract per-symbol SVGs into out_dir. If symbols is None, extract every
    row in the db. Returns the number of SVGs written.

    `variant` selects which path to KEEP: VARIANT_LINE / VARIANT_ONED keep
    `sym-line` (and drop `sym-fill`); VARIANT_FILL keeps `sym-fill`."""
    keep_cls = SVG_CLASS_TO_KEEP[variant]
    drop_cls = "sym-fill" if keep_cls == "sym-line" else "sym-line"
    drop_pattern = _drop_path_pattern(drop_cls)

    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        if symbols is None:
            cur = conn.execute("SELECT symkey, width, height, svg FROM symbol")
        else:
            placeholders = ",".join("?" * len(symbols))
            cur = conn.execute(
                f"SELECT symkey, width, height, svg FROM symbol "
                f"WHERE symkey IN ({placeholders})",
                symbols,
            )
        n = 0
        for symkey, width, height, body in cur:
            body = drop_pattern.sub("", body)
            # Wrap the <g> body in a complete SVG document. The transform
            # inside the <g> already scales the raw path numbers (units
            # ~3000) into the symbol's natural width/height range.
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{width}" height="{height}" '
                f'viewBox="0 0 {width} {height}">\n'
                f'{body}\n'
                f'</svg>\n'
            )
            (out_dir / f"{symkey}.svg").write_text(svg)
            n += 1
        return n
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path,
                        help="Path to iswa2010.db (sutton-signwriting/font-db)")
    parser.add_argument("--out", required=True, type=Path,
                        help="Output directory for per-symbol SVG files")
    parser.add_argument(
        "--symbols", nargs="*", default=None,
        help="Symbol keys to extract. Omit to extract all ~37k symbols, "
             "or pass `dev` for the hand-picked dev subset.",
    )
    parser.add_argument(
        "--variant", choices=[VARIANT_LINE, VARIANT_FILL], default=VARIANT_LINE,
        help="Which source path to keep: `line` (sym-line; for OneD and Line "
             "builds) or `fill` (sym-fill; for Fill).",
    )
    args = parser.parse_args()
    if args.symbols == ["dev"]:
        args.symbols = DEV_SYMBOLS
    label = "all" if args.symbols is None else f"{len(args.symbols)}"
    print(f"Extracting {label} symbols ({args.variant}) from {args.db} → {args.out}")
    n = extract(args.db, args.out, args.symbols, args.variant)
    print(f"Wrote {n} SVG file(s).")


if __name__ == "__main__":
    main()
