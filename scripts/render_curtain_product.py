# -*- coding: utf-8 -*-
"""Standalone curtain routing with local renderers and automatic output checks."""

from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageChops


DETAIL_NAME_PATTERN = re.compile(
    r"^(?P<sku>.+)_detail_(?P<cm>10|15)$",
)
DETAIL_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MISSING_DIMENSIONS = {"/", "／"}
FORMAL_OUTPUT_SIZE = 2880
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SCRIPTS = PROJECT_ROOT / "scripts"
ASSET_DIR = PROJECT_ROOT / "assets"
sys.path.insert(0, str(PROJECT_SCRIPTS))


class CatalogError(ValueError):
    """Raised when catalog data cannot select one safe rendering route."""


@dataclass(frozen=True)
class CatalogMatch:
    sku: str
    row_number: int
    matched_rows: list[int]
    length_raw: str
    width_raw: str
    route: str
    repeat_height_cm: float | None
    repeat_width_cm: float | None
    encoding: str


def _normalize_sku(value: str) -> str:
    return " ".join(str(value).split())


def _sku_key(value: str) -> str:
    normalized = _normalize_sku(value)
    return "".join(
        chr(ord(character) + 32) if "A" <= character <= "Z" else character
        for character in normalized
    )


def parse_detail_name(path: str | Path) -> tuple[str, int]:
    candidate = Path(path)
    if candidate.suffix.lower() not in DETAIL_EXTENSIONS:
        raise ValueError(f"Unsupported detail image extension: {candidate.suffix}")
    match = DETAIL_NAME_PATTERN.fullmatch(candidate.stem)
    if not match:
        raise ValueError(
            f"Detail image name must end with _detail_10 or _detail_15: {candidate.name}"
        )
    sku = _normalize_sku(match.group("sku"))
    if not sku:
        raise ValueError("Detail image SKU cannot be empty")
    return sku, int(match.group("cm"))


def classify_repeat(
    length_raw: object,
    width_raw: object,
) -> tuple[str, float | None, float | None]:
    length_text = str(length_raw).strip() if length_raw is not None else ""
    width_text = str(width_raw).strip() if width_raw is not None else ""
    length_missing = length_text in MISSING_DIMENSIONS
    width_missing = width_text in MISSING_DIMENSIONS

    if length_missing and width_missing:
        return "plain-detail", None, None
    if length_missing != width_missing:
        raise CatalogError("repeat length and width must both be numeric or both be /")
    if not length_text or not width_text:
        raise CatalogError("repeat length and width cannot be blank")

    try:
        repeat_height_cm = float(length_text)
        repeat_width_cm = float(width_text)
    except ValueError as error:
        raise CatalogError("repeat length and width must be positive numbers or both /") from error
    if (
        not math.isfinite(repeat_height_cm)
        or not math.isfinite(repeat_width_cm)
        or repeat_height_cm <= 0
        or repeat_width_cm <= 0
    ):
        raise CatalogError("repeat length and width must be positive")
    return "complete-repeat", repeat_height_cm, repeat_width_cm


def _read_catalog_rows(
    path: Path,
) -> tuple[list[tuple[int, dict[str, str]]], list[str], str]:
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                fieldnames = list(reader.fieldnames or [])
                rows: list[tuple[int, dict[str, str]]] = []
                for row in reader:
                    rows.append((reader.line_num, row))
                return rows, fieldnames, encoding
        except UnicodeDecodeError as error:
            last_error = error
    raise CatalogError(f"catalog is neither UTF-8 nor GB18030: {path}") from last_error


