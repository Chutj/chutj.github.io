"""Synthetic format fixtures; no authoritative FIG source writes."""
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
import import_gallery as importer


class FigureNoteFormatsTest(unittest.TestCase):
    def fixture(self, directory):
        source = Path(directory).resolve()
        (source/'论文来源与核查状态.md').write_text('# Paper registry\n', encoding='utf-8')
        folder = source/'Maps'; folder.mkdir()
        filename = 'N_2026_Example_Fig1_a.png'
        Image.new('RGB',(12,10),'white').save(folder/filename)
        (folder/'Maps.md').write_text(
            '| Material | Paper | Figure | Image |\n'
            '| Example | Nature · 10.1234/example | Fig.1 a | [Open]('+filename+') |\n'
            '## Example\n\n![Example]('+filename+')\n\n'
            '**来源**　Example paper; DOI: 10.1234/example.\n\n'
            '**表示什么**　A real source would describe this panel.\n\n'
            '**值得学习**　Aligned panels.\n', encoding='utf-8')
        pdfs=source/'PDF原文';pdfs.mkdir()
        registry=[dict(doi='10.1234/example',title='Example paper',first_author='Example Author')]
        (pdfs/'sources.json').write_text(json.dumps(registry),encoding='utf-8')
        return source,folder,registry

    def test_explicit_colon_and_fullwidth_separators(self):
        for text in ['**Paper**: Example\n\n**Color**: Blue', '**Paper**：Example\n\n**Color**：Blue', '**Paper**　Example\n\n**Color**　Blue']:
            self.assertEqual(importer.fields_of(text), {'Paper':'Example','Color':'Blue'})
        self.assertEqual(importer.fields_of('**Unstructured** ordinary bold prose'), {})

    def test_new_source_fields_and_registry_are_parsed_without_rights_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            source,_,_=self.fixture(directory)
            records,issues,_=importer.scan(source, {'Maps':'Maps'})
            self.assertEqual(len(records),1,issues)
            self.assertEqual(records[0]['doi'],'10.1234/example')
            self.assertEqual(records[0]['paper'],'Example paper')
            self.assertNotIn('rights',records[0])

    def test_disagreeing_source_doi_is_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            source,folder,_=self.fixture(directory)
            p=folder/'Maps.md';p.write_text(p.read_text(encoding='utf-8').replace('DOI: 10.1234/example','DOI: 10.1234/different'),encoding='utf-8')
            records,issues,_=importer.scan(source, {'Maps':'Maps'})
            self.assertEqual(records,[])
            self.assertTrue(any(x['code']=='metadata_conflict' for x in issues))

    def test_reviewed_authors_survive_repeat_import_without_recopying(self):
        parent=importer.LOCAL/'tests';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            base=Path(directory);source=base/'source';source.mkdir()
            self.fixture(source)
            output=base/'output';output.mkdir()
            (output/'category-labels.json').write_text(json.dumps({'Maps':'Maps'}),encoding='utf-8')
            importer.run(source,output)
            raw=json.loads((output/'inventory.json').read_text(encoding='utf-8'))['records'][0]
            note=next(v for v in raw['variants'] if v['path']==raw['canonical_note'])
            translation={raw['id']:dict(note_sha256=note['note_sha256'],title='Reviewed title',author='First Author; Second Author')}
            (output/'english.json').write_text(json.dumps(translation),encoding='utf-8')
            importer.run(source,output)
            repeat=importer.run(source,output,True)
            record=json.loads((output/'catalog.json').read_text(encoding='utf-8'))['records'][0]
            self.assertEqual(record['author'],'First Author; Second Author')
            self.assertEqual(repeat['summary']['unchanged'],1)
            self.assertEqual(repeat['summary']['images_to_copy'],0)

    def test_conflicting_pdf_registry_does_not_choose_a_title(self):
        with tempfile.TemporaryDirectory() as directory:
            source,_,registry=self.fixture(directory)
            registry.append(dict(doi='10.1234/example',title='Another paper',first_author='Another Author'))
            (source/'PDF原文/sources.json').write_text(json.dumps(registry),encoding='utf-8')
            records,issues,_=importer.scan(source, {'Maps':'Maps'})
            self.assertEqual(records,[])
            self.assertTrue(any(x['code']=='pdf_registry_conflict' for x in issues))


