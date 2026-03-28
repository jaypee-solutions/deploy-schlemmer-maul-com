#!/usr/bin/env python3
"""
Derive a perceptually-uniform color palette from a logo image using OkLCh.

Usage:
    python scripts/oklab_palette.py path/to/logo.png

The script:
  1. Loads the image and filters out background/border pixels
  2. Clusters remaining pixels (k-means, k=8) to find dominant colors
  3. Converts to OkLCh (cylindrical Oklab)
  4. Selects the primary color (highest chroma in warm-yellow range)
  5. Derives complementary + hue-rotated variants
  6. Prints a formatted terminal table
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass

import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Color math: sRGB <-> Oklab <-> OkLCh
# All matrices from Björn Ottosson (2020): https://bottosson.github.io/posts/oklab/
# ---------------------------------------------------------------------------

# sRGB -> linear RGB (IEC 61966-2-1 transfer function)
def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = np.asarray(c, dtype=np.float64)
    low = c / 12.92
    high = ((c + 0.055) / 1.055) ** 2.4
    return np.where(c <= 0.04045, low, high)


# linear RGB -> sRGB
def _linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    low = c * 12.92
    high = 1.055 * (c ** (1.0 / 2.4)) - 0.055
    return np.where(c <= 0.0031308, low, high)


# linear sRGB -> XYZ D65
_M_RGB_TO_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
])

# XYZ D65 -> LMS (Oklab M1)
_M_XYZ_TO_LMS = np.array([
    [0.8189330101, 0.3618667424, -0.1288597137],
    [0.0329845436, 0.9293118715,  0.0361456387],
    [0.0482003018, 0.2643662691,  0.6338517070],
])

# l̃m̃s̃ -> Oklab (M2)
_M_LMS_TO_LAB = np.array([
    [0.2104542553, 0.7936177850, -0.0040720468],
    [1.9779984951, -2.4285922050,  0.4505937099],
    [0.0259040371,  0.7827717662, -0.8086757660],
])

# Inverses
_M_LAB_TO_LMS = np.linalg.inv(_M_LMS_TO_LAB)
_M_LMS_TO_XYZ = np.linalg.inv(_M_XYZ_TO_LMS)
_M_XYZ_TO_RGB = np.linalg.inv(_M_RGB_TO_XYZ)


def srgb_to_oklch(rgb_255: np.ndarray) -> np.ndarray:
    """Convert Nx3 sRGB (0-255 uint8) → Nx3 OkLCh (L∈[0,1], C≥0, h∈[0,360))."""
    lin = _srgb_to_linear(rgb_255 / 255.0)
    xyz = lin @ _M_RGB_TO_XYZ.T
    lms = xyz @ _M_XYZ_TO_LMS.T
    lms_ = np.cbrt(lms)
    lab = lms_ @ _M_LMS_TO_LAB.T
    L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    C = np.sqrt(a ** 2 + b ** 2)
    h = np.degrees(np.arctan2(b, a)) % 360.0
    return np.stack([L, C, h], axis=1)


def oklch_to_srgb_hex(L: float, C: float, h_deg: float) -> tuple[str, tuple[int, int, int]]:
    """Convert a single OkLCh value → hex string + (R,G,B) tuple."""
    h_rad = math.radians(h_deg)
    a = C * math.cos(h_rad)
    b = C * math.sin(h_rad)
    lab = np.array([[L, a, b]])
    lms_ = lab @ _M_LAB_TO_LMS.T
    lms = lms_ ** 3
    xyz = lms @ _M_LMS_TO_XYZ.T
    lin = xyz @ _M_XYZ_TO_RGB.T
    srgb = _linear_to_srgb(lin)[0]
    r, g, bl = (int(round(v * 255)) for v in np.clip(srgb, 0, 1))
    return f"#{r:02X}{g:02X}{bl:02X}", (r, g, bl)


# ---------------------------------------------------------------------------
# Image analysis
# ---------------------------------------------------------------------------

def load_pixels(path: str) -> np.ndarray:
    """Load image, convert to RGB, return Nx3 uint8 array."""
    img = Image.open(path).convert("RGBA")
    arr = np.array(img, dtype=np.float32)
    # Flatten; respect alpha — drop mostly-transparent pixels
    alpha = arr[:, :, 3]
    mask = alpha > 128
    rgb = arr[:, :, :3][mask].astype(np.uint8)
    return rgb


def filter_background(pixels: np.ndarray) -> np.ndarray:
    """Remove near-white and near-black pixels (background + border)."""
    lin = _srgb_to_linear(pixels / 255.0)
    # Perceived lightness (Y channel of XYZ)
    Y = lin @ _M_RGB_TO_XYZ[1]  # second row = Y
    # Keep pixels with 0.03 < Y < 0.85 (not black, not white)
    mask = (Y > 0.03) & (Y < 0.85)
    return pixels[mask]


def kmeans(pixels: np.ndarray, k: int = 8, iterations: int = 20, seed: int = 42) -> np.ndarray:
    """Simple k-means on Nx3 float array; returns k×3 centroids."""
    rng = np.random.default_rng(seed)
    # Work in linear space for perceptual accuracy
    lin = _srgb_to_linear(pixels / 255.0)
    idx = rng.choice(len(lin), k, replace=False)
    centers = lin[idx].copy()
    for _ in range(iterations):
        dists = np.linalg.norm(lin[:, None] - centers[None], axis=2)  # N×k
        labels = dists.argmin(axis=1)
        new_centers = np.array([
            lin[labels == i].mean(axis=0) if (labels == i).any() else centers[i]
            for i in range(k)
        ])
        if np.allclose(centers, new_centers, atol=1e-6):
            break
        centers = new_centers
    # Convert centroids back to sRGB 0-255
    srgb = _linear_to_srgb(centers)
    return np.clip(srgb * 255, 0, 255).round().astype(np.uint8)


# ---------------------------------------------------------------------------
# Palette derivation
# ---------------------------------------------------------------------------

@dataclass
class PaletteEntry:
    role: str
    hex: str
    rgb: tuple[int, int, int]
    L: float
    C: float
    h: float


def derive_palette(primary_lch: tuple[float, float, float]) -> list[PaletteEntry]:
    """Given primary OkLCh, return full palette via hue rotations."""
    L, C, h0 = primary_lch

    roles = [
        ("primary",         h0),
        ("primary_warm",    h0 - 30),
        ("primary_cool",    h0 + 30),
        ("secondary",       h0 + 180),
        ("secondary_warm",  h0 + 150),
        ("secondary_cool",  h0 + 210),
        ("accent_split_a",  h0 + 120),
        ("accent_split_b",  h0 - 120),
    ]

    entries = []
    for role, h in roles:
        h_norm = h % 360.0
        hex_val, rgb = oklch_to_srgb_hex(L, C, h_norm)
        entries.append(PaletteEntry(role=role, hex=hex_val, rgb=rgb, L=L, C=C, h=h_norm))
    return entries


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _ansi_swatch(hex_color: str) -> str:
    """Return an ANSI-colored block for terminal preview."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"\033[48;2;{r};{g};{b}m  \033[0m"


def print_table(entries: list[PaletteEntry]) -> None:
    col_w = [20, 10, 18, 40]
    header = f"{'Role':<{col_w[0]}} {'Hex':<{col_w[1]}} {'RGB':<{col_w[2]}} {'OkLCh (L, C, h°)'}"
    sep = "─" * sum(col_w)
    print()
    print("  Schlemmer-Maul Brand Palette (OkLCh)")
    print(f"  {sep}")
    print(f"  {header}")
    print(f"  {sep}")
    for e in entries:
        swatch = _ansi_swatch(e.hex)
        rgb_str = f"rgb({e.rgb[0]}, {e.rgb[1]}, {e.rgb[2]})"
        lch_str = f"oklch({e.L:.3f}, {e.C:.3f}, {e.h:.1f}°)"
        print(f"  {swatch} {e.role:<{col_w[0]-3}} {e.hex:<{col_w[1]}} {rgb_str:<{col_w[2]}} {lch_str}")
    print(f"  {sep}")
    print()


def print_sampled_colors(lch_colors: np.ndarray, rgb_colors: np.ndarray) -> None:
    """Print the dominant colors extracted from the image."""
    print()
    print("  Dominant colors extracted from logo:")
    print("  " + "─" * 70)
    for i, (lch, rgb) in enumerate(zip(lch_colors, rgb_colors)):
        hex_val = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
        swatch = _ansi_swatch(hex_val)
        print(f"  {swatch} cluster {i+1}  {hex_val}  oklch({lch[0]:.3f}, {lch[1]:.3f}, {lch[2]:.1f}°)")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <logo.png>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    print(f"\nLoading: {path}")

    pixels = load_pixels(path)
    print(f"Total pixels (opaque): {len(pixels):,}")

    filtered = filter_background(pixels)
    print(f"After background filter: {len(filtered):,}")

    if len(filtered) < 8:
        print("Too few colorful pixels found — check that the image path is correct.", file=sys.stderr)
        sys.exit(1)

    centroids = kmeans(filtered, k=8)
    lch_centroids = srgb_to_oklch(centroids)

    print_sampled_colors(lch_centroids, centroids)

    # Select primary: highest chroma in warm-yellow range (h ∈ [55°, 115°])
    candidates = [
        (i, lch)
        for i, lch in enumerate(lch_centroids)
        if 55 <= lch[2] <= 115
    ]

    if not candidates:
        # Fallback: highest chroma overall
        print("No warm-yellow cluster found; using highest-chroma color as primary.")
        best_idx = int(np.argmax(lch_centroids[:, 1]))
    else:
        best_idx = max(candidates, key=lambda x: x[1][1])[0]

    primary_lch = tuple(lch_centroids[best_idx])  # type: ignore[arg-type]
    print(f"Primary selected: cluster {best_idx + 1} — "
          f"oklch({primary_lch[0]:.3f}, {primary_lch[1]:.3f}, {primary_lch[2]:.1f}°)")

    palette = derive_palette(primary_lch)
    print_table(palette)


if __name__ == "__main__":
    main()
