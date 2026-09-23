"""Render a classified folder with no human approval step; write a UTF-8 Excel-readable CSV report."""
from __future__ import annotations
import argparse
import csv
import os
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_curtain_delivery import render_delivery
from render_curtain_product import parse_detail_name, resolve_route, _sku_key
from scan_fabrics import collect_inputs

REPORT_FIELDS = ['序号', '原图', 'SKU', '分类', '结果', '输出文件', '宽(px)', '高(px)', '大小(MB)', '耗时(秒)', '原因']


def load_classification(path: Path, folder: Path) -> dict[str, dict]:
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if not {'file', 'category'}.issubset(reader.fieldnames or []):
            raise ValueError('Classification CSV needs file and category columns')
        result = {}
        for row in reader:
            p = (folder / row['file']).resolve()
            if folder not in p.parents:
                raise ValueError(f'Classification file escapes input directory: {row["file"]}')
            key = p.relative_to(folder).as_posix()
            if key in result:
                raise ValueError(f'Duplicate classification row: {key}')
            category = row['category'].strip()
            if category not in ('', 'plain', 'large-pattern', 'uncertain', 'invalid'):
                raise ValueError(f'Unknown classification: {category}')
            row['category'] = category
            result[key] = row
        return result


def _optional_path(value: str | None, base: Path):
    return (base / value.strip()).resolve() if value and value.strip() else None


def _optional_number(value: str | None):
    return float(value) if value and value.strip() else None


def run_batch(input_dir: Path, output_dir: Path, classification_path: Path,
    *, catalog_path: Path | None = None, plain_only: bool = False, recursive: bool = False,
    overwrite: bool = False, sku_column='SKU', length_column='长', width_column='宽') -> tuple[list[dict], Path]:
    folder, destination = input_dir.resolve(), output_dir.resolve()
    if destination == folder or folder in destination.parents:
        raise ValueError('Output directory must be outside the source folder')
    files = collect_inputs(folder, recursive)
    if not files:
        raise ValueError('No supported source images')
    classes = load_classification(classification_path, folder)
    file_keys = {p.relative_to(folder).as_posix() for p in files}
    unknown = set(classes) - file_keys
    if unknown:
        raise ValueError(f'Classification has missing/non-scanned source files: {sorted(unknown)}')
    skus = {}
    for path in files:
        try:
            sku, _ = parse_detail_name(path)
        except ValueError:
            continue
        key = _sku_key(sku)
        if key in skus:
            raise ValueError(f'Duplicate output SKU: {path.name} and {skus[key].name}')
        skus[key] = path
    destination.mkdir(parents=True, exist_ok=True)
    report_path = destination / '生图统计表.csv'
    if report_path.exists() and not overwrite:
        report_path = destination / f'生图统计表-{uuid4().hex[:8]}.csv'
    rows = []
    for index, path in enumerate(files, 1):
        started = time.perf_counter()
        relative = path.relative_to(folder).as_posix()
        info = classes.get(relative, {})
        category = info.get('category', '')
        row = dict.fromkeys(REPORT_FIELDS, '')
        row.update({'序号': index, '原图': relative, '分类': category, '结果': '跳过'})
        try:
            sku, _ = parse_detail_name(path)
            row['SKU'] = sku
            if category in ('', 'uncertain', 'invalid'):
                row['原因'] = info.get('reason') or '未分类、无法确定或输入无效；不自动按素色处理'
            elif plain_only and category == 'large-pattern':
                row['原因'] = info.get('reason') or '大花纹；本次仅生成素色'
            else:
                width = _optional_number(info.get('repeat_width_cm'))
                height = _optional_number(info.get('repeat_height_cm'))
                if category == 'large-pattern' and catalog_path is None and width is None and height is None:
                    row['原因'] = '大花纹缺少真实花位尺寸，已跳过'
                else:
                    plain = category == 'plain' and catalog_path is None and width is None and height is None
                    route, _, _ = resolve_route(sku, catalog_path=catalog_path, plain=plain,
                        repeat_width_cm=width, repeat_height_cm=height,
                        sku_column=sku_column, length_column=length_column, width_column=width_column)
                    complete = _optional_path(info.get('complete_repeat'), classification_path.resolve().parent)
                    master = _optional_path(info.get('fused_master'), classification_path.resolve().parent)
                    if category == 'large-pattern' and route == 'plain-detail':
                        row['原因'] = '大花纹与素色目录标记冲突，已跳过'
                    elif plain_only and route != 'plain-detail':
                        row['原因'] = '目录记录为有花位面料；本次仅生成素色'
                    elif route == 'complete-repeat' and complete is None and master is None:
                        row['原因'] = '缺少完整花位图，已跳过；不降级为素色'
                    else:
                        output, _ = render_delivery(path, output_dir=destination,
                            catalog_path=catalog_path, plain=plain,
                            complete_repeat_path=complete, fused_master_path=master,
                            repeat_width_cm=width, repeat_height_cm=height,
                            sku_column=sku_column, length_column=length_column, width_column=width_column,
                            overwrite=overwrite)
                        row.update({'结果': '成功', '输出文件': output.name, '宽(px)': 2880, '高(px)': 2880,
                                    '大小(MB)': round(output.stat().st_size / 1048576, 2), '原因': route})
        except FileExistsError:
            row['原因'] = '同名成品已存在，未覆盖'
        except Exception as error:
            row.update({'结果': '失败', '原因': str(error)})
        row['耗时(秒)'] = round(time.perf_counter() - started, 2)
        rows.append(row)
        # Keep a useful report even if a long batch is interrupted later.
        temporary = report_path.with_name(f'.{report_path.name}.{uuid4().hex}.tmp')
        try:
            with temporary.open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS)
                writer.writeheader(); writer.writerows(rows)
                counts = Counter(r['结果'] for r in rows)
                writer.writerow({'序号': '合计', '原因': f'已处理 {len(rows)}/{len(files)}；成功 {counts["成功"]}；跳过 {counts["跳过"]}；失败 {counts["失败"]}'})
            os.replace(temporary, report_path)
        finally:
            temporary.unlink(missing_ok=True)
        print(f'{index}/{len(files)} {relative}: {row["结果"]}', flush=True)
    return rows, report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_dir', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--classification', required=True, type=Path)
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--plain-only', action='store_true')
    parser.add_argument('--recursive', action='store_true')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--sku-column', default='SKU')
    parser.add_argument('--length-column', default='长')
    parser.add_argument('--width-column', default='宽')
    args = parser.parse_args()
    rows, report = run_batch(args.input_dir, args.output_dir, args.classification,
        catalog_path=args.catalog, plain_only=args.plain_only, recursive=args.recursive,
        overwrite=args.overwrite, sku_column=args.sku_column, length_column=args.length_column,
        width_column=args.width_column)
    print(report)
    return int(any(r['结果'] == '失败' for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
