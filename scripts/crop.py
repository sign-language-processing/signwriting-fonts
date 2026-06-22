"""Crop a PNG to its content, trimming uniform background, plus a margin.

The 2D font advances a fixed box width, so an hb-view render of a single sign
is padded out to that box. Cropping to ink gives each sign its natural size —
the way the OneD examples are tight simply because their glyphs advance.

    python -m scripts.crop path/to.png --margin 20
"""
import argparse

import numpy as np
from PIL import Image


def crop(path: str, margin: int) -> None:
    im = Image.open(path)
    gray = np.asarray(im.convert("L")).astype(int)
    mask = np.abs(gray - int(gray[0, 0])) > 8  # differs from corner background
    if not mask.any():
        return  # blank image; leave as-is
    rows = np.where(mask.any(1))[0]
    cols = np.where(mask.any(0))[0]
    box = (max(0, cols[0] - margin), max(0, rows[0] - margin),
           min(im.width, cols[-1] + 1 + margin), min(im.height, rows[-1] + 1 + margin))
    im.crop(box).save(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--margin", type=int, default=20)
    args = parser.parse_args()
    crop(args.path, args.margin)


if __name__ == "__main__":
    main()
