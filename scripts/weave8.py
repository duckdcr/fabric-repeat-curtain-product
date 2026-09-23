# -*- coding: utf-8 -*-
"""Physical-scale curtain texturing v8.

Keep the validated rendering invariants fixed: 193.9 cm unfolded panel width,
9 subwindows at 73%, 18% minimum-error seams, no flips, fixed UV geometry,
and template-luminance shading.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from PIL import Image, ImageFilter

Image.MAX_IMAGE_PIXELS = None

ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
PW_PX, PH_PX, BASE = 405.0, 1128.0, 1254.0
PW_CM, PH_CM = 193.9, 270.0
TILE_FRACTION = 0.73
TILE_POSITIONS = 9
OVERLAP_FRACTION = 0.18


def _gray_asset(name: str) -> np.ndarray:
    return np.asarray(Image.open(ASSET_DIR / name).convert("L"))


def _packed_uv(name: str) -> np.ndarray:
    packed = np.asarray(Image.open(ASSET_DIR / name).convert("RGB"), dtype=np.uint32)
    return (packed[:, :, 0] * 256 + packed[:, :, 1]).astype(np.uint16)


def _fixed_uv_x() -> np.ndarray:
    return np.load(ASSET_DIR / "uvx_fixed.npy").astype(np.float32)


def _open_square_rgb(path: str | Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    ratio = image.width / image.height
    if not 0.99 <= ratio <= 1.01:
        raise ValueError(
            f"Input must be a square physical sample; got {image.width}x{image.height}. "
            "Crop without perspective distortion before rendering."
        )
    return image


def _normalize_illumination(image: Image.Image) -> Image.Image:
    """Remove camera-scale color gradients while retaining woven texture."""
    rgb = image.convert("RGB")
    longest = max(rgb.size)
    scale = min(1.0, 320.0 / longest)
    proxy_size = (
        max(32, int(round(rgb.width * scale))),
        max(32, int(round(rgb.height * scale))),
    )
    proxy = rgb.resize(proxy_size, Image.Resampling.LANCZOS)
    radius = max(8.0, min(proxy_size) * 0.10)
    illumination = proxy.filter(ImageFilter.GaussianBlur(radius=radius)).resize(
        rgb.size, Image.Resampling.BILINEAR
    )

    source = np.asarray(rgb, dtype=np.float32)
    low_frequency = np.asarray(illumination, dtype=np.float32)
    target = np.median(low_frequency.reshape(-1, 3), axis=0)
    corrected = source * (target[None, None, :] / np.maximum(low_frequency, 1.0))
    return Image.fromarray(np.clip(corrected, 0, 255).astype(np.uint8), "RGB")


def build_roll(
    src_path: str | Path,
    sample_cm: float,
    hd: float,
    vd: float,
    seed: int = 0,
    tile_frac: float = TILE_FRACTION,
    n_pos: int = TILE_POSITIONS,
) -> tuple[np.ndarray, int, int]:
    """Build a two-panel fabric roll from unflipped minimum-cut subwindows."""
    from quilt_cut import paste_min_cut

    if sample_cm <= 0:
        raise ValueError("sample_cm must be positive")
    rng = np.random.default_rng(seed)
    width = int(round(2 * PW_CM * hd))
    height = int(round(PH_CM * vd))
    full_width = int(round(sample_cm * hd))
    full_height = int(round(sample_cm * vd))
    full = np.asarray(
        _normalize_illumination(_open_square_rgb(src_path)).resize(
            (full_width, full_height), Image.Resampling.LANCZOS
        ),
        dtype=np.uint8,
    )

    tile_width = max(16, int(full_width * tile_frac))
    tile_height = max(16, int(full_height * tile_frac))
    room_x, room_y = full_width - tile_width, full_height - tile_height
    grid_size = int(np.ceil(np.sqrt(n_pos)))
    positions = [
        (
            int(i * room_y / max(1, grid_size - 1)),
            int(j * room_x / max(1, grid_size - 1)),
        )
        for i in range(grid_size)
        for j in range(grid_size)
    ][:n_pos]
    tiles = [
        np.ascontiguousarray(full[y : y + tile_height, x : x + tile_width])
        for y, x in positions
    ]

    overlap_x = max(4, int(tile_width * OVERLAP_FRACTION))
    overlap_y = max(4, int(tile_height * OVERLAP_FRACTION))
    step_x, step_y = tile_width - overlap_x, tile_height - overlap_y
    roll = np.zeros((height, width, 3), dtype=np.uint8)
    filled = np.zeros((height, width), dtype=bool)
    for y in range(0, height, step_y):
        x = -int(rng.integers(0, tile_width))
        while x < width:
            tile = tiles[int(rng.integers(0, len(tiles)))]
            visible_tile = np.ascontiguousarray(tile[:, -x:]) if x < 0 else tile
            target_x = max(0, x)
            if target_x < width and visible_tile.shape[1] > 0:
                paste_min_cut(
                    roll,
                    filled,
                    visible_tile,
                    y,
                    target_x,
                    overlap_x,
                    overlap_y,
                )
            x += step_x
    return roll, width, height


def render(
    fabric_path: str | Path,
    sample_cm: float,
    size: int = 12288,
    output_size: int | None = None,
    seed: int = 7,
    strip: int = 512,
) -> tuple[Image.Image, dict[str, object]]:
    """Render a white-background double-pinch curtain at physical scale."""
    if size < 512:
        raise ValueError("size must be at least 512 pixels")
    horizontal_density = size * (PW_PX / BASE) / PW_CM
    vertical_density = size * (PH_PX / BASE) / PH_CM
    roll_density = vertical_density
    roll, roll_width, roll_height = build_roll(
        fabric_path, sample_cm, roll_density, vertical_density, seed=seed
    )

    mask_source = _gray_asset("mask.png")
    uv_x_source = _fixed_uv_x()
    uv_y_source = _packed_uv("uv-y.png")
    template_source = _gray_asset("double-pinch-template.png")
    reference_brightness = float(
        np.percentile(template_source[mask_source > 0].astype(np.float32), 55)
    )
    output = np.empty((size, size, 3), dtype=np.uint8)

    for y_start in range(0, size, strip):
        y_end = min(size, y_start + strip)
        source_start = int(np.floor(y_start / size * BASE))
        source_end = min(
            int(np.ceil(y_end / size * BASE)) + 1,
            int(BASE),
        )
        top = int(round(source_start / BASE * size))
        resized_height = int(round((source_end - source_start) / BASE * size))

        def band(array: np.ndarray, mode: int, dtype=np.float32) -> np.ndarray:
            image = Image.fromarray(array[source_start:source_end]).resize(
                (size, max(1, resized_height)), mode
            )
            resized = np.asarray(image, dtype=dtype)
            return resized[y_start - top : y_start - top + (y_end - y_start)]

        mask = band(mask_source, Image.Resampling.NEAREST) / 255.0
        template = band(template_source, Image.Resampling.BILINEAR)
        uv_x = band(uv_x_source, Image.Resampling.BILINEAR)
        uv_y = band(uv_y_source, Image.Resampling.BILINEAR)
        x_coordinates = np.arange(size, dtype=np.float32)[None, :]
        u_cm = (
            np.where(x_coordinates >= size / 2.0, PW_CM, 0.0)
            + uv_x / 65535.0 * PW_CM
        )
        v_cm = uv_y / 65535.0 * PH_CM
        px = np.clip(u_cm * roll_density, 0, roll_width - 1.001)
        py = np.clip(v_cm * vertical_density, 0, roll_height - 1.001)
        x0 = px.astype(np.int32)
        y0 = py.astype(np.int32)
        fraction_x = (px - x0)[..., None]
        fraction_y = (py - y0)[..., None]
        color = (
            roll[y0, x0].astype(np.float32)
            * ((1 - fraction_x) * (1 - fraction_y))
            + roll[y0, x0 + 1].astype(np.float32)
            * (fraction_x * (1 - fraction_y))
            + roll[y0 + 1, x0].astype(np.float32)
            * ((1 - fraction_x) * fraction_y)
            + roll[y0 + 1, x0 + 1].astype(np.float32)
            * (fraction_x * fraction_y)
        )
        shade = np.clip(template / reference_brightness, 0.12, 1.30)[..., None]
        alpha = mask[..., None]
        output[y_start:y_end] = (
            np.clip(color * shade, 0, 255) * alpha + 255.0 * (1 - alpha)
        ).astype(np.uint8)

    image = Image.fromarray(output)
    if output_size and output_size != size:
        image = image.resize((output_size, output_size), Image.Resampling.LANCZOS)
    return image, {
        "illumination_normalization": "multiplicative-low-frequency-rgb-v1",
        "illumination_proxy_max_px": 320,
        "horizontal_px_per_cm_average": horizontal_density,
        "horizontal_px_per_cm_peak": vertical_density,
        "vertical_px_per_cm": vertical_density,
        "roll_px_per_cm": roll_density,
        "roll_size": [roll_width, roll_height],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sample-cm", required=True, type=float)
    parser.add_argument("--size", type=int, default=12288)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    image, info = render(args.input, args.sample_cm, size=args.size, seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output, quality=95, subsampling=0)
    print(f"output={args.output} size={image.size} metrics={info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
