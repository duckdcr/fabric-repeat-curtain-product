"""Inventory source photos and create numbered contact sheets for agent classification."""
from __future__ import annotations
import argparse
import csv
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image, ImageDraw, ImageOps
from render_curtain_product import DETAIL_EXTENSIONS, parse_detail_name

FIELDS = ['file', 'category', 'reason', 'complete_repeat', 'fused_master', 'repeat_width_cm', 'repeat_height_cm']


def collect_inputs(folder: Path, recursive: bool = False) -> list[Path]:
    if not folder.is_dir():
        raise NotADirectoryError(folder)
    candidates = folder.rglob('*') if recursive else folder.iterdir()
    return sorted((p for p in candidates if p.is_file() and p.suffix.lower() in DETAIL_EXTENSIONS),
                  key=lambda p: p.relative_to(folder).as_posix())


def scan(folder: Path, work_dir: Path, recursive: bool = False) -> Path:
    folder = folder.resolve()
    work_dir = work_dir.resolve()
    if work_dir == folder or folder in work_dir.parents:
        raise ValueError('Put the scan workspace outside the input folder')
    files = collect_inputs(folder, recursive)
    if not files:
        raise ValueError('No supported image files in source folder')
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest = work_dir / 'classification.csv'
    if manifest.exists():
        raise FileExistsError(f'Preserve existing classification: {manifest}; choose a fresh workspace')
    rows = []
    for start in range(0, len(files), 20):
        group = files[start:start+20]
        page = Image.new('RGB', (1200, ((len(group)+3)//4)*275), 'white')
        draw = ImageDraw.Draw(page)
        for offset, path in enumerate(group):
            relative = path.relative_to(folder).as_posix()
            row = dict.fromkeys(FIELDS, '')
            row['file'] = relative
            x, y = (offset % 4)*300, (offset // 4)*275
            try:
                sku, _ = parse_detail_name(path)
                with Image.open(path) as source:
                    if not .99 <= source.width / source.height <= 1.01:
                        raise ValueError('Detail photo is not square')
                    thumb = ImageOps.contain(source.convert('RGB'), (290, 245))
                page.paste(thumb, (x, y))
            except Exception as error:
                row['category'], row['reason'] = 'invalid', str(error)
            # ASCII index is portable across systems without bundled CJK fonts.
            draw.text((x+4, y+250), f'#{start+offset+1:03d}', fill='black')
            rows.append(row)
        page.save(work_dir / f'contact-{start//20+1:03d}.jpg', quality=90)
    with manifest.open('x', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(rows)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_dir', type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--recursive', action='store_true')
    args = parser.parse_args()
    print(scan(args.input_dir, args.work_dir, args.recursive))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
