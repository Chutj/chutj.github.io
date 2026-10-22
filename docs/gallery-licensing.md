# Figure licensing and candidate previews

The Gallery notice and per-figure credits describe individual permissions; they
do not grant rights, override third-party exceptions or license the collection
as a whole. Rights review requests use the contact channel in the notice.

The real production allowlist remains the sole publication gate. A candidate is
not approved: its status is `candidate-needs-final-confirmation`, and both
`human_reviewed` and `public_use_allowed` remain false. Public rights now require
an explicit modification status and additional-credit notice as well as the
existing attribution, license, evidence fingerprint and human approval fields.
Evidence or image changes require reassessment.

## Isolated preview

The ignored `.gallery-local/candidates.json` contains prepared English records,
source/catalog/metadata hashes and a reference to the local audit. It contains no
automatic approval. The preparation script validates all these before writing.

```powershell
python scripts/preview_gallery_candidates.py --dry-run
python scripts/preview_gallery_candidates.py --hugo <verified-hugo.exe-path> --serve
```

The second command creates a unique ignored snapshot inside
`.gallery-local/candidate-previews/`, copies only selected image assets, creates
proportional WebP thumbnails, and builds in Hugo's `production` environment.
The candidate-data partial override exists only in that disposable snapshot.
The main website's strict public partial is never replaced. The preview server
binds to `127.0.0.1:1316`, uses memory rendering, and prominently labels candidates
as pending final confirmation. Do not publish this preview directory or its build
output. It is intentionally separate from deployable production output.

The full private Gallery remains available using `scripts/preview-gallery.ps1`.
A normal production build without private data continues to show an empty
Gallery until explicitly approved records and approved public media URLs exist.

Before real publication: confirm the selected records, retain required credits,
review the exact image/version and modification statement, then separately
authorize media hosting. For OSS, use dedicated public objects with stable hash
names and proportional thumbnails, allowlist the exact HTTPS image host, and
never upload PDFs, private metadata, review evidence or credentials. Pin the
final image, metadata and evidence hashes in the actual approval record. Run
the public validator and clean-checkout build again. Neither this script nor
the licensing notice performs these publication steps.
