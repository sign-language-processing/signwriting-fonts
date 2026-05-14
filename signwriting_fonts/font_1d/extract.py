"""Extract per-symbol SVGs from font-db's iswa2010.db.

Writes one .svg file per symbol key into the output directory. The SVGs use the
original cubic-Bezier source paths (font-db is just a SQLite wrapper around the
same SVG glyphs that Slevinski's signwriting_2010_fonts/source/svg_line.zip ships).

For 1D rendering we keep only the `sym-line` path. The `sym-fill` path encodes
the white interior used in 2-tone (Line + Fill) layering; in a monochrome 1D
glyph that interior would render as black ink, hiding the ring it sits in.

Output naming: <symkey>.svg, e.g. S2ff00.svg.
"""

import argparse
import re
import sqlite3
from pathlib import Path

# Matches the entire sym-fill <path .../> element so we can drop it.
_SYM_FILL_PATH = re.compile(r'<path class="sym-fill"[^/]*/>')

# Small subset for fast iteration — mirrors what the 2D pipeline uses today.
# Expand to "all" once the build pipeline is solid.
DEFAULT_SYMBOLS = [
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


def extract(db_path: Path, out_dir: Path, symbols: list[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        for key in symbols:
            row = conn.execute(
                "SELECT width, height, svg FROM symbol WHERE symkey = ?",
                (key,),
            ).fetchone()
            if row is None:
                print(f"  ! {key} not found in db, skipping")
                continue
            width, height, body = row
            # Drop the sym-fill path (see module docstring).
            body = _SYM_FILL_PATH.sub("", body)
            # Wrap the <g> body in a complete SVG document. The transform inside
            # the <g> already scales the raw path numbers (units ~3000) into
            # the symbol's natural width/height range.
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{width}" height="{height}" '
                f'viewBox="0 0 {width} {height}">\n'
                f'{body}\n'
                f'</svg>\n'
            )
            (out_dir / f"{key}.svg").write_text(svg)
            print(f"  wrote {key}.svg ({width}x{height})")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path,
                        help="Path to iswa2010.db (sutton-signwriting/font-db)")
    parser.add_argument("--out", required=True, type=Path,
                        help="Output directory for per-symbol SVG files")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS,
                        help="Symbol keys to extract (defaults to a small dev subset)")
    args = parser.parse_args()
    print(f"Extracting {len(args.symbols)} symbols from {args.db} → {args.out}")
    extract(args.db, args.out, args.symbols)


if __name__ == "__main__":
    main()
