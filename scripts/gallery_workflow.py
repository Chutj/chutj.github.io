"""Prepare a private update batch, or publish an explicitly approved pinned batch.

This orchestrates existing import, PDF, export and clean-build gates. It does not
infer permission from a license name. Reports and approval inputs stay private.
"""
import argparse
import copy
import datetime as dt
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import uuid
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import import_gallery as importer
import export_public_gallery as exporter
from public_gallery_schema import APPROVAL_FIELDS, validate_dataset

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = importer.IMAGE_EXTENSIONS | {'.md', '.pdf', '.json'}
HUGO = shutil.which('hugo') or str(Path.home() / 'AppData/Local/Microsoft/WinGet/Packages/Hugo.Hugo.Extended_Microsoft.Winget.Source_8wekyb3d8bbwe/hugo.exe')


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode('utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def load(path, default=None):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default


def save(path, value):
    importer.atomic_write(path, encoded(value))


def run(args, root=ROOT):
    result = subprocess.run([str(a) for a in args], cwd=root, capture_output=True,
                            encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError('Command failed: '+' '.join(map(str, args))+'\n'+result.stdout+result.stderr)
    return result.stdout.strip()


def observe(source):
    """Hash real inputs, not mtimes; reject links and never write to FIG."""
    source = source.resolve()
    if not source.is_dir():
        raise ValueError('FIG source is unavailable')
    files = {}
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise ValueError('Source symlink requires manual investigation: '+str(path))
        if path.is_file() and path.suffix.lower() in EXTENSIONS:
            files[path.relative_to(source).as_posix()] = digest(path.read_bytes())
    return files


def differences(before, after):
    return {action: sorted(k for k in keys if predicate(k)) for action, keys, predicate in (
        ('added', after, lambda k: k not in before),
        ('modified', after, lambda k: k in before and before[k] != after[k]),
        ('removed', before, lambda k: k not in after))}


def git_changes(root):
    names = set(filter(None, run(['git', 'ls-files', '--others', '--exclude-standard', '-z'], root).split('\0')))
    names.update(filter(None, run(['git', 'diff', 'HEAD', '--name-only', '-z'], root).split('\0')))
    result = {}
    for name in sorted(names):
        path = root/name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError('Changed submodule/symlink requires separate review: '+name)
        result[name] = digest(path.read_bytes()) if path.exists() else None
    return result


def private_path(root, path):
    path = Path(path).resolve()
    if not path.is_relative_to((root/'.gallery-local').resolve()):
        raise ValueError('Batch and approvals must remain under .gallery-local')
    return path


def scan_changes(root, changes):
    """Inspect actual candidate bytes, not just ignore rules or file names."""
    secret = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}')
    for name in changes:
        path = root/name
        if (name.startswith(('.gallery-local/', 'public/', 'resources/')) or
                path.suffix.lower() in ('.pdf', '.pem', '.key') or path.name.startswith('.env')):
            raise ValueError('Private/generated candidate file: '+name)
        if path.is_file() and secret.search(path.read_bytes()):
            raise ValueError('Possible credential in candidate: '+name)


def deployment_status(commit, wait=False):
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('A full commit SHA is required')
    def get(url):
        request = Request(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'Figure-Gallery-Workflow'})
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    last = {}
    for attempt in range(7 if wait else 1):
        runs = get('https://api.github.com/repos/Chutj/chutj.github.io/actions/workflows/hugo.yaml/runs?head_sha='+commit)['workflow_runs']
        last = dict(commit=commit, runs=[dict(id=r['id'], status=r['status'], conclusion=r['conclusion'], url=r['html_url']) for r in runs])
        if runs and runs[0]['status'] == 'completed':
            last['jobs'] = [dict(name=j['name'], conclusion=j['conclusion']) for j in get(runs[0]['jobs_url'])['jobs']]
            return last
        if wait and attempt < 6:
            print('Waiting for GitHub Actions for '+commit[:12], flush=True)
            time.sleep(5)
    return last


