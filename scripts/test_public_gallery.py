"""Policy fixtures only, never real research permissions or public site data."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
import uuid

from public_gallery_schema import metadata_hash, validate_dataset
from export_public_gallery import plan

ROOT=Path(__file__).resolve().parents[1]


def fixture():
    # Synthetic contract object: not an asserted scientific source or image.
    record=dict(id='policy-fixture',title='Policy test fixture — not research data',
        primary='Policy test',categories=['Policy test'],journal='Test fixture',year=2026,
        doi='10.1234/policy-fixture',figure='Fixture',paper='Synthetic policy contract test',
        author='Test fixture',source='https://doi.org/10.1234/policy-fixture',
        sections={k:'Synthetic policy test text.' for k in ('What the figure shows','Statistics & symbols','Color & encoding','Design lessons','Verification & limitations')},
        translation_status='reviewed',width=800,height=600)
    rights=dict(status='approved',public_use_allowed=True,human_reviewed=True,
        approved_by='policy-test-only',approved_at='2020-01-01',permission_basis='license',
        license='Synthetic test permission',license_url='https://example.org/policy',
        evidence_reference='TEST-NOT-A-REAL-PERMISSION',attribution='Synthetic policy fixture only',review_evidence_sha256='b'*64,
        modification_status='Synthetic fixture, no actual image.',additional_credit='Test fixture only.')
    approval=dict(id=record['id'],source_image_sha256='a'*64,metadata_sha256=metadata_hash(record),
        rights=rights,image='https://cdn.example.org/fixture.png',thumbnail='https://cdn.example.org/fixture-thumb.webp',
        srcset='https://cdn.example.org/fixture-small.webp 320w, https://cdn.example.org/fixture-thumb.webp 640w')
    public=dict(record,**{k:v for k,v in approval.items() if k!='id'})
    policy=dict(schema_version=1,image_hosts=['cdn.example.org'],approved_records=[approval])
    return public,policy


class PublicPolicyTest(unittest.TestCase):
    def test_empty_is_valid_and_approved_fixture_requires_every_gate(self):
        self.assertEqual(validate_dataset(dict(schema_version=1,records=[]),dict(schema_version=1,image_hosts=[],approved_records=[])),0)
        record,policy=fixture()
        self.assertEqual(validate_dataset(dict(schema_version=1,records=[record]),policy),1)
        for field,value in [('status','unverified'),('human_reviewed',False),('public_use_allowed',False),('approved_by',''),('evidence_reference','')]:
            bad=copy.deepcopy(record);bad['rights'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                validate_dataset(dict(schema_version=1,records=[bad]),policy)

    def test_missing_whitelist_changed_metadata_and_private_paths_rejected(self):
        record,policy=fixture()
        empty=dict(schema_version=1,image_hosts=['cdn.example.org'],approved_records=[])
        with self.assertRaises(ValueError):validate_dataset(dict(schema_version=1,records=[record]),empty)
        changed=copy.deepcopy(record);changed['title']='Changed after review'
        with self.assertRaises(ValueError):validate_dataset(dict(schema_version=1,records=[changed]),policy)
        extra=copy.deepcopy(record);extra['raw_fields']={'private':'not allowed'}
        with self.assertRaises(ValueError):validate_dataset(dict(schema_version=1,records=[extra]),policy)
        for url in ('http://cdn.example.org/a.png','https://localhost/a.png','https://127.0.0.1/a.png','https://cdn.example.org/.gallery-local/a.png','https://other.example.org/a.png'):
            bad=copy.deepcopy(policy);bad['approved_records'][0]['image']=url
            with self.subTest(url=url),self.assertRaises(ValueError):validate_dataset(dict(schema_version=1,records=[]),bad)

    def test_export_does_not_promote_local_unverified_rights(self):
        root=ROOT/'.gallery-local/public-policy-tests'/uuid.uuid4().hex
        (root/'data/gallery').mkdir(parents=True)
        (root/'.gallery-local').mkdir()
        record,policy=fixture()
        def write(path,obj):path.write_text(json.dumps(obj),encoding='utf-8')
        write(root/'data/gallery/allowlist.json',policy)
        local=copy.deepcopy(record);local['rights']['status']='unverified'
        local['pdf_reference']={'evidence_sha256':'b'*64}
        write(root/'.gallery-local/catalog.json',dict(records=[local]))
        write(root/'.gallery-local/inventory.json',dict(records=[dict(id=record['id'],image_sha256='a'*64)]))
        dataset,rejected=plan(root)
        self.assertEqual(dataset['records'],[]);self.assertEqual(len(rejected),1)
        local['rights']=copy.deepcopy(policy['approved_records'][0]['rights'])
        write(root/'.gallery-local/catalog.json',dict(records=[local]))
        dataset,rejected=plan(root)
        self.assertEqual(len(dataset['records']),1);self.assertFalse(rejected)
        local['pdf_reference']['evidence_sha256']='c'*64
        write(root/'.gallery-local/catalog.json',dict(records=[local]))
        self.assertEqual(len(plan(root)[1]),1)

    def test_hugo_gate_and_no_private_data_dependency(self):
        site=ROOT/'.gallery-local/public-policy-tests'/uuid.uuid4().hex/'site'
        site.mkdir(parents=True)
        for folder in ('assets','layouts','content','data'):
            shutil.copytree(ROOT/folder,site/folder)
        shutil.copy2(ROOT/'hugo.toml',site/'hugo.toml')
        shutil.copytree(ROOT/'themes/PaperMod',site/'themes/PaperMod',ignore=shutil.ignore_patterns('.git'))
        record,policy=fixture()
        (site/'data/gallery/allowlist.json').write_text(json.dumps(policy),encoding='utf-8')
        hugo=shutil.which('hugo') or str(Path.home()/'AppData/Local/Microsoft/WinGet/Packages/Hugo.Hugo.Extended_Microsoft.Winget.Source_8wekyb3d8bbwe/hugo.exe')
        for name,candidate,expected in [('approved',record,1),('edited',dict(record,title='Changed after review'),0),('unverified',dict(record,rights=dict(record['rights'],status='unverified')),0)]:
            (site/'data/gallery/public.json').write_text(json.dumps(dict(schema_version=1,records=[candidate])),encoding='utf-8')
            output=site.parent/('out-'+name)
            build=subprocess.run([hugo,'build','--minify','--noBuildLock','--destination',str(output)],cwd=site,capture_output=True,encoding='utf-8',env=dict(os.environ,HUGO_ENVIRONMENT='production',HUGO_ENV='production'))
            self.assertEqual(build.returncode,0,build.stderr);self.assertEqual(build.stderr,'')
            html=(output/'gallery/index.html').read_text(encoding='utf-8')
            self.assertEqual('id=gallery-data' in html or 'id="gallery-data"' in html,bool(expected),name)
            if not expected:self.assertIn('No public figures available',html)
            self.assertNotIn('.gallery-local',html);self.assertNotIn('gallery-private/',html)
        self.assertFalse((site/'.gallery-local').exists())


if __name__=='__main__':unittest.main()
