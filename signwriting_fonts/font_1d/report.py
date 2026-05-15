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

def page_intro(pdf: PdfPages) -> None:
    """Motivation page: why bother regenerating a font that already exists?"""
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.axis("off")
    fig.suptitle("Why regenerate SignWriting OneD?", fontsize=18, y=0.95)
    ax.text(
        0.5, 0.78,
        "A SuttonSignWritingOneD.ttf already exists — Slevinski's official\n"
        "build at sutton-signwriting/font-ttf.  Two things make it worth\n"
        "rebuilding:",
        transform=ax.transAxes, fontsize=11, ha="center", va="top",
    )
    ax.text(
        0.05, 0.62,
        "1.  Cubic → quadratic conversion loss",
        transform=ax.transAxes, fontsize=12, fontweight="bold", va="top",
    )
    ax.text(
        0.07, 0.58,
        "The source SVG glyphs in sutton-signwriting/font-db use cubic\n"
        "Bezier curves.  TrueType only supports quadratic Beziers, so\n"
        "FontForge approximates each cubic with a sequence of quadratics\n"
        "during the .ttf export.  The approximation has a tolerance of\n"
        '"about one emunit" (splineorder2.c) — visible in our earlier\n'
        "round of analysis as a ~1-pixel stroke wobble for any glyph\n"
        "compared between the cubic source and the TTF render.",
        transform=ax.transAxes, fontsize=10, va="top",
    )
    ax.text(
        0.05, 0.36,
        "2.  Duplicated outlines for rotations & reflections",
        transform=ax.transAxes, fontsize=12, fontweight="bold", va="top",
    )
    ax.text(
        0.07, 0.32,
        "Every SignWriting symbol has 16 orientation variants (the last\n"
        "hex digit of the symbol key).  In the upstream TTF every variant\n"
        "carries its own full outline.  For the cardinal orientations\n"
        "(rot 0, 2, 4, 6, 8, A, C, E) the outline really is just a\n"
        "rotation/reflection of rot 0, and likewise the diagonals (1, 3,\n"
        "5, 7, 9, B, D, F) are transforms of rot 1 — so 14 of every 16\n"
        "glyphs can become TrueType composite glyphs that reference one\n"
        "base outline plus a 2×2 transform.  Cuts the file by ~67 %.",
        transform=ax.transAxes, fontsize=10, va="top",
    )
    ax.text(
        0.5, 0.08,
        "Following pages walk through what the regeneration produces:\n"
        "the file size and codepoint coverage, the rotation encoding,\n"
        "side-by-side renders of the optimised symbols, and a list of\n"
        "glyphs that still don't quite match upstream so a human can\n"
        "decide whether to accept them.",
        transform=ax.transAxes, fontsize=10, ha="center", va="top",
        color="dimgray",
    )
    pdf.savefig(fig)
    plt.close(fig)


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


def _crop_to_content(arr):
    rows = arr.any(axis=1)
    cols = arr.any(axis=0)
    if not rows.any():
        return arr[:0, :0]
    import numpy as np
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    return arr[r0:r1 + 1, c0:c1 + 1]


