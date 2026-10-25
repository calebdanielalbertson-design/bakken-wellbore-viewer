# Staging GIS refresh and survey classification review

Reviewed October 17, 2026. This document separates confirmed existing code from the new staging runner and remaining work. No public viewer, scheduled job or hosted database was changed by this review.

## Confirmed source data and existing pipeline

The currently prepared full viewer dataset comes from the October 17 GIS archives. `outputs/wellbore-viewer/refresh-validation.json` reports 48,929 branches, 22,498 unique permits, 5,495,609 retained stations, 29 skipped source records and 3,756 duplicate-MD records. `work/nd-refresh-2026-10-17/download-provenance.json` records exact source URLs, ZIP checksums, retained origin and processing command. The Wells archive contains 44,005 metadata records; this is a larger population than the wells with displayed horizontal surveys.

Official free GIS endpoints used by the staging runner:

- `https://gis.dmr.nd.gov/downloads/oilgas/shapefile/OGD_Wells.zip`
- `https://gis.dmr.nd.gov/downloads/oilgas/shapefile/OGD_Horizontals.zip`
- `https://gis.dmr.nd.gov/downloads/oilgas/shapefile/OGD_DrillingSpacingUnits.zip`

The existing reusable scripts live in `outputs/wellbore-viewer/`:

| Script / function | Confirmed behavior |
| --- | --- |
| `prepare_data.py:main`, nested `emit` | Reads required DBF fields, filters nonfinite/invalid coordinates, inclination, MD and signed TVD; sorts by permit/API/branch/MD using disk-backed SQLite; retains the last source row for duplicate branch MD; discards branches with fewer than two stations; writes Float32 geometry and manifest. |
| `classifier.py:Settings`, `classify` | Classifies each strictly increasing-MD branch independently. Recomputes sections by default. Splits classification context across gaps over 1,000 ft; uses MD persistence and station evidence for sideways-deviation candidates. |
| `prepare_metrics.py:station_metrics`, `tortuosity`, `main` | Reproduces geometry ordering/filtering, checks branch identities/counts/offsets and projected geometry alignment, computes DLS/build/turn/tortuosity/departure, and emits aligned metrics plus validation. |
| `prepare_section_scales.py:main`; `prepare_metrics.py:section_metric_scales` | Validates exact manifest/geometry alignment and derives finite full-resolution per-section quantiles. |
| `prepare_operators.py:resolve_operator`, `build_sidecar` | Joins reported snapshot operator to survey branches using permit/API evidence. Commercial display groups are separate from exact source operator text. Does not reconstruct historical ownership. |
| `prepare_well_names.py:resolve_name`, `build_sidecar`, `prepare` | Uses permit plus exact API14 first; allows API10 fallback only for an unambiguous identical nonblank source name. Binds sidecar to exact manifest SHA256. |
| `prepare_dsu.py:prepare` | Converts original NAD83 polygons and source attributes; retains overlaps; rejects unsupported projection. IDs are hashes of attributes plus geometry, so attribute changes can change IDs. Does not establish persistent legal-unit identity across snapshots. |
| `prepare_dsu_membership.py:lateral_geometry`, `merged_well_geometry`, `build` | Clips section-4 incoming survey segments against original DSU polygons in viewer XY feet. Excludes MD gaps over 1,000 ft, nonfinite/nonincreasing records and zero XY segments. Unions exact retraced/shared branch linework per permit/API10 and records positive-length intersections. This is geometric overlap, not legal membership or production allocation. |

The dated `work/nd-refresh-2026-10-17/refresh_log_data.py` separately supplies `manifest_identity`, `rebind_catalog` and sample/index checks for local GR/CBL sources. LAS measurements are not GIS downloads. The new runner does not update those local indexes or catalogs; a later geometry activation must explicitly rebuild/rebind them or withhold incompatible log overlays.

`prepare_data.py` command options: positional DBF and new output directory; required `--tvd-sign positive|negative`; `--source-crs NAD83|WGS84`; optional fixed `--origin LONGITUDE LATITUDE`; `--classifier-config FILE`; and legacy `--preserve-sections`. Production refreshes must use recomputation, not that legacy flag.

The current fixed origin is `[-102.99897097700921, 47.91137672734358]`. The projection is the retained NAD83 ellipsoidal tangent east/south plane in feet. Y is negative relative TVD. It is not an elevation-corrected subsurface datum.

