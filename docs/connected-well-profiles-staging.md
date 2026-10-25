# Connected well profiles: staging implementation

Implementation date: October 17, 2026, America/Chicago (some run timestamps are October 18 UTC). User scope: load available wells, historical production and DSUs into the separate Railway staging project, build connected profiles, and prepare a safe GIS/survey recalculation workflow. The public website and its prepared viewer outputs must remain unchanged. Premium DMR production access is pending; no credentials or new production observations were invented.

## Validated release

Release: `99d1a120b7181bf1d08ae38da55eaec2721798ac2bb5dce82a6e9a1a1ba908e1`.

Manifest SHA-256: `9c7d3306ef7b349ef08ae6d04f1654e29e565e647daf69d2218675b42f5ee858`.

Local immutable package: `work/bakken-forward-preview/data/well-bundle-20261018-v2/`. The superseded v1 package is retained; v2 adds the required production API identity bindings. Its six compressed data tables are byte-identical to v1.

| Population | Imported read-model records |
| --- | ---: |
| Wells from the public October 17 Wells snapshot | 44,005 |
| Mapped survey branches | 48,929 |
| Original DSU footprints | 10,573 |
| Positive geometric well–DSU lateral overlaps | 75,736 |
| Historical whole-well production months | 3,011,237 |
| Wells with historical production | 25,055 |
| Quarantined production identities | 504 |

The quarantined identities account for 42,526 original observations and remain in `well_issues`; their absence from the current registry does not establish zero production, abandonment or an invalid original report. These counts are separate from the historical inventory workbook's audit findings.

Production covers 348 explicitly supplied months: January 1952–December 1955 and January 2000–December 2024. The earlier years reflect the larger full-registry population, rather than only wells with displayed horizontal surveys. No 1956–1999 or 2025–2026 production is supplied. Current prepared data contains oil/condensate only; gas, water and producing days are not imported as zeros.

The exact valid imported total is **5,846,896,506 bbl**, used as an import reconciliation check, not a Bakken-only/lifetime/current-production statistic. Independent read-only SQL aggregation of matched source observations agrees. All current source oil values are integral; none came from the viewer's Float32 matrix. There are no invalid matched well-months in this release, although invalid/conflict handling is implemented and tested.

## Sources and identity

- Wells: `work/nd-refresh-2026-10-17/sources/wells/OGD_Wells.dbf`, original public NAD83 GIS snapshot. Complete source attributes remain in the record payload; zero TD and blank dates are normalized to unknown where appropriate.
- Surveys: `outputs/wellbore-viewer/full-dataset/manifest.json` and hash-bound geometry tiles, classified using v2.0. These contain 5,495,609 retained stations for 22,498 surveyed well identities. The SQL model stores branch summaries and tile/offset/count references; it does **not** duplicate all station rows in PostgreSQL. Prepared binary assets remain the 3D transport.
- DSUs: `dist/data/dsu/drilling-spacing-units.geojson`, original `Feature.geometry`, with source IDs and original attributes. Display insets, bands, approximate depth zones and old inventory predictions are excluded from the SQL footprint payload. Nominal acres and measured full polygon acres remain separate. Existing measured acres are bound to the exact manifest/DSU footage release and EPSG:5070 calculations.
- Membership: `dist/data/dsu/dsu-well-membership.json`, checked against the exact survey manifest and original DSU-file hashes. Positive unioned lateral plan-length overlap is retained; no UI overlap threshold is applied during import.
- Historical production: exact observations from `work/nd-refresh-2026-10-17/production/production-audit.sqlite`, representing the supplied 2000–2023 CSV, 2024 XLSX and historical XLSX. Original source-file hashes were computed successfully. Distributed metadata contains filenames/hashes, not local absolute paths.

Wells use normalized state file number plus complete API14 evidence. Branch identity hashes file number, API14 and source branch label; release-local manifest indices remain references, not persistent identities. Conflicts are quarantined. Production attaches once per whole well, never once per branch. Matching uses the full well registry, not the old audit's geometry-subset `matched` flag.

