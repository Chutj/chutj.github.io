# Private PDF references and rights review

FIG sources are read-only. This extends the existing private catalog and never
copies PDFs into the site or grants publication permission. Local import needs
Python 3.10+, Pillow and PyMuPDF. Public CI uses only standard Python and Hugo.

## Commands

Run from the website repository:

```powershell
# Full incremental import, including new FIG images and PDFs
.\scripts\update-gallery.ps1 -DryRun -Json
.\scripts\update-gallery.ps1

# Enrich only the currently imported records; no additional images
python scripts/pdf_gallery.py --dry-run --json
python scripts/pdf_gallery.py
.\scripts\preview-gallery.ps1

python -m unittest discover -s scripts -p 'test_*.py' -v
python scripts/check_release_snapshot.py
```

Both Python entry points accept `--source` and `--output`. Saved local settings
take precedence over the historical home-relative FIG default. `PDF原文/` is
the inspected source convention; missing PDFs are diagnosed, not guessed.
Dry-run writes nothing, including no parser cache.

## Matching and extraction

`PDF原文/sources.json`, in-document DOI in the first two pages, title words and
SHA-256 identify PDFs. Absolute registry paths are ignored. Paths outside the
source are rejected. A stale filename can match an identical checksum and DOI;
the discrepancy remains in the report. New versions can match DOI/title, but
ambiguous contents are not silently chosen. An unregistered PDF requires a
unique in-document DOI and title cross-check. Filenames alone never establish
identity.

Unique main-text `Fig. N |` / `Figure N:` blocks locate captions. Same-size,
geometrically overlapping text in the other column is retained as a candidate
continuation. Body references are stored separately. Extended Data labels and
body-only mentions do not count as main captions. Duplicate labels remain
ambiguous. Page numbers are 1-based file pages, not printed labels; bounding
boxes support visual checks. Extraction is not OCR or proof of panel/crop
correspondence. Image-only PDFs, unusual layouts and failures need manual work.

## Private data

Everything below remains in ignored `.gallery-local/`:

- `pdf-cache/<SHA256>-v<parser-version>.json`: text, geometry, DOI, captions and
  license candidates. Unchanged content is not parsed again.
- `catalog.json`: existing cards plus small local PDF/review summaries. Raw
  captions, body quotations and full PDF paths are excluded from browser data.
- `inventory.json` / `state.json`: original Chinese notes, evidence references,
  stable identities, source fingerprints and rights invalidation.
- `pdf-review.json`: per-paper/per-figure evidence, caption location, license,
  credit candidates, attribution requirements, unresolved issues and actions.
- `review-index.md` / `reviews/<doi>.md`: index and separate paper reports.
- `english-candidates.json`: editorial paraphrases pinned to evidence hashes,
  separate from existing reviewed translations in `english.json`.
- `official-evidence.json`: optional deliberately collected official-page URL,
  access date, content hash and rights excerpt. Normal import is offline and
  never sends local PDFs to a service or refreshes remote pages automatically.

Existing reviewed descriptions are preserved. Editorial candidates are drafts.
Future records initially receive a clearly labeled extraction scaffold, not a
scientific interpretation invented from a Figure number. Changed evidence
withholds stale drafts. Moving a draft into reviewed English notes remains a
human action.

Evidence fingerprints include PDF bytes, caption, article license, image bytes,
original note hashes and captured official-page evidence. Changes reset local
rights to unverified and public use to false. The explicit public whitelist now
also pins `rights.review_evidence_sha256`; export rejects a stale review even
when image bytes are unchanged. An already exported public snapshot cannot
inspect a private library: re-export/review it for each later release.

PDF-only refresh also hashes the current selected Markdown blocks without
overwriting the retained Chinese snapshot. A later full FIG import can flag old
English translations for re-review if source notes or even provenance links have
changed. Review that plan before applying it; it can also discover new images.

## Human review

`restricted`, `needs-review` and `unverified` are automated triage candidates.
The pipeline never generates final `permitted`. Publication requires the
separate human-reviewed whitelist and reviewed English metadata.

Article licenses and figure credit candidates are distinct. Caption scans
recognize reproduction/permission notices, BioRender and licensed basemaps.
No detected exception is not proof that third-party rights are absent. Inspect
the rendered image, complete caption, credit lines and supplementary terms.
The report gives a permission route; verify the actual rights holder instead
of inferring one from the first author. Conflicting PDF/page evidence needs
manual resolution.

Review display, crops, adaptation, downloads and site purpose individually.
CC BY-NC-ND restricts commercial use and distributing adapted material; merely
changing format is not automatically an adaptation. Cropped panels require a
context-specific assessment. CC BY requires attribution, license links and
change notices. Third-party CC BY-SA basemap or illustration credits require
separate scope review. Exclusive-license material stays out unless an explicit
permission or another applicable basis is established. This is review assistance,
not a legal conclusion.

Official terms: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/),
[CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/),
[Springer Nature permissions](https://www.nature.com/reprints).

Only scripts, tests, templates, config, frontend assets and public documentation
are commit candidates. PDF caches, drafts, extracts, source images and review
evidence are private. The validator inspects actual Git tracking and publish
output in addition to `.gitignore`. See [release-readiness.md](release-readiness.md).
