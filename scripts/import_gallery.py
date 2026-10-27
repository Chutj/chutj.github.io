"""Incrementally scan a read-only FIG library into an ignored local Hugo overlay."""
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import json
import os
import re
import uuid
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image
from gallery_schema import CATEGORY_LABELS

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.gallery-local'
DEFAULT_SOURCE = Path.home() / 'WorkBuddy/LiteraturePush/绘图参考'
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.tif', '.tiff', '.bmp', '.svg', '.avif', '.heic'}
DOI = re.compile(r'10\.\d{4,9}/[-._;/:A-Za-z0-9]+')
CJK = re.compile(r'[\u3400-\u9fff]')
FIELD_ALIASES = {
    'What the figure shows': ['表示什么'],
    'Statistics & symbols': ['统计与符号', '必要的统计与符号', '必要的样本与符号说明', '必要的定义', '空间尺度与统计单元'],
    'Color & encoding': ['配色与编码', '配色与图例', '配色与来源', '配色策略', '取色来源'],
    'Design lessons': ['值得学习', '值得学习（含用户观察）', '排版与值得学习', '值得学习（用户重点：配色）', '排版与表达技巧'],
    'Verification & limitations': ['核查说明', '核查状态', '核查材料', '解释与仿绘边界', '地图与仿绘边界', '素材性质与复用边界', '原文标注差异'],
}
TYPE_CATEGORIES = ['SHAP图', '示意图', '地图', '模型评估图', '散点图',
    '折线图_曲线图_时间序列', '柱状图_条形图', '直方图', '构成图', '极坐标图',
    '箱线图_小提琴图_雨云图', '热力图_矩阵图', '密度图_山脊图_累积分布',
    '误差棒_区间图_森林图', '气泡图', '等值线图_响应面图', '路径图_网络图',
    '流程图_研究框架图', '桑基图_弦图']
OVERLAY = '''# Private resources are assets, never static files.
[params]
galleryLocalPreview = true
galleryCatalog = '.gallery-local/catalog.json'
galleryRevision = 'CATALOG_REVISION'
[[module.mounts]]
source = 'assets'
target = 'assets'
[[module.mounts]]
source = '.gallery-local/assets'
target = 'assets/gallery-private'
'''


