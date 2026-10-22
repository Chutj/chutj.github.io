"""Opt-in public export. No images copied, no OSS requests, no automatic approval."""
import sys
sys.dont_write_bytecode = True
import argparse
import json
import os
from pathlib import Path
from public_gallery_schema import (APPROVAL_FIELDS, editor_payload, metadata_hash,
    validate_dataset, validate_policy)

ROOT=Path(__file__).resolve().parents[1]


def plan(root=ROOT):
    policy=json.loads((root/'data/gallery/allowlist.json').read_text(encoding='utf-8-sig'))
    approvals=validate_policy(policy)
    if not approvals:
        return {'schema_version':1,'records':[]},[]
    local=root/'.gallery-local'
    catalog=json.loads((local/'catalog.json').read_text(encoding='utf-8-sig'))['records']
    inventory={r['id']:r for r in json.loads((local/'inventory.json').read_text(encoding='utf-8-sig'))['records']}
    records=[]; rejected=[]
    for record in catalog:
        uid=record['id']
        if uid not in approvals:
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
    present={r['id'] for r in catalog}
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
