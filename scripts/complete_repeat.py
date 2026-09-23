# -*- coding: utf-8 -*-
"""Deterministic complete-repeat curtain texture renderer."""

from __future__ import annotations

from math import ceil
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from PIL import Image

import weave8


Image.MAX_IMAGE_PIXELS = None


def _require_positive(name: str, value: float) -> float:
    value = float(value)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def compute_repeat_contract(
    *,
    repeat_width_cm: float,
    repeat_height_cm: float,
    panel_width_cm: float,
    curtain_height_cm: float,
    panel_count: int = 2,
) -> dict[str, float | int]:
    """Return the exact physical repeat counts for the finished curtain."""
    repeat_width_cm = _require_positive("repeat_width_cm", repeat_width_cm)
    repeat_height_cm = _require_positive("repeat_height_cm", repeat_height_cm)
    panel_width_cm = _require_positive("panel_width_cm", panel_width_cm)
    curtain_height_cm = _require_positive("curtain_height_cm", curtain_height_cm)
    if panel_count <= 0:
        raise ValueError("panel_count must be positive")
    finished_total_width_cm = panel_width_cm * panel_count
    return {
        "repeat_width_cm": repeat_width_cm,
        "repeat_height_cm": repeat_height_cm,
        "panel_width_cm": panel_width_cm,
        "curtain_height_cm": curtain_height_cm,
        "panel_count": panel_count,
        "finished_total_width_cm": finished_total_width_cm,
        "vertical_repeat_count": curtain_height_cm / repeat_height_cm,
        "horizontal_repeat_count_per_panel": panel_width_cm / repeat_width_cm,
        "horizontal_repeat_count_total": finished_total_width_cm / repeat_width_cm,
    }


def build_repeat_roll(
    source_path: str | Path,
    *,
    repeat_width_cm: float,
    repeat_height_cm: float,
    finished_width_cm: float,
    finished_height_cm: float,
    pixels_per_cm: float,
) -> tuple[np.ndarray, dict[str, object]]:
    """Tile the complete repeat at exact physical scale and crop at roll edges."""
    repeat_width_cm = _require_positive("repeat_width_cm", repeat_width_cm)
    repeat_height_cm = _require_positive("repeat_height_cm", repeat_height_cm)
    finished_width_cm = _require_positive("finished_width_cm", finished_width_cm)
    finished_height_cm = _require_positive("finished_height_cm", finished_height_cm)
    pixels_per_cm = _require_positive("pixels_per_cm", pixels_per_cm)

    tile_width = max(1, int(round(repeat_width_cm * pixels_per_cm)))
    tile_height = max(1, int(round(repeat_height_cm * pixels_per_cm)))
    roll_width = max(2, int(round(finished_width_cm * pixels_per_cm)))
    roll_height = max(2, int(round(finished_height_cm * pixels_per_cm)))

    tile = np.asarray(
        Image.open(source_path)
        .convert("RGB")
        .resize((tile_width, tile_height), Image.Resampling.LANCZOS),
        dtype=np.uint8,
    )
    repeated = np.tile(
        tile,
        (
            ceil(roll_height / tile_height),
            ceil(roll_width / tile_width),
            1,
        ),
    )
    roll = np.ascontiguousarray(repeated[:roll_height, :roll_width])
    return roll, {
        "repeat_tile_pixels": [tile_width, tile_height],
        "roll_size": [roll_width, roll_height],
        "pixels_per_cm": pixels_per_cm,
    }


def render_complete_repeat(
    source_path: str | Path,
    *,
    repeat_width_cm: float,
    repeat_height_cm: float,
    panel_width_cm: float = 280.0,
    curtain_height_cm: float = 280.0,
    panel_count: int = 2,
    size: int = 12288,
    strip: int = 512,
) -> tuple[Image.Image, dict[str, object]]:
    """Map an exact complete repeat through the fixed double-pinch UV template."""
    if size < 512:
        raise ValueError("size must be at least 512 pixels")
    if panel_count != 2:
        raise ValueError("the fixed double-pinch template requires two panels")

    contract = compute_repeat_contract(
        repeat_width_cm=repeat_width_cm,
        repeat_height_cm=repeat_height_cm,
        panel_width_cm=panel_width_cm,
        curtain_height_cm=curtain_height_cm,
        panel_count=panel_count,
    )
    vertical_density = size * (weave8.PH_PX / weave8.BASE) / curtain_height_cm
    horizontal_density_average = (
        size * (weave8.PW_PX / weave8.BASE) / panel_width_cm
    )
    roll, roll_metrics = build_repeat_roll(
        source_path,
        repeat_width_cm=repeat_width_cm,
        repeat_height_cm=repeat_height_cm,
        finished_width_cm=contract["finished_total_width_cm"],
        finished_height_cm=curtain_height_cm,
        pixels_per_cm=vertical_density,
    )
    roll_height, roll_width = roll.shape[:2]

    mask_source = weave8._gray_asset("mask.png")
    uv_x_source = weave8._fixed_uv_x()
    uv_y_source = weave8._packed_uv("uv-y.png")
    template_source = weave8._gray_asset("double-pinch-template.png")
    reference_brightness = float(
        np.percentile(template_source[mask_source > 0].astype(np.float32), 55)
    )
    output = np.empty((size, size, 3), dtype=np.uint8)

    for y_start in range(0, size, strip):
        y_end = min(size, y_start + strip)
        source_start = int(np.floor(y_start / size * weave8.BASE))
        source_end = min(
            int(np.ceil(y_end / size * weave8.BASE)) + 1,
            int(weave8.BASE),
        )
        top = int(round(source_start / weave8.BASE * size))
        resized_height = int(
            round((source_end - source_start) / weave8.BASE * size)
        )

        def band(
            array: np.ndarray,
            mode: int,
            dtype: type[np.floating] | type[np.uint8] = np.float32,
        ) -> np.ndarray:
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
            np.where(x_coordinates >= size / 2.0, panel_width_cm, 0.0)
            + uv_x / 65535.0 * panel_width_cm
        )
        v_cm = uv_y / 65535.0 * curtain_height_cm
        px = np.clip(u_cm * vertical_density, 0, roll_width - 1.001)
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

    return Image.fromarray(output), {
        "renderer": "complete-repeat-v1",
        "render_seed": 0,
        "contract": contract,
        "horizontal_px_per_cm_average": horizontal_density_average,
        "vertical_px_per_cm": vertical_density,
        **roll_metrics,
    }