Distinct valid pools are summed once per well-month. Equal pool duplicates collapse once. Any missing/negative/invalid/conflicting pool invalidates the whole month; no partial sums. Unobserved months are absent from SQL and emitted as null in the bounded chart response. Reported zero remains numeric zero. Per-month source IDs refer to the fingerprinted audit; original row/line detail remains in that local audit rather than being copied into every API payload.

## PostgreSQL and API

Implementation under `work/bakken-forward-preview/`:

- `build_well_bundle.py`: immutable, fingerprinted six-table export; publishes `release.json` last. Standard-library builder; source files are opened read-only.
- `wells_schema.sql`: constrained PostgreSQL relational model.
- `wells_store.py`: explicit SQLite/PostgreSQL importer, ownership marker, atomic release publication, source revalidation, and targeted reader grants.
- `wells_backend.py`: bounded read-only search/profile/production/DSU API, repeatable-read transactions and literal parameterized searches.
- `verify_wells.py`: real PostgreSQL reader identity, effective permissions, counts, source-total and endpoint checks; also checks the original 80-record Forward sample remains available.
- `profiles/`: local responsive profile UI with name/file/API search, historical chart, branch table, geometric DSU relationships, provenance and 3D selection link. Mixed-release related responses are withheld until reselected.
- `prepare_connected_bundle.py`: fixed allowlist for the private API/import deployment. Original SQLite files, corpus, viewer binaries, local settings and credentials are excluded.

Tables:

- `well_app`: application/schema ownership marker.
- `well_releases` / `well_active`: immutable release metadata and one active pointer.
- `well_registry`, `well_branches`, `well_dsus`, `well_memberships`, `well_issues`: release-specific records and constrained relationships.
- `well_production_versions`, `well_production_identities`, `well_production`: independently shared production versions. The version hashes both compressed CSV content and complete file/API bindings. An unchanged production version is reused across GIS releases; new GIS metadata does not duplicate millions of historical rows. Reuse cannot bind old production to a changed API for the same file number.

All tables are added alongside the existing `forward_metadata` / `forward_records`. No old research/inventory output is deleted. PostgreSQL receives DSU polygons as source-CRS GeoJSON in JSONB and validated precomputed overlap rows; PostGIS installation and live server-side clipping are **not** part of this first release.

API routes:

```text
GET /api/wells/meta
GET /api/wells?q=NAME_OR_FILE_OR_API&offset=0&limit=20
GET /api/wells/19033
GET /api/wells/19033/production
GET /api/wells/19033/dsus
```

Search limit is 1–50; DSU details are bounded and explicitly report truncation. Runtime requests never create tables, import sources or repair missing data. An unavailable/unimported release returns 503, not an empty successful result. `BAKKEN_REQUIRE_WELL_RELEASE=1` adds well-release readiness to the existing `/health` check in staging. The runtime `forward_reader` receives SELECT-only access; a separate temporary owner connection is used for the explicit import and removed afterward.

## Local review and staging boundary

Start from `work/bakken-forward-preview`:

```powershell
python wells_store.py data/well-bundle-20261018-v2
python serve.py --port 58522
```

Review `http://127.0.0.1:58522/profiles/?well=19033`. This loopback preview reads an equivalent validated local SQLite projection; it is **not** a tunnel or live connection to Railway. The private Railway API reads PostgreSQL. No public API domain, TCP database proxy, public navigation/DNS change, customer sign-in or payment system is introduced. A protected shared staging frontend remains a separate access-design step.

Railway target: private project `e2cc4cb2-b22f-4ea4-99ed-329befa4cf60`, staging environment `78d48523-3b40-4010-8d4f-10c04d69fe23`, API `f73fc3a9-e7ce-451f-a985-e46e08040ba0`. Production environment remains empty. Existing resource caps/plan are unchanged. One-time pre-deploy import settings and the temporary owner reference must be cleared after verification; the final deployment runs with reader credentials only.

## Refresh and remaining decisions