def serialized(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def load_json(path, default):
    value = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default
    if not isinstance(value, type(default)):
        raise ValueError(f'Invalid JSON structure in {path.name}')
    return value


def local_path(directory, raw, source):
    """Accept only relative library links, with Windows traversal containment."""
    raw = unquote(raw.strip().strip('<>'))
    if urlsplit(raw).scheme or raw.startswith(('/', '\\')) or '\\' in raw:
        raise ValueError('Not a local relative image link')
    path = (directory / raw.split('#', 1)[0]).resolve()
    if not path.is_relative_to(source):
        raise ValueError('Image link escapes the source library')
    return path


def issue(issues, code, path, detail):
    issues.append(dict(code=code, path=str(path), detail=detail))


def fields_of(block):
    # Preserve arbitrary additional fields and multiline content in raw metadata.
    return {m[0].strip(): m[1].strip() for m in re.findall(
        r'(?ms)^\*\*([^*]+)\*\*[ \t]*(?:[：:]|\u3000)[ \t]*(.*?)(?=^\*\*[^*]+\*\*[ \t]*(?:[：:]|\u3000)|\Z)', block)}


def canonical_figure(value):
    return re.sub(r'[^a-z0-9]+', '', value.lower())


def english_figure(value):
    value = value.replace('完整_用户图', 'Full figure (user-provided)').replace('完整', 'Full figure').replace('用户图', 'User-provided image')
    if CJK.search(value):
        figure = re.search(r'Fig\.?\s*\d+', value, re.I)
        return (figure[0] if figure else 'Figure') + ' (panel label pending translation)'
    return value


def scan(source, labels):
    issues, papers = [], {}
    registry = source / '论文来源与核查状态.md'
    try:
        registry_text = registry.read_text(encoding='utf-8-sig')
        for line in registry_text.splitlines():
            cells = [c.strip() for c in re.split(r'(?<!\\)\|', line.strip('|'))]
            if len(cells) < 3 or not cells[2].startswith('10.'):
                continue
            match = re.search(r'\[([^]]+)\]\((https://[^)]+)\)', cells[1])
            doi = DOI.search(cells[2])
            if match and doi:
                value = dict(author=cells[0], paper=match[1], source=match[2])
                key = doi[0].lower()
                if key in papers and papers[key] != value:
                    issue(issues, 'registry_conflict', registry.name, key)
                    papers[key] = None
                else:
                    papers[key] = value
    except (OSError, UnicodeError) as exc:
        issue(issues, 'registry_unreadable', registry.name, str(exc))
    # New FIG batches keep paper identities in the existing PDF registry.
    # Use explicit, unambiguous metadata only; this grants no publication rights.
    fallback = defaultdict(list)
    pdf_registry = source / 'PDF原文' / 'sources.json'
    if pdf_registry.is_file():
        try:
            entries = load_json(pdf_registry, [])
            for entry in entries:
                doi = str(entry.get('doi', '')).lower()
                title = str(entry.get('title', '')).strip()
                author = str(entry.get('first_author', '')).strip()
                if DOI.fullmatch(doi) and title and author:
                    fallback[doi].append(dict(author=author, paper=title, source='https://doi.org/'+doi))
            for doi, values in fallback.items():
                if doi in papers:
                    continue
                if len({(v['author'], v['paper']) for v in values}) == 1:
                    papers[doi] = values[0]
                else:
                    issue(issues, 'pdf_registry_conflict', pdf_registry.name, doi)
        except (OSError, UnicodeError, ValueError, AttributeError) as exc:
            issue(issues, 'pdf_registry_unreadable', pdf_registry.name, str(exc))
    folders = sorted(p for p in source.iterdir() if p.is_dir()
        and not p.name.startswith(('_', '.')) and p.name != 'PDF原文')
    images, notes = {}, defaultdict(list)
    markdown_count = associations = 0
    for folder in folders:
        category = folder.name
        if category not in labels:
            labels[category] = category if not CJK.search(category) else 'Source category ' + sha(category.encode())[:8]
            issue(issues, 'category_translation_pending', category, 'Add an English label in category-labels.json')
        for image in sorted(folder.iterdir()):
            if not image.is_file() or image.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            associations += 1
            if not image.resolve().is_relative_to(source):
                issue(issues, 'unsafe_image_path', image.name, 'Skipped symlink outside source')
                continue
            try:
                image_bytes = image.read_bytes()
                image_sha = sha(image_bytes)
                with Image.open(image) as opened:
                    width, height = opened.size
                    extension = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}.get(opened.format)
                    opened.verify()
                if not extension:
                    raise ValueError('Unsupported actual image format')
                images[image.resolve()] = dict(path=image, image_sha256=image_sha, width=width,
                    height=height, extension=extension, category=category)
            except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
                issue(issues, 'unreadable_image', image.relative_to(source), str(exc))
        for md in sorted(folder.glob('*.md')):
            markdown_count += 1
            if not md.resolve().is_relative_to(source):
                issue(issues, 'unsafe_markdown_path', md.name, 'Skipped symlink outside source')
                continue
            try:
                body = md.read_text(encoding='utf-8-sig')
                rows = defaultdict(list)
                for line in body.splitlines():
                    if not line.startswith('|'):
                        continue
                    cells = [c.strip() for c in re.split(r'(?<!\\)\|', line.strip('|'))]
                    if len(cells) < 4:
                        continue
                    for link in re.findall(r'\[[^]]*\]\(([^)]+)\)', cells[-1]):
                        try:
                            path = local_path(folder, link, source)
                            if path.suffix.lower() in IMAGE_EXTENSIONS:
                                rows[path].append(cells)
                                if not path.exists():
                                    issue(issues, 'missing_image', md.relative_to(source), unquote(link))
                        except ValueError as exc:
                            issue(issues, 'unsafe_image_path', md.relative_to(source), str(exc))
                blocks = re.split(r'(?m)^##\s+', body)[1:]
                if not blocks and (rows or re.search(r'!\[[^]]*\]\(', body)):
                    issue(issues, 'unparsed_markdown', md.relative_to(source), 'No per-figure level-two sections')
                for block in blocks:
                    embedded = re.findall(r'!\[[^]]*\]\(([^)]+)\)', block)
                    if not embedded:
                        continue
                    for link in embedded:
                        try:
                            image = local_path(folder, link, source)
                            if image.suffix.lower() not in IMAGE_EXTENSIONS:
                                continue
                            if image not in images:
                                issue(issues, 'unavailable_image' if image.exists() else 'missing_image', md.relative_to(source), unquote(link))
                                continue
                            table = rows.get(image, [])
                            if len(table) != 1:
                                issue(issues, 'metadata_row_missing_or_ambiguous', md.relative_to(source), image.name)
                                continue
                            cells = table[0]
                            row_dois = {d.lower().rstrip('.,;') for d in DOI.findall(cells[1])}
                            fields = fields_of(block)
                            paper_dois = {d.lower().rstrip('.,;') for d in DOI.findall(fields.get('论文', fields.get('来源', '')))}
                            if not fields or len(row_dois) != 1 or (paper_dois and paper_dois != row_dois):
                                issue(issues, 'metadata_conflict', md.relative_to(source), image.name)
                                continue
                            doi = next(iter(row_dois))
                            journal = cells[1].split('·', 1)[0].strip()
                            figure = cells[2]
                            normalized = '## ' + block.strip()
                            notes[image].append(dict(category=category, filename=image.name,
                                path=str(md.relative_to(source)), title=block.splitlines()[0].strip(),
                                doi=doi, journal=journal, figure=figure, fields=fields,
                                markdown=normalized, note_sha256=sha(normalized.encode('utf-8'))))
                        except ValueError as exc:
                            issue(issues, 'unsafe_image_path', md.relative_to(source), str(exc))
            except (OSError, UnicodeError) as exc:
                issue(issues, 'unparsed_markdown', md.relative_to(source), str(exc))
    grouped = defaultdict(list)
    filenames = defaultdict(set)
    for path, image in images.items():
        grouped[image['image_sha256']].append(image)
        filenames[path.name].add(image['image_sha256'])
    for filename, hashes in filenames.items():
        if len(hashes) > 1:
            issue(issues, 'filename_content_conflict', filename, 'Different bytes share a source filename; records quarantined')
    candidates = []
    for image_sha, copies in sorted(grouped.items()):
        variants = [note for copy in copies for note in notes[copy['path'].resolve()]]
        if any(len(filenames[c['path'].name]) > 1 for c in copies):
            continue
        if not variants:
            issue(issues, 'description_missing', copies[0]['path'].relative_to(source), 'No reliably parsed description; excluded from Gallery')
            continue
        identities = {(v['doi'], canonical_figure(v['figure'])) for v in variants}
        journals = {v['journal'].casefold() for v in variants}
        if len(identities) != 1 or len(journals) != 1:
            issue(issues, 'cross_category_metadata_conflict', copies[0]['path'].name, 'DOI/figure/journal disagree; record quarantined')
            continue
        doi, figure_key = next(iter(identities))
        paper = papers.get(doi)
        if paper is None:
            issue(issues, 'paper_source_missing_or_conflicting', copies[0]['path'].name, doi)
            continue
        years = {int(m[1]) for c in copies if (m := re.search(r'_(\d{4})_', c['path'].name))}
        if len(years) != 1:
            issue(issues, 'year_missing_or_conflicting', copies[0]['path'].name, 'No unique source filename year')
            continue
        categories = sorted({c['category'] for c in copies})
        candidates.append(dict(image_sha256=image_sha, image=copies[0], copies=copies,
            variants=sorted(variants, key=lambda v: (v['path'], v['filename'])),
            identity=doi+'|'+figure_key, doi=doi, year=next(iter(years)),
            categories=categories, **paper))
    issues = list({(i['code'],i['path'],i['detail']): i for i in issues}.values())
    return candidates, issues, dict(category_folders=len(folders), markdown_files=markdown_count,
        image_associations=associations, unique_image_contents=len(grouped),
        cross_category_copies=max(0, len(images)-len(grouped)))


