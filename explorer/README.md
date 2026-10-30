# Wellbore Section Explorer

## October 17, 2026 data refresh and operator view

The full survey was rebuilt from the October 17, 2026 `OGD_Horizontals.zip` at [ND DMR GIS downloads](https://gis.dmr.nd.gov/gisdownload.asp): **48,929 branches, 22,498 permit/API10 wells, and 5,495,609 retained stations**. The accompanying `OGD_Wells.zip` contains 44,005 well records. All 48,929 displayed survey branches matched a reported operator by permit and API10. Source archives, hashes, processing checks and the previous full dataset are retained locally under `work/nd-refresh-2026-10-17/` in the project workspace.

Choose **Operator** under **Color wellbores by**. Hess/Chevron is green; XTO is amber. The supplied legend's combined names are display groups, with each well's exact reported operator retained in its selection details. Unlisted operators have stable individual colors. **Show operator group** filters paths, search results and monthly production totals; **Fit displayed operators** frames that group. Filters remain active when switching to DLS or another color mode. **Show all operators** restores the complete dataset.

The source operator describes this snapshot and is shown for every historical production month. The grouping does not reconstruct ownership history. Production coverage remains the supplied historical records through December 2024; refreshing surveys does not create later production months. The sample and video subsets retain their original geometry and now include the new operator metadata.

Operator metadata can be regenerated with `python prepare_operators.py OGD_Wells.dbf DATASET_FOLDER --source-date YYYY-MM-DD`. The command validates the join and writes `operators.json` without changing station geometry. A local operator-view URL is `/viewer/?dataset=full&color=operator`.

The log service now uses the refreshed survey index. Its local source paths are configured in `local-settings.json` (`lasDir` and `surveyDbf`), with optional `BAKKEN_LAS_DIR`, `BAKKEN_SURVEY_DBF` and `BAKKEN_MANIFEST` environment overrides. Restart the local server and reload the browser after replacing survey indexes or catalogs. Original LAS measurements are retained.

## Record a local showcase video

Open `/viewer/?showcase=cluster` on the running local server for the video studio. It uses 31 wells / 65 branches from the full dataset near permit 21994, with their original survey and production records. The included subset has independent fidelity checks in `viewer/data/showcase/verification.json`.

Click **Record 35-second showcase** to create a silent 1920×1080 video: azimuth, DLS with separate section scales, then monthly production from January 2016 through December 2024. The capture uses the actual viewer renderer. **Review azimuth / DLS / production** inspects three points in the recorded file, and **Download MP4 video** saves it locally. A browser without MP4 recording support offers WebM instead. No video or source data is posted automatically. The normal viewer stays unchanged unless this studio URL is requested.

`/viewer/?showcase=1` uses the larger 376-branch sample instead. The final database counts in the ending card refer to the full prepared survey database; the recording labels its displayed representative subset separately.

## Open the full dataset

Double-click `start-viewer.cmd` to open the full dataset in your browser. Alternatively, from an already open viewer, click **Open dataset folder** and select `full-dataset` beside this file. Files are read locally and are not uploaded. Use Edge or Chrome for folder selection and WebGL support.

- Drag: orbit. Right-drag: pan. Mouse wheel: zoom.
- Search for a permit, API, or branch; click a result to focus it.
- Click a path to inspect it, then use **Zoom to well** to center navigation on a point on that wellbore and frame all its branches. Section colors remain visible on selected paths.
- Once focused, scrolling can continue forward at close range without the old zoom/pan slowdown. Double-click any path to recenter on that exact point without changing viewing distance. Search results use the same well-centered navigation. Normal panning still moves the center freely.
- Fit dataset or Fit North Dakota restores navigation at the larger area scale.
- Use section checkboxes, Plan/3D/Side views, and depth exaggeration.
- Fit dataset restores the overview.

## Survey color options

Use **Color wellbores by** at the top of the sidebar. **Well section** restores the original section colors, including lime laterals and yellow curves. Ten additional choices color individual survey intervals:

| Choice | Meaning |
| --- | --- |
| Dogleg severity (DLS) | Change in 3D survey direction per 100 ft measured depth |
| Curvature | The same directional change expressed in radians per 1,000 ft |
| Local tortuosity | 3D path length divided by the endpoint chord over a centered 1,000-ft MD window; straight = 1 |
| Inclination | Degrees from downward vertical |
| Azimuth | Source bearing with a cyclic scale: 0° and 360° have the same color |
| Build / drop rate | Signed inclination change per 100 ft MD |
| Turn rate | Shortest signed azimuth change per 100 ft MD |
| True vertical depth | Relative TVD in feet |
| Measured depth | Source MD in feet |
| Horizontal departure | Horizontal distance from the branch's first observed station |

**Color scaling** defaults to **Scale by well section**. Vertical, Directional, Curve, Drillback, and Lateral each have a separate range, shared across every well in that section. Curve extremes therefore do not set the lateral's color scale. The sidebar lists each section's active range. Equal colors across different sections can represent different values; compare the legends when making cross-section comparisons.

Automatic ranges use exact 2nd–98th percentiles of the full dataset's finite station measurements for each section, independently for each metric. Build and turn use symmetric ±98th-percentile absolute values to keep zero neutral. These limits remain fixed when panning, selecting wells, or loading nearby detail. Extreme values remain stored and use the endpoint colors. Constant-valued sections get a small nonzero display range, and sections without usable measurements stay gray. Azimuth retains its fixed cyclic compass scale.

Expand **Customize color scales**, choose **Section to customize**, and enter a minimum and maximum (or a symmetric limit for signed rates), then click **Apply limits**. **Reset this section to automatic** restores its percentile range. Custom settings remain separate by section and metric for the current dataset session. Choose **One shared scale** to compare absolute values across sections. Viridis and a brighter blue–yellow–red palette are available; signed and compass modes retain their respective diverging/cyclic palettes. Selected-well details show the branch's actual measurement range, not clipped display limits. Depth exaggeration does not change the measurements.

Gray means unavailable. Rates are undefined at each branch's first station and across MD gaps over 1,000 ft. Azimuth is hidden below 5° inclination; turn requires both interval ends to be at least 5°. Source azimuths outside 0–360° are masked, including their adjacent DLS and turn intervals. Short survey intervals and extreme finite values remain in the audit; display limits do not modify the stored values.

Tortuosity includes planned curves and depends on survey resolution. It is a geometric path/chord ratio, not a calibrated drilling-quality score or a measurement of unobserved microtortuosity. Its window shortens at branch ends and large gaps, requiring at least 500 ft of covered MD and three distinct geometry points. Departure begins at the first available station, which may be below the surface. TVD is not a common-elevation datum.

The overview preserves the maximum DLS/tortuosity and largest-magnitude signed build/turn inside each displayed span. Zoom in for individual survey intervals. Measurements load with nearby detail tiles; the browser does not load all 5.50 million station measurements at once. Source coordinates and branch geometry remain unchanged.

Production continues to control lateral width. Choosing a measurement overrides the survey paths' production colors, while GR and CBL overlays retain their own palettes. Enable **Show other survey paths** when inspecting measurements alongside well logs.

Preparation verified every retained coordinate and overview row against the existing datasets: 5,495,609 stations / 48,929 branches in refreshed full data and 31,984 stations / 376 branches in the sample. Analytic fixtures and independent source DLS calculations passed. Dataset folders include `metrics-validation.json`, `metrics-binary-verification.json`, and `metrics-summary.json` for review.

To prepare measurements for another compatible dataset, install NumPy and pandas, then run:

```text
python prepare_metrics.py "path/to/source.dbf" "existing-dataset-folder" "new-metrics-folder"
```

Review the validation reports, then copy the generated `.json` and `.bin` files into that dataset folder and reload. The importer requires the exact DBF that produced the retained geometry and refuses coordinate/alignment mismatches. It reads the source and geometry without modifying them.

Definitions: [AADE / Occidental directional-survey presentation](https://www.aade.org/application/files/9016/7639/0157/AADE-22-PBC_TechForum_Lightfoot_-_Oxy.pdf) describes dogleg severity; [OpenStax, arc length and curvature](https://openstax.org/books/calculus-volume-3/pages/3-3-arc-length-and-curvature) describes curvature. The local tortuosity window and display scales are this viewer's explicit choices.

## Monthly oil production

The **Size laterals by production** checkbox adds lime-green widths to the lateral sections. Vertical, directional, curve (yellow), and drillback colors remain unchanged. Monthly data loads locally with the survey dataset.

- Use **Play**, pause, previous/next month, the timeline slider, or **Jump to month**. Playback speed ranges from 1 to 12 months per second. Playing from the final month restarts the selected period at its first reported month.
- **Playback period** defaults to January 2000–December 2024. Historical reports for December 1952–December 1955 are a separate period in the full dataset. There is no supplied coverage for 1956–1999.
- Display width is proportional to the square root of monthly oil barrels: 40,000 bbl is twice as wide as 10,000 bbl. The default symbol is 10 screen pixels wide at 10,000 bbl. **Lateral display size** changes that reference width for all months together. These are display symbols, not physical bore diameters. Thin centerlines remain for visibility.
- A reported zero is thin muted lime. Missing production is gray. Missing records are never converted to zero or interpolated. The reported-well count shows how much of the matched population has data in that month.
- Select a well to see its monthly barrels and a production history for the selected period. Gaps in the chart indicate missing reports. Hover a chart point for its month and barrels.
- Monthly totals cover matched wells in the loaded survey dataset, across all reported pools. Distinct pools are summed once. All branches of the same well share its value; totals never multiply by branch count or imply allocation between laterals.

**Coverage:** 20,848 of the full survey's 21,966 unique wells match by both permit/file number and API. The 47,802 survey branches remain separate geometrically. The sample includes 191 matched wells. Geometry is the current survey for every displayed month; historical oil production does not establish when a displayed horizontal branch was drilled.

The source CSV contains 2,819,116 pool/month rows from 2000–2023. The 2024 workbook adds 253,811 rows. The older workbook actually covers January 1952–December 1955; 273 records match 16 viewer wells, starting December 1952. The supplied 2016–2020 ODS overlaps the CSV and was not appended. Three sampled ODS oil values agreed exactly with the CSV.

The combined viewer matrix contains 2,333,381 usable well/month values, including 213,314 reported zeros. No duplicate pool/month keys, conflicting oil, invalid oil, or permit/API mismatches were found in these imported sources. All 337 monthly totals and reported-well counts were reconciled against the source records. `full-dataset/production-audit.json` and `production-validation.json` retain the checks.

Production is stored once per well/month in `production.json` and `oil.bin`, not repeated at every survey station. Instanced strips use existing lateral geometry and one shared monthly value texture. Changing months updates values without rebuilding the paths. The existing overview and detailed tile budget remain in use. Both production shaders compiled in an offscreen OpenGL ES 3.0 context. Model/controller checks cover real data totals, selection, playback, period gaps, missing/zero values, dataset replacement, and shared tile geometry. Numerical picking checks cover distant thick paths, close clipping, plan view and depth exaggeration. Browser interaction and end-to-end frame-rate testing were not performed for this addition; performance on a work laptop depends on its graphics hardware.

### Add another production export

The current launcher needs Python 3 with NumPy and a WebGL-capable browser; the bundled runtime already supplies NumPy. Survey geometry, production, and metric colors are packaged. GR/CBL extraction also needs the original source files described below. Preparing new production data additionally requires Python's `openpyxl` package for Excel input. Run the included importer with explicit paths:

```text
python prepare_production.py --manifest full-dataset/manifest.json --csv "path/to/history.csv" --xlsx "path/to/2024.xlsx" "path/to/2025.xlsx" --out "new-production-folder"
```

CSV columns: `File No`, `API_WELLNO`, `PoolNo`, `Pool Name`, `RPT_DATE`, `BBLS_OIL_COND`. Excel sheet headers: `File No`, `API No`, `Pool`, `Date`, `BBLS Oil`. An Excel report's **BBLS Oil** is used, not Oil Sold. Source files are read without modification. Choose a new output folder. After reviewing its audit, copy `production.json`, `oil.bin`, and `production-audit.json` beside the corresponding survey `manifest.json`, then reload the viewer. The SQLite audit database is an intermediate file and need not be copied.

Repeated well/pool/month records with the same oil value collapse once; differing oil values or unusable pool contributions make that entire well-month unavailable. A spreadsheet pool name is matched to a CSV pool ID only when unique for the same well/month. The importer verifies file number plus API; a unique ten-digit API base may match the same permit's fourteen-digit API ending in `0000`. These supplied sources matched exactly without API conversion.

## Run entirely locally

Run `start-viewer.cmd` on this Windows computer. It opens the packaged viewer in your browser. Keep its console open while using the viewer. The launcher uses the installed bundled Python runtime (or `python` if available).

## North Dakota reference plane

The **North Dakota plane** checkbox shows/hides a transparent state polygon at TVD 0. The **Plan view** and **Fit North Dakota** buttons frame the state in a north-up orthographic view: drag to pan and scroll to zoom. **Fit dataset** frames the wells; **Zoom to well** still frames all sibling branches. **3D view** restores mouse orbiting over the area being explored. The reference plane is independent of depth exaggeration and does not intercept well selection.

Four labels mark Census internal reference points for Williston, Dickinson, Minot, and Bismarck. These are geographic anchors, not exact downtown or address locations. The state outline is a reference for orientation; it is not the Bakken formation or producing-area boundary. TVD 0 is a common display plane, not terrain or a common elevation datum.

Source: U.S. Census Bureau, TIGERweb, January 1, 2026 vintage. The [state boundary](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/0) was requested in NAD83 (EPSG:4269) with 0.001-degree display generalization; the [city references](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/4) use Census internal latitude/longitude attributes. The 1,313-vertex outline and four city points are bundled under `viewer/data/reference` and load locally without external map requests. The exact source queries and metadata are included in `metadata.json` there.

The full NAD83 dataset uses the same tangent-plane projection for both maps and wells. On WGS84 sample datasets the NAD83 geographic outline is an approximate orientation layer; no precise inter-datum transformation is applied. Tests verified projection orientation, polygon triangulation, state framing, plan zoom scale, region preservation on return to 3D, dataset replacement, and local asset availability. No new browser interaction or visual test was run for this addition.

## Included data

The sample uses the new classification on survey stations from `AA_SAMPLE_OGD_Horizontals_classified_4.dbf`: 376 well branches, 31,984 stations after removing one duplicate measured depth.

The full dataset was prepared from `OGD_Horizontals.dbf`: 47,802 branches and 5,360,341 stations. 155 invalid rows were excluded and 3,193 duplicate measured depths were removed, keeping the last input record. Original survey data was not modified.

Version 2 defines **Drillback** as the user's requested **pronounced sideways deviation within the mostly vertical interval**. A return toward vertical is not required. This replaces the old single-station negative-build rule. These are geometric candidates, not confirmation of redrilling or drilling intent.

The detector uses a three-station median inclination and looks for episodes with at least **75 ft of horizontal departure from the observed episode start**, at least **150 ft of measured-depth persistence**, and at least **3 stations** at **3–35° inclination**. The episode is colored as a whole once that evidence is present, including the outbound deflection. Horizontal departure is measured from that episode's first observed anchor, not assumed surface coordinates. The last sustained build toward a lateral is excluded using 250-ft build windows; surveys missing the landing still protect a final buildup beyond 35°. Large survey gaps over 1,000 ft reset the detector. A fixed inclined upper tangent may qualify under this geometric definition.

Vertical is sky blue, Directional purple, Curve yellow, Drillback coral red, Lateral lime green, and Unknown gray. Baseline classification retains the notebook's 6.5° vertical and 85° lateral cutoffs and 4.5°/100 ft curve criterion. Drillback overrides a baseline Vertical/Directional/Curve label only after the sustained geometric evidence is met. The source coordinates, TVD, branch grouping, and measured-depth ordering are unchanged. On the full dataset, v2 flags 10,600 candidate intervals across 9,536 branches; the sample has 92 intervals across 79 branches. Every coordinate was compared against the previous dataset and is unchanged.

Each flagged branch includes its interval's MD range, peak smoothed inclination, horizontal departure, and reason in the dataset manifest. See `validation-v2.json` for classification totals and verification. Selected-well details show the available reasons. The thresholds are deliberately transparent, configurable starting values, not calibrated or industry-standard operating limits. Definitions of inclination and build/drop can be found in [SLB's inclination glossary](https://glossary.slb.com/en/terms/i/inclination) and [directional-drilling overview](https://www.slb.com/-/media/files/oilfield-review/defining-directional-drilling.ashx). The thresholds and category definition above are this viewer's rules.


Coordinates are in feet, with NAD83 (full) or WGS84 (sample) geographic positions mapped into a local tangent east/north plane. The horizontal datum is retained, with no NAD83/WGS84 transformation between datasets. Vertical coordinates use **relative TVD**, assuming source depths are feet. Positive TVD in the original and negative TVD in the sample are normalized explicitly. Ground/KB elevations are not included. This is not a common-elevation/subsea-depth comparison or a collision-clearance tool. The source PRJ declares NAD83 although older XML metadata mentions NAD27; verify against authoritative survey control before using map alignment for measurements.

Branches remain separate and start at their first available station; missing surface sections are not fabricated. Segments take the section label of the ending station, matching the notebook's section-line convention. The notebook's output lines are 2D; this viewer constructs its own 3D geometry from station coordinates and TVD.

## Larger imports

Install Python with numpy and pandas, then run:

```text
python prepare_data.py "path/to/OGD_Horizontals.dbf" "new-output-folder" --tvd-sign positive --source-crs NAD83
```

For the existing negative-depth classified sample, use `--tvd-sign negative --source-crs WGS84`. Fields `long`, `lat`, `measdpth`, `inclinatio`, `azimuth`, `tvd`, `wl_permit`, `api_wellno`, and `well_sub` are required. Classification is recomputed by default, even when the DBF has a `section` field. Add `--preserve-sections` only to keep existing labels. Use `--classifier-config classifier-settings.json` to override thresholds. Copy the included settings file and adjust it before importing to a new folder. Choose a new output folder on each run. Records are sorted on disk, so allow temporary disk space for the import.

The viewer loads a simplified overview first, then up to eight nearby chunks with a 250,000-station detail budget. A selected well's chunk can exceed that budget. Section transitions are preserved in the overview; other stations are sampled every twelve records, so zoom in for full detail. This is a first implementation: overview memory still grows with dataset size, and extremely large datasets may require a multilevel spatial index. No fixed frame-rate guarantee has been established.

Browser checks cover sample/full loading, search and canvas selection, Zoom to well, section toggles, depth scaling, and mobile layout. Classifier fixtures cover meaningful deviation with/without return, straight vertical surveys, isolated inclination and position spikes, ordinary kickoff, lateral steering, survey gaps, and threshold overrides. Full database geometry was rendered successfully. Performance on other GPUs may vary.

Three.js r180 is bundled under its MIT license.

## Navigation update

Zoom to well uses an actual point on the selected trajectory nearest the full well's midpoint, then frames all sibling branches around it. After native wheel/middle-drag/pinch camera movement, a minimum useful orbit radius advances the navigation target forward if necessary. This preserves the full camera movement and prevents subsequent zoom and pan steps from approaching zero. It is a moving navigation target, not a barrier around the well. The orthographic plan view retains its existing zoom behavior. Depth exaggeration is applied once to pivots and recentered hit points.

Camera-level tests used the bundled OrbitControls and real well geometry: 250 repeated inward gestures, continued travel beyond the original target, panning at close range, large gestures, outward zoom, recentering without a distance change, orbiting around the selected point, 8x exaggeration, and framing all sibling branches. The North Dakota projection/plan-mode regression checks also passed. No new browser visual QA was run.

## Gamma ray tubes

The launcher opens a vertical view around FileNo 21994. Averaged mode starts with 500 nearby wells; Detailed mode starts with 50. The panel adds 100 wells in averaged mode (limit 1,000) or 25 in Detailed mode (limit 100). Existing wells stay loaded at the limit; remove individual wells to make room. Nearby loading selects sources compatible with the current scale and shows progress. The well list scrolls independently. Search the survey catalog and select a well to load its available GR source. Use **Vertical view** to frame the gamma tubes and **3D view** or drag to orbit. **Show other survey paths** adds trajectory context.

Tube radius and color both follow gamma ray. The default shared scale is 0–300 API, with a maximum display radius of 120 ft: radius = 120 × clamp(GR / 300, 0, 1). This is exaggerated display geometry, not physical bore diameter. The maximum radius, shared API ceiling, and Turbo/Spectral palette are adjustable. Values above the ceiling are capped visually; hover retains the raw GR value and measured depth. Counts and unknown units require the relative mode, which scales each displayed log to its own 95th percentile. This is a visual comparison, not cross-tool calibration.

The overlay follows observed VERT survey branches, including any inclined stations they contain. Detailed gamma is linearly sampled at 10 ft measured-depth spacing and positioned by survey MD interpolation. The default averaged mode uses the interval means described below. Missing gamma intervals remain open, and there is no extension above or below observed survey coverage. TVD retains the existing viewer convention; no SSTVD calculation or elevation alignment is applied.

The local server reads LAS files and the refreshed survey DBF from the paths in `local-settings.json`. These original files must remain available. The bundled Python runtime includes the NumPy dependency used for gamma extraction. Nothing is uploaded or changed in the source files. Source file, curve, unit, and identity/data-quality flags are shown for the selected gamma well. Automatic source choices are provisional; a source selector exposes other candidate curves.

Numerical source checks reproduce four existing viewer trajectories within 0.008 ft and exercise twelve nearby gamma loads plus three wrapped LAS files. These checks do not establish tool calibration or formation identity.

## Local video studios

The local video studios are available at `/viewer/?showcase=cluster` (35 seconds)
and `/viewer/?showcase=tour` (50 seconds). The North Dakota tour starts with the
statewide outline and survey overview, zooms into 31 wells, and shows plan, side,
3D, ten numeric coloring modes, four GR/CBL wells, and monthly production.
Use **Preview scene** to inspect the tour, then **Record 50-second tour** and
download the finished MP4. Recording uses local data and the actual WebGL
renderer. The tour preloads logs and requires the local LAS and survey sources
described above; the original showcase needs only prepared geometry and production.

## Cement bond amplitude

Choose **CBL amplitude** in **3D well logs** to switch from gamma ray to conventional 3-ft cement-bond amplitude. The initial averaged group loads 500 usable nearby wells, with additions of 100 and a 1,000-well limit; Detailed mode uses 50 initially and a 100-well limit. These are actual cement-bond amplitude curves, not gamma curves drawn from files named CBL. The first catalog excludes 5-ft amplitude, sector arrays, attenuation, bond index and VDL waveforms from this comparison.

The default amplitude display is 0–100 mV with Turbo colors; Spectral and the maximum display radius remain available. Radius is proportional to the measured amplitude up to the chosen display ceiling. This is a visual scale, not a bond-quality threshold or cement thickness. Larger/warm tubes represent higher measured amplitude. Lower amplitude can indicate stronger casing-to-cement bonding, but tool calibration, casing and well conditions also affect the response. This viewer does not establish hydraulic isolation or assign pass/fail grades.

Detailed CBL values are linearly sampled at 5 ft measured-depth intervals along the observed VERT survey branches. The default averaged mode uses the interval means described below. The source gap checks remain in use. Valid zero amplitudes are retained and shown by a thin gray centerline; null values remain open gaps. Hover shows the measured mV and MD, and the source selector identifies the curve and LAS file. The GR mode retains its previous 10 ft sampling and handling.

Manufacturer interpretation reference: https://www.slb.com/products-and-services/innovating-in-oil-and-gas/well-construction/well-cementing/cement-evaluation/cement-bond-logging-tools

## Average interval and larger well groups

The default **Sample interval** is now **100 ft average**. It starts with 500 usable nearby wells, adds 100 at a time, and allows 1,000 in view. **Detailed** restores the finer 5 ft CBL/10 ft GR display with 50 starting wells and a 100-well limit. Changing the sample interval reloads a group around the selected well; it does not mix detailed and averaged values in one view.

Each mean is computed independently within fixed 100 ft measured-depth bins from the selected native LAS curve. The calculation weights by valid measured-depth length, integrates linearly between neighboring valid samples, and excludes nulls, native depth gaps and unsupported survey intervals. It does not average between wells or convert between tools. CBL zero amplitudes remain valid. Partial interval coverage is retained and identified on hover.

Tube radius and color show interval means. Hover also shows the bin's MD bounds, valid coverage, source value range and sample count. Short changes are smoothed; use Detailed to inspect them. Source gaps remain open in the geometry. Means are cached locally and invalidated when the source LAS or survey fingerprint, measurement, interval or averaging algorithm changes. Original logs are not modified.

## Drilling spacing units (DSUs)

Enable **Show 3D DSU boxes** to load the local DSU layer. The boxes follow the
published footprint polygons, including irregular and overlapping units. They
occupy an **approximate Lodgepole–Three Forks display interval** near the laterals;
they are not columns from the surface and are not a legal interpretation of orders.
Use **Inspect DSUs instead of wells** to pick a box, choose among overlapping
records, zoom to it, or show only that DSU. Turn inspection off to select wells.
Upper/lower offsets shift the estimated boundaries in feet. The normal depth-scale
slider exaggerates wells and DSU boxes together without changing physical TVD.

The local October 17, 2026 snapshot contains 10,573 source records. Fixed acreage colors follow Bakken Forward: 1,280 green, 1,920 blue, 2,560 orange,
3,840 purple, 640 teal and 5,120 pink. Other sizes are gray. A continuous acreage
scale and spacing/drilling type remain available.
Optional saved Bakken Forward colors use a **September 12, 2026 screening model**
based on September 7 GIS. Only 759 current records have eligible exact matches;
413 matches require review and 9,401 records are unmatched. Gray means unavailable,
never zero. This historical model has not been recalculated for October data.
Its saved assumptions are 8 wells/1,280 acres, 2-mile laterals, $70 oil, 13 days/well,
and $8.5 million/well. Development is a modeled percentage; confidence is a score,
not a probability. No DSU operator ownership is inferred.

Depth placement uses converted TVD picks dated September 7: nearby same-well
Lodgepole/Birdbear pairs are preferred (up to five within 25 km). Birdbear top is an
approximate proxy for the Three Forks base. Other units use screened separate
top medians, Lodgepole +800 ft, or nearest long-lateral TVD −800/+200 ft. A regional
9,000–10,000 ft fallback exists when no control is available. All depths use the
existing provisional KB/relative-TVD convention with no reference-elevation
correction. This is an illustration, not a fitted or verified formation surface.
The inspector reports the method, control count, distances and date. Formation
surfaces and exact order-defined limits can replace these estimates later.

Generated DSU data, formation picks and historical model files remain local and
are ignored by Git. Copy `viewer/data/dsu/` when moving the populated installation.
To prepare fresh public footprints without GIS dependencies:

```sh
python prepare_dsu.py OGD_DrillingSpacingUnits.zip local-data/dsus.geojson
```

For approximate depths, supply the existing resolved converted-TVD picks CSV
(FileNo, formation_code, tvd_ft, easting_m, northing_m, top_md_ft, status,
survey_gap_ft and datum/reference fields). Source XY is EPSG:32121 metres;
`--coordinates source` requires pyproj. `--coordinates manifest` uses matching
VERT-branch bounding-box centers as approximate locations and records that choice.

```sh
python prepare_dsu_zone.py --dsus local-data/dsus.geojson --manifest full-dataset/manifest.json --tops local-data/converted-tops.csv --output local-data/dsu-zones.json
python merge_dsu_zones.py local-data/dsus.geojson local-data/dsu-zones.json viewer/data/dsu/drilling-spacing-units.geojson
```

Create the output folder before merging. Without formation picks, the viewer
can load the footprint-only output at that same path and explicitly uses the
regional approximate interval. The public ZIP has no depths or inventory fields.
Historical inventory colors require a separately audited exact-identity join;
the raw importer does not invent those estimates.

Source: [ND DMR public GIS downloads](https://gis.dmr.nd.gov/gisdownload.asp).
Geology context: [NDGS Three Forks](https://www.dmr.nd.gov/dmr/ndgs/three-forks).

### Nested overlap display

The default **Nested outlines** view keeps centers open and uses Bakken Forward's
fixed inward display offsets: 640 acres = 0 ft, 1,280 = 100 ft, 1,920 = 220 ft,
2,560 = 340 ft, 3,840 = 460 ft, 5,120 = 580 ft. Intermediate sizes interpolate;
larger units use a logarithmic extension. Fifty-foot perimeter bands are computed
with mitred negative buffers in EPSG:5070, then returned to NAD83. They are display
symbols, not setbacks or lease-line corridors. Source polygons, published acres,
inventory estimates and original depth intervals remain unchanged. Offsets depend
on nominal acreage, so filtering does not move them. If any component is too narrow
for a band, the entire record falls back to its original unfilled outline.

**Optional depth separation** starts off. It provides an exploded view by lifting
larger acreage classes above smaller ones, at the chosen feet per level; the
inspector reports each display lift separately. Well paths and estimated zone
depths do not change. **Source footprint boxes** restores the original boundaries
and disables the display lift. Selection uses full source footprints with the
same display lift and still exposes overlapping records independently.

To regenerate the display geometry, install optional Shapely and pyproj, then:

```sh
python prepare_dsu_display.py local-data/dsus-with-zones.geojson viewer/data/dsu/drilling-spacing-units.geojson
```

The helper preserves all source geometry/properties and adds separate display
geometry, provenance, containment checks and an audit. It requires NAD83 input.
The current local snapshot has 10,572 nested-band records and one original-outline
fallback. Generated geometry remains local.

### Select a DSU: wells and combined monthly production

Enable **Inspect DSUs instead of wells** and click a box, choose an overlapping
record, or use the DSU search. The associated well paths are highlighted in cyan;
other paths dim. Production ribbons on the selected group retain full opacity.
The sidebar shows whole-well combined monthly oil, coverage, reported period
volume and a well list. **Play group production** uses the existing monthly
timeline. Clear the DSU selection or hide the layer to restore the operator scope.
Operator filters intersect both the highlighted group and its production totals.
A direct link accepts `?dataset=full&dsu=STABLE_DSU_ID`.

Membership uses exact XY clipping of classified section-4 lateral segments against
the original source footprint. It unions exact shared/retraced linework within
each permit/API10 well, excludes point-only touches and unsupported MD gaps over
1,000 ft, and retains every well branch for highlighting. Display insets and
depth separation never affect membership. This is geometric association, not
legal assignment, completion attribution, ownership or a verified bench match.
The default rule requires 660 ft of lateral inside; users can choose any positive
length or at least half of the well's supported lateral length. This threshold
is an inspection choice, not a regulatory setback or drainage assumption.

Monthly volumes count each matching physical well once across its branches. They
are whole-well reported oil across pools, not prorated by clipped path length.
Missing reports are not zero; partial months are marked in the group chart.
Overlapping DSU group totals must not be summed as exclusive allocations. Available
production still ends in December 2024. The index validates the current full
survey's manifest SHA256 and branch identities; other datasets require a rebuild.

Prepare the optional association index with `requirements-dsu.txt` installed:

```sh
python prepare_dsu_membership.py viewer/data/dsu/drilling-spacing-units.geojson full-dataset viewer/data/dsu/dsu-well-membership.json
node tests/dsu-production.mjs
```

The Python helper requires prepared station tiles and aligned MD metrics. The
generated index/audit stays in ignored `viewer/data/dsu/`. Synthetic Node tests
need no external data; optional prepared data can be checked with `--data PATH`.

### NDIC order links

The selected-DSU card can show the NDIC order history and the latest stated well
allowance for the unit, taken from the local order queue's unit atlas
(`local_order_queue/unit_atlas/data.json`). The DMR shapefile carries order
numbers on only 9 of 10,573 DSUs, so links are geometric: each atlas footprint
(land description + pool) is matched to source DSU polygons by plan-view
intersection over union. A footprint at 95% or more is an exact match; 80–95% is
a close match. Both are linked, to every DSU at or above 80%. Footprints at 50–80%
go to the `review` list without a link.

The unit allowance is the most recent dated latest event across its linked
footprints, using the atlas's own latest-event order (date, then order number).
Same-day conflicts stay without a value. `mixed` marks units whose footprints
state different allowances. The card compares the allowance with the September
model's capacity and assigned wells. **Color DSUs by → Wells allowed · NDIC
orders** and **Show units → Units with an NDIC order allowance** use the same
values. Allowances are machine-extracted from order text and not human-reviewed.
A stated allowance does not prove that the order governs today.

```sh
python prepare_dsu_orders.py "C:/Users/User/Desktop/Cases and orders/local_order_queue/unit_atlas/data.json" viewer/data/dsu/drilling-spacing-units.geojson viewer/data/dsu/dsu-orders.json
python serve.py --orders-db "C:/Users/User/Desktop/Cases and orders/local_order_queue/queue.sqlite3"
```

The atlas is read without changes. The link file records the atlas and DSU
hashes, and the viewer rejects it for a different DSU snapshot. `--orders-db`
opens the queue read-only so order numbers in the card open the source PDF.
Without it the card still shows order numbers, but without links.

#### Order history from the land index (preferred)

`prepare_dsu_order_history.py` writes the same `dsu-orders.json` from the order
queue's land index (`local_order_queue/land_index`) instead of the atlas. The
index parses every extracted order's operative clauses into PLSS tracts,
including quarter and half sections, units spanning townships, pooled units and
pool zone tables, and builds their geometry from the BLM CadNSDI sections the
atlas cached. Each DSU collects every order whose unit overlaps it (80% or more)
and every Bakken zone table whose listed land contains it. A zone also has to
match the DSU's acreage (within 15%) and, when the header says STANDUP or
LAYDOWN, the DSU's plan-view shape.

Events are ordered by order number. The latest order that states a count sets
the allowance, and a later termination ends it. Within one order, a count stated
for the unit itself outranks a zone-table count. A zone header without a count
(for example `ZONE III (1280H-STANDUP)`) states acreage only and never sets or
resets an allowance. The atlas read those headers as one well. The file also
carries order applicants, which `prepare_dsu_headroom.py` uses for undrilled
units.

```sh
cd "C:/Users/User/Desktop/Cases and orders/local_order_queue/land_index"
python parse_all.py && python build_geometry.py
cd -
python prepare_dsu_order_history.py "C:/Users/User/Desktop/Cases and orders/local_order_queue/land_index/data/land_index.sqlite3" viewer/data/dsu/drilling-spacing-units.geojson viewer/data/dsu/dsu-orders.json
```

Rebuild `dsu-headroom.json` afterwards. Orders still pending in the queue are
missing until they are extracted and the index is rebuilt.

### Remaining permitted wells

For each DSU with a single linked allowance, `prepare_dsu_headroom.py` subtracts
the wells drilled there: distinct Bakken-pool wells with at least 660 ft of
surveyed lateral inside, from `dsu-well-membership.json`. Wells whose Well Index
`ProducedPools` names only another pool (Madison, Red River and others) are not
counted. `SANISH` counts as Bakken, and blank or confidential pools are kept.

Overlapping units share wells, so statewide totals assign each well to one unit:
the one holding the largest share of its lateral, with ties going to the smaller
unit. Units with a stated allowance take precedence over overlapping units without
one. The card shows both counts. `remainingConservative` instead subtracts every
well from every unit it crosses, giving a lower bound. Well Index `LOC`, `DRL`
and confidential horizontal permits not yet in the survey count as pending, by
surface location. The holder is the operator group of most wells in the unit, or
the latest order's applicant for undrilled units. County comes from Well Index
records in the order's sections.

**Color DSUs by → Remaining permitted wells** maps the balance (red is over the
allowance). **Show units → Units with remaining permitted wells** filters to units
with room. **Remaining permitted wells · statewide** lists totals by county,
operator or pool; clicking a row shows only its units. Units over their allowance
carry a review hint. A large overlapping unit authorized for one or two wells
usually means the underlying units' orders are not linked yet.

```sh
python prepare_dsu_headroom.py viewer/data/dsu/dsu-orders.json viewer/data/dsu/dsu-well-membership.json viewer/data/dsu/drilling-spacing-units.geojson full-dataset "C:/Users/User/Downloads/Well_Index (14).zip" "C:/Users/User/Desktop/Cases and orders/local_order_queue/unit_atlas/data.json" viewer/data/dsu/dsu-headroom.json
```

A positive balance is room under the latest linked order, not a verified
drillable location. The holder is not legal unit operatorship. The
`local_order_queue/well_inventory/` preview computed the same comparison per
atlas footprint; this build replaces it inside the viewer.

### Inventory methodology review

The September scenario is retained as a legacy model under review, not a current
validated count of remaining drillable wells. An October 17 local audit examines
overlap allocation versus engineering capacity, exclusive well assignments,
geometry-fingerprint reproducibility, well-count versus length-equivalent measures,
unknown benches and validation requirements. The populated installation includes
`viewer/inventory-review.html`; detailed retained-model audit outputs stay local
and are not published in this source repository.

The proposed replacement uses actual PLSS township/section land accounting,
within-well lateral union, explicitly chosen development layouts and persistent
candidate corridor IDs across overlapping DSU alternatives. Township aggregation
must use the shared nonoverlapping ledger rather than sum the old DSU estimates.
No replacement inventory or calibrated development probability is claimed by
this viewer feature.

## Lateral footage inventory (October 17, 2026)

Open /viewer/?dataset=full&inventory=dsu or /viewer/?dataset=full&inventory=township.
Enable Show footage scenarios, choose a geography and metric, and switch low/base/high capacity. DSU cards and township search/click selections show mapped lateral feet, measured eligible acres, and all three scenario results. Township metrics cover eligible Bakken DSU land within each township; full township acres and coverage are shown separately. September DSU results remain in their original color options and the comparison card.

Initial rates are 49.5 / 66 / 82.5 lateral ft per acre: illustrative comparisons, not calibrated forecasts. Edit the densities and Apply; Reset comparison restores them. Values above 100% remain visible. Feet remaining is scenario footage headroom rather than verified locations. Surveyed plan footage is a drilling proxy, not verified completed footage or MD. Inventory includes all surveyed operators regardless of display filters. Never add overlapping DSU totals.

The new data files are viewer/data/inventory/footage.json and townships.geojson. They require the exact October full survey manifest and installed boundaries. Other dataset folders remain viewable, but unmatched footage analysis is unavailable. No internet is needed for these prepared assets. Turbo attribution and Apache 2.0 terms are in viewer/TURBO-LICENSE.txt.
