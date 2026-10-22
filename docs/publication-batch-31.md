# First complete publication batch

On 2026-10-22 the website owner explicitly authorized publication after final
verification, confirming free, noncommercial academic learning and visualization
reference use. The batch has **31 distinct images**: one CC BY 4.0 figure and
30 CC BY-NC-ND 4.0 figures. Seventeen use verified publisher Versions of Record;
14 use explicitly licensed publisher Article in Press versions. The latter are
identified in each detail panel and must not be silently replaced by a later
version. Six imperfect source selections were replaced by four complete original
figures; the three Figure 5 selections from Sabut et al. share one full figure.

## Evidence and display scope

The saved publisher PDFs, DOI/title/authors, per-figure captions, credit lines,
license notices and official article rights statements were cross-checked.
Article in Press PDFs are identified as such on the documents and in the original
source registry. Current official pages retain the corresponding NC-ND notice;
Bai and Sabut explicitly describe future replacement by the final version.
The final direct PDF-link attempts encountered publisher identity responses,
so no new publisher-byte match is asserted. The reviewed, hash-pinned saved
publisher versions remain the selected sources. PNAS's article page presents a
verification challenge; its saved final publisher PDF page 1 explicitly supplies
the article-specific license. Challenges are not treated as article evidence.

Unaltered full figures or accurately identified panel excerpts remain independent
reference items. They have not been recolored, relabeled, redrawn or recombined.
Complete replacements were rasterized directly from the licensed PDF, keeping
all panel content and layout. Thumbnails use proportional resizing and technical
WebP conversion. Short descriptions are independently written summaries.
NC-ND permits noncommercial reproduction in whole or part; technical conversion
and unaltered excerpts are assessed under the actual display context, not a
blanket rule that every crop is either prohibited or allowed. See the
[license](https://creativecommons.org/licenses/by-nc-nd/4.0/legalcode.en) and
[CC FAQ](https://creativecommons.org/faq/#can-i-reuse-an-excerpt-of-a-larger-work-that-is-licensed-with-the-noderivs-restriction).

Third-party scope remains figure-specific. Sabut Figure 2 f–g (BioRender) and
Hadi Figure 1 (TM World Borders / SA scope) are excluded, together with the
19 source selections lacking permission. Sabut's a–c and d–e excerpts exclude
f–g entirely. Identified Natural Earth map credits are retained; public-domain
basemap data does not make the full scientific graphic public domain.

Each public record retains full authorship, original paper, journal/year, DOI,
copyright/publisher credit, license link, source version and modification notice.
New versions or changed use require review again; no endorsement or blanket
collection license is implied.

## Existing approval and export contract

The existing public allowlist, public record schema and exact media hash manifest
remain mandatory. Only selected images and their three proportional thumbnails
are tracked in `static/figures/approved/`. No PDF or original source tree is
published. The current size is well below Pages limits; no OSS service or keys
are required.

The private `publication-records.json` stores explicitly approved publication
variants, alongside rather than replacing the complete source catalog. It uses
the same public record and approval fields. The exporter verifies each variant's
actual image, audit fingerprint and all underlying source record bindings.
Source-image, imported PDF evidence or source-metadata changes require
reassessment. Private paths and bindings are never serialized into public data.
CI consumes only already reviewed public JSON and approved media, without the
FIG source or private directory. Importing a new image does not grant approval.

Future additions reuse the same process: import locally, verify version and
figure rights, prepare the exact display file and credits, obtain explicit
approval, pin image/metadata/evidence/media hashes, export, validate the clean
production build, then commit and deploy with authorization.