def check_safety(output, source):
    import subprocess
    output = output.resolve()
    if not output.is_relative_to(LOCAL.resolve()) or output == source or source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError('Output must be inside .gallery-local and disjoint from the read-only source')
    forbidden = ('.gallery-local/', 'public/', 'resources/_gen/', 'assets/gallery-private/', 'static/gallery-private/')
    tracked = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z']).decode().split('\0')
    leaks = [p for p in tracked if p.startswith(forbidden)]
    if leaks:
        raise ValueError('Private/generated files already tracked by Git: '+', '.join(leaks))
    probe = str((output / 'catalog.json').relative_to(ROOT)).replace('\\', '/')
    result = subprocess.run(['git', '-C', str(ROOT), 'check-ignore', '--no-index', '--quiet', probe])
    if result.returncode != 0:
        raise ValueError('Output is not protected by actual Git ignore rules')


def atomic_write(path, content):
    if path.exists() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    with temporary.open('xb') as stream:
        stream.write(content)
    os.replace(temporary, path)
    return True


def run(source, output=LOCAL, dry_run=False):
    source, output = source.resolve(strict=True), output.resolve()
    check_safety(output, source)
    settings = load_json(output / 'settings.json', {})
    labels = dict(CATEGORY_LABELS, **load_json(output / 'category-labels.json', {}))
    translations = load_json(output / 'english.json', {})
    state_path = output / 'state.json'
    previous = load_json(state_path, dict(schema_version=2, records={}))
    if previous.get('schema_version') != 2:
        raise ValueError('Unsupported state schema; migration must be explicit')
    old = previous['records']
    # Migration only: reuse the reviewed primary description from the former sample.
    legacy = {v['filename']: v for v in load_json(output / 'provenance.json', [])}
    if not state_path.exists():
        # Preserve the first prototype's IDs during the one-time state migration.
        for record in load_json(output / 'catalog.json', {'records': []}).get('records', []):
            prior = next((v for name,v in legacy.items() if Path(name).stem == record.get('id')), None)
            if prior:
                old[record['id']] = dict(identity=record['doi'].lower()+'|'+canonical_figure(record['figure']),
                    image_sha256=prior['image_sha256'], canonical_note=prior['source_note'], source_status='active')
    candidates, issues, summary = scan(source, labels)
    if not summary['category_folders'] or any(i['code'] in ('registry_unreadable','registry_conflict') for i in issues):
        raise ValueError('Source folder or paper registry is not safe to import; existing output preserved')
    by_hash, by_identity, by_path = defaultdict(list), defaultdict(list), defaultdict(list)
    for uid, value in old.items():
        by_hash[value['image_sha256']].append(uid)
        by_identity[value['identity']].append(uid)
        for path in value.get('source_files', []):
            by_path[path].append(uid)
    identity_counts = defaultdict(int)
    for c in candidates:
        identity_counts[c['identity']] += 1
    records, inventory, next_state, plans, claimed = [], [], {}, {}, set()
    record_actions = {}
    asset_copies = []
    added = updated = unchanged = 0
    for candidate in candidates:
        key, image_sha = candidate['identity'], candidate['image_sha256']
        exact = by_hash.get(image_sha, [])
        source_files = sorted(str(c['path'].relative_to(source)) for c in candidate['copies'])
        path_matches = {uid for path in source_files for uid in by_path.get(path, []) if old[uid]['identity'] == key}
        path_match = sorted(path_matches) if len(path_matches) == 1 else []
        identity_match = by_identity.get(key, []) if identity_counts[key] == 1 else []
        uid = (exact or path_match or (identity_match if len(identity_match) == 1 else []) or [None])[0]
        if uid is None:
            stable_key = key if identity_counts[key] == 1 else key+'|'+image_sha
            uid = 'fig-' + uuid.uuid5(uuid.NAMESPACE_URL, 'fig-local:'+stable_key).hex
        if uid in claimed:
            issue(issues, 'ambiguous_identity', uid, 'Multiple source images match one existing record; skipped')
            continue
        claimed.add(uid)
        variants = candidate['variants']
        previous_record = old.get(uid, {})
        preferred = previous_record.get('canonical_note', '').replace('\\','/')
        canonical = next((v for v in variants if v['path'].replace('\\','/') == preferred), None)
        if canonical is None:
            canonical = next((v for v in variants if legacy.get(v['filename'], {}).get('source_note', '').replace('\\','/') == v['path'].replace('\\','/')), variants[0])
        # Prefer an actual figure-type folder to a cross-cutting design folder.
        # Every displayed category still comes from the source's memberships.
        if canonical['category'] not in TYPE_CATEGORIES:
            typed = [v for v in variants if v['category'] in TYPE_CATEGORIES]
            if typed:
                canonical = min(typed, key=lambda v: (TYPE_CATEGORIES.index(v['category']), v['path']))
        translation = translations.get(uid, translations.get(canonical['filename'], {}))
        reviewed = translation.get('note_sha256') == canonical['note_sha256'] and bool(translation.get('title'))
        if reviewed and CJK.search(json.dumps(translation, ensure_ascii=False)):
            issue(issues, 'non_english_translation', uid, 'Translation contains Chinese text; using English source metadata')
            reviewed = False
        translation_status = 'reviewed' if reviewed else ('needs_review' if translation else 'pending')
        if not reviewed:
            issue(issues, 'translation_pending', uid, 'Original metadata retained privately; English description requires review')
        english_sections = translation.get('sections', {}) if reviewed else {}
        sections = {label: english_sections.get(label) or 'English translation pending review. Original notes are retained in the local inventory.' for label in FIELD_ALIASES}
        asset_name = image_sha + candidate['image']['extension']
        rights = previous_record.get('rights', dict(status='unverified', public_use_allowed=False,
            license=None, license_url=None, attribution=None, evidence=None, approved_by=None, approved_at=None))
        # An image replacement always invalidates any future rights decision.
        if previous_record and (previous_record['image_sha256'] != image_sha or previous_record['identity'] != key):
            rights = dict(status='unverified', public_use_allowed=False, license=None,
                license_url=None, attribution=None, evidence=None, approved_by=None, approved_at=None)
        figure_label = english_figure(canonical['figure'])
        raw_colors = ' '.join(canonical['fields'].get(k, '') for k in FIELD_ALIASES['Color & encoding'])
        colors = dict(hex_values=sorted(set(re.findall(r'#[a-fA-F0-9]{6}\b|#[a-fA-F0-9]{3}\b', raw_colors))), verification='see_source_notes')
        display = dict(id=uid, primary=labels[canonical['category']],
            categories=[labels[v] for v in candidate['categories']],
            title=translation['title'] if reviewed else figure_label+' — '+candidate['paper'],
            journal=canonical['journal'], year=candidate['year'], doi=candidate['doi'],
            figure=figure_label, paper=candidate['paper'],
            author=(translation.get('author') or candidate['author']) if reviewed else candidate['author'],
            source=candidate['source'], sections=sections, translation_status=translation_status,
            asset='gallery-private/'+asset_name, width=candidate['image']['width'],
            height=candidate['image']['height'], rights=rights, colors=colors)
        raw = dict(id=uid, identity=key, image_sha256=image_sha, width=display['width'], height=display['height'],
            source_files=source_files,
            categories=candidate['categories'], canonical_note=canonical['path'],
            raw_title=canonical['title'], raw_fields=canonical['fields'],
            canonical_sections={name:{k:canonical['fields'][k] for k in aliases if k in canonical['fields']} for name,aliases in FIELD_ALIASES.items()},
            variants=variants, doi=candidate['doi'], journal=canonical['journal'], year=candidate['year'],
            figure=canonical['figure'], paper=candidate['paper'], author=candidate['author'], rights=rights,
            translation_status=translation_status, colors=colors,
            storage=dict(provider='local', object_key=None, public_url=None, approved_to_upload=False))
        fingerprint = sha(serialized(dict(raw=raw, display=display)))
        value = dict(identity=key, image_sha256=image_sha, canonical_note=canonical['path'],
            fingerprint=fingerprint, rights=rights, source_status='active', source_files=source_files)
        if uid not in old:
            added += 1
            record_actions[uid] = 'new'
        elif old[uid].get('fingerprint') != fingerprint or old[uid].get('source_status') != 'active':
            updated += 1
            record_actions[uid] = 'updated'
        else:
            unchanged += 1
            record_actions[uid] = 'unchanged'
        next_state[uid] = value
        records.append(display); inventory.append(raw)
        asset_path = output / 'assets' / asset_name
        if not asset_path.resolve().is_relative_to(output):
            raise ValueError('Private asset path escapes output through a symlink')
        if not asset_path.exists() or sha(asset_path.read_bytes()) != image_sha:
            asset_copies.append((candidate['image']['path'], asset_path, image_sha))
    inactive = 0
    for uid, value in old.items():
        if uid not in next_state:
            next_state[uid] = dict(value, source_status='missing_or_quarantined')
            if value.get('source_status') == 'active':
                inactive += 1
    records.sort(key=lambda r: r['id'])
    inventory.sort(key=lambda r: r['id'])
    next_state = dict(schema_version=2, records=next_state)
    # Extend the same private snapshot; no separate card list or public export.
    # Import lazily so public CI does not need PDF/image parsing dependencies.
    from pdf_gallery import build as build_pdf_review
    pdf_payloads, pdf_summary = build_pdf_review(source, output,
        dict(schema_version=2, records=records), dict(schema_version=2, records=inventory), next_state)
    records = json.loads(pdf_payloads[output/'catalog.json'])['records']
    inventory = json.loads(pdf_payloads[output/'inventory.json'])['records']
    next_state = json.loads(pdf_payloads[state_path])
    # Compare final enriched records, including evidence invalidation, rather
    # than the intermediate pre-PDF representation.
    added = updated = unchanged = 0
    raw_by_id = {r['id']:r for r in inventory}
    for record in records:
        uid = record['id']
        fingerprint = sha(serialized(dict(raw=raw_by_id[uid],display=record)))
        next_state['records'][uid]['fingerprint'] = fingerprint
        action = ('new' if uid not in old else 'updated' if
            old[uid].get('fingerprint') != fingerprint or old[uid].get('source_status') != 'active' else 'unchanged')
        record_actions[uid] = action
        added += action == 'new'; updated += action == 'updated'; unchanged += action == 'unchanged'
    payloads = {
        output / 'catalog.json': serialized(dict(schema_version=2, records=records)),
        output / 'inventory.json': serialized(dict(schema_version=2, records=inventory)),
        state_path: serialized(next_state),
        output / 'hugo.toml': OVERLAY.replace("source = '.gallery-local/assets'", 'source = '+json.dumps((output/'assets').relative_to(ROOT).as_posix())).replace("galleryCatalog = '.gallery-local/catalog.json'", 'galleryCatalog = '+json.dumps((output/'catalog.json').relative_to(ROOT).as_posix())).replace('CATALOG_REVISION', sha(serialized(dict(schema_version=2, records=records)))).encode(),
        output / 'settings.json': serialized(dict(settings, source=str(source))),
    }
    payloads.update({p:b for p,b in pdf_payloads.items() if p not in
        (output/'catalog.json',output/'inventory.json',state_path)})
    if any(not path.resolve().is_relative_to(output) for path in [*payloads, output/'last-report.json']):
        raise ValueError('Generated data path escapes output through a symlink')
    for path, content in payloads.items():
        if not path.exists() or path.read_bytes() != content:
            plans[str(path.relative_to(ROOT))] = 'update' if path.exists() else 'create'
    for _, path, _ in asset_copies:
        plans[str(path.relative_to(ROOT))] = 'update' if path.exists() else 'create'
    summary.update(checked_records=summary['unique_image_contents'], valid_records=len(records),
        added=added, updated=updated, unchanged=unchanged, inactive=inactive,
        images_to_copy=len(asset_copies), translated=sum(r['translation_status']=='reviewed' for r in records),
        translation_pending=sum(r['translation_status']!='reviewed' for r in records), issues=len(issues))
    summary.update(missing_images=sum(i['code']=='missing_image' for i in issues),
        parse_failures=sum(i['code'] in ('unparsed_markdown','metadata_row_missing_or_ambiguous','description_missing') for i in issues),
        metadata_conflicts=sum('conflict' in i['code'] for i in issues))
    summary['pdf_review'] = pdf_summary
    report = dict(schema_version=2, dry_run=dry_run, source=str(source), summary=summary,
        report_file=str((output/'last-report.json').relative_to(ROOT)),
        files=plans, diagnostics=issues, records=[dict(id=r['id'],title=r['title'], action=record_actions[r['id']]) for r in records])
    if dry_run:
        return report
    from pdf_gallery import verify_sources
    verify_sources(source, pdf_payloads, output)
    for source_file, destination, expected in asset_copies:
        content = source_file.read_bytes()
        if sha(content) != expected:
            raise RuntimeError('Source image changed while importing; rerun after FIG finishes writing')
        atomic_write(destination, content)
    # Publish catalog atomically, then update the watched local config to trigger
    # a Hugo rebuild even for metadata-only changes (no asset files changed).
    catalog_path = output/'catalog.json'
    for path, content in payloads.items():
        if path not in (catalog_path, output/'hugo.toml'):
            atomic_write(path, content)
    atomic_write(catalog_path, payloads[catalog_path])
    atomic_write(output/'hugo.toml', payloads[output/'hugo.toml'])
    report_path = output/'last-report.json'
    atomic_write(report_path, serialized(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Defaults to saved settings, then the linked FIG library')
    parser.add_argument('--output', type=Path, default=LOCAL, help='Must remain inside .gallery-local')
    parser.add_argument('--dry-run', action='store_true', help='Read-only plan; writes no files')
    parser.add_argument('--json', action='store_true', help='Print the full plan and diagnostics')
    args = parser.parse_args()
    try:
        settings = load_json(args.output/'settings.json', {})
        source = args.source or Path(settings.get('source', DEFAULT_SOURCE))
        report = run(source, args.output, args.dry_run)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            s = report['summary']
            print(('DRY RUN' if args.dry_run else 'UPDATED')+f": checked {s['checked_records']}, valid {s['valid_records']}; new {s['added']}, changed {s['updated']}, unchanged {s['unchanged']}, inactive {s['inactive']}; copy {s['images_to_copy']} images.")
            print(f"Cross-category copies deduplicated: {s['cross_category_copies']}; diagnostics: {s['issues']}; English reviewed/pending: {s['translated']}/{s['translation_pending']}.")
            print(f"Missing images: {s['missing_images']}; parse failures: {s['parse_failures']}; metadata conflicts: {s['metadata_conflicts']}.")
            for path, action in list(report['files'].items())[:8]:
                print(f'  {action}: {path}')
            if len(report['files']) > 8:
                print(f"  ... {len(report['files'])-8} more files; use --dry-run --json for the full plan.")
            print('Diagnostics: '+('use --dry-run --json (no files written)' if args.dry_run else str(args.output/'last-report.json')))
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        print(f'STOP: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
