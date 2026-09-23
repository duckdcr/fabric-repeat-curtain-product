# -*- coding: utf-8 -*-
"""Efros-Freeman minimum-error seam image quilting."""

from __future__ import annotations

import numpy as np


def _min_path_vertical(error: np.ndarray) -> np.ndarray:
    """Return the minimum-cost top-to-bottom path through an error surface."""
    height, width = error.shape
    cumulative = error.astype(np.float64).copy()
    backtrack = np.zeros((height, width), dtype=np.int32)
    for row in range(1, height):
        left = np.concatenate([[np.inf], cumulative[row - 1, :-1]])
        middle = cumulative[row - 1]
        right = np.concatenate([cumulative[row - 1, 1:], [np.inf]])
        choices = np.vstack([left, middle, right])
        selected = np.argmin(choices, axis=0)
        backtrack[row] = selected - 1
        cumulative[row] += choices[selected, np.arange(width)]
    path = np.zeros(height, dtype=np.int32)
    path[-1] = int(np.argmin(cumulative[-1]))
    for row in range(height - 2, -1, -1):
        path[row] = path[row + 1] + backtrack[row + 1, path[row + 1]]
        path[row] = min(max(path[row], 0), width - 1)
    return path


def paste_min_cut(
    canvas: np.ndarray,
    filled: np.ndarray,
    tile: np.ndarray,
    y: int,
    x: int,
    overlap_x: int,
    overlap_y: int,
) -> None:
    """Paste a tile using minimum-error cuts in occupied overlap regions."""
    canvas_height, canvas_width = canvas.shape[:2]
    tile_height, tile_width = tile.shape[:2]
    y_end, x_end = min(canvas_height, y + tile_height), min(canvas_width, x + tile_width)
    if y_end <= y or x_end <= x:
        return
    source = tile[: y_end - y, : x_end - x].astype(np.float32)
    destination = canvas[y:y_end, x:x_end]
    occupied = filled[y:y_end, x:x_end]
    take_source = np.ones(source.shape[:2], dtype=bool)

    if occupied[:, :overlap_x].any() and overlap_x > 1 and source.shape[1] > overlap_x:
        error = (
            (destination[:, :overlap_x].astype(np.float32) - source[:, :overlap_x]) ** 2
        ).sum(axis=2)
        error = np.where(occupied[:, :overlap_x], error, 0.0)
        path = _min_path_vertical(error)
        columns = np.arange(overlap_x)[None, :]
        take_source[:, :overlap_x] = columns >= path[:, None]

    if occupied[:overlap_y, :].any() and overlap_y > 1 and source.shape[0] > overlap_y:
        error = (
            (destination[:overlap_y, :].astype(np.float32) - source[:overlap_y, :]) ** 2
        ).sum(axis=2).T
        error = np.where(occupied[:overlap_y, :].T, error, 0.0)
        path = _min_path_vertical(error)
        rows = np.arange(overlap_y)[None, :]
        take_source[:overlap_y, :] &= (rows >= path[:, None]).T

    keep_destination = occupied & ~take_source
    canvas[y:y_end, x:x_end] = np.where(
        keep_destination[..., None], destination, source.astype(np.uint8)
    )
    filled[y:y_end, x:x_end] = True

