"""Synthetic parsing/policy fixtures, never research or actual permissions."""
import hashlib
import json
from pathlib import Path
import unittest
import uuid

import fitz
import pdf_gallery as pdf

ROOT=Path(__file__).resolve().parents[1]


class PDFReviewTest(unittest.TestCase):
    def setUp(self):
        self.base=ROOT/'.gallery-local/pdf-tests'/uuid.uuid4().hex
        self.source=self.base/'source';self.output=self.base/'output'
        (self.source/'PDF原文').mkdir(parents=True)
        self.doi='10.1234/synthetic-policy-fixture'
        self.title='Synthetic PDF policy fixture for automated tests'
        self.record=dict(id='test-figure',doi=self.doi,paper=self.title,journal='Synthetic fixture',
            year=2026,figure='Fig.1 a',title='Synthetic fixture',translation_status='pending',
            rights=dict(status='unverified',public_use_allowed=False))
        self.raw=dict(id='test-figure',image_sha256='a'*64,variants=[dict(note_sha256='b'*64)])
        self.state=dict(records={'test-figure':dict(rights=self.record['rights'])})

    def make_pdf(self,doi=None,license_text='Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License',caption='Fig. 1 | Synthetic caption. Diagram credit: BioRender.',name='fixture.pdf'):
        document=fitz.open();page=document.new_page()
        page.insert_text((40,40),self.title,fontsize=10)
        page.insert_text((40,65),doi or self.doi,fontsize=10)
        page.insert_textbox((40,100,550,180),caption,fontsize=9)
        page.insert_textbox((40,220,550,300),'Open Access This article is licensed under a '+license_text,fontsize=9)
        page.insert_text((40,350),'Related discussion in Fig. 1: synthetic body explanation.',fontsize=10)
        path=self.source/'PDF原文'/name
        document.save(path);document.close()
        return path

    def registry(self,path,doi=None):
        entry=dict(doi=doi or self.doi,title=self.title,pdf_relative_path=path.relative_to(self.source).as_posix(),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),paper_id='TEST')
        (self.source/'PDF原文/sources.json').write_text(json.dumps([entry]),encoding='utf-8')

    def build(self):
        return pdf.build(self.source,self.output,dict(records=[self.record]),dict(records=[self.raw]),self.state)

    def persist(self,writes):
        for path,content in writes.items():
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)

    def review(self,writes):
        return json.loads(writes[self.output/'pdf-review.json'])['figures']['test-figure']

    def test_caption_doi_credit_and_license_are_candidates_only(self):
        path=self.make_pdf();self.registry(path)
        writes,stats=self.build();f=self.review(writes)
        self.assertEqual(stats['captions_located'],1)
        self.assertEqual(f['reference']['caption']['page'],1)
        self.assertTrue(f['reference']['body_references'])
        self.assertEqual(f['article_license']['candidate'],'CC BY-NC-ND 4.0')
        self.assertTrue(f['figure_specific_rights']['candidate_credit_lines'])
        self.assertFalse(f['human_reviewed']);self.assertFalse(f['public_use_allowed'])
        self.assertNotEqual(f['review_status'],'permitted')
        html_data=json.loads(writes[self.output/'catalog.json'])['records'][0]['pdf_reference']
        self.assertNotIn('caption',html_data);self.assertNotIn('body_references',html_data)

    def test_wrong_doi_missing_and_duplicate_captions_fail_closed(self):
        path=self.make_pdf(doi='10.1234/wrong');self.registry(path)
        self.assertEqual(self.build()[1]['papers_matched'],0)
        path=self.make_pdf(caption='Body references Fig. 1, without a caption label.',name='new.pdf');self.registry(path)
        self.assertEqual(self.build()[1]['captions_located'],0)
        path=self.make_pdf(name='duplicate.pdf');self.registry(path)
        doc=fitz.open(path);page=doc.new_page();page.insert_text((40,100),'Fig. 1 | A second ambiguous caption.',fontsize=9)
        edited=self.source/'PDF原文/edited.pdf';doc.save(edited);doc.close();self.registry(edited)
        self.assertEqual(self.build()[1]['captions_located'],0)

    def test_cache_dry_plan_idempotence_and_pdf_change_invalidates_rights(self):
        path=self.make_pdf();self.registry(path)
        writes,stats=self.build()
        self.assertEqual(stats['parsed'],1);self.assertFalse(self.output.exists())
        self.persist(writes)
        self.record=json.loads(writes[self.output/'catalog.json'])['records'][0]
        self.raw=json.loads(writes[self.output/'inventory.json'])['records'][0]
        self.state=json.loads(writes[self.output/'state.json'])
        again,stats=self.build();self.assertEqual(stats['parsed'],0);self.assertEqual(stats['reused'],1)
        self.assertTrue(all(p.read_bytes()==b for p,b in again.items()))
        self.record['rights']=dict(status='approved',public_use_allowed=True)
        changed=self.make_pdf(caption='Fig. 1 | A changed synthetic caption.',name='version2.pdf');self.registry(changed)
        result,_=self.build()
        updated=json.loads(result[self.output/'catalog.json'])['records'][0]
        self.assertEqual(updated['rights']['status'],'unverified');self.assertFalse(updated['rights']['public_use_allowed'])

    def test_metadata_or_official_evidence_change_invalidates_candidate(self):
        path=self.make_pdf();self.registry(path)
        writes,_=self.build();fingerprint=self.review(writes)['evidence_sha256'];self.persist(writes)
        candidate={'test-figure':dict(status='candidate-needs-review',evidence_sha256=fingerprint,
            title='Synthetic suggestion',sections={'What the figure shows':'Synthetic paraphrase, not research.'})}
        (self.output/'english-candidates.json').write_text(json.dumps(candidate),encoding='utf-8')
        self.assertEqual(self.review(self.build()[0])['english_candidate']['title'],'Synthetic suggestion')
        self.raw['variants'][0]['note_sha256']='c'*64
        f=self.review(self.build()[0]);self.assertIsNone(f['english_candidate'])
        self.assertTrue(any('withheld' in s for s in f['unresolved_issues']))

    def test_exclusive_and_conflicting_licenses_never_permitted(self):
        path=self.make_pdf(license_text='Publisher holds an exclusive licence.');self.registry(path)
        self.assertEqual(self.review(self.build()[0])['review_status'],'restricted')
        self.output.mkdir(exist_ok=True)
        (self.output/'official-evidence.json').write_text(json.dumps({self.doi:{'article_license':'CC BY 4.0'}}),encoding='utf-8')
        self.assertEqual(self.review(self.build()[0])['review_status'],'needs-review')

    def test_pdf_only_observes_current_selected_markdown_changes(self):
        path=self.make_pdf();self.registry(path)
        note=self.source/'notes.md'
        note.write_text('## Synthetic figure\n![fixture](fixture.png)\nOriginal synthetic note.',encoding='utf-8')
        self.raw['variants']=[dict(path='notes.md',filename='fixture.png',note_sha256='b'*64)]
        first,_=self.build();self.persist(first)
        original=self.review(first)['evidence_sha256']
        self.record=json.loads(first[self.output/'catalog.json'])['records'][0]
        self.record['rights']=dict(status='approved',public_use_allowed=True)
        note.write_text(note.read_text()+' Changed synthetic description.',encoding='utf-8')
        updated,_=self.build()
        self.assertNotEqual(self.review(updated)['evidence_sha256'],original)
        self.assertFalse(json.loads(updated[self.output/'catalog.json'])['records'][0]['rights']['public_use_allowed'])

    def test_malformed_pdf_missing_directory_and_path_escape(self):
        (self.source/'PDF原文/broken.pdf').write_bytes(b'not a PDF')
        writes,stats=self.build()
        diagnostics=json.loads(writes[self.output/'pdf-review.json'])['diagnostics']
        self.assertTrue(any(d['code']=='pdf_parse_failed' for d in diagnostics))
        path=self.make_pdf();self.registry(path)
        index=self.source/'PDF原文/sources.json'
        entries=json.loads(index.read_text());entries[0]['pdf_relative_path']='../outside.pdf'
        index.write_text(json.dumps(entries))
        diagnostics=json.loads(self.build()[0][self.output/'pdf-review.json'])['diagnostics']
        self.assertTrue(any(d['code']=='invalid_pdf_registry_path' for d in diagnostics))


if __name__=='__main__':unittest.main()
