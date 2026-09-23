"""Copy the skill to an unrelated directory and test real delivery with bundled assets."""
from __future__ import annotations
import csv
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))


def worker():
    import numpy as np
    from PIL import Image
    from batch import run_batch
    from check_environment import check
    from render_curtain_delivery import render_delivery
    from render_curtain_product import resolve_route, CatalogError, _validate_saved_image
    from scan_fabrics import scan, FIELDS

    class StandaloneTests(unittest.TestCase):
        def setUp(self):
            self.temp = tempfile.TemporaryDirectory(prefix='curtain-test-')
            self.addCleanup(self.temp.cleanup)
            self.root = Path(self.temp.name)
            self.sources = self.root/'inputs'; self.sources.mkdir()
            self.detail = self.sources/'PLAIN_detail_15.jpg'
            rng = np.random.default_rng(42)
            pixels = np.clip(140+rng.normal(0, 5, (128, 128, 3)), 0, 255).astype('uint8')
            Image.fromarray(pixels).save(self.detail)

        def catalog(self, rows):
            target = self.root/'catalog.csv'
            with target.open('w', encoding='utf-8-sig', newline='') as f:
                writer=csv.writer(f); writer.writerow(['SKU','长','宽']); writer.writerows(rows)
            return target

        def test_local_dependencies(self):
            check()

        def test_routing_and_invalid_catalog(self):
            self.assertEqual(resolve_route('PLAIN', plain=True), ('plain-detail',None,None))
            for h,w in [(None,10),(0,10),(-1,10),(float('nan'),10),(float('inf'),10)]:
                with self.assertRaises(CatalogError):
                    resolve_route('PLAIN', repeat_height_cm=h, repeat_width_cm=w)
            positive=self.catalog([['PLAIN',63,71]])
            with self.assertRaises(CatalogError):
                resolve_route('PLAIN', catalog_path=positive, plain=True)
            with self.assertRaises(CatalogError):
                resolve_route('PLAIN', catalog_path=positive, repeat_height_cm=64, repeat_width_cm=71)
            conflict=self.catalog([['PLAIN','/','/'],['PLAIN',63,71]])
            with self.assertRaises(CatalogError):
                resolve_route('PLAIN',catalog_path=conflict)

        def test_actual_plain_batch_and_large_pattern_skip(self):
            Image.new('RGB',(128,128),'red').save(self.sources/'LARGE_detail_15.jpg')
            Image.new('RGB',(128,128),'blue').save(self.sources/'UNKNOWN_detail_10.png')
            manifest=scan(self.sources,self.root/'scan')
            with manifest.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
            for row in rows:
                if row['file'].startswith('PLAIN'): row['category']='plain'
                if row['file'].startswith('LARGE'): row['category']='large-pattern'
            with manifest.open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
            result,report=run_batch(self.sources,self.root/'out',manifest,plain_only=True)
            self.assertEqual([r['结果'] for r in result].count('成功'),1)
            self.assertEqual([r['结果'] for r in result].count('跳过'),2)
            output=self.root/'out'/'PLAIN_double-pinch.webp'
            _validate_saved_image(output,2880)
            with output.open('rb') as f: original=f.read()
            again,_=run_batch(self.sources,self.root/'out',manifest,plain_only=True)
            self.assertTrue(all(r['结果']=='跳过' for r in again))
            self.assertEqual(output.read_bytes(),original)
            self.assertFalse(list((self.root/'out').glob('*.json')))
            with report.open(encoding='utf-8-sig',newline='') as f: report_rows=list(csv.DictReader(f))
            self.assertEqual(len(report_rows),4)
            self.assertIn('成功 1；跳过 2；失败 0',report_rows[-1]['原因'])

        def test_actual_full_repeat_without_approval(self):
            source=self.root/'full-repeat.png'
            pixels=np.zeros((128,128,3),dtype='uint8')
            pixels[:,:64]=[130,90,60];pixels[:,64:]=[190,170,130]
            Image.fromarray(pixels).save(source)
            output,report=render_delivery(self.detail, output_dir=self.root/'out',
                complete_repeat_path=source, repeat_height_cm=63, repeat_width_cm=71)
            self.assertEqual(report['route'],'complete-repeat')
            self.assertAlmostEqual(report['repeat']['horizontal_count_total'],560/71)
            self.assertEqual(report['source_mode'],'complete-repeat-as-is')
            _validate_saved_image(output,2880)
            self.assertEqual([p.name for p in output.parent.iterdir()],[output.name])

        def test_no_missing_repeat_fallback(self):
            with self.assertRaises(CatalogError):
                render_delivery(self.detail,output_dir=self.root/'out',repeat_height_cm=63,repeat_width_cm=71)
            self.assertFalse(list((self.root/'out').glob('*.webp')))
            with self.assertRaises(CatalogError):
                render_delivery(self.detail,output_dir=self.root/'out',
                    complete_repeat_path=self.detail,repeat_height_cm=63,repeat_width_cm=71)

        def test_duplicate_outputs_are_blocked(self):
            Image.new('RGB',(128,128),'white').save(self.sources/'PLAIN_detail_10.png')
            manifest=scan(self.sources,self.root/'scan')
            with self.assertRaisesRegex(ValueError,'Duplicate output SKU'):
                run_batch(self.sources,self.root/'out',manifest,plain_only=True)

        def test_cli_from_unrelated_cwd(self):
            script=Path(__file__).with_name('render_curtain_delivery.py')
            result=subprocess.run([sys.executable,str(script),'--help'],cwd=self.root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertNotIn('--fusion-audit',result.stdout)
            self.assertNotIn('--project-root',result.stdout)

    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StandaloneTests))
    return 0 if result.wasSuccessful() else 1


def main():
    if '--worker' in sys.argv:
        return worker()
    skill=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='portable-curtain-') as temp:
        target=Path(temp)/'relocated-skill'
        shutil.copytree(skill,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        env=os.environ.copy();env.pop('PYTHONPATH',None);env['PYTHONDONTWRITEBYTECODE']='1'
        return subprocess.call([sys.executable,str(target/'scripts'/'test_standalone.py'),'--worker'],
                               cwd=temp,env=env)


if __name__ == '__main__':
    raise SystemExit(main())
