"""Exact publication file scope, independent of private FIG data."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from public_gallery_media import validate_media


class PublicMediaTest(unittest.TestCase):
    def test_only_exact_approved_bytes_can_be_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root/'data/gallery').mkdir(parents=True)
            path = root/'static/figures/approved/test/figure.png'; path.parent.mkdir(parents=True)
            content = b'policy-fixture-not-real-image'; path.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            url = 'https://chutj.github.io/figures/approved/test/figure.png'
            record = dict(id='fixture',image=url,thumbnail=url,srcset='',source_image_sha256=digest)
            policy = dict(approved_records=[record]); dataset = dict(records=[record])
            manifest = root/'data/gallery/media.json'
            manifest.write_text(json.dumps(dict(schema_version=1,files=[dict(id='fixture',url=url,sha256=digest)])))
            self.assertEqual(validate_media(root,dataset,policy),{'static/figures/approved/test/figure.png'})
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'bytes changed'):validate_media(root,dataset,policy)
            path.write_bytes(content); other=path.with_name('unapproved.png');other.write_bytes(b'unapproved')
            with self.assertRaisesRegex(ValueError,'Unapproved raster'):validate_media(root,dataset,policy)
            with self.assertRaises(ValueError):validate_media(root,dict(records=[]),dict(approved_records=[]))

    def test_unexpected_output_and_missing_output_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); output=root/'output';output.mkdir()
            (output/'unapproved.webp').write_bytes(b'not-approved')
            with self.assertRaisesRegex(ValueError,'Unexpected raster'):validate_media(root,dict(records=[]),dict(approved_records=[]),output)


if __name__ == '__main__':unittest.main()
