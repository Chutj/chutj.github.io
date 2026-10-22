"""Candidate previews never constitute public approval."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from preview_gallery_candidates import validate_candidates, ROOT
from public_gallery_schema import metadata_hash, validate_rights
from test_public_gallery import fixture


class CandidateTest(unittest.TestCase):
    def test_candidates_fail_public_approval_and_require_modification_notice(self):
        record, _ = fixture()
        rights = dict(record['rights'], status='candidate-needs-final-confirmation',
                      public_use_allowed=False, human_reviewed=False)
        with self.assertRaises(ValueError):
            validate_rights(rights)
        for field in ('modification_status', 'additional_credit'):
            bad = dict(record['rights']); bad.pop(field)
            with self.assertRaises(ValueError):
                validate_rights(bad)

    def test_candidate_hashes_and_audit_scope_fail_closed(self):
        base = ROOT / '.gallery-local/tests'; base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temporary:
            root = Path(temporary); private = root / '.gallery-local'
            (private / 'assets').mkdir(parents=True)
            record, _ = fixture(); content = b'test-image-byte-fingerprint'
            digest = hashlib.sha256(content).hexdigest()
            current = dict(record, asset=f'gallery-private/{digest}.png', pdf_reference={'evidence_sha256': 'b'*64})
            candidate = copy.deepcopy(record)
            candidate.update(source_image_sha256=digest,
                             catalog_sha256=hashlib.sha256(json.dumps(current, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                             metadata_sha256=metadata_hash(record))
            candidate['rights'].update(status='candidate-needs-final-confirmation', human_reviewed=False, public_use_allowed=False)
            def write(name, data):
                (private / name).write_text(json.dumps(data), encoding='utf-8')
            write('catalog.json', {'records': [current]})
            write('audit.json', {'figures': {record['id']: {'review_status': 'Likely permitted', 'source_image_sha256': digest}}})
            write('candidates.json', {'audit_path': 'audit.json', 'records': [candidate]})
            asset = private / 'assets' / (digest + '.png'); asset.write_bytes(content)
            self.assertEqual(len(validate_candidates(root)), 1)
            asset.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'Image bytes changed'):
                validate_candidates(root)
            asset.write_bytes(content)
            candidate['title'] = 'Changed after preparation'
            write('candidates.json', {'audit_path': 'audit.json', 'records': [candidate]})
            with self.assertRaisesRegex(ValueError, 'metadata changed'):
                validate_candidates(root)
            write('candidates.json', {'audit_path': '../outside.json', 'records': [candidate]})
            with self.assertRaisesRegex(ValueError, 'private directory'):
                validate_candidates(root)


if __name__ == '__main__':
    unittest.main()
