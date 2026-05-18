"""Split assets/hex_bases.png into per-terrain top-face PNGs with transparency.

Reads the composite sheet, isolates each 3D hex, removes the starfield background,
clips to the visible top face, and writes assets/hex_bases/<terrain>.png.
"""

from __future__ import annotations

import colorsys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "assets" / "hex_bases.png"
OUT_DIR = REPO_ROOT / "assets" / "hex_bases"

# Left-to-right, top row then bottom row (matches sheet layout).
TERRAIN_NAMES = ("grassland", "woodland", "mountain", "river", "bridge")

COMPONENT_THRESHOLD = 80
MIN_COMPONENT_PIXELS = 50_000
PAD_PX = 10


def _classify_pixel(r: int, g: int, b: int) -> str:
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    if v < 0.15:
        return "bg"
    # Brown dirt sides only — grey rock / wood can be low-saturation tops.
    if s < 0.22 and v < 0.5 and 0.02 < h < 0.11:
        return "side"
    if s > 0.35 and 0.18 < h < 0.45:
        return "top"
    if s > 0.3 and 0.5 < h < 0.7:
        return "top"
    if s < 0.4 and 0.0 < h < 0.12:
        return "side"
    if v > 0.5 and s > 0.2:
        return "top"
    return "other"


def _hsv_side_cut_row(crop: np.ndarray) -> int:
    """First row in the centre band where dirt sides dominate (terrain hexes)."""
    h, w = crop.shape[:2]
    x_lo, x_hi = int(w * 0.25), int(w * 0.75)
    for y in range(int(h * 0.25), h):
        top_count = 0
        side_count = 0
        for x in range(x_lo, x_hi):
            r, g, b, _a = (int(v) for v in crop[y, x])
            if r + g + b < 80:
                continue
            label = _classify_pixel(r, g, b)
            if label == "top":
                top_count += 1
            elif label == "side":
                side_count += 1
        if side_count > top_count and side_count > 25:
            return y
    return int(h * 0.62)


def _content_fraction_cut(comp: np.ndarray, fraction: float) -> int:
    rows = np.where(comp.any(axis=1))[0]
    if len(rows) == 0:
        return comp.shape[0]
    top, bottom = int(rows[0]), int(rows[-1])
    return top + int((bottom - top) * fraction)


def _flat_top_hex_mask(w: int, h: int, cut_y: int) -> Image.Image:
    """Mask approximating the isometric top face (flat-top hex silhouette)."""
    cut_y = max(8, min(cut_y, h - 1))
    # Trim a few pixels below the rim so side faces are excluded.
    cut_y = int(cut_y * 0.96)
    inset_y = cut_y * 0.95
    # Narrower lower corners clip visible 3D side faces on isometric tiles.
    points = [
        (w * 0.5, h * 0.06),
        (w * 0.90, h * 0.30),
        (w * 0.78, inset_y),
        (w * 0.5, float(cut_y)),
        (w * 0.22, inset_y),
        (w * 0.10, h * 0.30),
    ]
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask


def _find_hex_components(
    rgba: np.ndarray,
) -> list[tuple[int, int, int, int, int, int]]:
    bright = (
        rgba[:, :, 0].astype(np.int32)
        + rgba[:, :, 1].astype(np.int32)
        + rgba[:, :, 2].astype(np.int32)
    ) > COMPONENT_THRESHOLD
    labeled, count = ndimage.label(bright)
    components: list[tuple[int, int, int, int, int, int]] = []
    for label_id in range(1, count + 1):
        ys, xs = np.where(labeled == label_id)
        if len(xs) < MIN_COMPONENT_PIXELS:
            continue
        span_w = xs.max() - xs.min()
        span_h = ys.max() - ys.min()
        if span_w > rgba.shape[1] * 0.85 and span_h > rgba.shape[0] * 0.85:
            continue  # starfield backdrop merged with sheet
        components.append(
            (label_id, int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        )
    # Top row (smaller y), left-to-right; then bottom row, left-to-right.
    components.sort(key=lambda item: (item[2] > rgba.shape[0] // 2, item[1]))
    return components


def _extract_top_face(
    rgba: np.ndarray,
    labeled: np.ndarray,
    label_id: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    terrain: str,
) -> Image.Image:
    y0p = max(0, y0 - PAD_PX)
    y1p = min(rgba.shape[0] - 1, y1 + PAD_PX)
    x0p = max(0, x0 - PAD_PX)
    x1p = min(rgba.shape[1] - 1, x1 + PAD_PX)

    crop = rgba[y0p : y1p + 1, x0p : x1p + 1].copy()
    comp = labeled[y0p : y1p + 1, x0p : x1p + 1] == label_id
    h, w = crop.shape[:2]

    hsv_cut = _hsv_side_cut_row(crop)
    fraction_cut = _content_fraction_cut(comp, 0.57)
    # HSV fails on low-saturation rock; never cut above the content-based estimate.
    cut_y = max(hsv_cut, fraction_cut)

    hex_mask = np.array(_flat_top_hex_mask(w, h, cut_y)) > 0
    alpha = (comp & hex_mask).astype(np.uint8) * 255
    crop[:, :, 3] = np.minimum(crop[:, :, 3], alpha)
    crop[cut_y + 1 :, :, 3] = 0

    # Remove dark starfield pixels that leaked into the bbox corners.
    rgb_sum = (
        crop[:, :, 0].astype(np.int32)
        + crop[:, :, 1].astype(np.int32)
        + crop[:, :, 2].astype(np.int32)
    )
    crop[:, :, 3] = np.where((crop[:, :, 3] > 0) & (rgb_sum > COMPONENT_THRESHOLD), crop[:, :, 3], 0)

    # Drop remaining dirt-side pixels in the lower band of the top face.
    side_band_top = int(cut_y * 0.72)
    for y in range(side_band_top, min(cut_y + 1, h)):
        for x in range(w):
            if crop[y, x, 3] == 0:
                continue
            r, g, b = (int(crop[y, x, c]) for c in range(3))
            if _classify_pixel(r, g, b) == "side":
                crop[y, x, 3] = 0

    surface = Image.fromarray(crop)
    bbox = surface.getbbox()
    if bbox is None:
        raise RuntimeError(f"No visible pixels after extraction for {terrain}")
    return surface.crop(bbox)


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"Missing source image: {SOURCE}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rgba = np.array(Image.open(SOURCE).convert("RGBA"))
    bright = (
        rgba[:, :, 0].astype(np.int32)
        + rgba[:, :, 1].astype(np.int32)
        + rgba[:, :, 2].astype(np.int32)
    ) > COMPONENT_THRESHOLD
    labeled, _ = ndimage.label(bright)

    components = _find_hex_components(rgba)
    if len(components) != len(TERRAIN_NAMES):
        raise SystemExit(
            f"Expected {len(TERRAIN_NAMES)} hex sprites, found {len(components)}. "
            "Check hex_bases.png layout."
        )

    for terrain, (label_id, x0, y0, x1, y1) in zip(TERRAIN_NAMES, components, strict=True):
        tile = _extract_top_face(rgba, labeled, label_id, x0, y0, x1, y1, terrain)
        out_path = OUT_DIR / f"{terrain}.png"
        tile.save(out_path)
        print(f"Wrote {out_path} ({tile.size[0]}x{tile.size[1]})")


if __name__ == "__main__":
    main()