## What the classifier actually means

Classifier v2.0 is a transparent heuristic, not independently verified geological or operational truth. Its defaults are: vertical maximum 6.5 degrees; lateral minimum 85 degrees; curve rate 4.5 degrees/100 ft; upper vertical-context cap 35 degrees; sideways episode start 3 degrees, at least 75 ft departure, 150 ft MD persistence and three stations. Landing context is 70 degrees. Terminal-build protection uses a 250 ft window and 0.5 degree/100 ft rate. Gaps over 1,000 ft split classification context.

The user-defined Drillback label means a pronounced sustained sideways deviation in the upper mostly vertical interval. It is a geometric candidate and does not prove a sidetrack, drilling back, abandonment or completed interval. Source branch code is preserved; different branches are never connected for classification/rates. The global overview still draws sampled endpoint spans, so a visual span must not be mistaken for complete survey support. Derived rates and membership exclude large MD gaps.

Metrics retain missing values as NaN. DLS is calculated from adjacent survey tangents per 100 ft MD. Tortuosity is geometric arc/chord within a centered 1,000 ft MD window, clipped at branch ends/gaps with at least 500 ft support and three distinct positions. Azimuth below 5 degrees inclination is undefined. Section scales are recalculated from the new classified station population.

## Revision and QA issues that matter

1. **A survey feed changes historical geometry as well as adding wells.** The last recorded comparison has 1,282 added and 155 removed branch identities; 606 added and 74 removed permits. Do not interpret disappearance as abandonment or delete production/history. Manifest numeric branch IDs are generation-local positions, not persistent keys.
2. **Current import policy loses conflicting same-MD records.** Both geometry and metrics retain last source row. Preserve raw archives and flag conflicting duplicates; do not claim source conflicts have been resolved analytically.
3. **Classification is not completion or target evidence.** Classified lateral feet cannot identify Middle Bakken versus Three Forks, active versus abandoned branches, or completed footage without additional sources.
4. **Current QA surfaces extremes but does not establish accuracy.** The existing metric validation reports 66 large MD gaps, 23 intervals under 0.1 ft MD, 49 azimuths outside 0–360 degrees, 207 DLS values above 100 degrees/100 ft and 3,390 tortuosity values above 2. These are review flags, not evidence of operations. Invalid source azimuths become missing adjacent DLS/turn metrics; classifier v2.0 itself still wraps its finite source azimuths.
5. **Spatial relationships need explicit versioning.** Preserve source polygons, not their display insets. Overlapping DSUs remain many-to-many. A point touch does not create lateral membership. Full-well production may appear in multiple overlapping DSUs and is not an exclusive acreage allocation.
6. **Current historical production has limited coverage.** GIS refresh does not create newer production or backfill missing months. The existing public matrix ends December 2024 and contains a separate limited historical period; current premium access is pending. Import only supplied historical records with source/revision dates and keep absent values distinct from zero.
7. **Township/DSU footage refresh is not yet general.** `work/footage-inventory-2026-10-17/build_footage.py:build` rejects any manifest other than its hardcoded October 17 SHA256 and reads an old membership path. Reusing it unchanged on a new feed is unsafe. Its EPSG:5070 footprint/linework approach can be generalized later with explicit inputs and versioned model parameters; the staging runner intentionally does not copy old scenario outputs onto fresh surveys.
8. **DSU display zones are separate estimates.** Existing `prepare_dsu_zone.py` uses dated picks and approximate fallbacks. A raw DSU refresh has no newly verified formation surface. Do not relabel those estimates as current measurements.

## New staging-only refresh command

`work/bakken-forward-preview/refresh_gis.py` is a local orchestration command. It does not load SQL, publish the website, alter a current dataset, or install a recurring job.

Read-only plan (default):

```powershell
python work/bakken-forward-preview/refresh_gis.py --plan
```

Validate existing official-name local ZIPs without rebuilding:

```powershell
python work/bakken-forward-preview/refresh_gis.py --execute --acquire-only --source-dir work/downloaded-gis
```

Use repeated `--archive SOURCE=PATH` options for separately stored local archives, where SOURCE is `wells`, `horizontals` or `dsu`. These override the corresponding `--source-dir` file and do not modify the originals.

Download and build a new private candidate, comparing against an earlier validated run:

