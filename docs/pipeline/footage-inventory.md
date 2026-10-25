# Lateral-footage inventory comparison

This feature compares mapped lateral footage with explicit capacity-density
scenarios for North Dakota Bakken DSUs and townships. It preserves the saved
September count-based results. It does not establish remaining legal locations,
completed footage, recoverable reserves or future rig demand.

## Calculation and spatial scope

For each supported reporting footprint:

```text
scenario capacity ft = eligible measured acres × scenario density ft/ac
development % = 100 × mapped lateral ft / scenario capacity ft
signed balance ft = scenario capacity ft − mapped lateral ft
feet remaining = max(signed balance ft, 0)
```

Raw development percentages above 100%, signed balances and excess footage are
retained. Missing or unsupported observations stay unavailable; they are not
interpreted as zero development. Actual intersecting well counts remain separate
from footage and two-mile equivalents.

The initial low/base/high densities are 49.5, 66 and 82.5 ft/ac. Base is the
historical assumption of eight two-mile equivalents per 1,280 acres expressed in
footage. Low and high are illustrative ±25% comparisons. They are editable and
are not calibrated capacity estimates or confidence bounds.

`prepare_footage.py` reads the prepared survey geometry and aligned MD metrics.
It uses classified lateral segments, screens unsupported MD gaps greater than
1,000 ft and unions shared/retraced plan geometry within each permit/API10 well.
It transforms the survey tangent coordinates back to geographic NAD83, then
uses EPSG:5070 metres for planar clipping and area measurement. Footage is
projected horizontal path length converted to feet, not measured-depth length.

DSU calculations retain the original footprints, including published overlaps.
Insets and display depth separation do not change the calculation.
Stated source acres, measured polygon acres and eligible acres remain separate.
Each DSU is an independent alternative; summing overlapping DSU rows double counts.

Townships are dissolved by their full PLSS township/range/direction key. Their
eligible acreage is the intersection with the union of supported Bakken DSU
footprints, rather than the entire township. Footage is clipped to those same
portions. This clips observations to township reporting areas without assigning
each well to only one township. A well crossing township boundaries contributes only its clipped
footage to each; well counts across townships are not additive.
Source PLSS gaps and overlaps are audited rather than repaired into a gapless
partition. Supplied township keys lack principal-meridian identity; no missing
meridian is invented. Review the audit before summing regional totals.

## Implementation

- `viewer/footage-model.js`: scenario arithmetic, missing-data handling, snapshot
  validation and Turbo color scaling.
- `viewer/footage.js`: scenario controls, township display/picking, inspector
  tables, saved preferences and loading of matching prepared assets.
- `viewer/dsu.js` and `viewer/dsu-model.js`: DSU coloring and inspector integration
  while retaining the existing legacy inventory modes.
- `prepare_footage.py`: projected spatial allocation, input hashes and audit.
- `tests/footage-*.mjs` and `tests/test_prepare_footage.py`: synthetic regression
  checks requiring no original well or production records.

The browser validates the full survey manifest, DSU source and township geometry
against the prepared snapshot. Rebuilding surveys, classifications or boundaries
requires rebuilding the footage assets. Inventory uses all surveyed operators,
independently of the current well display filter. Existing production remains
whole-well reporting and is not allocated by these footage fractions.

## Preparing or transferring data

Required local inputs are a prepared full survey with aligned MD metrics,
NAD83 DSU GeoJSON with the viewer's stable IDs and supported formation metadata,
and a PLSS township shapefile with its projection and associated sidecars.
The original public DSU ZIP alone does not supply the full prepared metadata.
Public GIS sources are available from
[North Dakota DMR](https://gis.dmr.nd.gov/gisdownload.asp).

From a source checkout:

```sh
python -m pip install -r requirements-footage.txt
python prepare_footage.py --help
python prepare_footage.py --dsus viewer/data/dsu/drilling-spacing-units.geojson --dataset full-dataset --townships local-data/Townships.shp --output-dir local-data/footage-build
```

After reviewing the generated audit, copy `footage.json` and
`townships.geojson` from that output folder into `viewer/data/inventory/`.
Keep the audit with the local data backup. Do not replace the existing DSU file
or legacy inventory with the generated township layer. To transfer the working
installation, copy the matching survey, DSU and inventory directories together.
Generated data and original workbook/model artifacts are excluded from Git.

## Interpretation and next validation

This stage supports geometric comparison. Formation eligibility comes from the
prepared source mask, not a new bench interpretation. Middle Bakken versus Three
Forks targets, abandoned branches, sidetrack completion states, productive
intervals and interference are not independently verified. Within-well geometric
union cannot distinguish stacked targets that share the same plan path.

Review representative 1,280-, 1,920-, 2,560- and 3,840-acre DSUs, section-line
overlaps, irregular boundaries, two-/three-/four-mile laterals and partial
townships against source surveys and completion records. Check area conservation,
clipped footage, missing-data coverage and independent projected GIS measurements.
Then calibrate regional and target-specific layouts before translating footage
headroom into feasible locations, development timing or expected drilling demand.

Turbo's adapted polynomial and attribution are distributed under Apache-2.0;
see `viewer/TURBO-LICENSE.txt`.