See [staging-refresh-review.md](staging-refresh-review.md) for the exercised GIS runner, classifier thresholds and limitations. It detects source-content/code/config changes, rebuilds geometry → metrics → section scales → operators → names → original DSUs → geometric membership, and preserves earlier runs on failure. A real isolated cached-source rebuild reproduced all classified station labels and all membership pairs. Regression agreement does not establish geological/operational truth.

Automatic collection is not enabled. Start with reviewed staging candidates; select cadence, retention and source-change thresholds before scheduling. Source disappearance is a review condition, never inferred abandonment. Preserve legal DSU overlaps and distinguish geometric relationships from allocation, ownership and controlling orders.

The old footage/inventory builder is snapshot-specific. Fresh GIS candidates must not reuse old township footage/scenario results, formation-zone estimates or GR/CBL branch indices without explicit recalculation/rebinding. Premium production integration is deferred until source access and allowed use are available. Backups/restore exercises and a protected staging sharing path remain required before production dependence.

## Validation evidence

- 101 Python tests passed after the integrated implementation, including 26 refresh fixtures, seven builder fixtures, four refresh-to-SQL bridge fixtures, 14 storage/API integration contracts and six explicitly mocked PostgreSQL contracts. Mock contracts are not real PostgreSQL verification.
- Frontend actual-module regression tests passed for null versus zero, time gaps, literal rendering, unsafe links, stale selection and mixed-release protection.
- Local full import reproduced every manifest table count. Browser review confirmed name search, production chart, two branches and four overlapping DSUs for file 19033; a newer well without supplied production showed unknown coverage rather than zero.
- GIS integration evidence: `work/bakken-forward-preview/data/gis-runs/run-20261017-integration/integration-verification.json`.
- Real PostgreSQL verification passed at `2026-10-18T02:52:13.808481368Z` after the temporary owner reference was removed. `work/bakken-forward-preview/railway-wells-reader-verification.json` confirms every table count, exact oil total, search/profile/production/DSU API reads, SELECT-only reader privileges and retention of the original 40 notices plus 40 orders/provisions.
- Final successful private staging deployment: `f35ca92e-fd47-46c3-97ed-c272dd2d2efc`. `work/bakken-forward-preview/railway-wells-staging-final.json` confirms no import owner reference, empty pre-deploy hook, well-release readiness required, no public API origin, no public database domain/TCP proxy, two staging services and zero production services. The one-time startup reconciliation completed with reader credentials only; future start configuration is restored to the normal Gunicorn command.

Operational detail: after removing import settings, a plain Railway `redeploy` reused the earlier deployment's import hook and safely failed because the owner connection was absent. A fresh allowlisted `up` used the revised settings and succeeded. Use a fresh deployment when changing the import/start configuration. No data was rolled back or deleted by that failed attempt.

The exact v2 builder source is preserved at `work/bakken-forward-preview/data/builder-snapshots/build_well_bundle-efd1894e8cf2c4b5308e14eac4d1a940973727e6653ec8391cd685624c32e7b6.py`. Later bridge support does not mutate the v2 package.

## Local FracFocus profile addition — October 20, 2026

User scope: one simple FracFocus section in the existing local well profiles. No new top-level page, map layer, scheduled collection, PostgreSQL import, public publication, or other feature expansion. Current production and GIS releases remain intact.

The section shows separate disclosure records with completion date, reported carrier-water gallons, a 42 gal/bbl conversion, and operator at disclosure. Expand a treatment to see the start/end dates, source well name, API and DisclosureId. Three records are shown initially; older records remain available in a disclosure list. Source details and snapshot coverage are expandable. Missing water is “Not reported,” a reported zero remains zero, and an unavailable snapshot is not presented as no treatment. No per-well sums, proppant estimates, monthly injection rates, completed-length normalization, or branch allocation are computed.