def lookup_catalog(
    csv_path: str | Path,
    sku: str,
    *,
    sku_column: str = "SKU",
    length_column: str = "长",
    width_column: str = "宽",
) -> CatalogMatch:
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    rows, fieldnames, encoding = _read_catalog_rows(path)
    required = {sku_column, length_column, width_column}
    missing = sorted(required.difference(fieldnames))
    if missing:
        raise CatalogError(f"catalog missing required columns: {', '.join(missing)}")

    normalized_target = _sku_key(sku)
    matches: list[tuple[int, dict[str, str]]] = []
    for row_number, row in rows:
        if _sku_key(row.get(sku_column, "")) == normalized_target:
            matches.append((row_number, row))
    if not matches:
        raise CatalogError(f"SKU not found in catalog: {sku}")

    interpreted: list[tuple[str, float | None, float | None]] = []
    for _, row in matches:
        interpreted.append(classify_repeat(row.get(length_column), row.get(width_column)))
    first_interpretation = interpreted[0]
    if any(value != first_interpretation for value in interpreted[1:]):
        raise CatalogError(f"conflicting catalog records for SKU: {sku}")

    first_row_number, first_row = matches[0]
    route, repeat_height_cm, repeat_width_cm = first_interpretation
    return CatalogMatch(
        sku=_normalize_sku(first_row[sku_column]),
        row_number=first_row_number,
        matched_rows=[row_number for row_number, _ in matches],
        length_raw=str(first_row[length_column]).strip(),
        width_raw=str(first_row[width_column]).strip(),
        route=route,
        repeat_height_cm=repeat_height_cm,
        repeat_width_cm=repeat_width_cm,
        encoding=encoding,
    )


def _clip_mask(size: tuple[int, int], asset_dir: Path) -> Image.Image:
    with Image.open(asset_dir / 'mask.png') as source:
        mask = source.convert('L').point(lambda p: 255 if p >= 128 else 0)
    with Image.open(asset_dir / 'double-pinch-template.png') as source:
        silhouette = source.convert('L').point(lambda p: 255 if p < 245 else 0)
    if mask.size != silhouette.size:
        raise ValueError('Template and mask dimensions differ')
    mask = ImageChops.multiply(mask, silhouette)
    if not mask.getbbox():
        raise ValueError('Empty template mask')
    return mask.resize(size, Image.Resampling.BILINEAR)


def _clip_to_template(image: Image.Image, asset_dir: Path) -> Image.Image:
    return Image.composite(image.convert('RGB'), Image.new('RGB', image.size, 'white'), _clip_mask(image.size, asset_dir))


def _validate_saved_image(path: Path, expected_size: int) -> None:
    import numpy as np
    with Image.open(path) as image:
        image.load()
        if image.size != (expected_size, expected_size) or image.mode != 'RGB' or image.format != 'WEBP':
            raise ValueError('Output must be RGB WebP with the requested dimensions')
        outside = np.asarray(_clip_mask(image.size, ASSET_DIR)) == 0
        if not np.all(np.asarray(image)[outside] == 255):
            raise ValueError('Output background outside the curtain silhouette is not white')


def resolve_route(sku: str, *, catalog_path=None, plain=False,
    repeat_width_cm=None, repeat_height_cm=None,
    sku_column='SKU', length_column='长', width_column='宽') -> tuple[str, float | None, float | None]:
    if catalog_path is not None:
        match = lookup_catalog(catalog_path, sku, sku_column=sku_column,
                               length_column=length_column, width_column=width_column)
        if plain and match.route != 'plain-detail':
            raise CatalogError('Cannot override positive catalog repeat dimensions with --plain')
        if repeat_width_cm is not None or repeat_height_cm is not None:
            explicit = classify_repeat(repeat_height_cm, repeat_width_cm)
            if explicit != (match.route, match.repeat_height_cm, match.repeat_width_cm):
                raise CatalogError('Explicit repeat dimensions conflict with catalog')
        return match.route, match.repeat_height_cm, match.repeat_width_cm
    if plain:
        if repeat_width_cm is not None or repeat_height_cm is not None:
            raise CatalogError('--plain cannot be combined with repeat dimensions')
        return 'plain-detail', None, None
    if repeat_width_cm is not None or repeat_height_cm is not None:
        return classify_repeat(repeat_height_cm, repeat_width_cm)
    raise CatalogError('Provide --plain for a classified plain swatch, a catalog, or both repeat dimensions')


