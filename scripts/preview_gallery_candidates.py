"""Build an isolated, loopback-only candidate preview; NEVER grants publication rights.

Input: ignored .gallery-local/candidates.json, prepared from reviewed evidence.
The real public dataset, allowlist, source assets and Git index are never changed.
Hugo runs in production mode in a disposable ignored snapshot. A preview-only
partial override lives exclusively in that snapshot, never in the main site.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid

from public_gallery_schema import EDITOR_FIELDS, LOCAL_TEXT, metadata_hash, validate_rights

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def validate_candidates(root=ROOT):
    manifest = read(root / '.gallery-local/candidates.json')
    catalog = {r['id']: r for r in read(root / '.gallery-local/catalog.json')['records']}
    private = (root / '.gallery-local').resolve()
    audit_path = (private / manifest['audit_path']).resolve()
    if not audit_path.is_relative_to(private):
        raise ValueError('Audit evidence must stay in the private directory')
    audit = read(audit_path)['figures']
    records = manifest['records']
    if not records or len({r['id'] for r in records}) != len(records):
        raise ValueError('Empty or duplicate candidate list')
    for record in records:
        rid = record['id']; current = catalog[rid]; evidence = audit[rid]
        if record['rights']['human_reviewed'] or record['rights']['public_use_allowed']:
            raise ValueError('Candidate must remain unapproved')
        if record['rights']['status'] != 'candidate-needs-final-confirmation':
            raise ValueError('Explicit candidate status required')
        if current['pdf_reference']['evidence_sha256'] != record['rights']['review_evidence_sha256']:
            raise ValueError('PDF/credit evidence changed; reassess candidate')
        if evidence['review_status'] != 'Likely permitted':
            raise ValueError('Unresolved/restricted records are excluded')
        if metadata_hash(record) != record['metadata_sha256']:
            raise ValueError('English candidate metadata changed after preparation')
        if hashlib.sha256(json.dumps(current, sort_keys=True, ensure_ascii=False).encode()).hexdigest() != record['catalog_sha256']:
            raise ValueError('Source catalog changed; reassess candidate')
        asset = (root / '.gallery-local/assets' / Path(current['asset']).name).resolve()
        if asset.parent != (root / '.gallery-local/assets').resolve():
            raise ValueError('Asset escaped private directory')
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        if digest != record['source_image_sha256'] or digest != evidence['source_image_sha256']:
            raise ValueError('Image bytes changed after rights assessment')
        public_text = {key: record[key] for key in EDITOR_FIELDS}
        public_text['rights'] = record['rights']
        if LOCAL_TEXT.search(json.dumps(public_text, ensure_ascii=False)):
            raise ValueError('Private paths or untranslated fields in candidate output')
        # Intentionally prove that these real candidates fail the public gate.
        try:
            validate_rights(record['rights'])
        except ValueError:
            pass
        else:
            raise ValueError('Candidate unexpectedly passed publication approval')
    return records


def prepare(root=ROOT):
    from PIL import Image
    records = validate_candidates(root)
    site = root / '.gallery-local/candidate-previews' / uuid.uuid4().hex / 'site'
    site.mkdir(parents=True)
    # Explicit source directories only; no private data, PDFs, caches or public/.
    for name in ('archetypes', 'assets', 'content', 'data', 'i18n', 'layouts'):
        source = root / name
        if source.exists():
            shutil.copytree(source, site / name)
    shutil.copy2(root / 'hugo.toml', site / 'hugo.toml')
    shutil.copytree(root / 'themes/PaperMod', site / 'themes/PaperMod',
                    ignore=shutil.ignore_patterns('.git'))
    media = site / 'static/candidate-figures'; media.mkdir(parents=True)
    output = []
    for record in records:
        digest = record['source_image_sha256']
        src = next((root / '.gallery-local/assets').glob(digest + '.*'))
        original = digest + src.suffix.lower(); shutil.copy2(src, media / original)
        variants = []
        with Image.open(src) as image:
            for width in (320, 640, 960):
                thumb = image.convert('RGB'); thumb.thumbnail((width, 4096), Image.Resampling.LANCZOS)
                filename = f'{digest}-{width}.webp'; thumb.save(media / filename, quality=85)
                variants.append((f'/candidate-figures/{filename}', thumb.width))
        clean = {key: record[key] for key in EDITOR_FIELDS}
        clean.update(rights=record['rights'], image='/candidate-figures/' + original,
                     thumbnail=variants[1][0], srcset=', '.join(f'{url} {width}w' for url, width in variants))
        output.append(clean)
    # These files exist only in the ignored snapshot, never in the real source.
    (site / 'data/gallery/candidates.json').write_text(json.dumps(output, ensure_ascii=False), encoding='utf-8')
    (site / 'layouts/_partials/gallery/public-records.html').write_text(
        '{{ return hugo.Data.gallery.candidates }}', encoding='utf-8')
    (site / 'candidate.toml').write_text('[params]\ngalleryCandidatePreview = true\n', encoding='utf-8')
    return site


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--hugo', required=False)
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--port', type=int, default=1316)
    args = parser.parse_args()
    records = validate_candidates()
    if args.dry_run:
        print(json.dumps({'candidates': len(records), 'approved': 0, 'writes': 'none',
                          'planned_output': '.gallery-local/candidate-previews/<unique>/site'}, indent=2))
        return
    site = prepare()
    hugo = args.hugo or shutil.which('hugo')
    if not hugo:
        raise SystemExit('Pass --hugo with the verified Hugo executable path')
    output = site.parent / 'output'
    command = [hugo, 'build', '--environment', 'production', '--config', 'hugo.toml,candidate.toml',
               '--destination', str(output), '--noBuildLock', '--minify']
    result = subprocess.run(command, cwd=site, capture_output=True, text=True, encoding='utf-8')
    print(result.stdout); print(result.stderr)
    if result.returncode or 'WARN' in result.stderr or 'WARN' in result.stdout:
        raise SystemExit('Candidate build failed or warned')
    html = (output / 'gallery/index.html').read_text(encoding='utf-8')
    for forbidden in ('.gallery-local', 'gallery-private/', 'file://', 'C:\\', 'D:\\'):
        if forbidden in html:
            raise SystemExit('Private location in output')
    if list(output.rglob('*.pdf')):
        raise SystemExit('PDF in candidate output')
    expected = {r['id'] for r in records}
    for record in read(ROOT / '.gallery-local/catalog.json')['records']:
        if record['id'] not in expected and record['id'] in html:
            raise SystemExit('Nonselected record leaked into preview')
    report = {'candidate_count': len(records), 'approved_count': 0, 'environment': 'production',
              'site': str(site), 'output': str(output), 'publication': 'not approved; loopback preview only'}
    report_dir = ROOT / '.gallery-local/step22'; report_dir.mkdir(exist_ok=True)
    (report_dir / 'preview-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    if args.serve:
        subprocess.run([hugo, 'server', '--environment', 'production', '--config', 'hugo.toml,candidate.toml',
                        '--bind', '127.0.0.1', '--port', str(args.port), '--baseURL', f'http://localhost:{args.port}/',
                        '--renderToMemory', '--noBuildLock', '--disableFastRender'], cwd=site, check=True)


if __name__ == '__main__':
    main()
