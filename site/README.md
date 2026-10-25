# Bakken Subsurface Analytics public site

This separate publishing checkout hosts the professional homepage, public viewer,
and methodology at `https://bakkensubsurface.com`. The existing local installation
and the GitHub source checkout remain separate.

`dist/` is the complete static deployment. The hosting identity is retained in
`.openai/hosting.json`; do not create another Site for this checkout.

The prepared public survey snapshot is dated October 17, 2026. Production is a
historical series ending December 2024. The public package includes the prepared
geometry/metrics, operator metadata, monthly oil, DSUs and footage scenarios.
Raw logs, workbooks, DBFs, private audit pages and local APIs are excluded.
Review `docs/PUBLIC-DATA-RELEASE.md` for provenance and interpretation details.

The homepage and methodology use the supplied Bakken logo with charcoal, sky
blue and lime accents. `brand.css` is loaded only by those pages; viewer styling
and data remain separate. The original logo PNG is preserved byte for byte,
with its whitespace framed by CSS. The compact favicon is an SVG interpretation
of its well-path mark. Bakken Forward and its Railway backend remain in staging;
this branding release adds no research routes or backend connection.

The homepage features the 75-second YouTube overview `Q2YHrcazXAg` below the
opening section. Its local poster loads without contacting YouTube; the
privacy-enhanced YouTube iframe is created only when the visitor presses play.
A separate Watch on YouTube link remains available. The homepage-only module
and responsive styles do not change the viewer or its data.

The October 18 trajectory display update adds continuous red drillback episodes
and cyan **U-turn laterals** in Well section mode. Cyan covers the full supported
continuous lateral block on a detected branch, preserving curve/vertical colors
and branch boundaries. DLS, operator and other metric views keep their existing
scales. The production shader preserves cyan for a U-turn even when production
is unavailable; missing values still produce no width. Faint/hidden path context
continues to override these display colors.
Mobile plan fitting reserves space for the camera controls, selected-well panel,
message and bottom buttons, keeping the complete U-turn clear of those overlays
while retaining the wellbore navigation pivot.

`full-dataset/well-shape-overlays.json` is an optional versioned sidecar bound to
the exact survey manifest and overview hashes. It contains only explicit branch
identities and retained overview/incoming-segment index ranges. It changes no
base section, geometry, metric, production, DSU membership or inventory file.
An invalid/stale sidecar falls back to saved section colors. “Use trajectory
refinements” provides the same baseline comparison; the cyan legend can hide
U-turn laterals independently. Regenerate and review the sidecar after a survey
refresh, rather than reusing branch IDs from another snapshot.

On mobile, compact camera/color/layer controls sit above the canvas. Production
playback starts collapsed; hiding it pauses playback and retains the selected
month and production sizing. DSU and township visibility can be toggled
independently. The Well paths selector offers full color, thin faint gray paths,
or hidden paths; faint/hidden views preserve the underlying production data and
color selections. Choosing a quick color view restores full-color paths.

Prepared JSON, GeoJSON and binary data larger than 4 KiB are stored as deterministic
gzip objects in content-hashed parts of at most 20 MiB. This keeps the complete
stored static release below the hosting artifact's 256 MiB expanded limit; the
local preflight uses a stricter 250 MiB target. Original logical data files are
not duplicated alongside their compressed objects.

The version-2 transport index records each original length/SHA-256, gzip
length/SHA-256, part length/SHA-256 and original MIME type. The bootstrap verifies
compressed parts and the joined gzip object, decompresses it with the browser's
`DecompressionStream('gzip')`, then verifies and returns the exact original bytes
to existing viewer loaders. A current HTTPS browser with Web Crypto is required;
unsupported browsers receive a clear message. Do not add a `Content-Encoding`
header to the `.gz.bin` objects: explicit decompression follows integrity checks.

Rebuild assets and the transport index together with
`scripts/prepare_public_viewer.py` in the parent workspace, then run
`python validate_release.py` and `node test_public_transport.mjs` in this checkout.
The validator checks stored size and every logical reconstruction; the transport
test exercises browser-compatible decompression and failure handling. Preserve matching survey, DSU,
membership and footage snapshots. The immutable public-parts cache rule remains
valid; the index and application files should continue to revalidate.

Local preview:

```sh
python -m http.server 58518 --bind 127.0.0.1 --directory dist
```

Publishing uses the Sites source-workflow helper, followed by save and deployment
of that exact pushed commit and archive. Do not publish local secrets or source
audits in `dist/`. Credentials are passed through hidden stdin, never committed.

The robots file and sitemap make the crawlable pages discoverable. Google Search
Console ownership verification and indexing status are external account state;
publication alone does not guarantee inclusion or ranking in search results.
