# Bakken Subsurface Analytics: public data release record

Prepared October 17, 2026 for the static website at `https://bakkensubsurface.com`.
This record describes the intended publication package and known provenance
limitations. It is not a license grant, legal opinion, or confirmation of rights
that have not been established. Only `dist/` is intended for hosting; this document
and local source/audit work remain outside the deployment directory.

## Intended public package

Anything served by the static website is publicly retrievable, including data
requested only after a visitor selects a feature. Splitting a large file, omitting
directory listings, or excluding a path in `robots.txt` does not restrict access.

| Public asset family | Intended contents | Provenance and interpretation |
| --- | --- | --- |
| Website and viewer code | Homepage, methodology, viewer HTML/CSS/JavaScript, bundled viewer dependencies, screenshots | Project-authored presentation plus third-party dependencies. Preserve applicable notices from the source package. Do not infer a data license from the application code license. |
| `/full-dataset/manifest.json`, overview, station tiles | Prepared October 17, 2026 well branches, identifiers, attributes, and relative-TVD geometry | Derived from the official ND DMR horizontal-survey GIS snapshot. 48,929 branch records, 22,498 permit/API10 well identities, and 5,495,609 prepared stations. A mapped branch is not a verified completion or a new drilling event. |
| `/full-dataset/metrics.json`, metric tiles and section scales | Survey-derived direction, inclination, DLS/curvature, local tortuosity, depth, departure, and section color scales | Derived calculations from the same prepared survey geometry/MD. Geometric section labels and drillback candidates are not confirmed operational histories. |
| `/full-dataset/operators.json` | Reported current operators, display groups, palette and filters | Joined from the October 17 ND DMR well-attribute snapshot. Group aliases are display conveniences; they do not establish historical operator identity, ownership, or working interests. |
| `/full-dataset/production.json` and oil binary/parts | Matched monthly well-level oil/condensate volumes, month identities, missingness, and aggregate coverage metadata | Derived from user-supplied historical exports identified as DMR reports: 2000–2023 CSV, 2024 workbook, and 1951–1955 workbook. Available observations cover January 2000–December 2024 plus a separate limited December 1952–December 1955 series. No supplied 1956–1999 or 2025–2026 coverage. See the unresolved provenance item below. |
| `/viewer/data/dsu/` | Original published DSU footprints and source attributes, separate display bands, approximate depth intervals, saved historical inventory comparison, and geometric well-membership index | October 17 ND DMR DSU source; September formation controls and historical screening-model values remain separately dated. Exact within-well line union and positive-length XY intersection support membership; this is not legal well assignment or operator attribution. Original footprints are retained. |
| `/viewer/data/inventory/footage.json` | Measured DSU/township eligible acreage and mapped classified lateral plan footage, coverage, methods, and source hashes | EPSG:5070 calculations from the current detailed survey and original DSUs. Unverified targets/completions remain unverified. The artifact contains observations; density scenarios are applied in the interface. Independent DSU rows overlap and are nonadditive. |
| `/viewer/data/inventory/townships.geojson` | Full supplied township boundaries dissolved by township/range/direction keys | Derived PLSS reference geometry. Footage eligibility is the township intersection with the union of reported-Bakken DSUs, not full-township prospective acreage. Missing principal-meridian identity is not invented. |
| `/viewer/data/reference/` | North Dakota boundary, selected places, reference metadata | U.S. Census Bureau TIGERweb, January 1, 2026 vintage, retrieved September 12, 2026. State geometry is generalized for display; city positions are Census internal points. These are orientation layers, not a cadastral survey or Bakken extent. Preserve the packaged source attribution. |
| Explicitly selected sample/showcase assets, if packaged | Smaller prepared subsets used by optional showcase routes | Same source/provenance limits as the full dataset. Their exact release presence is determined by the final staged package, not this list. |

The integration process may split the DSU GeoJSON and production binary into
smaller static files. Reconstructed content must pass exact-byte SHA-256 checks.
Transport parts do not change the data meaning or resolve provenance questions.

## Source access and terms observed