```powershell
python work/bakken-forward-preview/refresh_gis.py --execute --previous work/staging-gis-runs/PRIOR_READY_RUN
```

Omit `--previous` for the first run. Use `--classifier-config FILE` for a reviewed configuration change. The optional `--origin LONGITUDE LATITUDE` defaults to the current fixed origin; changing origin is a processor revision and causes a rebuild. `--runs-dir` must be a dedicated child of this workspace's `work/` directory. `--use-existing-labels` and `--preserve-sections` are unsupported and rejected.

Each fresh run directory records:

- Original archives; immutable extracted source components; archive SHA256 and content identity from DBF/SHP/SHX/PRJ/CPG hashes. Repacked ZIPs with unchanged relevant content do not require a rebuild.
- Observation time, HTTP Last-Modified/ETag where supplied, original ZIP member times and DBF header date. None is presented as a verified source-publication timestamp.
- A copied processor/configuration snapshot, script hashes, classifier version/parameters, projection/depth policy and run ID. Code or settings changes force recalculation even when sources do not change.
- Sequential geometry, metrics, section-scale, operator, name, raw DSU and membership steps, with separate logs. Metrics are copied into the candidate dataset only after exact section-scale checks. Source provenance is added to the candidate manifest before dependent hashes are built.
- Per-run status: `acquiring`, `processing`, `ready_for_review`, `no_change`, `acquired_not_processed`, or `failed`. Failures preserve earlier runs; no latest/current/public pointer is switched. A no-change result references its validated predecessor.
- Alignment checks, missing name/operator counts and metric quality flags. Ready for review is not permission to treat geometric results as legal/completion truth.

Downloads use only the three exact official HTTPS URLs; redirects are refused for review. Caps are 600 MiB per ZIP, 4 GiB expanded, 2 GiB per member, 32 members and 300:1 expansion. ZIP members must be expected flat shapefile components, including the exact `OGD_Horizontals_Line` companion family present in the official Horizontals ZIP; traversal, absolute/nested paths, duplicates, links, encryption, unsupported members, CRC failures, missing required components, HTML responses, truncation and unsupported projection fail the candidate.

Runtime dependencies for processing remain the existing local NumPy, pandas and Shapely packages. These processors are not included in the lightweight API container's current requirements. No automatic recurring refresh is enabled. No new network download was performed for this implementation; the downloader was exercised with offline HTTP fixtures.

## Integration verification performed

An actual isolated rebuild used the three retained October 17 official source archives. All seven subprocesses completed successfully in candidate `work/bakken-forward-preview/data/gis-runs/run-20261017-integration/20261018T023013Z-e1cb0deb9b00/`; its status is `ready_for_review`. The processor hash recorded by that run matches the executed `refresh_gis.py`. The sources and previous prepared/public data were not changed.

`work/bakken-forward-preview/data/gis-runs/run-20261017-integration/integration-verification.json` records the comparison against the existing full dataset:

- 48,929 branches; 5,495,609 stations; 10,573 DSUs; zero missing survey well-name/operator joins.
- Exact branch identity/count/tile/offset agreement and **zero changed classified station labels** across all 5.5 million stations.
- 39 coordinate differences within two Float32 ULPs, maximum 0.03125 ft; 34 finite metric differences, maximum absolute difference 0.000030517578125. All missing metric positions remain identical.
- All 75,736 DSU-well membership pairs and corresponding branch memberships agree. Maximum clipped/total lateral length difference is 0.015579 ft from Float32 coordinate rounding.
- Section populations: Vertical 1,310,524; Directional 45,003; Curve 517,841; Drillback 651,266; Lateral 2,970,975; Unknown 0. Metric quality flags match the original snapshot.
- No SQL import, public website update, production refresh or scheduled job was performed by this command.

The staging runner has 26 passing offline tests covering safe archive handling, CRC failures, download limits, allowlist/redirect rejection, container-versus-content revision identity, stale metadata rejection, unknown coverage, classification populations, failure isolation, and read-only planning. The existing classifier's 12 analytic/edge-case fixtures also pass unchanged. Reproducing current labels is a regression check; it does not independently validate geological or operational interpretation.

## Practical next stages

### Prepare a reviewed GIS run for SQL import

`work/bakken-forward-preview/prepare_refreshed_wells.py` bridges a completed staging GIS run to the immutable well-profile bundle builder. Its default is a read-only plan; it does not import SQL, download data, change a public site, or activate a schedule.

