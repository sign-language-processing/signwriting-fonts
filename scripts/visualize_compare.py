"""Side-by-side: render an FSW string with the package's bundled (upstream
Sutton) fonts vs. our rebuilt Line/Fill in ``fonts/``, by monkey-patching
``signwriting.visualizer.visualize.get_font``.

Run:
    python -m scripts.visualize_compare
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageFont

from signwriting.visualizer import visualize

FSW_STRINGS = [
    "M542x536S30307482x477S30d30487x494S10001510x506S20600520x500",
    "M534x518S2ff00482x483S17600502x496S21e00520x500",
]

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERRIDE_DIR = REPO_ROOT / "fonts"
OUT_PATH = REPO_ROOT / "assets" / "visualize_compare.png"


def make_override(font_dir: Path):
    @lru_cache(maxsize=None)
    def get_font(font_name: str) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(font_dir / f"{font_name}.ttf"), 30)

    return get_font


def render(label: str, fsw: str, font_dir: Path | None) -> Image.Image:
    if font_dir is None:
        visualize.get_font.cache_clear()
        visualize.get_symbol_size.cache_clear()
    else:
        visualize.get_font = make_override(font_dir)
        visualize.get_symbol_size.cache_clear()
    img = visualize.signwriting_to_image(fsw).convert("RGBA")
    print(f"  {label}: {img.size}")
    return img


def label_strip(text: str, width: int, height: int = 24) -> Image.Image:
    from PIL import ImageDraw

    strip = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(strip)
    draw.text((6, 4), text, fill=(0, 0, 0, 255))
    return strip


SCALE = 6  # SignWriting positions land each FSW into a ~60×60 box; scale up
           # so artefacts and glyph shapes are visible side-by-side.


def upscale(img: Image.Image) -> Image.Image:
    return img.resize((img.width * SCALE, img.height * SCALE), Image.NEAREST)


def main() -> None:
    bundled_path = Path(visualize.__file__).parent
    LABEL_H = 28
    GAP_BETWEEN_COLS = 40
    GAP_BETWEEN_ROWS = 20

    rows = []
    for fsw in FSW_STRINGS:
        print(f"FSW: {fsw}")
        original = upscale(render(f"  original ({bundled_path.name})", fsw, None))
        override = upscale(render(f"  override ({OVERRIDE_DIR.name})", fsw, OVERRIDE_DIR))
        rows.append((fsw, original, override))

    col_width = max(max(o.width, v.width) for _, o, v in rows)
    canvas_w = col_width * 2 + GAP_BETWEEN_COLS
    row_h = max(max(o.height, v.height) for _, o, v in rows)
    canvas_h = LABEL_H + len(rows) * (row_h + GAP_BETWEEN_ROWS)

    canvas = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 255))
    canvas.paste(label_strip(f"original ({bundled_path.name}/)", col_width, LABEL_H), (0, 0))
    canvas.paste(label_strip(f"override ({OVERRIDE_DIR.name}/)", col_width, LABEL_H),
                 (col_width + GAP_BETWEEN_COLS, 0))

    y = LABEL_H
    for _, original, override in rows:
        canvas.paste(original, (0, y), original)
        canvas.paste(override, (col_width + GAP_BETWEEN_COLS, y), override)
        y += row_h + GAP_BETWEEN_ROWS

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