def proposals(root):
    """Reviewed proposals use the exporter's existing publication-variant shape."""
    entries = load(root/'.gallery-local/release-proposals.json', {'records': []})['records']
    ids = [entry['record']['id'] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate release proposal ID')
    return entries


def review_inputs(root):
    """Pin local review inputs too; a changed official evidence file needs refresh."""
    local = root/'.gallery-local'
    names = {'official-evidence.json', 'english.json', 'release-proposals.json', 'publication-records.json'}
    entries = proposals(root)+load(local/'publication-records.json', {'records': []})['records']
    for entry in entries:
        names.update((entry['asset'], entry['evidence_file']))
    result = {}
    for name in sorted(names):
        path = (local/name).resolve()
        if not path.is_relative_to(local.resolve()) or path.is_symlink():
            raise ValueError('Unsafe private review input')
        result[name] = digest(path.read_bytes()) if path.is_file() else None
    return result


def approved_entry(entry, reviewer, date):
    result = copy.deepcopy(entry)
    result['record']['rights'].update(status='approved', public_use_allowed=True,
        human_reviewed=True, approved_by=reviewer, approved_at=date)
    return result


def validation_context(root):
    """One immutable local snapshot per batch, avoiding repeated large JSON parses."""
    local = root/'.gallery-local'
    content = {name: (local/name).read_bytes() for name in ('catalog.json', 'inventory.json')}
    return dict(content=content, **{name[:-5]: {r['id']: r for r in json.loads(data)['records']}
                                    for name, data in content.items()})


def verify_validation_context(root, context):
    for name, content in context['content'].items():
        if (root/'.gallery-local'/name).read_bytes() != content:
            raise ValueError('Local library changed during batch validation; prepare/review again')


def validate_entry(root, entry, policy, context=None):
    context = context or validation_context(root)
    catalog = context['catalog']; inventory = context['inventory']
    record = entry['record']
    approval = {k: record[k] for k in APPROVAL_FIELDS}
    exporter.prepared_record(root, entry, approval, catalog, inventory)
    validate_dataset({'schema_version': 1, 'records': [record]},
        dict(schema_version=1, image_hosts=policy['image_hosts'], approved_records=[approval]))


def retain_editorial_overlays(root, old_catalog, old_inventory, valid_public):
    """Keep prior manual edits only when all source/evidence bindings are identical.

    Historical direct edits may predate publication variants. The low-level
    importer regenerates its catalog; do not silently discard those edits or
    grant rights to another version while integrating that importer.
    """
    local = root/'.gallery-local'
    catalog = load(local/'catalog.json'); inventory = load(local/'inventory.json')
    raw = {r['id']: r for r in inventory['records']}
    retained = []
    for record in catalog['records']:
        uid = record['id']; old = old_catalog.get(uid); previous = old_inventory.get(uid)
        if not old or not previous or old.get('translation_status') != 'reviewed':
            continue
        old_raw = {k: v for k, v in previous.items() if k != 'rights'}
        new_raw = {k: v for k, v in raw[uid].items() if k != 'rights'}
        if old_raw != new_raw or old.get('pdf_reference') != record.get('pdf_reference'):
            continue
        changed = False
        for key in ('title', 'author', 'source', 'sections', 'translation_status'):
            if record.get(key) != old.get(key):
                record[key] = copy.deepcopy(old[key]); changed = True
        if uid in valid_public and record['rights'] != old['rights']:
            record['rights'] = copy.deepcopy(old['rights'])
            raw[uid]['rights'] = copy.deepcopy(previous['rights']); changed = True
        if changed:
            retained.append(uid)
    if retained:
        save(local/'inventory.json', inventory)
        save(local/'catalog.json', catalog)
        config = local/'hugo.toml'
        config.write_text(re.sub(r"galleryRevision = '[^']*'", "galleryRevision = '"+digest(encoded(catalog))+"'",
            config.read_text(encoding='utf-8')), encoding='utf-8')
    return retained


def prepare(source=None, dry_run=False, root=ROOT):
    local = root/'.gallery-local'
    source = Path(source or load(local/'settings.json', {}).get('source', importer.DEFAULT_SOURCE)).resolve()
    before = observe(source)
    previous = load(local/'workflow-source.json', {})
    plan = importer.run(source, local, True)
    delta = differences(previous, before)
    if dry_run:
        return dict(mode='prepare-dry-run', source_changes=delta, importer=plan, writes=False)
    old_catalog = {r['id']: r for r in load(local/'catalog.json', {'records': []})['records']}
    old_inventory = {r['id']: r for r in load(local/'inventory.json', {'records': []})['records']}
    old_public, _ = exporter.plan(root)
    valid_public = {r['id'] for r in old_public['records']}
    # Keep byte-for-byte pre-import snapshots without copying the whole image/PDF cache.
    backup = local/'updates/backups'/uuid.uuid4().hex
    for name in plan['files']:
        path = root/name
        if path.is_file():
            target = backup/path.relative_to(local)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    result = importer.run(source, local, False)
    retained = retain_editorial_overlays(root, old_catalog, old_inventory, valid_public)
    if observe(source) != before:
        raise ValueError('FIG changed during prepare; no release batch created. Rerun after FIG finishes writing.')
    policy = load(root/'data/gallery/allowlist.json')
    _, rejected = exporter.plan(root)
    public = {r['id'] for r in policy['approved_records']}
    published_sources = set(public)
    for entry in load(local/'publication-records.json', {'records': []})['records']:
        if entry['record']['id'] in public:
            published_sources.update(b['id'] for b in entry['bindings'])
    review = load(local/'pdf-review.json', {'figures': {}})['figures']
    ready, proposal_errors = [], []
    context = validation_context(root)
    for entry in proposals(root):
        try:
            # Probe a copy only. This is schema/byte validation, NOT human approval.
            validate_entry(root, approved_entry(entry, 'Validation-probe', dt.date.today().isoformat()), policy, context)
            ready.append(dict(id=entry['record']['id'], proposal_sha256=digest(encoded(entry)), entry=entry))
        except (ValueError, KeyError, OSError, TypeError) as exc:
            proposal_errors.append(dict(id=entry.get('record', {}).get('id'), reason=str(exc),
                source_ids=[b['id'] for b in entry.get('bindings', [])]))
    verify_validation_context(root, context)
    ready_sources = {b['id'] for r in ready for b in r['entry']['bindings']}
    fixable_sources = {uid for error in proposal_errors for uid in error['source_ids']}
    pending = []
    for record in load(local/'catalog.json')['records']:
        uid = record['id']; figure = review.get(uid, {})
        if uid in published_sources and not any(r['id'] == uid for r in rejected):
            continue
        status = figure.get('review_status', 'unverified')
        group = ('ready-for-human-approval' if uid in ready_sources else
                 'restricted' if status == 'restricted' else
                 'fixable' if uid in fixable_sources else 'needs-review')
        reasons = list(figure.get('unresolved_issues', []))
        reasons += [e['reason'] for e in proposal_errors if uid in e['source_ids']]
        if record.get('translation_status') != 'reviewed':
            reasons.append('English draft needs human scientific review')
        if uid not in ready_sources:
            reasons.append('No complete version-pinned release proposal; license/credits/alterations need review')
        pending.append(dict(id=uid, title=record['title'], doi=record['doi'], group=group,
            license_candidate=figure.get('article_license', {}).get('candidate', 'unverified'), reasons=reasons))
    payload = dict(schema_version=1, mode='prepare', source=str(source), source_files=before,
        source_changes=delta, public_policy_sha256=digest(encoded(policy)),
        local_catalog_sha256=digest((local/'catalog.json').read_bytes()),
        local_inventory_sha256=digest((local/'inventory.json').read_bytes()),
        proposals=ready, proposal_errors=proposal_errors, pending=pending,
        invalidated_public=rejected, git_changes=git_changes(root), review_inputs=review_inputs(root),
        head=run(['git', 'rev-parse', 'HEAD'], root), importer=result)
    scan_changes(root, payload['git_changes'])
    # Ignore volatile importer report/delta when choosing a repeatable batch ID.
    batch_id = digest(encoded({k: payload[k] for k in ('source_files', 'public_policy_sha256',
        'local_catalog_sha256', 'local_inventory_sha256', 'proposals', 'git_changes', 'review_inputs', 'head')}))[:20]
    batch = local/'updates'/batch_id
    batch.mkdir(parents=True, exist_ok=True)
    if not (batch/'report.json').exists():
        save(batch/'report.json', payload)
        template = dict(batch=batch_id, report_sha256=digest(encoded(payload)), approved_by='',
            approved_at='', records=[], confirm_noncommercial_use=False,
            note='Select exact proposal IDs and proposal_sha256 values after human review; empty list publishes nothing.')
        save(batch/'approval-template.json', template)
        lines = ['# Figure Gallery 待发布报告', '', '批次：`'+batch_id+'`', '',
            f"本地 {result['summary']['valid_records']} 条；新增 {result['summary']['added']}，更新 {result['summary']['updated']}，停用 {result['summary']['inactive']}。",
            f"可提交人工批准的版本固定提案 {len(ready)} 条；正式白名单 {len(public)} 条；失效公开绑定 {len(rejected)} 条。", '',
            '本报告不构成版权批准；未修改公开白名单。', '', '## 来源变化', '',
            *[f"- {key}: {len(values)}" for key, values in delta.items()], '',
            '## 待审核记录', '', '| ID | 分组 | 原因 |', '| --- | --- | --- |',
            *[f"| {r['id']} | {r['group']} | {'; '.join(map(str,r['reasons'])).replace('|','/')} |" for r in pending], '',
            '## 失效公开绑定', '', *[f"- {r['id']}: {r['reason']}" for r in rejected], '',
            '## 需修复的提案', '', *[f"- {r['id']}: {r['reason']}" for r in proposal_errors], '',
            '完整 PDF 定位、图注、英文候选和版权证据仍见本地 pdf-review.json、english-candidates.json、reviews/；不能仅凭自动提取的许可证批准。']
        (batch/'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    save(local/'workflow-source.json', before)
    save(local/'updates/latest.json', dict(batch=batch_id, report=str(batch/'REPORT.md')))
    return dict(batch=batch_id, report=str(batch/'REPORT.md'), importer=result['summary'],
        source_changes=delta, ready=len(ready), pending=len(pending), invalidated_public=rejected,
        pending_groups={group: sum(r['group'] == group for r in pending) for group in
            ('ready-for-human-approval', 'fixable', 'needs-review', 'restricted')},
        retained_editorial_overlays=retained,
        repeated_batch=(load(batch/'report.json') != payload), public_allowlist_changed=False)


def publication_plan(approval_path, root=ROOT):
    approval = load(private_path(root, approval_path))
    if not approval or not re.fullmatch(r'[a-f0-9]{20}', approval.get('batch', '')):
        raise ValueError('Explicit batch approval required')
    batch = root/'.gallery-local/updates'/approval['batch']
    report = load(batch/'report.json')
    if not report or digest(encoded(report)) != approval.get('report_sha256'):
        raise ValueError('Approval does not match immutable prepare report')
    if not approval.get('approved_by', '').strip() or not approval.get('approved_at'):
        raise ValueError('Human reviewer and approval date required')
    selected = approval.get('records', [])
    if not selected or len({s['id'] for s in selected}) != len(selected):
        raise ValueError('Select explicit unique proposal IDs; empty batch cannot publish')
    local = root/'.gallery-local'
    for field, name in [('local_catalog_sha256', 'catalog.json'), ('local_inventory_sha256', 'inventory.json')]:
        if digest((local/name).read_bytes()) != report[field]:
            raise ValueError('Local library changed since prepare; prepare/review again')
    if observe(Path(report['source'])) != report['source_files']:
        raise ValueError('FIG inputs changed since prepare; prepare/review again')
    if review_inputs(root) != report['review_inputs']:
        raise ValueError('Local review inputs changed since prepare; refresh evidence and prepare/review again')
    if run(['git', 'rev-parse', 'HEAD'], root) != report['head'] or git_changes(root) != report['git_changes']:
        raise ValueError('Git source changed since prepare; prepare/review again')
    policy = load(root/'data/gallery/allowlist.json')
    if digest(encoded(policy)) != report['public_policy_sha256']:
        raise ValueError('Official allowlist changed since prepare')
    choices = {p['id']: p for p in report['proposals']}
    entries = []
    context = validation_context(root)
    for selection in selected:
        proposal = choices.get(selection['id'])
        if not proposal or selection.get('proposal_sha256') != proposal['proposal_sha256']:
            raise ValueError('Unreviewed ID or proposal version selected')
        entry = approved_entry(proposal['entry'], approval['approved_by'], approval['approved_at'])
        if re.search(r'\bNC\b|non[ -]?commercial', entry['record']['rights']['license'], re.I) and approval.get('confirm_noncommercial_use') is not True:
            raise ValueError('NC use needs explicit confirmation of actual noncommercial use')
        validate_entry(root, entry, policy, context)
        entries.append(entry)
    verify_validation_context(root, context)
    selected_ids = {e['record']['id'] for e in entries}
    # Unchanged public records must still pass current evidence checks too.
    current, rejected = exporter.plan(root)
    if any(r['id'] not in selected_ids for r in rejected):
        raise ValueError('An existing public approval is stale; repair/reapprove it before release: '+str(rejected))
    records = [r for r in current['records'] if r['id'] not in selected_ids]+[e['record'] for e in entries]
    policy['approved_records'] = [p for p in policy['approved_records'] if p['id'] not in selected_ids]+[
        {k: e['record'][k] for k in APPROVAL_FIELDS} for e in entries]
    dataset = dict(schema_version=1, records=sorted(records, key=lambda r: r['id']))
    validate_dataset(dataset, policy)
    return approval, batch, report, entries, dataset, policy


def media_payloads(root, entries):
    """Create only approved proportional thumbnails, keeping original bytes."""
    from PIL import Image
    files, manifest = {}, []
    prior_media = {m['url']: m for m in load(root/'data/gallery/media.json', {'files': []})['files']}
    for entry in entries:
        record = entry['record']; original = exporter.private_file(root, entry['asset']).read_bytes()
        image = Image.open(io.BytesIO(original)); image.load()
        if image.size != (record['width'], record['height']):
            raise ValueError('Reviewed dimensions do not match approved image')
        urls = [(record['image'], None)]
        urls += [(part.strip().split()[0], int(part.strip().split()[1][:-1])) for part in record['srcset'].split(',') if part.strip()]
        if record['thumbnail'] not in {url for url, _ in urls}:
            raise ValueError('Thumbnail must be a pinned srcset variant')
        for url, width in urls:
            parsed = urlsplit(url)
            if parsed.netloc != 'chutj.github.io' or not parsed.path.startswith('/figures/approved/'+record['source_image_sha256']+'/'):
                raise ValueError('Workflow uses reviewed site-hosted hash paths only; OSS needs separate review')
            relative = 'static/'+parsed.path.lstrip('/')
            if '..' in Path(relative).parts:
                raise ValueError('Unsafe media path')
            if width is None:
                content = original
            else:
                if not parsed.path.endswith('.webp'):
                    raise ValueError('Generated thumbnails must be WebP')
                target_width = min(width, image.width)
                thumb = image.resize((target_width, max(1, round(image.height*target_width/image.width))), Image.Resampling.LANCZOS)
                buffer = io.BytesIO(); thumb.convert('RGB').save(buffer, format='WEBP', quality=90)
                content = buffer.getvalue()
                existing = root/relative
                if existing.exists():
                    pin = prior_media.get(url)
                    if existing.is_symlink() or not pin or pin['id'] != record['id'] or digest(existing.read_bytes()) != pin['sha256']:
                        raise ValueError('Existing thumbnail has no matching reviewed media pin')
                    # Retain previously published, exactly pinned technical versions.
                    content = existing.read_bytes()
            if relative in files and files[relative] != content:
                raise ValueError('Conflicting media path')
            files[relative] = content
            manifest.append(dict(id=record['id'], url=url, sha256=digest(content)))
        if 'legend' in record:
            legend=record['legend']; parsed=urlsplit(legend['image'])
            if parsed.netloc!='chutj.github.io' or not parsed.path.startswith('/figures/approved/'+record['source_image_sha256']+'/'):
                raise ValueError('Shared legend must use the reviewed site-hosted figure path')
            content=exporter.private_file(root,'supplementary/'+legend['sha256']+'.png').read_bytes()
            if digest(content)!=legend['sha256']:
                raise ValueError('Shared legend differs from reviewed version')
            with Image.open(io.BytesIO(content)) as shared:
                if shared.size!=(legend['width'],legend['height']):raise ValueError('Shared legend dimensions changed')
            relative='static/'+parsed.path.lstrip('/')
            existing=root/relative
            if existing.exists() and (existing.is_symlink() or existing.read_bytes()!=content):
                raise ValueError('Existing shared legend differs; use a new reviewed version URL')
            files[relative]=content
            manifest.append(dict(id=record['id'],url=legend['image'],sha256=legend['sha256']))
    return files, manifest


def publish(approval_path, execute=False, hugo=HUGO, root=ROOT):
    if execute and (root/'gallery-component.lock.json').exists():
        raise ValueError('This website uses a pinned SCI Figure Gallery component. Use prepare_approved_release.py, capture-public and sync_website.py apply before the website commit; standalone --execute would invalidate the component lock. No public files changed.')
    approval, batch, report, entries, dataset, policy = publication_plan(approval_path, root)
    files, new_media = media_payloads(root, entries)
    selected = {e['record']['id'] for e in entries}
    media = load(root/'data/gallery/media.json', dict(schema_version=1, files=[]))
    media['files'] = [m for m in media['files'] if m['id'] not in selected]+new_media
    files.update({'data/gallery/public.json': encoded(dataset),
        'data/gallery/allowlist.json': encoded(policy), 'data/gallery/media.json': encoded(media)})
    changes = report['git_changes']
    scan_changes(root, changes)
    # A Gallery update must not silently commit unrelated Home/config changes.
    for name in changes:
        if not name.startswith(('scripts/', 'docs/', 'data/gallery/', 'static/figures/approved/')) or changes[name] is None:
            raise ValueError('Unrelated/deleted file needs separate review: '+name)
    if not execute:
        return dict(mode='publish-plan', selected=sorted(selected), public_total=len(dataset['records']),
            files=sorted(files), git_source_files=sorted(changes), writes=False,
            note='No whitelist changes, staging, commit or push. --execute is the explicit publishing action.')
    if run(['git', 'branch', '--show-current'], root) != 'main':
        raise ValueError('Publish requires main')
    if run(['git', 'remote', 'get-url', 'origin'], root).rstrip('/') not in (
            'https://github.com/Chutj/chutj.github.io.git', 'git@github.com:Chutj/chutj.github.io.git'):
        raise ValueError('Unexpected origin; stopped')
    if run(['git', 'diff', '--cached', '--name-only'], root):
        raise ValueError('Existing staged changes require separate review')
    # Back up all replaced bytes before touching public inputs. Never auto-delete.
    backup = batch/'before-publish'
    if backup.exists():
        raise ValueError('A publish attempt already exists; inspect publish-result.json before retrying')
    backup.mkdir()
    result = dict(status='started', batch=approval['batch'], selected=sorted(selected), public_total=len(dataset['records']))
    try:
        for name, content in files.items():
            path = root/name
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Unsafe public target')
            if path.exists():
                old = backup/name; old.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, old)
                if name.startswith('static/') and path.read_bytes() != content:
                    raise ValueError('Existing media differs; never overwrite a published version')
            importer.atomic_write(path, content)
        from validate_public_gallery import validate
        validate(root)
        result['tests'] = run([sys.executable, '-m', 'unittest', 'discover', '-s', 'scripts', '-p', 'test_*.py', '-q'], root)
        import check_release_snapshot as snapshot
        old_root = snapshot.ROOT
        try:
            snapshot.ROOT = root
            result['clean_build'] = snapshot.check(hugo)
        finally:
            snapshot.ROOT = old_root
        expected = {**changes, **{name: digest(content) for name, content in files.items()}}
        current = git_changes(root)
        if any(name not in expected or expected[name] != value for name, value in current.items()):
            raise ValueError('Unexpected changes appeared during release checks')
        scan_changes(root, current)
        tracked = filter(None, run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], root).split('\0'))
        scan_changes(root, dict.fromkeys(tracked))
        if observe(Path(report['source'])) != report['source_files']:
            raise ValueError('FIG changed during release checks; prepare/review again')
        if review_inputs(root) != report['review_inputs']:
            raise ValueError('Local review inputs changed during release checks')
        context = validation_context(root)
        for entry in entries:
            validate_entry(root, entry, policy, context)
        verify_validation_context(root, context)
        run(['git', 'fetch', 'origin', 'main'], root)
        # Remote commits are never merged/rebased/forced by this workflow.
        run(['git', 'merge-base', '--is-ancestor', 'origin/main', 'HEAD'], root)
        if current:
            run(['git', 'add', '--', *sorted(current)], root)
            staged = set(filter(None, run(['git', 'diff', '--cached', '--name-only', '-z'], root).split('\0')))
            if staged != set(current):
                raise ValueError('Unexpected staged content')
            for name in staged:
                if digest(subprocess.check_output(['git', 'show', ':'+name], cwd=root)) != expected[name]:
                    raise ValueError('Staged bytes differ from reviewed release: '+name)
            run(['git', 'commit', '-m', 'Update reviewed Figure Gallery batch '+approval['batch']], root)
        result['commit'] = run(['git', 'rev-parse', 'HEAD'], root)
        run(['git', 'push', 'origin', 'main'], root)
        result['status'] = 'pushed'
        # Persist approved variant bindings only after the public inputs pass.
        prior = load(root/'.gallery-local/publication-records.json', {'records': []})
        prior['records'] = [e for e in prior['records'] if e['record']['id'] not in selected]+entries
        save(root/'.gallery-local/publication-records.json', prior)
        run(['git', 'fetch', 'origin', 'main'], root)
        if run(['git', 'rev-parse', 'origin/main'], root) != result['commit']:
            raise ValueError('Remote main changed after push; inspect deployment')
        try:
            result['deployment'] = deployment_status(result['commit'], wait=True)
            if result['deployment']['runs'] and result['deployment']['runs'][0]['conclusion'] not in (None, 'success'):
                raise ValueError('GitHub Actions failed; inspect the recorded run URL')
        except OSError as exc:
            result['deployment'] = dict(status='not-verified', reason=str(exc), next='Run status --commit '+result['commit'])
    except Exception as exc:
        result.update(status='stopped', error=str(exc),
            recovery='No force/reset/automatic deletion. Inspect backups, Git status and the exact commit before retrying.')
        raise
    finally:
        save(batch/'publish-result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='mode', required=True)
    p = commands.add_parser('prepare'); p.add_argument('--source', type=Path); p.add_argument('--dry-run', action='store_true'); p.add_argument('--json', action='store_true', help='Include full source change paths and diagnostics')
    p = commands.add_parser('publish'); p.add_argument('--approval', type=Path, required=True); p.add_argument('--execute', action='store_true'); p.add_argument('--hugo', default=HUGO)
    p = commands.add_parser('status'); p.add_argument('--commit')
    args = parser.parse_args()
    try:
        if args.mode == 'prepare':
            result = prepare(args.source, args.dry_run)
            if not args.json:
                result['source_changes'] = {key: len(values) for key, values in result['source_changes'].items()}
                if args.dry_run:
                    plan = result['importer']
                    result.update(importer=plan['summary'], files=plan['files'], diagnostics=len(plan['diagnostics']))
        elif args.mode == 'publish':
            result = publish(args.approval, args.execute, args.hugo)
        elif args.commit:
            result = deployment_status(args.commit)
        else:
            latest = load(ROOT/'.gallery-local/updates/latest.json', {})
            result = dict(latest=latest, git_status=run(['git', 'status', '--short']),
                public_figures=len(load(ROOT/'data/gallery/public.json')['records']),
                publish_result=load(ROOT/'.gallery-local/updates'/latest.get('batch', '_')/'publish-result.json'))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print('STOP: '+str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
