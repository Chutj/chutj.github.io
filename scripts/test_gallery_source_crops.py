"""Synthetic source-crop policy tests; never reads FIG or real approval evidence."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import uuid
from export_public_gallery import prepared_record
from public_gallery_schema import APPROVAL_FIELDS,metadata_hash
from test_public_gallery import fixture

def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

class SourceCropPolicyTest(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]/'.gallery-local/crop-tests'/uuid.uuid4().hex
        local=self.root/'.gallery-local';(local/'assets').mkdir(parents=True)
        self.record,_=fixture();self.content=b'unchanged classified FIG crop';h=hashlib.sha256(self.content).hexdigest()
        self.record.update(source_image_sha256=h,primary='Maps',categories=['Maps'])
        self.record['metadata_sha256']=metadata_hash(self.record)
        self.source=dict(id=self.record['id'],primary='Maps',categories=['Maps'],asset='gallery-private/'+h+'.png',pdf_reference=dict(evidence_sha256='0'*64))
        self.raw=dict(id=self.record['id'],image_sha256=h)
        evidence=dict(id='test-evidence',description='Synthetic test only')
        (local/'evidence.json').write_text(json.dumps(dict(records=[evidence])),encoding='utf-8')
        self.record['rights']['review_evidence_sha256']=digest(evidence)
        (local/'assets'/(h+'.png')).write_bytes(self.content)
        self.entry=dict(record=self.record,asset='assets/'+h+'.png',evidence_file='evidence.json',evidence_id=evidence['id'],
            bindings=[dict(id=self.record['id'],image_sha256=h,catalog_sha256=digest(self.source),inventory_sha256=digest(self.raw),pdf_evidence_sha256='0'*64)])

    def check(self):
        return prepared_record(self.root,self.entry,{k:self.record[k] for k in APPROVAL_FIELDS},
            {self.source['id']:self.source},{self.raw['id']:self.raw})

    def test_exact_source_crop_is_accepted(self):self.assertEqual(self.check(),self.record)

    def test_approved_full_figure_cannot_replace_classified_crop(self):
        content=b'synthetic full A plus B';h=hashlib.sha256(content).hexdigest()
        self.record['source_image_sha256']=h;self.entry['asset']='assets/'+h+'.png'
        (self.root/'.gallery-local'/self.entry['asset']).write_bytes(content)
        with self.assertRaisesRegex(ValueError,'exact classified FIG crop'):self.check()

    def test_category_union_is_rejected_even_with_an_explicit_approval(self):
        self.record['categories'].append('Bar charts');self.record['metadata_sha256']=metadata_hash(self.record)
        with self.assertRaisesRegex(ValueError,'categories must match'):self.check()

    def test_multiple_sources_cannot_be_merged_into_one_card(self):
        extra=copy.deepcopy(self.entry['bindings'][0]);extra['id']='second-source';self.entry['bindings'].append(extra)
        with self.assertRaisesRegex(ValueError,'one source crop per card'):self.check()
