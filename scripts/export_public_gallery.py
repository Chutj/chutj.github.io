"""Opt-in public export. No images copied, no OSS requests, no automatic approval."""
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import json
import os
from pathlib import Path
from public_gallery_schema import (APPROVAL_FIELDS, editor_payload, metadata_hash,
    validate_dataset, validate_policy)

ROOT=Path(__file__).resolve().parents[1]


def private_file(root, relative):
    base=(root/'.gallery-local').resolve()
    path=(base/relative).resolve()
    if not path.is_relative_to(base) or not path.is_file() or path.is_symlink():
        raise ValueError('Reviewed publication asset/evidence must be a private regular file')
    return path


def prepared_record(root, entry, approval, catalog, inventory):
    """Explicitly reviewed publication variant; never mutates the source catalog.

    Binds the actual reviewed file and audit evidence to every original source
    record. Any import/PDF/source-metadata change requires review again.
    """
    if set(entry)!={'record','asset','evidence_file','evidence_id','bindings'}:
        raise ValueError('Incomplete reviewed publication variant')
    record=entry['record'];uid=approval['id']
    if record.get('id')!=uid or any(record.get(k)!=approval[k] for k in APPROVAL_FIELDS):
        raise ValueError('Prepared record differs from explicit approval')
    if hashlib.sha256(private_file(root,entry['asset']).read_bytes()).hexdigest()!=approval['source_image_sha256']:
        raise ValueError('Prepared publication image changed')
    if 'legend' in record:
        legend=record['legend']
        if hashlib.sha256(private_file(root,'supplementary/'+legend['sha256']+'.png').read_bytes()).hexdigest()!=legend['sha256']:
            raise ValueError('Reviewed shared legend changed')
    evidence=json.loads(private_file(root,entry['evidence_file']).read_text(encoding='utf-8'))['records']
    matches=[r for r in evidence if r.get('id')==entry['evidence_id']]
    if len(matches)!=1 or hashlib.sha256(json.dumps(matches[0],sort_keys=True,ensure_ascii=False).encode()).hexdigest()!=approval['rights']['review_evidence_sha256']:
        raise ValueError('Prepared rights evidence changed')
    if not entry['bindings'] or len({b['id'] for b in entry['bindings']})!=len(entry['bindings']):
        raise ValueError('Explicit unique source bindings required')
    if len(entry['bindings'])!=1 or entry['bindings'][0]['image_sha256']!=record['source_image_sha256']:
        raise ValueError('Use the exact classified FIG crop, one source crop per card; complete-figure substitution is not allowed')
    for binding in entry['bindings']:
        source=catalog.get(binding['id']);raw=inventory.get(binding['id'])
        if not source or not raw:
            raise ValueError('Reviewed variant source absent from current library')
        if record['primary']!=source['primary'] or set(record['categories'])!=set(source['categories']):
            raise ValueError('Public categories must match this classified FIG crop, not a complete-figure category union')
        fingerprint=hashlib.sha256(json.dumps(source,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        raw_fingerprint=hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if (fingerprint!=binding['catalog_sha256'] or raw_fingerprint!=binding['inventory_sha256'] or raw.get('image_sha256')!=binding['image_sha256']
                or source.get('pdf_reference',{}).get('evidence_sha256')!=binding['pdf_evidence_sha256']):
            raise ValueError('Reviewed source metadata/image/PDF changed; reassessment required')
        asset=private_file(root,'assets/'+Path(source['asset']).name)
        if hashlib.sha256(asset.read_bytes()).hexdigest()!=binding['image_sha256']:
            raise ValueError('Original local image bytes changed')
    return record


def plan(root=ROOT):
    policy=json.loads((root/'data/gallery/allowlist.json').read_text(encoding='utf-8-sig'))
    approvals=validate_policy(policy)
    if not approvals:
        return {'schema_version':1,'records':[]},[]
    local=root/'.gallery-local'
    catalog=json.loads((local/'catalog.json').read_text(encoding='utf-8-sig'))['records']
    inventory={r['id']:r for r in json.loads((local/'inventory.json').read_text(encoding='utf-8-sig'))['records']}
    records=[]; rejected=[]
    prepared_path=local/'publication-records.json'
    prepared={}
    if prepared_path.exists():
        for entry in json.loads(prepared_path.read_text(encoding='utf-8'))['records']:
            uid=entry['record']['id']
            if uid in prepared:raise ValueError('Duplicate reviewed publication ID')
            prepared[uid]=entry
    catalog_by_id={r['id']:r for r in catalog}
    for uid,entry in prepared.items():
        if uid not in approvals:continue
        try:
            public=prepared_record(root,entry,approvals[uid],catalog_by_id,inventory)
            validate_dataset({'schema_version':1,'records':[public]},policy)
            records.append(public)
        except (ValueError,KeyError,OSError) as exc:
            rejected.append(dict(id=uid,reason=str(exc)))
    for record in catalog:
        uid=record['id']
        if uid not in approvals or uid in prepared:
            continue
        approval=approvals[uid]
        raw=inventory.get(uid,{})
        if (raw.get('image_sha256')!=approval['source_image_sha256']
                or metadata_hash(record)!=approval['metadata_sha256']
                or record.get('pdf_reference',{}).get('evidence_sha256')!=approval['rights']['review_evidence_sha256']
                or any(record.get('rights',{}).get(k)!=v for k,v in approval['rights'].items())):
            rejected.append(dict(id=uid,reason='Image, metadata or local rights differ from explicit human approval'))
            continue
        public=editor_payload(record)
        public.update({k:approval[k] for k in APPROVAL_FIELDS})
        try:
            validate_dataset({'schema_version':1,'records':[public]},policy)
            records.append(public)
        except ValueError as exc:
            rejected.append(dict(id=uid,reason=str(exc)))
    present={r['id'] for r in catalog}|set(prepared)
    rejected.extend(dict(id=uid,reason='Approved record absent from active local catalog') for uid in approvals if uid not in present)
    dataset={'schema_version':1,'records':sorted(records,key=lambda r:r['id'])}
    validate_dataset(dataset,policy)
    return dataset,rejected


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Write the approved dataset after reviewing the dry-run')
    parser.add_argument('--dry-run',action='store_true',help='Explicit read-only mode (the default)')
    args=parser.parse_args()
    try:
        if args.apply and args.dry_run:raise ValueError('Choose --apply or --dry-run')
        dataset,rejected=plan()
        print(f"Approved export: {len(dataset['records'])}; rejected approvals: {len(rejected)}; mode: "+('apply' if args.apply else 'dry-run'))
        for rejection in rejected:print(rejection['id']+': '+rejection['reason'])
        if rejected:raise ValueError('Resolve rejected approvals before exporting; public dataset unchanged')
        if args.apply:
            target=ROOT/'data/gallery/public.json'
            content=(json.dumps(dataset,ensure_ascii=False,indent=2)+'\n').encode()
            if target.read_bytes()!=content:
                temporary=target.with_name('public.json.tmp')
                temporary.write_bytes(content);os.replace(temporary,target)
        return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print('STOP: '+str(exc),file=sys.stderr);return 1


if __name__=='__main__':
    raise SystemExit(main())
