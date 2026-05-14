"""Build a PDF report comparing the upstream OneD font with our regenerated
versions (unoptimized and ellipse-optimized).

Pages:
  1. Summary + file-size table.
  2. Circles (S21e00, S2ff00, S17600) rendered in all three variants — the
     primary optimization currently implemented.
  3. Rotation family (S10000–S10005) — future optimization candidate; this
     page demonstrates the new font renders rotations at all, so we have a
     regression baseline once GSUB-based rotation dedup lands.

When more optimizations land, add another page per category.
"""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from PIL import Image

from signwriting_fonts.font_1d._symkey import symkey_to_codepoint


FONTS = [
    ("original (upstream OneD)",      "fonts/SuttonSignWritingOneD.ttf"),
    ("new (no optimisations)",        "fonts/SignWritingOneD-unopt.ttf"),
    ("new (ellipse + rotation dedup)","fonts/SignWritingOneD-base.ttf"),
]


def hb_render(font_path: Path, text: str, font_size: int = 96,
              margin: int = 8) -> Image.Image:
    """Render `text` with `font_path` via hb-view; return a PIL image."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        out = Path(tf.name)
    subprocess.run(
        ["hb-view", str(font_path), text,
         "--output-file", str(out),
         "--font-size", str(font_size),
         "--margin", str(margin)],
        check=True, capture_output=True,
    )
    img = Image.open(out).convert("RGB")
    out.unlink(missing_ok=True)
    return img


def _symkey_text(symkey: str) -> str:
    return chr(symkey_to_codepoint(symkey))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_summary(pdf: PdfPages, fonts: list[tuple[str, Path]]) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.axis("off")

    fig.suptitle("SignWriting OneD — regeneration report", fontsize=18, y=0.95)
    ax.text(0.05, 0.88,
            "Comparison of the upstream Sutton SignWriting OneD font vs the\n"
            "font regenerated from font-db's cubic-Bezier SVG sources, with\n"
            "and without our ellipse-replacement optimization.",
            transform=ax.transAxes, fontsize=11, va="top")

    # Size table
    ax.text(0.05, 0.72, "File size", transform=ax.transAxes, fontsize=14,
            fontweight="bold", va="top")
    rows = []
    base_size = None
    for label, path in fonts:
        size = Path(path).stat().st_size
        if base_size is None:
            base_size = size
            delta = ""
        else:
            pct = 100.0 * (size - base_size) / base_size
            delta = f"{pct:+.1f}% vs original"
        rows.append([label, f"{size:,} bytes", f"{size/1024:.1f} KB", delta])
    table = ax.table(
        cellText=rows,
        colLabels=["variant", "size", "", "Δ"],
        loc="upper left",
        bbox=[0.05, 0.55, 0.9, 0.15],
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)

    ax.text(0.05, 0.45, "Glyph count", transform=ax.transAxes, fontsize=14,
            fontweight="bold", va="top")
    from fontTools.ttLib import TTFont
    glyph_rows = []
    for label, path in fonts:
        f = TTFont(path)
        cmap = f.getBestCmap()
        glyph_rows.append([label, f"{len(cmap):,} mapped codepoints"])
    table2 = ax.table(
        cellText=glyph_rows,
        colLabels=["variant", "glyphs"],
        loc="upper left",
        bbox=[0.05, 0.30, 0.9, 0.10],
        cellLoc="left",
    )
    table2.auto_set_font_size(False)
    table2.set_fontsize(10)

    pdf.savefig(fig)
    plt.close(fig)


def page_compare_symbols(
    pdf: PdfPages,
    title: str,
    subtitle: str,
    symkeys: list[str],
    fonts: list[tuple[str, Path]],
    font_size: int = 96,
) -> None:
    """Render the same set of symbols in each font, one row per font."""
    n_rows = len(fonts)
    fig, axes = plt.subplots(n_rows, 1, figsize=(8.5, 2.0 * n_rows + 1.5))
    if n_rows == 1:
        axes = [axes]

    fig.suptitle(title, fontsize=14)
    if subtitle:
        fig.text(0.5, 0.93, subtitle, ha="center", fontsize=10, color="gray")

    text = "".join(_symkey_text(k) for k in symkeys)
    for ax, (label, path) in zip(axes, fonts):
        img = hb_render(Path(path), text, font_size=font_size)
        ax.imshow(img)
        ax.set_title(label, fontsize=10, loc="left")
        ax.axis("off")

    fig.tight_layout(rect=[0, 0, 1, 0.92])
    pdf.savefig(fig)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_report(output_path: Path) -> None:
    if shutil.which("hb-view") is None:
        raise RuntimeError("hb-view not on PATH; install harfbuzz (brew install harfbuzz)")

    fonts = [(label, Path(p)) for label, p in FONTS]
    missing = [p for _, p in fonts if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"missing fonts (run `make` first): {missing}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(output_path) as pdf:
        page_summary(pdf, fonts)

        page_compare_symbols(
            pdf,
            title="Ellipse optimization — circular glyphs",
            subtitle="hand-traced cubic circles replaced by 4-segment Bezier ellipses",
            symkeys=["S21e00", "S2ff00", "S17600"],
            fonts=fonts,
        )

        page_compare_symbols(
            pdf,
            title="Rotation dedup — cardinal siblings of S10000",
            subtitle="rot 2/4/6/8/a/c/e are composite glyphs referencing rot 0 "
                     "+ a transform; diagonals (1,3,5,7,9,b,d,f) keep their "
                     "hand-redrawn outlines",
            symkeys=[f"S1000{i:x}" for i in range(8)],
            fonts=fonts,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("report.pdf"),
                        help="Output PDF path (default: report.pdf)")
    args = parser.parse_args()
    print(f"Building {args.output} …")
    build_report(args.output)
    print(f"Done. {args.output} ({args.output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