Source: the user-supplied `Downloads/FracFocusCSV (1)/DisclosureList_1.csv` and its `readme csv.txt`. Original files are read-only. Source SHA-256: `0363f3f81625c7a3bcf5eb95bab879fd7bbd420be5a61ac28c56a461e94aaedf`. The complete 244,095-row source was checked, including conflicting disclosure IDs outside a nominal state filter. The resulting sidecar accepts 18,304 North Dakota disclosures across 17,208 complete API14 identities; nine records require source/identity review. This candidate population includes both North Dakota state labels and API prefix 33, so it differs from the earlier state-label-only count of 18,310. The accepted records have 16,558 reported water values (including 37 zeros) and 1,746 missing values. There are 271 same-API/date groups with 548 disclosures; they are retained separately and flagged for review rather than silently merged. Accepted job dates span June 6, 2009–February 15, 2026. This is snapshot coverage, not a verified export date or complete basin history.

Implementation under `work/bakken-forward-preview/`:

- `fracfocus_store.py`: explicit atomic import into a separate local `data/fracfocus.sqlite`; raw evidence, row fingerprints, source hashes and file/API bindings are retained. Exact duplicates collapse; conflicting DisclosureIds are quarantined. Failed preparation preserves the previous sidecar.
- `fracfocus_backend.py`: bounded read-only `GET /api/wells/{file}/fracfocus`, registered only in `serve.py`. Exact API14 matches only. API10 suffix candidates are counted for review, not assigned. The response carries its well release and identity; stale, unavailable or partial snapshots return 503. `DATABASE_URL` is refused before any remote connection attempt.
- `profiles/profiles.js`, `profiles.css`, `index.html`: compact section in the existing profile with source and identity checks. An unrelated long release fingerprint in existing notes was made wrapping-safe to prevent horizontal overflow on phones.
- `tests/test_fracfocus.py` and `profiles/test_profiles.mjs`: import/API and frontend contracts.

Snapshot ID: `ff-0ad3f890933900dc204d6834`, bound to the existing well release above. The local sidecar is about 31 MB. No cloud deployment allowlist, Railway service, public checkout, original production database or GIS dataset was modified.

To prepare and review from `work/bakken-forward-preview`:

```powershell
python fracfocus_store.py '~/Downloads\FracFocusCSV (1)\DisclosureList_1.csv'
python serve.py --port 58523
```

Open `http://127.0.0.1:58523/profiles/?well=35721&q=35721#fracfocus`. A. Johnson (35721) has a reported water quantity, CHLOE (19033) has missing water, file 20055 has four disclosures, and file 100 has no exact disclosure in this snapshot.

Validation: 13 backend/import tests passed, including conflicting duplicates, missing/zero/invalid volumes, API suffix exclusion, source mutation rollback, missing/partial snapshots, and release binding. Frontend checks passed for identity/release mismatches, stale selections, literal text rendering, missing quantities and a failed FracFocus request leaving the rest of the profile available. Browser review covered reported/missing water, the older-disclosure expansion, 1,280-pixel desktop and 390-pixel phone layouts, and expanded source details. Final phone document width was 375 pixels within a 390-pixel viewport; no browser console errors were observed. Screenshot: `work/fracfocus-review/local-fracfocus-preview.jpg`.

The separate read-only `Desktop/GIS` inventory is in `work/fracfocus-review/gis-inventory.md` and `.json`. It identifies historical log tops, survey snapshots and spacing units for later controlled validation. An older FracFocus/wellbore derivative repeats water across ingredient rows and has a suspicious stored API value. It was not used for this feature. Other proposed production, disposal, regulatory and geological additions remain deferred.

## Scope correction: shared spud and frac timeline — October 20, 2026

The user clarified that the intended primary feature is the existing 3D viewer date slider, not a separate profile feature. The local profile disclosure list remains supporting context. The local viewer now offers **Monthly oil** or **Spud & frac activity** in the existing Production tab and reuses one month slider, playback transport and lateral-size control. Public hosting, Railway and original databases remain unchanged.

In activity mode the current mapped well geometry becomes visible in its reported spud month and stays visible thereafter. This is a well-level timing proxy: it does not reconstruct footage drilled within a month, date individual branches, or establish a completed interval. Before-spud paths cannot be picked or highlighted; search explains why a result is hidden. Unknown or inconsistent spud dates are excluded by default, with an explicit include-unknown option. All sections are masked using a small well-indexed texture, so advancing the month does not rebuild millions of survey stations.