The [ND DMR GIS download page](https://gis.dmr.nd.gov/gisdownload.asp), checked
October 17, 2026, provides downloadable horizontal surveys, wells, DSUs and
reference shapefiles. It identifies NAD83/ESRI PRJ files and includes a state
accuracy/reliance disclaimer: information may be incorrect or out of date and the
state does not warrant accuracy or reliability. Retain source attribution and the
project's snapshot date. That disclaimer is not, by itself, an express
redistribution license. This review did not establish an explicit open-data
license for the downloaded layers; do not label them public domain or CC0 without
additional source evidence.

Spacing source context is available from the [DMR well-permitting
page](https://www.dmr.nd.gov/dmr/oilgas/wellpermitting). The viewer is independent of
the agency. State publication of a footprint does not make the project's estimated
depth box, nested display band, historical screening model, or footage scenario an
official state interpretation.

## Unresolved production provenance

The production inputs were supplied as local spreadsheets/CSV. Their names and
contents identify them as historical DMR-style exports, but possession of those
files and public availability of related state statistics do not independently
establish the original download location, applicable export terms, or permission
to redistribute this exact prepared series. No independent licensing confirmation
was obtained in this review. The exact-source hashes are retained in local audits;
personal source paths must not be published.

Before describing the production release as cleared, record the original source
URL or official export mechanism, the relevant terms or permission, the person/date
of confirmation, and any required attribution. Until established, this item stays
unresolved. The public page may accurately describe supplied historical exports;
it must not claim an official live feed, agency endorsement, a public-domain
license, or complete historical coverage. This document does not resolve the
publication decision on the operator's behalf.

## Interpretation that must travel with the release

- Survey and operator snapshots are dated October 17, 2026. Production ends in
  December 2024; present geometry is held fixed during playback.
- Mapped lateral plan footage is a drilling-geometry proxy, not verified completed
  or perforated footage, reservoir depletion, reserves, EUR, or drillable inventory.
  Coincident stacked paths within a well can be collapsed when target evidence is
  unavailable; separate wells remain separate.
- Scenario densities of 49.5/66/82.5 ft per acre are illustrative. The 66 case is
  eight two-mile equivalents per 1,280 acres; ±25% cases are not calibrated ranges
  or confidence bounds. A positive residual does not demonstrate feasible locations.
- DSU footprint measurements and whole-well group production are nonadditive across
  overlapping DSUs. Township measurements use a separate union-clipped ledger;
  source gaps/overlaps remain explicit.
- Approximate DSU depths use a provisional KB/per-well relative-TVD convention,
  without reference-elevation correction. They are neither legal vertical limits
  nor verified formation surfaces. Inward bands and exploded depth display are
  symbols, not setbacks.
- The optional September 12 historical screening comparison uses September 7 GIS
  and exact supported matches only. It was not recalculated for October and is
  under review. Gray/unavailable is never silently converted to zero.
- Reported operators and display groups are not historical ownership or undeveloped
  acreage-control evidence. Geometric well association is not a legal assignment.
- The live methodology page must remain reachable from the homepage and viewer.

## Excluded from the public static package

- Raw LAS/logs, private log catalogs and indexes, local log APIs, DBF source files,
  personal spreadsheets, raw production workbooks/CSV, and local database files.
- Private inventory workbooks, historical audit workspaces, source-code snapshots
  containing personal paths, and standalone local validation/audit outputs unless
  separately reviewed and intentionally selected.
- Tokens, credentials, `.env` files, `.git`, source archives, local server scripts,
  absolute desktop/document paths, machine usernames and unrelated working files.

The static viewer must show that local log services are unavailable rather than
requesting private `/api` endpoints or implying that log records are hosted.
No user accounts, uploads, or private-data access are introduced by this release.

## Release verification record

Before publication, the integration owner should retain a machine-readable
inventory of hosted paths, byte sizes and hashes; verify the immutable full survey
manifest against dependent membership/footage fingerprints; verify split-file
reconstruction; scan staged text/JSON for personal paths and secrets without
printing secret values; and exercise production, DSU selection and township
footage in a clean static-host preview. Readiness checks establish package
integrity and intended exposure, not legal rights or scientific calibration.

### Independent bounded staging check — October 17, 2026

The staged package was checked after public integration, without modifying the
viewer or its data:

- Parsed methodology links/anchors and the sitemap; all three local route targets
  and all seven page anchor targets existed. Canonicals use the requested domain.
- Scanned 60 text assets (43,118,838 bytes) plus the reconstructed DSU GeoJSON for
  Windows/personal Unix paths, file URIs, recognizable private-key/token formats,
  and loopback URLs. No private-path, token-pattern or loopback findings occurred.
  One `file://` match is an explanatory comment in the bundled Three.js source,
  not a source path or network request.
- Found no staged LAS, DBF, spreadsheets/CSV, database, source ZIP, `.env`, or Git
  working files in this bounded inventory.
- Reconstructed production oil (28,073,448 bytes) and DSU GeoJSON (33,046,802 bytes)
  from the staged transport parts; both matched their declared complete SHA-256.
  The reconstructed DSU content also parsed as JSON.

Pattern scans are not proof of the absence of every secret or provenance defect.
This task did not deploy, modify original datasets, establish production
redistribution terms, or certify future changes to the package. Browser/static
runtime verification and the final deployment record belong to the integration
and release owner. The unresolved production item above remains unresolved after
these integrity and exposure checks.
