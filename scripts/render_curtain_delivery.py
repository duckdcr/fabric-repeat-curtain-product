"""Standalone 2880px delivery; automatic checks only, no approval files."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_curtain_product import render_product, parse_detail_name


def _publish_image_only(staged_image: Path, final_image: Path, overwrite: bool) -> None:
    final_image.parent.mkdir(parents=True, exist_ok=True)
    temporary = final_image.with_name(f'.{final_image.name}.{uuid4().hex}.tmp')
    try:
        shutil.copyfile(staged_image, temporary)
        if overwrite:
            os.replace(temporary, final_image)
        else:
            os.link(temporary, final_image)
    finally:
        temporary.unlink(missing_ok=True)


def render_delivery(detail_path: str | Path, *, output_dir: str | Path,
    catalog_path: str | Path | None = None, plain: bool = False,
    complete_repeat_path: str | Path | None = None, fused_master_path: str | Path | None = None,
    repeat_width_cm: float | None = None, repeat_height_cm: float | None = None,
    sku_column: str = 'SKU', length_column: str = '长', width_column: str = '宽',
    overwrite: bool = False) -> tuple[Path, dict]:
    sku, _ = parse_detail_name(detail_path)
    final_image = Path(output_dir) / f'{sku}_double-pinch.webp'
    if final_image.exists() and not overwrite:
        raise FileExistsError(final_image)
    with tempfile.TemporaryDirectory(prefix='curtain-delivery-') as temporary:
        staged_image, _, report = render_product(
            detail_path, output_dir=temporary, catalog_path=catalog_path, plain=plain,
            complete_repeat_path=complete_repeat_path, fused_master_path=fused_master_path,
            repeat_width_cm=repeat_width_cm, repeat_height_cm=repeat_height_cm,
            sku_column=sku_column, length_column=length_column, width_column=width_column,
            output_size=2880)
        _publish_image_only(staged_image, final_image, overwrite)
    return final_image, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('detail', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--plain', action='store_true', help='Input is already classified as plain/fine weave; no catalog needed')
    parser.add_argument('--complete-repeat', type=Path)
    parser.add_argument('--fused-master', type=Path, help='Optional ready-to-render full-repeat master')
    parser.add_argument('--repeat-width-cm', type=float)
    parser.add_argument('--repeat-height-cm', type=float)
    parser.add_argument('--sku-column', default='SKU')
    parser.add_argument('--length-column', default='长')
    parser.add_argument('--width-column', default='宽')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    image, report = render_delivery(args.detail, output_dir=args.output_dir,
        catalog_path=args.catalog, plain=args.plain, complete_repeat_path=args.complete_repeat,
        fused_master_path=args.fused_master, repeat_width_cm=args.repeat_width_cm,
        repeat_height_cm=args.repeat_height_cm, sku_column=args.sku_column,
        length_column=args.length_column, width_column=args.width_column, overwrite=args.overwrite)
    print(json.dumps({'output': str(image), 'route': report['route'], 'size': report['output_size']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
