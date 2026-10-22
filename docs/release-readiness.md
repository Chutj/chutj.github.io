# Local and public Figure Gallery release boundary

## Two data paths

Local preview uses the ignored `.gallery-local/catalog.json` and its private asset
mount. It is enabled only by `hugo server`, the development environment and the
explicit local overlay. Continue using `scripts/update-gallery.ps1` and
`scripts/preview-gallery.ps1`. PDF evidence enrichment of the same 46 records is
documented in [pdf-review.md](pdf-review.md); raw evidence remains private.

Production uses only `data/gallery/public.json` and the explicit approvals in
`data/gallery/allowlist.json`. Neither the production template branch nor the CI
validator reads `.gallery-local/`. The public dataset, approval list and allowed
image-host list are initially empty. With zero approved figures the Gallery
shows its English heading, introduction and Coming soon / No public figures
available message, without private record counts, controls, paths or metadata.
Home and navigation continue to work.

## Explicit public approval contract

No image is approved merely because its article is online, it is in the FIG
library, or a license name can be guessed. For a future approved entry, both
the local rights record and the committed whitelist must explicitly agree.
The exporter never approves records or changes either set of rights.

Each whitelist entry pins a stable record ID, the source image SHA256 and the
exact reviewed English metadata SHA256. Its `rights` object must include:

- `status: approved`, `public_use_allowed: true`, `human_reviewed: true`;
- `approved_by` and an `approved_at` date (YYYY-MM-DD);
- `permission_basis` (`license` or `written_permission`), `license`, and
  `license_url` (required for license-based use);
- `evidence_reference`, an opaque ID for the reviewed permission evidence;
- `review_evidence_sha256`, the current private PDF/credit/license evidence hash;
- the complete required `attribution` text.

Keep private permission emails/contracts outside Git. An opaque evidence ID can
refer to them without committing personal details or local file paths. Reviewers
must decide what attribution and reviewer identifier are appropriate to publish:
the public JSON is public, including its rights fields.

An entry also specifies HTTPS `image`, `thumbnail` and optional responsive
`srcset` URLs. Image hostnames must be explicitly listed in `image_hosts`. Private
hosts, HTTP, local file paths, credentials, query tokens and fragment-bearing
URLs are rejected. Create separate OSS thumbnail objects instead of committing
expiring signed URLs. No placeholder OSS URL is included in the real dataset.

All five English description sections must be reviewed. Original private fields,
local paths, storage credentials and arbitrary extra fields are forbidden in
public records. Scientific content and image hashes must match the approval;
changed metadata or image content requires renewed review. Human approval is a
review process, not a claim this software can independently verify.

Future export commands, only after permission review and OSS preparation:

```powershell
python scripts/export_public_gallery.py --dry-run
python scripts/export_public_gallery.py --apply
python scripts/validate_public_gallery.py
```

The exporter's default is read-only. It refuses partial export when pinned
approvals are stale or missing. It copies no images and performs no OSS upload.
The committed `public.json` is a sanitized snapshot; CI does not regenerate it
from private data. Direct Hugo builds have a second whitelist/hash/URL gate,
so unapproved and edited records are also withheld when CI validation is skipped.
The existing masonry/search/sort/detail component is reused for approved public
records, with public attribution; private assets retain their local-only URL gate.

## Clean checkout verification

```powershell
python scripts/check_release_snapshot.py
```

This makes an actual clean clone of committed HEAD and initializes its pinned
PaperMod submodule. It builds that version first. It then overlays only files
Git considers commit candidates into the disposable clone, creates a temporary
Git tree (not a commit), archives that tree, and checks out the pinned theme in
the candidate snapshot. Ignored files are never copied. The candidate has no
`.gallery-local/` directory, and the source repository's index and HEAD are checked
for changes. Any staging happens only in the disposable clone.

The candidate runs the public validator with Python `-S` (no site packages),
Hugo v0.168.0 production build, and output inspection. Reports and outputs stay
under ignored `.gallery-local/release-checks/`. The checks inspect actual tracked
paths, archive contents, built files and unauthorized private IDs, not just ignore
patterns. This simulates the clean filesystem and build commands on Windows;
it does not claim a hosted Linux Actions run or a deployment has taken place.

The report distinguishes the actual committed HEAD from candidate files. Before
the first Gallery source commit, HEAD can build successfully without containing
`/gallery/`. A passing candidate snapshot alone does not prove those files have
been committed. Review the report's `candidate_changes` before staging.

The existing workflow now validates the public whitelist before Hugo and checks
the actual publish output before uploading the Pages artifact. It still uses
Hugo v0.168.0, recursive submodules and GitHub's official Pages actions. These
public checks need only Python's standard library, not FIG files, Pillow, Node,
OSS credentials or a local absolute source path.

## Safe next commit and launch steps

After review, source code/configuration that can be committed includes:
`hugo.toml`, `.gitignore`, the gallery content page, the test article's draft flag,
`layouts/`, `assets/css/`, `assets/js/`, `scripts/`, `docs/`, the empty
`data/gallery/` contract and the updated existing workflow. Keep the pinned
PaperMod submodule and `.gitmodules`. README and the root test HTML are unchanged.

Do not commit `.gallery-local/`, generated `public/`, resource caches, Python
bytecode, private permission evidence or credentials. Existing ignored images
do not need to be deleted to produce a clean public build.

Before launch, review the candidate diff and repeat the clean snapshot checks,
then explicitly authorize committing and pushing the complete source set. Check
the actual hosted Actions build/deploy result and the public Home/Gallery URLs.
No changes to the current Pages setting are needed if its Source is already
GitHub Actions. It is safe to launch the empty public Gallery first. Publish real
images only after per-image permission review, public-safe English metadata,
OSS host/object/thumbnail setup and an explicitly approved export.

Policy tests use clearly synthetic fixtures in ignored test directories; they
never grant real FIG records publication permission or modify the real whitelist.
