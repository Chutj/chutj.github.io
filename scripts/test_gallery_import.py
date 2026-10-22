"""Integration checks using real FIG copies in ignored, disposable fixtures.

The authoritative FIG source is opened for reading only. No fixture is deleted.
"""
import json
import re
import shutil
import socket
import subprocess
import time
import unittest
import uuid
from pathlib import Path
from urllib.request import urlopen

import import_gallery as importer


class IncrementalGalleryTest(unittest.TestCase):
    def setUp(self):
        self.base = importer.LOCAL / 'tests' / uuid.uuid4().hex
        self.source = self.base / 'source'
        self.output = self.base / 'output'
        self.source.mkdir(parents=True)
        registry = '论文来源与核查状态.md'
        (self.source / registry).write_bytes((importer.DEFAULT_SOURCE / registry).read_bytes())
        self.add_real('地图', 'NCC_2026_Xu_02762-2_Fig2_b-e-h.png')
        self.add_real('示意图', 'NC_2026_Bai_78296-0_Fig2_c.png')

    def add_real(self, category, filename):
        origin = importer.DEFAULT_SOURCE / category
        target = self.source / category
        target.mkdir(exist_ok=True)
        text = (origin / (category+'.md')).read_text(encoding='utf-8-sig')
        block = next(b for b in re.split(r'(?m)^##\s+', text)[1:] if ']('+filename+')' in b)
        row = next(line for line in text.splitlines() if line.startswith('|') and filename in line)
        md = target / (category+'.md')
        existing = md.read_text(encoding='utf-8') if md.exists() else ''
        md.write_text(existing+'\n| Material | Paper | Figure | Image |\n| --- | --- | --- | --- |\n'+row+'\n\n## '+block, encoding='utf-8')
        shutil.copyfile(origin/filename, target/filename)
        return md, target/filename

    def run_import(self, dry=False):
        return importer.run(self.source, self.output, dry)

    def catalog(self):
        return json.loads((self.output/'catalog.json').read_text(encoding='utf-8'))['records']

    def test_dry_run_and_idempotence(self):
        report = self.run_import(True)
        self.assertEqual(report['summary']['added'], 2)
        self.assertFalse(self.output.exists())
        self.assertTrue(report['files'])
        self.run_import()
        snapshots = {p:p.stat().st_mtime_ns for p in self.output.rglob('*') if p.is_file()}
        repeat = self.run_import()
        self.assertEqual(repeat['summary']['unchanged'], 2)
        self.assertEqual(repeat['summary']['images_to_copy'], 0)
        self.assertEqual(repeat['files'], {})
        for path, modified in snapshots.items():
            if path.name != 'last-report.json':
                self.assertEqual(path.stat().st_mtime_ns, modified)
        self.assertEqual(len({r['id'] for r in self.catalog()}), 2)

    def test_new_and_description_update(self):
        self.run_import()
        md, image = self.add_real('散点图', 'NCC_2026_Xu_02762-2_Fig4_g-i.png')
        report = self.run_import()
        self.assertEqual(report['summary']['added'], 1)
        self.assertEqual(report['summary']['images_to_copy'], 1)
        prior_ids = {r['id'] for r in self.catalog()}
        md.write_text(md.read_text(encoding='utf-8')+'\n\n**Fixture update**: description-change integration check.\n', encoding='utf-8')
        changed = self.run_import()
        self.assertEqual(changed['summary']['updated'], 1)
        self.assertEqual(changed['summary']['images_to_copy'], 0)
        self.assertEqual({r['id'] for r in self.catalog()}, prior_ids)
        inventory = json.loads((self.output/'inventory.json').read_text(encoding='utf-8'))
        self.assertTrue(any('Fixture update' in r['raw_fields'] for r in inventory['records']))

    def test_rename_image_replacement_and_rights_reset(self):
        self.run_import()
        prior = {r['doi']:r['id'] for r in self.catalog()}
        folder = self.source/'地图'
        old_name = 'NCC_2026_Xu_02762-2_Fig2_b-e-h.png'
        new_name = 'NCC_2026_Xu_02762-2_Fig2_b-e-h_renamed.png'
        (folder/old_name).rename(folder/new_name)
        md = folder/'地图.md'
        md.write_text(md.read_text(encoding='utf-8').replace(old_name,new_name),encoding='utf-8')
        renamed = self.run_import()
        self.assertEqual(renamed['summary']['added'], 0)
        self.assertEqual(renamed['summary']['updated'], 1)
        self.assertEqual(renamed['summary']['images_to_copy'], 0)
        uid = prior['10.1038/s41558-026-02762-2']
        state = json.loads((self.output/'state.json').read_text(encoding='utf-8'))
        state['records'][uid]['rights']['public_use_allowed'] = True
        (self.output/'state.json').write_text(json.dumps(state),encoding='utf-8')
        # PNG trailing bytes change content without altering the real figure pixels.
        p = folder/new_name
        p.write_bytes(p.read_bytes()+b'\n')
        changed = self.run_import()
        self.assertEqual(changed['summary']['added'], 0)
        self.assertEqual(changed['summary']['images_to_copy'], 1)
        record = next(r for r in self.catalog() if r['id']==uid)
        self.assertFalse(record['rights']['public_use_allowed'])

    def test_cross_category_duplicate(self):
        self.run_import()
        self.add_real('配色参考', 'NCC_2026_Xu_02762-2_Fig2_b-e-h.png')
        result = self.run_import()
        self.assertEqual(result['summary']['valid_records'], 2)
        self.assertEqual(result['summary']['added'], 0)
        self.assertEqual(result['summary']['cross_category_copies'], 1)
        self.assertEqual(result['summary']['images_to_copy'], 0)

    def test_description_change_invalidates_translation(self):
        self.output.mkdir(parents=True)
        # Test invalidation against this fixture's notes, which may differ from
        # historical translations as the external FIG library evolves.
        translations=json.loads((importer.LOCAL/'english.json').read_text(encoding='utf-8'))
        candidates,_,_=importer.scan(self.source,dict(importer.CATEGORY_LABELS))
        for candidate in candidates:
            for variant in candidate['variants']:
                if variant['filename'] in translations:
                    translations[variant['filename']]['note_sha256']=variant['note_sha256']
        (self.output/'english.json').write_text(json.dumps(translations),encoding='utf-8')
        first = self.run_import()
        self.assertEqual(first['summary']['translated'], 2)
        before_config = (self.output/'hugo.toml').read_bytes()
        md = self.source/'地图'/'地图.md'
        md.write_text(md.read_text(encoding='utf-8')+'\n\n**Fixture update**: review invalidation check.\n',encoding='utf-8')
        second = self.run_import()
        self.assertEqual(second['summary']['updated'],1)
        self.assertEqual(second['summary']['images_to_copy'],0)
        self.assertEqual(second['summary']['translated'],1)
        self.assertTrue(any(r['translation_status']=='needs_review' for r in self.catalog()))
        self.assertNotEqual((self.output/'hugo.toml').read_bytes(),before_config)

    def test_anomalies_and_real_hugo_preview(self):
        self.add_real('散点图', 'NCC_2026_Xu_02762-2_Fig4_g-i.png')
        broken = self.source/'地图'/'broken.md'
        broken.write_text('## Missing figure\n![missing](missing.png)\n',encoding='utf-8')
        bad = self.source/'示意图'/'bad.md'
        bad.write_text('| Broken | Source | Fig | [image](absent.png) |\n',encoding='utf-8')
        report = self.run_import()
        self.assertEqual(report['summary']['valid_records'], 3)
        self.assertGreater(report['summary']['missing_images'], 0)
        self.assertGreater(report['summary']['parse_failures'], 0)
        hugo = shutil.which('hugo') or str(Path.home()/'AppData/Local/Microsoft/WinGet/Packages/Hugo.Hugo.Extended_Microsoft.Winget.Source_8wekyb3d8bbwe/hugo.exe')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
        with (self.base/'hugo.log').open('wb') as log:
            process = subprocess.Popen([hugo,'server','--config','hugo.toml,'+str(self.output/'hugo.toml'),
                '--bind','127.0.0.1','--port',str(port),'--baseURL',f'http://localhost:{port}/',
                '--renderToMemory','--noBuildLock','--environment','development'],cwd=importer.ROOT,stdout=log,stderr=log)
            try:
                html = None
                for _ in range(150):
                    if process.poll() is not None:
                        self.fail((self.base/'hugo.log').read_text(encoding='utf-8'))
                    try:
                        html = urlopen(f'http://127.0.0.1:{port}/gallery/',timeout=1).read().decode('utf-8')
                        break
                    except OSError:
                        time.sleep(0.1)
                self.assertIsNotNone(html)
                data = re.search(r'<script id="gallery-data" type="application/json"[^>]*>(.*?)</script>',html,re.S)
                self.assertEqual(len(json.loads(data[1])), 3)
            finally:
                process.terminate(); process.wait(timeout=10)

    def test_conflicting_source_metadata_reported(self):
        md = self.source/'地图'/'地图.md'
        text = md.read_text(encoding='utf-8')
        first_line = next(line for line in text.splitlines() if line.startswith('|') and '02762-2' in line)
        replacement = first_line.replace('10.1038/s41558-026-02762-2','10.1038/s41467-026-78296-0')
        md.write_text(text.replace(first_line,replacement),encoding='utf-8')
        report = self.run_import()
        self.assertGreater(report['summary']['metadata_conflicts'], 0)
        self.assertEqual(len(self.catalog()),1)

    def test_public_build_isolation(self):
        self.run_import()
        public = json.loads((importer.ROOT/'data/gallery/public.json').read_text(encoding='utf-8'))['records']
        expected_ids = {record['id'] for record in public}
        manifest = importer.ROOT/'data/gallery/media.json'
        media = json.loads(manifest.read_text(encoding='utf-8'))['files'] if manifest.exists() else []
        expected_paths = {item['url'].removeprefix('https://chutj.github.io/') for item in media}
        hugo = shutil.which('hugo') or str(Path.home()/'AppData/Local/Microsoft/WinGet/Packages/Hugo.Hugo.Extended_Microsoft.Winget.Source_8wekyb3d8bbwe/hugo.exe')
        for name, extra in [('production', []), ('overlay', ['--config','hugo.toml,'+str(self.output/'hugo.toml'),'--environment','development'])]:
            target = self.base / ('build-'+name)
            built = subprocess.run([hugo,'build','--minify','--noBuildLock','--destination',str(target),*extra],
                cwd=importer.ROOT,capture_output=True,encoding='utf-8')
            self.assertEqual(built.returncode,0,built.stderr)
            self.assertEqual(built.stderr,'')
            html = (target/'gallery/index.html').read_text(encoding='utf-8')
            if not expected_ids:
                self.assertIn('Coming soon',html)
                self.assertNotIn('gallery-data',html)
            else:
                self.assertIn('gallery-data',html)
                for uid in expected_ids:self.assertIn(uid,html)
            for record in self.catalog():
                if record['id'] not in expected_ids:self.assertNotIn(record['id'],html)
            actual_paths = {p.relative_to(target).as_posix() for p in target.rglob('*') if p.suffix.lower() in ('.png','.jpg','.webp')}
            self.assertEqual(actual_paths,expected_paths)


if __name__ == '__main__':
    unittest.main()
