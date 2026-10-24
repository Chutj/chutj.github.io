"""Reviewed variants must remain bound to source records and exact evidence."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from export_public_gallery import prepared_record
from public_gallery_schema import APPROVAL_FIELDS
from test_public_gallery import fixture


class PublicationVariantTest(unittest.TestCase):
    def test_source_evidence_and_prepared_file_changes_require_reassessment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);private=root/'.gallery-local';(private/'assets').mkdir(parents=True)
            image=b'original-fixture';prepared=image
            image_sha=hashlib.sha256(image).hexdigest();prepared_sha=hashlib.sha256(prepared).hexdigest()
            (private/'assets/source.png').write_bytes(image);(private/'prepared.png').write_bytes(prepared)
            source=dict(id='source',asset='gallery-private/source.png',pdf_reference={'evidence_sha256':'b'*64})
            evidence={'id':'source','assessment':'explicit test evidence only'}
            (private/'audit.json').write_text(json.dumps({'records':[evidence]}))
            record,_=fixture();record['source_image_sha256']=prepared_sha
            source.update(primary=record['primary'],categories=record['categories'])
            record['rights']['review_evidence_sha256']=hashlib.sha256(json.dumps(evidence,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            approval={k:record[k] for k in APPROVAL_FIELDS}
            entry=dict(record=record,asset='prepared.png',evidence_file='audit.json',evidence_id='source',bindings=[dict(id='source',image_sha256=image_sha,pdf_evidence_sha256='b'*64,catalog_sha256=hashlib.sha256(json.dumps(source,sort_keys=True,ensure_ascii=False).encode()).hexdigest())])
            catalog={'source':source};inventory={'source':{'image_sha256':image_sha}}
            entry['bindings'][0]['inventory_sha256']=hashlib.sha256(json.dumps(inventory['source'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            self.assertEqual(prepared_record(root,entry,approval,catalog,inventory)['id'],record['id'])
            changed=copy.deepcopy(catalog);changed['source']['pdf_reference']['evidence_sha256']='c'*64
            with self.assertRaisesRegex(ValueError,'reassessment required'):prepared_record(root,entry,approval,changed,inventory)
            changed_inventory={'source':dict(inventory['source'],description='source notes changed')}
            with self.assertRaisesRegex(ValueError,'reassessment required'):prepared_record(root,entry,approval,catalog,changed_inventory)
            (private/'prepared.png').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'publication image changed'):prepared_record(root,entry,approval,catalog,inventory)
            (private/'prepared.png').write_bytes(prepared)
            (private/'audit.json').write_text(json.dumps({'records':[dict(evidence,assessment='changed')]}))
            with self.assertRaisesRegex(ValueError,'rights evidence changed'):prepared_record(root,entry,approval,catalog,inventory)

    def test_prepared_record_cannot_change_permission_or_escape_private_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);record,_=fixture();approval={k:copy.deepcopy(record[k]) for k in APPROVAL_FIELDS}
            entry=dict(record=record,asset='../outside.png',evidence_file='audit.json',evidence_id='source',bindings=[])
            with self.assertRaisesRegex(ValueError,'private regular file'):prepared_record(root,entry,approval,{}, {})
            entry['record']['rights']['human_reviewed']=False
            with self.assertRaisesRegex(ValueError,'differs from explicit approval'):prepared_record(root,entry,approval,{}, {})


if __name__=='__main__':unittest.main()