The full reported FracFocus carrier-water quantity is assigned once to the job **end month**. Blue lateral symbol width follows the square root of reported gallons, with a fixed reference of 10 pixels at 10 million gallons. This is a comparison symbol, not a physical bore diameter, stimulated reservoir volume or injection rate. Inactive laterals remain thin gray; an event with missing or review-required water remains thin amber. All branches share their physical well's symbol quantity, but summaries deduplicate the well identity. Possible duplicate disclosures remain separate records and their monthly water is withheld. If any included event for a well-month lacks a usable quantity, that well-month quantity is unknown rather than a partial sum. Basin/filtered summaries are explicitly **known gallons**, with missing-data counts; they are not complete treatment totals. Area selection scopes whole wells, not spatially allocated injection volumes.

Activity source binds to the exact existing GIS release, FracFocus snapshot and current survey-manifest SHA-256 (`328deaf1f1d2bf9c9d7d5e961cd25be653f082a51fb6966f13be9e495ef4599c`). The local snapshot contains 22,498 unique mapped file/API identities over 48,929 survey branches. 22,469 wells have usable spud dates; four are missing and 25 are withheld for chronology review. There are 18,165 mapped disclosures, of which 18,137 have an eligible end month and 28 have undated/inconsistent timing. 546 possible duplicate disclosures retain review flags. These are current local audit totals, not claims about every Bakken completion.

Spud months span November 1952–October 2026. Supplied FracFocus treatment dates end February 15, 2026. Later slider months explicitly say treatment coverage is unavailable rather than showing zero treatment activity. No disclosure in earlier months is absence of a record, not proof that no frac occurred. Water, sand/proppant, cumulative injection and premium production ingestion have not been inferred or added.

Local implementation:

- `work/bakken-forward-preview/build_activity_snapshot.py`: reads existing local SQLite stores without changing them; validates source/release/identity and survey hashes; atomically prepares `data/activity-snapshot.json` (8.54 MB). Source raw files remain untouched.
- `viewer/activity-model.js`: universal whole-well indices, contiguous months, spud visibility, explicit no-event/missing/review/zero distinctions and scope summaries.
- `viewer/build_preview_controller.py` generates local `viewer/production.js` from the unchanged public oil controller with guarded anchors. Independent oil and activity models share rendering and the slider. Oil gaps, original oil volumes and color modes are retained.
- `viewer/preview_hooks.py` applies guarded in-memory changes to the served app for picking, selection, search, fit-visible, DSU highlights and Gamma compatibility. No public viewer source is overwritten.
- `serve.py` allowlists only local viewer override assets and the prepared activity JSON. SQLite stores and source files are not web routes. The server binds only to loopback.

Review:

```powershell
cd work/bakken-forward-preview
python build_activity_snapshot.py
python viewer/build_preview_controller.py
python serve.py --port 58523
```

Open `http://127.0.0.1:58523/viewer/?dataset=full&timeline=activity&month=2020-01&well=35721&api=33053088220000`.

Verified A. Johnson (35721): hidden June 2019, visible from July 2019 (spud July 31), 14,802,545 reported gallons in January 2020, then no recorded treatment in February 2020. Switching to oil preserved February 2020. Mobile review at 390 × 844 confirmed playback, hide/show without removing size encoding, and no horizontal document overflow; desktop review used 1280 × 900. Browser console showed no errors. Offline checks cover builder identity and chronology, model summaries/branch deduplication, and viewer hook guards. The loopback preview is the review deliverable; no public release or refresh automation was created.

Validation counts: 13 activity-builder tests, 5 guarded-hook tests, the activity-model fixture/integration checks, and all 7 actual-controller lifecycle checks passed. The latter caught and verified fixes for stale scope counts and unknown-date option persistence across dataset reloads. Final screenshot: `work/fracfocus-review/local-frac-timeline.jpg`. The original profile and production outputs are preserved.