def render_product(detail_path: str | Path, *, output_dir: str | Path,
    catalog_path: str | Path | None = None, plain: bool = False,
    complete_repeat_path: str | Path | None = None, fused_master_path: str | Path | None = None,
    repeat_width_cm: float | None = None, repeat_height_cm: float | None = None,
    sku_column: str = 'SKU', length_column: str = '长', width_column: str = '宽',
    output_size: int = FORMAL_OUTPUT_SIZE, overwrite: bool = False) -> tuple[Path, Path, dict[str, Any]]:
    # Low-level helper writes a private machine report. Use delivery for final output.
    detail = Path(detail_path).resolve()
    if not detail.is_file():
        raise FileNotFoundError(detail)
    sku, window_cm = parse_detail_name(detail)
    route, height, width = resolve_route(sku, catalog_path=catalog_path, plain=plain,
        repeat_width_cm=repeat_width_cm, repeat_height_cm=repeat_height_cm,
        sku_column=sku_column, length_column=length_column, width_column=width_column)
    if not 512 <= output_size <= 16383:
        raise ValueError('Output size must be between 512 and 16383')
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    image_path = destination / f'{sku}_double-pinch.webp'
    report_path = destination / f'{sku}_double-pinch.audit.json'
    if not overwrite and (image_path.exists() or report_path.exists()):
        raise FileExistsError(image_path)
    for name in ('mask.png', 'double-pinch-template.png', 'uv-y.png', 'uvx_fixed.npy'):
        if not (ASSET_DIR / name).is_file():
            raise FileNotFoundError(ASSET_DIR / name)
    seed = sum(map(ord, detail.stem)) % 9973
    report: dict[str, Any] = {'sku': sku, 'detail_source': str(detail), 'detail_window_cm': window_cm,
        'route': route, 'output_size': [output_size, output_size],
        'template': str(ASSET_DIR / 'double-pinch-template.png'), 'mirrored': False, 'status': 'passed'}
    if route == 'plain-detail':
        if complete_repeat_path is not None or fused_master_path is not None:
            raise CatalogError('A complete-repeat source cannot be rendered through the plain route')
        from weave8 import render
        image, metrics = render(detail, window_cm, size=output_size, seed=seed)
        report.update(renderer='weave8', seed=seed, physical_contract={
            'panel_width_cm': 193.9, 'curtain_height_cm': 270.0, 'panel_count': 2})
    else:
        # No fusion skill, human approval, or approval JSON is required.
        source_arg = fused_master_path if fused_master_path is not None else complete_repeat_path
        if source_arg is None:
            raise CatalogError('Complete-repeat rendering requires --complete-repeat or --fused-master; no plain fallback')
        source = Path(source_arg).resolve()
        if source == detail:
            raise CatalogError('Do not use a partial detail photograph as the full-repeat source')
        if not source.is_file():
            raise FileNotFoundError(source)
        with Image.open(source) as im:
            im.verify()
        from complete_repeat import render_complete_repeat
        image, metrics = render_complete_repeat(source, repeat_width_cm=width,
            repeat_height_cm=height, panel_width_cm=280.0, curtain_height_cm=280.0, panel_count=2, size=output_size)
        report.update(renderer='complete-repeat-v1', repeat_source=str(source),
            source_mode='provided-master' if fused_master_path is not None else 'complete-repeat-as-is',
            physical_contract={'panel_width_cm': 280.0, 'curtain_height_cm': 280.0,
                               'panel_count': 2, 'finished_total_width_cm': 560.0},
            repeat={'H_repeat_cm': height, 'W_repeat_cm': width,
                    'vertical_count': 280.0 / height, 'horizontal_count_total': 560.0 / width})
    image = _clip_to_template(image, ASSET_DIR)
    report.update(metrics=metrics, template_crop={'applied': True, 'template_background_threshold': 245})
    temporary = destination / f'.{sku}.{uuid4().hex}.webp'
    try:
        image.convert('RGB').save(temporary, format='WEBP', lossless=True, quality=95, method=4)
        _validate_saved_image(temporary, output_size)
        if overwrite:
            os.replace(temporary, image_path)
        else:
            os.link(temporary, image_path)
        with report_path.open('w' if overwrite else 'x', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    finally:
        temporary.unlink(missing_ok=True)
    return image_path, report_path, report


if __name__ == '__main__':
    from render_curtain_delivery import main
    raise SystemExit(main())