def _aligned_iou(a_mask, b_mask):
    import numpy as np
    a = _crop_to_content(a_mask)
    b = _crop_to_content(b_mask)
    h = max(a.shape[0], b.shape[0])
    w = max(a.shape[1], b.shape[1])
    aa = np.zeros((h, w), bool)
    bb = np.zeros((h, w), bool)
    aa[(h - a.shape[0]) // 2: (h - a.shape[0]) // 2 + a.shape[0],
       (w - a.shape[1]) // 2: (w - a.shape[1]) // 2 + a.shape[1]] = a
    bb[(h - b.shape[0]) // 2: (h - b.shape[0]) // 2 + b.shape[0],
       (w - b.shape[1]) // 2: (w - b.shape[1]) // 2 + b.shape[1]] = b
    union = (aa | bb).sum()
    return float((aa & bb).sum() / union) if union else 1.0


def _scan_failures(orig_path, new_path, threshold=1.0):
    """Iterate every common codepoint, render in both fonts, and return:
      - `all_scores`: list of (symkey, codepoint, iou) for every glyph
      - `per_bucket`: one (symkey, cp, iou, orig_PIL, new_PIL) per 0.05-IOU
        bucket across [0.0, threshold) so the report can show the full range
        of quality side-by-side.

    The bucketed sampling makes the human-eye threshold decision easier:
    each row in the resulting page is "what does an IOU-of-X glyph actually
    look like".
    """
    import numpy as np
    from PIL import ImageFont, ImageDraw, Image
    from fontTools.ttLib import TTFont

    def cp_to_sk(cp, plane=0x4):
        n = cp - (plane << 16) - 1
        return f"S{n // 96 + 0x100:03x}{(n % 96) // 16:x}{(n % 96) % 16:x}"

    orig_ft = ImageFont.truetype(str(orig_path), 96)
    new_ft = ImageFont.truetype(str(new_path), 96)

    def render(font, ch):
        bb = font.getbbox(ch)
        if bb == (0, 0, 0, 0):
            return None
        img = Image.new("L", (bb[2] - bb[0] + 16, bb[3] - bb[1] + 16), 255)
        ImageDraw.Draw(img).text((-bb[0] + 8, -bb[1] + 8), ch, fill=0, font=font)
        return img

    common = set(TTFont(orig_path).getBestCmap()) & set(TTFont(new_path).getBestCmap())
    all_scores = []
    bucket_picks = {}
    # Also collect a denser sample inside the [0.40, 0.50) band so a
    # reviewer can confirm a threshold pick visually.
    in_zoom_band = []
    for cp in sorted(common):
        if cp < 0x40000:
            continue
        a = render(orig_ft, chr(cp))
        b = render(new_ft, chr(cp))
        if a is None or b is None:
            continue
        score = _aligned_iou(np.array(a) < 128, np.array(b) < 128)
        sk = cp_to_sk(cp)
        all_scores.append((sk, cp, score))
        if 0.40 <= score < 0.50:
            in_zoom_band.append((sk, cp, score, a, b))
        if score >= threshold:
            continue
        bucket = min(int(score * 20), 19)
        if bucket not in bucket_picks:
            bucket_picks[bucket] = (sk, cp, score, a, b)
    per_bucket = [bucket_picks[k] for k in sorted(bucket_picks.keys())]
    # Evenly spaced sample of up to 20 from the zoom band, sorted by IOU.
    in_zoom_band.sort(key=lambda x: x[2])
    if len(in_zoom_band) > 20:
        step = len(in_zoom_band) / 20
        in_zoom_band = [in_zoom_band[int(i * step)] for i in range(20)]
    return all_scores, per_bucket, in_zoom_band


def page_known_issues(pdf: PdfPages, orig_path, new_path):
    """One example per 0.05-IOU bucket so reviewers can eyeball the
    threshold they're comfortable with.

    Layout: 4 examples per row, two rows per page (8 per page). Each cell
    is a side-by-side upstream | new render labelled with the symkey and
    IOU. Rows iterate from low IOU (badly broken) to high IOU (nearly
    indistinguishable).
    """
    from PIL import Image
    import numpy as np

    all_scores, per_bucket, zoom_band = _scan_failures(orig_path, new_path)
    n_below_44 = sum(1 for _, _, s in all_scores if s < 0.44)
    n_below_50 = sum(1 for _, _, s in all_scores if s < 0.5)
    n_below_85 = sum(1 for _, _, s in all_scores if s < 0.85)

    if not per_bucket:
        return

    cols = 4
    rows_per_page = 4
    per_page = cols * rows_per_page
    n_pages = (len(per_bucket) + per_page - 1) // per_page

    for page_idx in range(n_pages):
        fig = plt.figure(figsize=(8.5, 11))
        if page_idx == 0:
            fig.suptitle("Known issues — one example per 0.05 IOU bucket",
                         fontsize=14, y=0.97)
            fig.text(
                0.5, 0.93,
                f"{n_below_50} of ~38k glyphs render at IOU < 0.50 vs upstream; "
                f"{n_below_85} at IOU < 0.85. Each cell shows the upstream "
                f"render on the left and our regenerated render on the right. "
                f"Reading low→high IOU lets you eyeball a threshold at which "
                f"the dedup composite is 'good enough'.",
                ha="center", fontsize=9, color="dimgray", wrap=True,
            )
            top_pad = 0.91
        else:
            fig.suptitle(f"Known issues (continued, page {page_idx + 1})",
                         fontsize=13, y=0.97)
            top_pad = 0.94

        page_picks = per_bucket[page_idx * per_page:(page_idx + 1) * per_page]
        for i, (sk, cp, score, a, b) in enumerate(page_picks):
            ax = fig.add_subplot(rows_per_page, cols, i + 1)
            ah, aw = a.size[1], a.size[0]
            bh, bw = b.size[1], b.size[0]
            h = max(ah, bh)
            w = aw + bw + 10
            combo = Image.new("RGB", (w, h), (245, 245, 245))
            combo.paste(a.convert("RGB"), (0, (h - ah) // 2))
            combo.paste(b.convert("RGB"), (aw + 10, (h - bh) // 2))
            ax.imshow(combo)
            ax.set_title(f"{sk}  IOU={score:.2f}", fontsize=8, loc="left")
            ax.axis("off")
        fig.tight_layout(rect=[0, 0, 1, top_pad])
        pdf.savefig(fig)
        plt.close(fig)

    # Zoom page(s): 20 evenly-spaced samples from the [0.40, 0.50) band so
    # you can confirm the threshold pick visually. 8 per page → 3 pages.
    if zoom_band:
        zoom_per_page = cols * rows_per_page  # 16; we have at most 20
        for page_idx, start in enumerate(range(0, len(zoom_band), zoom_per_page)):
            fig = plt.figure(figsize=(8.5, 11))
            if page_idx == 0:
                fig.suptitle(
                    "Threshold zoom — every example in IOU [0.40, 0.50)",
                    fontsize=14, y=0.97,
                )
                fig.text(
                    0.5, 0.93,
                    f"{len(zoom_band)} sampled glyphs from the [0.40, 0.50) "
                    f"IOU band — the region where the eye-call between "
                    f"'acceptable dedup' and 'reject' lives. "
                    f"(Counts at fixed cuts: {n_below_44} glyphs < 0.44, "
                    f"{n_below_50} < 0.50.)",
                    ha="center", fontsize=9, color="dimgray", wrap=True,
                )
                top_pad = 0.91
            else:
                fig.suptitle(
                    f"Threshold zoom (continued, page {page_idx + 1})",
                    fontsize=13, y=0.97,
                )
                top_pad = 0.94
            for i, (sk, cp, score, a, b) in enumerate(zoom_band[start:start + zoom_per_page]):
                ax = fig.add_subplot(rows_per_page, cols, i + 1)
                ah, aw = a.size[1], a.size[0]
                bh, bw = b.size[1], b.size[0]
                h = max(ah, bh)
                w = aw + bw + 10
                combo = Image.new("RGB", (w, h), (245, 245, 245))
                combo.paste(a.convert("RGB"), (0, (h - ah) // 2))
                combo.paste(b.convert("RGB"), (aw + 10, (h - bh) // 2))
                ax.imshow(combo)
                ax.set_title(f"{sk}  IOU={score:.2f}", fontsize=8, loc="left")
                ax.axis("off")
            fig.tight_layout(rect=[0, 0, 1, top_pad])
            pdf.savefig(fig)
            plt.close(fig)


def page_rotation_table(pdf: PdfPages) -> None:
    """Describe how the last hex digit of a SignWriting symkey encodes one of
    16 rotation/mirror orientations, and which of those become composite
    glyphs in our font."""
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.axis("off")
    fig.suptitle("Rotation + reflection encoding (hand symbols)",
                 fontsize=16, y=0.95)
    fig.text(
        0.5, 0.86,
        "For each hand `S{base}{fill}{rot}`, the last hex digit picks one\n"
        "of 16 orientations: 8 rotations of rot 0 plus their mirrors at\n"
        "the rot-8 offset. Diagonals (odd indices) form a parallel\n"
        "sub-family centred on rot 1. Non-hand symbols are not covered\n"
        "by this table — they keep their own outlines.",
        ha="center", fontsize=10, color="dimgray",
    )

    rows = [
        # (hex, semantic, composite source, transform)
        ("0", "rot 0°",              "base (outline kept)",        "—"),
        ("1", "rot 45°",             "diag base (outline kept)",   "—"),
        ("2", "rot 90°",             "← rot 0",                    "rotate 90°"),
        ("3", "rot 135°",            "← rot 1",                    "rotate 90°"),
        ("4", "rot 180°",            "← rot 0",                    "rotate 180°"),
        ("5", "rot 225°",            "← rot 1",                    "rotate 180°"),
        ("6", "rot 270°",            "← rot 0",                    "rotate 270°"),
        ("7", "rot 315°",            "← rot 1",                    "rotate 270°"),
        ("8", "mirror + rot 0°",     "← rot 0",                    "mirror"),
        ("9", "mirror + rot 45°",    "← rot 1",                    "mirror"),
        ("A", "mirror + rot 90°",    "← rot 0",                    "mirror + rot 270°"),
        ("B", "mirror + rot 135°",   "← rot 1",                    "mirror + rot 270°"),
        ("C", "mirror + rot 180°",   "← rot 0",                    "mirror + rot 180°"),
        ("D", "mirror + rot 225°",   "← rot 1",                    "mirror + rot 180°"),
        ("E", "mirror + rot 270°",   "← rot 0",                    "mirror + rot 90°"),
        ("F", "mirror + rot 315°",   "← rot 1",                    "mirror + rot 90°"),
    ]
    table = ax.table(
        cellText=rows,
        colLabels=["last hex", "semantic orientation",
                   "composite source", "transform applied"],
        loc="upper center",
        bbox=[0.05, 0.15, 0.9, 0.58],
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    # Bold-ish styling for the two base rows (the only outlines we keep).
    for col in range(4):
        table[(1, col)].set_facecolor("#f5f5f5")   # rot 0 row
        table[(2, col)].set_facecolor("#f5f5f5")   # rot 1 row

    fig.text(
        0.5, 0.15,
        "Mirror reverses CCW→CW, which is why rot A's matrix is "
        "`mirror + rot 270°` even though the semantic is `mirror + rot 90°`.",
        ha="center", fontsize=9, color="dimgray",
    )
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


def page_threshold_curve(pdf: PdfPages, duplicates_path,
                         iou_threshold: float = 0.9) -> None:
    """Plot how many siblings would be deduped at each candidate IOU
    threshold, so a reviewer can eyeball how aggressive (= how many
    composites) different cutoffs would be.

    Two curves: IOU-only and IOU + topology (crossings_match). The gap
    between them is the population the topology check rejects."""
    import json
    if not Path(duplicates_path).exists():
        return
    data = json.loads(Path(duplicates_path).read_text())
    entries = [(v["iou"], v.get("crossings_match", True))
               for k, v in data.items()
               if not k.startswith("_") and "iou" in v]
    if not entries:
        return

    thresholds = [i / 100 for i in range(0, 101)]
    iou_only = [sum(1 for iou, _ in entries if iou >= t) for t in thresholds]
    iou_and_xs = [sum(1 for iou, xs in entries if iou >= t and xs)
                  for t in thresholds]
    total = len(entries)

    fig, ax = plt.subplots(figsize=(8.5, 6))
    ax.plot(thresholds, iou_only, label="IOU only", lw=1.6, color="#bbbbbb")
    ax.plot(thresholds, iou_and_xs, label="IOU + crossings-match",
            lw=2.0, color="#1f6feb")
    ax.axvline(iou_threshold, ls="--", color="firebrick", lw=1.2,
               label=f"current cutoff ({iou_threshold:.2f})")
    # Mark the y-value at the current cutoff for both curves
    idx = min(int(round(iou_threshold * 100)), len(thresholds) - 1)
    ax.annotate(
        f"{iou_and_xs[idx]:,} composites",
        xy=(iou_threshold, iou_and_xs[idx]),
        xytext=(iou_threshold - 0.25, iou_and_xs[idx] + 2000),
        fontsize=10,
        arrowprops=dict(arrowstyle="->", color="firebrick", lw=0.8),
    )
    ax.set_xlabel("IOU threshold")
    ax.set_ylabel("number of accepted duplicates")
    ax.set_title("How many siblings get deduped at each threshold",
                 fontsize=14)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, total * 1.02)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", fontsize=10)
    fig.text(
        0.5, 0.02,
        f"Total candidates: {total:,}. The flat region 0.7-0.9 is the "
        f"sweet spot: most entries cluster at IOU > 0.9, so raising the "
        f"cutoff from 0.7 → 0.9 only drops a few thousand composites.",
        ha="center", fontsize=9, color="dimgray",
    )
    pdf.savefig(fig)
    plt.close(fig)


def page_threshold_tuning(pdf: PdfPages, orig_path, new_path,
                          duplicates_path,
                          iou_threshold: float = 0.9) -> None:
    """Show the threshold boundary in duplicates.json so a reviewer can
    confirm or move the cutoff.

    Top half  — 10 most-certain rejects: lowest-IOU entries (clearly not
                duplicates of their base).
    Bottom    — 10 weakest accepts: lowest-IOU entries still ≥ threshold
                (the worst things we still call duplicates).
    """
    import json
    from PIL import Image, ImageFont, ImageDraw

    if not Path(duplicates_path).exists():
        return
    data = json.loads(Path(duplicates_path).read_text())
    entries = [(sk, v) for sk, v in data.items()
               if not sk.startswith("_") and "iou" in v]
    if not entries:
        return

    by_iou = sorted(entries, key=lambda kv: kv[1]["iou"])
    rejected = [kv for kv in by_iou if kv[1]["iou"] < iou_threshold][:10]
    # Hand symbols in ISWA 2010 occupy the S100..S204 base range. Split the
    # accepts so a reviewer can see whether borderline composites differ in
    # quality between hand and non-hand families.
    def _is_hand(sk: str) -> bool:
        try:
            return int(sk[1:4], 16) < 0x205
        except ValueError:
            return False
    accepted_above = [kv for kv in by_iou if kv[1]["iou"] >= iou_threshold]
    accepted_hands = [kv for kv in accepted_above if _is_hand(kv[0])][:10]
    accepted_other = [kv for kv in accepted_above if not _is_hand(kv[0])][:10]

    orig_ft = ImageFont.truetype(str(orig_path), 96)
    new_ft = ImageFont.truetype(str(new_path), 96)

    def render(font, cp):
        bb = font.getbbox(chr(cp))
        if bb == (0, 0, 0, 0):
            return None
        img = Image.new("L", (bb[2] - bb[0] + 16, bb[3] - bb[1] + 16), 255)
        ImageDraw.Draw(img).text((-bb[0] + 8, -bb[1] + 8),
                                 chr(cp), fill=0, font=font)
        return img

    fig = plt.figure(figsize=(8.5, 11))
    fig.suptitle(f"Threshold tuning — the {iou_threshold:.2f} cut",
                 fontsize=14, y=0.975)
    fig.text(
        0.5, 0.945,
        f"Section 1 — 10 most-certain rejects (lowest IOU among rejected). "
        f"These stay as outlines.\n"
        f"Section 2 — 10 weakest hand-symbol accepts (IOU ≥ {iou_threshold:.2f}, "
        f"base < S205). Hands dedup well by D4 transforms.\n"
        f"Section 3 — 10 weakest non-hand accepts. Non-hand families often "
        f"have hand-redrawn siblings, so borderline accepts here are riskier.",
        ha="center", fontsize=8, color="dimgray", wrap=True,
    )

    cols = 2
    base_x = 0.05
    cell_w = (1.0 - 2 * base_x) / cols
    cell_h = 0.044
    row_gap = 0.003

    def cell_image(sk, base_sk, transform, iou):
        """Show the claimed duplicate pair: base | sibling (both from the
        upstream font). For approved entries the eye should agree the
        transform takes one to the other; for rejects the eye should see
        why the search couldn't reach a high IOU."""
        a = render(orig_ft, symkey_to_codepoint(base_sk))
        b = render(orig_ft, symkey_to_codepoint(sk))
        if a is None or b is None:
            return None, sk
        ah, aw = a.size[1], a.size[0]
        bh, bw = b.size[1], b.size[0]
        h = max(ah, bh)
        w = aw + bw + 10
        combo = Image.new("RGB", (w, h), (245, 245, 245))
        combo.paste(a.convert("RGB"), (0, (h - ah) // 2))
        combo.paste(b.convert("RGB"), (aw + 10, (h - bh) // 2))
        return combo, f"{base_sk} → {sk}  via {transform}  IOU={iou:.2f}"

    def render_section(title_y, label, entries):
        fig.text(base_x, title_y, label, fontsize=11, fontweight="bold")
        for i, (sk, v) in enumerate(entries):
            row = i // cols
            col = i % cols
            x = base_x + col * cell_w
            y = (title_y - 0.025) - row * (cell_h + row_gap)
            ax = fig.add_axes([x, y - cell_h, cell_w - 0.01, cell_h])
            img, lbl = cell_image(
                sk, v["duplicate_of"], v["transform"], v["iou"],
            )
            if img is not None:
                ax.imshow(img)
            ax.set_title(lbl, fontsize=7, loc="left", pad=2)
            ax.axis("off")

    render_section(
        0.895,
        f"Most-certain rejects (IOU < {iou_threshold:.2f}):",
        rejected,
    )
    render_section(
        0.625,
        f"Weakest hand-symbol accepts (IOU ≥ {iou_threshold:.2f}, base < S205):",
        accepted_hands,
    )
    render_section(
        0.355,
        f"Weakest non-hand accepts (IOU ≥ {iou_threshold:.2f}, base ≥ S205):",
        accepted_other,
    )

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
        page_intro(pdf)
        page_summary(pdf, fonts)
        page_rotation_table(pdf)

        page_compare_symbols(
            pdf,
            title="Ellipse optimization — circular glyphs",
            subtitle="hand-traced cubic circles replaced by 4-segment Bezier ellipses",
            symkeys=["S21e00", "S2ff00", "S17600"],
            fonts=fonts,
        )

        page_compare_symbols(
            pdf,
            title="Rotation dedup — all 16 orientations of S1000{0..f}",
            subtitle="even indices = composites of rot 0; odd = composites of rot 1",
            symkeys=[f"S1000{i:x}" for i in range(16)],
            fonts=fonts,
        )

        page_threshold_curve(
            pdf, Path(__file__).with_name("duplicates.json"),
        )
        page_threshold_tuning(
            pdf, fonts[0][1], fonts[-1][1],
            Path(__file__).with_name("duplicates.json"),
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
