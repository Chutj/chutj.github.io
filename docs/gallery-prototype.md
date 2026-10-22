# Local FIG → Figure Gallery pipeline

This site scans the existing external FIG library automatically. There is no
hand-maintained card list, and no database or translation service is required.
Run commands from the website repository. Python 3.10+ and Pillow are required;
PDF enrichment also needs PyMuPDF. The current Windows environment has these
dependencies. See [pdf-review.md](pdf-review.md) for evidence/review commands.

## Commands

```powershell
# Read-only counts, diagnostics and planned data/image file writes
.\scripts\update-gallery.ps1 -DryRun

# Full machine-readable plan, including every path and record action
.\scripts\update-gallery.ps1 -DryRun -Json

# Apply the local incremental update
.\scripts\update-gallery.ps1

# Start the private, loopback-only Hugo preview
.\scripts\preview-gallery.ps1
```

Equivalent Python commands are `python scripts/import_gallery.py --dry-run`,
`python scripts/import_gallery.py --dry-run --json`, and
`python scripts/import_gallery.py`.

The importer resolves the source from `--source` / `-Source`, then the saved
`.gallery-local/settings.json`, then the existing linked FIG location under
`~/WorkBuddy/LiteraturePush/绘图参考`. No file in that source is changed. Source
PDFs, original full-figure folders, and verification scripts are not imported.
Run updates after FIG has finished writing its files; concurrent importer runs
are not supported.

The local preview is `http://localhost:1313/gallery/`. An active preview reloads
through the local configuration's catalog revision, including metadata-only
changes. Identical runs leave the catalog, configuration and image mtimes alone.
Dry-run writes nothing, including no report file. Apply writes diagnostics to
`.gallery-local/last-report.json`; its own path is included in the report.

## Scanning and identity

The scanner reads all category folders, their Markdown tables and per-figure
sections, and the source-paper registry. It recognizes the inspected field-label
variants, retains additional raw fields, and extracts journal, year, DOI, figure
panels, paper title, first author, category membership, descriptions and recorded
hex color literals. A recorded color literal is not automatically verified as
an author-used palette. Raw color notes and verification limits remain available.

Image SHA256 merges byte-identical cross-category copies. DOI plus normalized
figure/panel identity seeds a UUID for new records. State matches image hashes,
source paths and figure identity to preserve IDs after renames or image changes.
Distinct crops are not merged solely because they share a figure number. The
migration preserves the first ten prototype IDs. Ambiguous matches and conflicts
are diagnosed rather than silently relabeled.

Only changed or missing output images are copied. Content-addressed filenames
keep different image versions separate, with extensions based on actual image
format and without re-encoding. Metadata fingerprints identify source and
translation updates. Missing/quarantined records become inactive; their previous
state and old local asset versions are retained. No automatic file deletion is
performed. No run depends on a fixed number of figures or `selection.json`.

Global source/registry failures stop before publishing a new snapshot. Missing
images, malformed entries, unsupported formats and contradictory per-record
metadata are reported and isolated; valid records can still build. The importer
writes atomic snapshots and updates the watched Hugo overlay last.

## English descriptions

Source notes are mostly Chinese. Journal, DOI, figure and English paper titles
can be displayed immediately without inventing a scientific description. New
records use the actual figure/paper information as an English title. An English
placeholder explicitly states when the description is awaiting translation.

Reviewed translations in ignored `.gallery-local/english.json` are keyed by
stable ID (preferred) or legacy filename. They contain `title`, `sections`, and
`note_sha256` matching the canonical description's hash in `inventory.json`.
The five section names are What the figure shows, Statistics & symbols, Color &
encoding, Design lessons, and Verification & limitations. When the canonical
source changes, an old translation is withheld and marked `needs_review`.
Additional category-specific notes remain separately traceable in `variants`.

Unknown category names are still captured. ASCII names are reused; untranslated
names receive a stable English category code and a diagnostic. Add reviewed
labels in ignored `category-labels.json` without editing frontend JavaScript.
The built-in label dictionary translates the current 24-category source taxonomy.

## Generated private data (schema version 2)

All generated data lives under Git-ignored `.gallery-local/`:

- `catalog.json`: English-facing, active Gallery records, dimensions, categories,
  source metadata, description translation status, color literals and rights.
- `inventory.json`: structured source fields, Chinese titles, every original
  description variant, source paths, note hashes, image hashes and storage fields.
- `state.json`: stable identities, source fingerprints, active/inactive status,
  source-path aliases and per-image rights decisions.
- `assets/<SHA256>.<actual extension>`: incremental byte-identical local copies.
- `hugo.toml`: opt-in private asset mounts, catalog path and revision.
- `settings.json`: source location for subsequent one-command runs.
- `last-report.json`: counts, record actions, file writes and diagnostics.

Legacy sample selections and provenance remain available but no longer control
which records are imported. The importer never removes them.

## Publication boundary

The importer checks actual Git tracking and ignore behavior before writing. It
refuses to proceed if `.gallery-local/`, `public/`, generated resource caches or
private asset/static paths are tracked. It also requires output to be under the
ignored local directory and disjoint from the source. Review `git status` before
any later commit; never force-add ignored files.

Private figures are mounted as Hugo assets, not static files. The Gallery loads
its catalog and publishes private asset permalinks only when Hugo is a server,
the environment is development, and the private overlay is enabled. Ordinary
production builds and non-server development builds use only the separately
approved public dataset (currently empty, so they show the public placeholder),
including when the private overlay is supplied. Tests also inspect output files
and Git's tracked files, rather than relying on `.gitignore` alone.

Every new record starts with `rights.status = unverified` and
`public_use_allowed = false`. License, license URL, attribution, evidence,
approver and approval date are reserved but blank. Replacing image content or
correcting its source identity resets approval. Even a future manual rights
approval does not bypass the local-server guard. Public export requires a separate
explicit whitelist, pinned checksums and complete permission evidence. See
[release-readiness.md](release-readiness.md) for the current publication contract
and clean-checkout validation commands.

For OSS, first review each image's redistribution license and attribution.
Then define approved object keys, private/public bucket policy, thumbnail variants,
checksum verification and optional signed URLs. Storage fields already reserve
`provider`, `object_key`, `public_url` and `approved_to_upload` (false). Keep
credentials in local environment variables or a future deployment secret store;
never store them in Markdown, generated JSON or Git. No OSS upload is implemented
or authorized by this local importer.

## Validation and frontend

```powershell
python -m unittest discover -s scripts -p test_gallery_import.py -v
```

Tests copy real FIG material into ignored fixtures and mutate only those copies.
They cover no-write dry-run, no-op reruns, additions, metadata updates, duplicate
categories, renames, image replacement, rights reset, stale translations, missing
images, metadata conflicts and a real Hugo server serving valid records alongside
bad entries. The source is never used as the mutation target.

The frontend retains its shortest-column masonry, sorting, search, category filter,
Reset and zoomable details. Breakpoints remain 3 columns at 1100px and above,
2 columns at 360–1099px, and 1 below 360px. Responsive WebP thumbnails and native
lazy loading keep originals out of the overview's image requests. Home is unchanged.