class EncodedNoteEvidenceTest(unittest.TestCase):
    def test_percent_encoded_image_name_matches_original_block_without_changing_its_hash(self):
        from urllib.parse import quote
        import hashlib
        import pdf_gallery
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory);filename='Example_Fig1_完整.png'
            block='Example\n\n![panel]('+quote(filename)+')\n'
            (source/'notes.md').write_text('## '+block,encoding='utf-8')
            evidence=pdf_gallery.current_note_evidence(source, {'variants':[{'path':'notes.md','filename':filename}]})
            self.assertEqual(evidence[0]['status'],'matched')
            self.assertEqual(evidence[0]['sha256'],hashlib.sha256(block.encode()).hexdigest())


class ArticleLicenseSignalsTest(unittest.TestCase):
    def test_publishing_licensee_does_not_cancel_explicit_reuse_license(self):
        import pdf_gallery
        text='Copyright 2020 The Authors; exclusive licensee AAAS. This is an open-access article distributed under the Creative Commons Attribution NonCommercial License 4.0.'
        row=pdf_gallery.license_candidate([{'blocks':[{'text':text,'bbox':[0,0,1,1]}],'links':[]}])
        self.assertEqual(row['candidate'],'CC BY-NC 4.0')
        self.assertFalse(row['conflict'])

    def test_exclusive_publishing_statement_without_cc_still_requires_permission(self):
        import pdf_gallery
        row=pdf_gallery.license_candidate([{'blocks':[{'text':'The Author(s), under exclusive licence to Springer Nature.','bbox':[0,0,1,1]}],'links':[]}])
        self.assertEqual(row['candidate'],'Publisher exclusive license / permission required')


class RegisteredPdfIdentityTest(unittest.TestCase):
    def test_late_doi_requires_exact_registered_path_and_hash(self):
        import pdf_gallery
        pdf={'dois':[],'document_dois':['10.1234/example'],'sha256':'a'*64}
        entry={'sha256':'a'*64}
        self.assertTrue(pdf_gallery.registered_pdf_match('10.1234/example','paper.pdf',pdf,entry,'paper.pdf'))
        self.assertFalse(pdf_gallery.registered_pdf_match('10.1234/example','other.pdf',pdf,entry,'paper.pdf'))
        self.assertFalse(pdf_gallery.registered_pdf_match('10.1234/example','paper.pdf',pdf,{'sha256':'b'*64},'paper.pdf'))
        self.assertFalse(pdf_gallery.registered_pdf_match('10.1234/other','paper.pdf',pdf,entry,'paper.pdf'))


class ArticleAndDataLicenseTest(unittest.TestCase):
    def test_explicit_article_license_is_distinguished_from_dataset_notice(self):
        import pdf_gallery
        blocks=[{'text':'The data are distributed under Creative Commons Attribution NonCommercial 4.0.','bbox':[0,0,1,1]},
                {'text':'Open Access This article is licensed under a Creative Commons Attribution 4.0 International License.','bbox':[0,0,1,1]}]
        row=pdf_gallery.license_candidate([{'blocks':blocks,'links':[]}])
        self.assertEqual(row['candidate'],'CC BY 4.0')
        self.assertEqual(len(row['evidence']),2)

    def test_license_word_and_hyphenated_noncommercial_are_supported(self):
        import pdf_gallery
        for notice,expected in [('Copyright The Authors. Distributed under a Creative Commons Attribution License 4.0 (CC BY).','CC BY 4.0'),
                ('This article is licensed under Creative Commons Attribution-NonCommercial-NoDerivatives 4.0.','CC BY-NC-ND 4.0')]:
            row=pdf_gallery.license_candidate([{'blocks':[{'text':notice,'bbox':[0,0,1,1]}],'links':[]}])
            self.assertEqual(row['candidate'],expected)