```powershell
python work/bakken-forward-preview/prepare_refreshed_wells.py --run work/staging-gis-runs/READY_RUN --plan
```

After reviewing the plan, explicitly create a new local bundle directory:

```powershell
python work/bakken-forward-preview/prepare_refreshed_wells.py --run work/staging-gis-runs/READY_RUN --execute --output work/bakken-forward-preview/data/well-bundle-NEXT
```

Replace `READY_RUN` with the actual completed run path. `no_change`, `failed`, partially processed and acquisition-only runs are rejected; for `no_change`, select its validated predecessor explicitly. The destination must be a fresh directory under this workspace's `work/`, outside the source run. SQL import remains a separate reviewed action.

The bridge verifies all recorded archive/component fingerprints, copied processor/configuration hashes, source-to-output links, manifest and DSU membership bindings, per-tile geometry/metrics hashes, aggregate validation hashes and the recomputed validation summary. It checks verified files again before the builder publishes `release.json`. A different current refresh-runner hash requires review rather than implicit acceptance of an older run. The recorded hashes are reproducibility checks, not a signed attestation of source accuracy.

Inputs are explicit: refreshed Wells DBF, survey manifest, well-name sidecar, raw DSU polygons and geometric membership, together with the existing `work/nd-refresh-2026-10-17/production/production-audit.sqlite` and `outputs/wellbore-viewer/full-dataset/production.json`. Optional `--production-db` and `--production-meta` select another reviewed historical source pair. The exact audit values are used; the viewer's Float32 production matrix is not imported.

The bridge always passes `footage_path=None`. Refreshed SQL DSUs retain published nominal acreage, while measured acreage is null with `measured_dsu_acres_status: unavailable_inventory_not_rebuilt`. Old measured acreage, formation/depth display estimates and inventory scenarios are not copied onto new source geometry.

Date meanings remain separate. For the isolated integration run above, the processor observed retained archives on **October 18 UTC**, while their DBF headers say **October 17**. Neither date establishes publication time. The new bundle carries `source_date_meaning: observed_at_not_verified_publication`, individual source observations/header dates, and a null source-publication timestamp. Historical production still covers only its supplied periods—currently January 1952–December 1955 and January 2000–December 2024 for the full registry. A GIS refresh does not create newer production or fill the intervening gap.

Validation: four offline bridge tests cover failed/stale runs, changed source/processor/metric files, explicit input mapping, withheld inventory and a concurrent-file-change rejection before READY. Seven bundle tests cover exact production, identity quarantine, null encoding, determinism and the new refresh context/final check. A read-only plan also passed against the actual 48,929-branch integration run. No replacement bundle was built during this bridge verification.

The builder source used for the existing final `well-bundle-20261018-v2` is preserved at `work/bakken-forward-preview/data/builder-snapshots/build_well_bundle-efd1894e8cf2c4b5308e14eac4d1a940973727e6653ec8391cd685624c32e7b6.py`, SHA256 `efd1894e8cf2c4b5308e14eac4d1a940973727e6653ec8391cd685624c32e7b6`. That release was not modified by these wrapper changes.

### Subsequent review and activation

1. Import the known, validated October 17 snapshots into staging SQL, retaining full Wells metadata independently of the survey subset. Preserve the old public outputs and historical production.
2. Run the new command against a fresh GIS download in an isolated staging directory. Compare raw source identities, added/removed/changed branch fingerprints, station counts/MD ranges, section footage changes, geometry bounds, missing joins, gaps and extreme metrics. Inspect representative unchanged wells, new laterals, updated surveys, sidetracks and malformed records. Source absence is a review condition, never a status inference.
3. Generalize the footage builder and carry explicit township source, exact new manifest/membership hashes and scenario model version. Do not carry stale historical DSU enrichment by positional IDs. Preserve earlier results for comparison.
4. After review, schedule one private refresh job with locking, retry/backoff, notifications, disk/resource budgets and retention. An unsuccessful import keeps last-good SQL generation available with an explicit stale/source-date indicator. Publish a SQL generation atomically only after validation, using a separate write-capable importer role; the website API remains read-only.
5. Add premium monthly production only after the user supplies the permitted source/access. Confirm licensing/display conditions before extending that pipeline. No missing values or time periods are invented.
