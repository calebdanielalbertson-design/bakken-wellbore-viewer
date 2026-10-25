# Bakken remaining-well inventory: implementation audit and replacement plan

Reviewed **October 17, 2026**. Purpose: identify undeveloped drilling potential, compare operators with stated attribution limits, and eventually support rig-demand planning. This is the requested first-stage review. No inventory output, density setting, source workbook, viewer asset, or application code was changed for this review.

## Recommendation on eight wells per 1,280 acres

Replace the single statewide assumption with **regional, target-specific density scenarios and an explicit candidate-location review**. Retain the original eight-well-per-1,280 method and results as the historical baseline. For a controlled comparison in the new length-based calculation, also use a clearly labeled density case of eight two-mile equivalents; its results will differ from the historical count-based method. The available evidence does not support substituting another universal number today.

The density assumption is only one source of error. Capacity and existing development must use the same geographic footprint and compatible units before density calibration can produce meaningful results. In the saved September model, overlap-adjusted acreage and exclusive whole-well assignment do not meet that condition. Raising or lowering eight would not repair it.

Use a first-stage screening measure of **two-mile equivalents per 1,280 measured eligible acres**, separately for each supported target and region. Calibrate against manually verified development patterns and production response, then test feasible trajectories and incremental section-line locations. Observed density is evidence of development, not proof that an area is fully developed or that its highest observed density is economically optimal.

For illustration only, an ideal 1,280-acre rectangle is 5,280 ft wide by 10,560 ft long. Eight parallel two-mile paths in one target imply a nominal 660-ft strip width. Four paths in each of two targets imply 1,320 ft per target under the same simplified arithmetic. Neither illustration accounts for setbacks, geology, interference, or actual drainage. Thus “eight” is ambiguous unless its length and target population are defined.

North Dakota Geological Survey RI-135 distinguishes Middle Bakken, upper Three Forks and middle Three Forks development. Its study area has approximately three to six wells per reservoir horizon per 1,280 acres, with additional middle Three Forks development in selected units. These are local observed patterns, not statewide recommendations. The evidence supports target and regional differentiation. See [RI-135, printed pp. 4 and 14–22](https://www.dmr.nd.gov/ndgs/documents/publication_List/pdf/RISeries/RI-135.pdf). The larger follow-up study reports variable incremental recovery across the sampled units, further supporting validation rather than automatically adding a bench everywhere. See the [DMR study announcement](https://www.dmr.nd.gov/dmr/news/middle-three-forks-2nd-bench-bakken-petroleum-system-contains-hundreds-millions-barrels).

## 1. Versions and evidence boundaries

There are three distinct inventory implementations plus the viewer. They must not be described as one calculation.

| Label | Available artifact | What it establishes |
| --- | --- | --- |
| Historical workbook (HW) | DSU_Well_Inventory_Report_MA_Consolidated.xlsx | Workbook method statements, formulas, cached assignments and operator/account rollups. Its original spatial build code and exact source shapefile snapshots were not found. |
| Saved September model (S12) | after_final | Saved September 12 inventory and code snapshot, using September 7 GIS. This is the model imported into the viewer. |
| Latest available Bakken Forward source (BF) | bakken-forward | Newer source with important safeguards and a separate local development-area worksheet. This portable checkout alone does not establish a running application's environment or current numerical totals. |
| Current local 3D viewer (V) | [dist](../dist/) and [prepared full dataset](../outputs/wellbore-viewer/full-dataset/) | October 17 surveyed geometry, DSU selection and production display, with dated S12 inventory fields retained as historical values. It does not run BF's inventory engine. |

Source code is the evidence for confirmed behavior. Older READMEs, model column names and the user's historical description are context, not proof of the active code path. Some BF documentation still describes legacy probability/price features that the latest engine no longer computes.

### Available datasets

| Dataset | Confirmed availability and scope | Material limitation |
| --- | --- | --- |
| HW | 22,321 distinct API/UWI rows and 10,594 DSU-detail rows; full workbook SHA-256 recorded below | Prepared spatial fields are stored values. Exact source vintage and geometries cannot be reconstructed from workbook formulas alone. |
| S12 | 10,594 saved DSUs, accepted/candidate assignment tables, code snapshot and input manifest | Dated September 7 spatial inputs; not an October inventory. |
| Viewer survey | October 17 download provenance; 48,929 branch records, 22,498 distinct permit/API10 well identities, 5,495,609 stations | A branch record is not a new physical well, completed interval or verified drilling event. |
| Viewer DSUs | 10,573 source records, 10,570 canonical records after exact duplicate collapse; 10,569 eligible Bakken records and one unknown formation | Published formation is not a verified well bench. Legal roles of overlapping orders remain unresolved. |
| Viewer measured acreage | Eligible canonical nominal acres sum 17,726,040; measured whole polygons sum 17,697,961; unique union is 8,123,596 acres in EPSG:5070 | These are different measures. Gross polygon totals are not additive development acreage. |
| Viewer membership | 21,168 wells have positive classified-lateral overlap with at least one supplied DSU; 1,262 with usable lateral geometry have none; 68 lack usable lateral geometry | These October geometric categories are not comparable directly with HW's 1,206 representative-point assignment failures. |
| Viewer monthly production | 20,826 matched production well identities, 337 available months: separate December 1952–December 1955 and January 2000–December 2024 periods | No supplied 1956–1999 or 2025–2026 production coverage. Missing reports are not zero production. This is not a complete-life EUR dataset. |
| Production source files | Provided 2000–2023 CSV, `DMR production 2024.xlsx`, and `DMR production 1951 1955.xlsx` exist; source row counts and hashes retained in the new dataset audit | File names do not establish complete month/well coverage. The older ODS mentioned in the conversation is not an established input to the current prepared playback. |
| PLSS | Local `Downloads/Townships (2)` and `Downloads/Sections (2)` shapefiles; 2,062 township fragments/2,047 township-range keys; 71,436 section fragments/71,331 section keys | Dissolve fragments using the supplied full keys and directions. Do not invent a missing principal-meridian attribute or treat township boundaries as legal DSUs. |
| Separate BF feed snapshot | Available external `.gis_data/current.json` was checked October 10: 43,983 well records, 48,827 horizontal records/22,449 FileNos, 10,583 DSU records | This is a different snapshot from V. Its detailed survey archive remains September 7. |
| BF runtime dependencies | Config supports external database, GIS, order-corpus and analytical paths | BF's portable directory has no default `local_data/production.db` or `.gis_data/current.json`. Runtime inputs cannot be inferred from defaults. |

Sources: [viewer download provenance](../outputs/wellbore-viewer/full-dataset/download-provenance.json), [existing geometry diagnostics](../work/inventory-review-2026-10-17/diagnostics.json), [membership audit](../work/dsu-membership-2026-10-17/dsu-well-membership.audit.json), [production audit](../outputs/wellbore-viewer/full-dataset/production-audit.json), and the new [historical/dataset audit](../work/inventory-methodology-2026-10-17/historical-method-audit.md). Counts are qualified by their own input populations and dates; they are not a new remaining-inventory estimate.

## 2. What the implementations actually calculate

### 2.1 Historical workbook

`Method & Assumptions!B4:B7`, `B12:B13` describe eight wells per 1,280 acres, 160 acres per well, a 0.0025-degree grid (approximately 12.8062 acres per cell near 48°N), one length-weighted horizontal representative point per well, and one acreage allocation per cell with priority to 1,280-acre DSUs. Those are workbook statements. The original grid origin, clipping rules, tie-breaks and exact geometry-processing implementation remain unavailable.

`DSU Detail` has separate gross, allocated unique-footprint, assignment and capacity fields. Representative row formulas:

```text
J3 = D3 / 'Method & Assumptions'!$B$5     gross-acre capacity
M3 = L3 / 'Method & Assumptions'!$B$5     unique-footprint capacity
K3 = MAX(J3-I3,0)                        gross-capacity residual
O3 = MAX(M3-N3,0)                        unique-capacity residual
```

The density cell `B4=8` and acres-per-well cell `B5=160` are separate literals. **Changing B4 alone will not change those capacity formulas.** Spatial inputs in `L` and assigned counts in `N` are static prepared results. `Operator Ranking!C:J` are stored aggregates; the M&A crosswalk links those aggregates, and `Consolidated Ranking` uses `SUMIF` over the crosswalk. `Executive Summary!B4:B6` are stored headline totals. Editing an assumption is not a verified refresh of the workbook.

**Historical audit findings confirmed within HW:** `Source Audit!B9` and blank `Well Assignment!G3:G22323` identify **1,206 of 22,321 wells without an assigned DSU**. `DSU Detail` contains 1,706 rows labeled `UNASSIGNED / NO WELL OPERATOR`; their `L` values sum to **2,102,481.1614 acres**, matching `Executive Summary!B5`. Those rows still contain **15 assigned wells**. Unattributed acreage therefore cannot be interpreted as virgin or undeveloped acreage. These findings have been reconciled to stored workbook rows, not reproduced from original GIS inputs and not adopted as current totals.

### 2.2 Shared S12/BF spatial engine

The two available `data/dsu_spatial.py` files are byte-identical. Their behavior differs materially from HW:

- `normalize_dsus` checks geometry/CRS, creates geometry-and-attribute identities and collapses exact duplicate records. Eligibility uses the reported DSU formation `Bakken`.
- `allocate_footprint` projects to **EPSG:5070**, polygonizes boundaries into atomic faces and allocates each face equally among covering records. It checks that allocated area equals union area. There is no 12.8-acre grid or preference for 1,280s.
- `match_legacy_dsus` uses validated identities and a conservative one-to-one historical crosswalk; row order is not a general join key.
- `assign_paths` dissolves horizontal linework by **FileNo**, finds exact intersections and assigns at most one DSU. It requires at least 90% whole-path coverage. A supported historical association can prevail; otherwise the best candidate must lead the next by at least five percentage points. Other cases retain review statuses.
- `representative_point()` at line 192 supplies DSU inspector coordinates. **It is not the well-assignment method.** The feed checks API conflicts, but operational assignment/deduplication is by FileNo, not the historical workbook's API/UWI point procedure.

`unique_footprint_acres` is **equal-share accounting acreage**, not an exclusive spatial parcel, ownership entitlement or drillable footprint. Keep separate: published nominal `dssize/size_acres`, measured whole `polygon_acres/gross_dsu_acres`, equal-share accounting acres, and selected-area `union_acres`.

### 2.3 Saved September inventory

The frozen S12 inventory engine uses allocated shares for capacity and accepted whole-well assignments for depletion. At density eight and the saved $70 price assumption, it first sets `capacity = round(allocated acres / 160, 1)`, then computes the count-based residual as `round(max(capacity - assigned wells, 0), 1)`. It also carries length-equivalent residuals and an assumed future-lateral conversion. The viewer's saved “remaining wells” field comes from the count-based residual.

The old equivalent helper replaces every lateral length below 3,000 ft with 10,000 ft. Old missing production is filled with zero, and heuristic rules populate development-probability fields. A legacy oil-price multiplier also scales capacity; it is neutral at the saved default of $70. Those are confirmed legacy behaviors, not calibrated geological, economic or timing models.

The existing [S12 audit](../work/inventory-review-2026-10-17/methodology-audit.json) records 5,970 published records and 4,624 review records. Of the published records, 4,198 have material polygon overlap. In 2,290 published DSUs, at least one September mapped well path with at least 90% coverage was accepted in another DSU; 1,028 show positive residual and no assigned wells despite such paths. This demonstrates a capacity/depletion alignment risk, not a replacement count of remaining locations.

### 2.4 Latest BF inventory engine

`app.main` merges the saved current well feed, rebuilds current spatial assignments and conditionally overlays detailed-survey lateral metrics. The inventory route requires current polygons. Its forecast route returns earlier and follows a separate activity-workload calculation.

`compute_dsu_inventory` deduplicates `FILE_NO, dsu_id`, aggregates accepted wells, and applies:

```text
D = selected density in two-mile equivalents per 1,280 acres
A = measured whole-polygon acres
whole_boundary_capacity_eq = round(A / 1,280 * D, 1)
existing_eq = sum(round(inventory_length_ft / 10,560, 2))
count_residual = max(capacity_eq - assigned physical-well count, 0)
equivalent_residual = max(capacity_eq - existing_eq, 0)
future physical-throughput equivalent = equivalent_residual / (future miles / 2)
```

These are parallel code fields, not equally valid units. The count residual mixes physical counts and two-mile equivalents whenever lengths differ. `remaining_per_1280` and `remaining_percentage` use it; `dev_percentage` uses equivalents. Their percentages need not complement one another.

Important newer safeguards at lines 127–212:

- Material overlap (more than 1 m² difference between whole and allocated share) withholds additive capacity/residual stock; whole-boundary capacity remains inspectable. Equal shares no longer define development capacity.
- Assignment-review or missing/nonpositive-length cases withhold remaining estimates. Positive short lengths are retained.
- `production_available=False` is the default, and the active caller does not enable it. Production quality remains unavailable rather than silently using stale data.
- Development-probability columns are explicitly unknown. Oil price is retained for API compatibility and no longer scales capacity.
- Operator attribution is conservative and separately reviewed, as discussed below.

The length overlay chooses the longest classified lateral branch per FileNo, with tie-breaks; it does not select a verified completed branch. `overlay_metrics` uses MD intervals whose endpoints are classified lateral, otherwise a plan-view path proxy. Spatial assignment and engineered length can consequently use different branch populations.

### 2.5 Existing local development-area worksheet

`area_path_evidence` unions selected DSUs in EPSG:5070, dissolves paths within each FileNo and clips them to that same union. `mapped_equivalents = clipped plan-view feet / 10,560`. This is the best existing starting point for spatial consistency; it still does not verify completed intervals, targets or reservoir depletion.

`worksheet_scenario` calculates:

```text
base_capacity_eq = union_acres / 1,280 * selected_density
extra_capacity_eq = user-entered total extra locations * (future miles / 2)
combined_residual_physical = max(base_capacity_eq + extra_capacity_eq
                                 - mapped_equivalents, 0) / (future miles / 2)
```

“Total extra” includes already-drilled section-line locations, whose mapped paths are deducted once. No additional polygon alone creates capacity. Local worksheets may overlap and are explicitly `forecast_eligible=False`; their residuals must not be summed into a basin forecast.

### 2.6 Viewer selection and production

[`build`](../work/dsu-membership-2026-10-17/build_membership.py:106) prepares exact original-footprint intersections of classified survey lateral segments. It unions retraced/shared linework within each well and excludes MD gaps above 1,000 ft. The [membership controller](../dist/dsu-wells.js:3) verifies the survey snapshot and offers any positive overlap, at least 660 ft, or at least 50%. Display insets and exploded-depth boxes do not alter membership.

The [production model](../dist/production-model.js:11) deduplicates selected branches to well production identities. It displays **whole-well production once within the selected group**, without clipping/prorating production to acreage. A well can occur in multiple overlapping DSU groups; group totals are nonadditive. Neither membership nor production aggregation is legal DSU allocation or an inventory calculation. [`enrich`](../work/dsu-2026-10-17/enrich_dsu.py:25) imports S12 metrics only after exact frozen fingerprint/attribute checks; line 63 maps `theoretical_remaining_wells` to the viewer's `remainingWells`. [The viewer](../dist/dsu.js:25) labels those estimates as legacy values under review.

## 3. Answers to the seven accuracy questions

| Question | Confirmed answer and consequence |
| --- | --- |
| 1. Two-, three- and four-mile consistency? | HW and the saved viewer count residual do not consistently length-normalize depletion. Latest BF has two-mile equivalents and divides future equivalents by 1/1.5/2, but parallel count-based fields remain inconsistent. Example: three existing 2/3/4-mile paths count as 3 physical wells and 4.5 equivalents. Against capacity 8, residuals are 5 versus 3.5. No arithmetic conversion proves three- or four-mile paths fit the selected land. |
| 2. Same capacity/depletion boundary? | S12 uses allocated accounting acreage versus an exclusively assigned whole well. Latest BF uses whole polygon acreage but subtracts full selected-branch length, even when only 90–99% of the combined assignment path lies inside. The separately chosen metric branch is not clipped. Assignment dissolves all mapped branches, while metrics select one branch. The development-area worksheet does clip path and area to the same union. |
| 3. Section-line opportunities suppressed? | HW's priority grid cannot represent overlapping legal roles by unique acreage alone. S12 equal shares shrink base capacity when overlays are added. Latest BF conservatively withholds overlapping stock. Real incremental section-line opportunities require order/trajectory evidence; neither deleting overlays nor adding their full acres is valid. |
| 4. Acreage fields separate? | BF/V diagnostics distinguish nominal, measured polygon, equal-share accounting, and union acreage. HW separately retains nominal gross and grid-derived unique acres, but no independently measured polygon-acre field was established in this audit. Its degree-grid approximation is not an exact projected-area calculation. Rename/document “unique” carefully; retain all measures. |
| 5. Targets, sidetracks, abandonment, completions? | Capacity is not bench-specific. Current TVD clusters are explicitly “Depth group N”, not geological benches. Longest-branch selection and whole-well status do not identify completed intervals or abandoned branches. Counts and footage can overstate or understate occupied development. Preserve physical-well, branch and completion identities separately. |
| 6. Operator attribution? | HW reports historical operator/account mappings. Latest BF labels a DSU only when all assigned wells have one valid, supported GIS-reported operator; mixed/unknown/empty cases remain unassigned. This is a well-operator association, not ownership of undeveloped acreage or a future development commitment. Dated display groups are separate from legal operator and commercial-account mappings. |
| 7. Missing data interpreted as zero? | HW has stored unassigned categories; their acres are not undeveloped land. S12 production nulls became zero. Latest BF withholds many unknowns, but zero assigned wells still does not establish complete geometry coverage. A residual SQL length default and default pandas sums remain risks. Viewer unavailable production is distinct from reported zero; unmatched inventory is gray rather than zero. |

ND DMR explains that spacing units include vertical limits and that overlapping units can enable section-line recovery. Its example corridor dimensions are explanatory, not a substitute for the applicable order and setbacks. Preserve the original legal boundaries and review order-specific incremental locations. See [DMR well-permitting guidance, spacing and overlapping-unit questions](https://www.dmr.nd.gov/dmr/oilgas/wellpermitting).

## 4. Prioritized accuracy risks and supporting evidence

**P0 — Resolve before publishing additive inventory or operator inventory rankings**

1. **Capacity/depletion boundary mismatch and overlapping legal roles.** The S12 findings above show this affects published values. The current 10,569 eligible DSUs have 22,761 positive-area overlap pairs; gross measured area is 2.18 times the union. Latest BF's withholding is an improvement, not a resolution of feasible inventory. Build a geographic ledger and a distinct legal-unit/candidate relationship table.
2. **Unverified target and occupied-interval population.** A broad `Bakken` polygon label, raw TVD, a mapped branch or a plugged/abandoned well status cannot determine which target/corridor remains available. No validated bench/active-completion ledger is present. Do not automatically return abandoned-well acreage to inventory, count every mapped sidetrack, or multiply acres by an assumed bench count.
3. **Insufficient model-to-current geometry coverage.** V currently carries 759 available S12 estimates, 413 review matches and 9,401 unmatched records. The 759 available-estimate footprints cover about 9.86% of the current DSU union; this is coverage of saved model values, not percent development. Existing diagnostics find many geometrically compatible unmatched units and a fingerprint reproducibility issue, but do not isolate its runtime/library cause. Resolve one-to-one identity/version joins before comparing totals or expanding matches; do not silently relax joins.
4. **Density lacks regional/target calibration.** Eight/160 is a screening input. No reviewed calibration sample, target-specific prospective mask, optimal-spacing study or validated candidate set underpins it. The workbook's disconnected B4/B5 literals also make a simple parameter edit ineffective. Keep comparisons explicit and withhold unsupported “feasible locations” totals.

**P1 — Resolve before interpreting residuals and operator comparisons**

5. **Length and count units disagree.** BF retains count-based and equivalent-based residuals, rounds each existing equivalent before summing, and mixes MD and plan-view proxies. S12's under-3,000-ft replacement affected 408 accepted wells in 337 DSUs and added 314.46 equivalents in that helper. That historical equivalent inflation does not explain the viewer's separate count-based residual by itself. Future outputs must name their units and round only at display time.
6. **A remaining missing-length escape path.** `db._load_base_data` uses `COALESCE(measured lateral, overlap_ft, 10000)`. `current_assignment_rows` labels a positive inherited value historical measured length. The current classifier overlay replaces it when available, but app lines 103–104 are conditional. A finite default can therefore evade the missing-length flag. Preserve measured/proxy/default provenance from ingestion and test the no-classifier route.
7. **Operator inference on undeveloped acreage.** Latest `operator attribution` avoids historical-applicant fallback and mixed-operator majority assumptions. Nonetheless, a single nearby/assigned operator is not proof of undeveloped-acre control. `compute_operator_inventory_summary` explicitly uses reported operators without parent rollup. `operator_groups` supplies dated display relationships; no active commercial/customer-account inventory crosswalk was found. Unknown acreage must remain visible and excluded from attributed rankings, with coverage shown.
8. **Unknown coverage can still look like no development.** S12 has 4,390 zero-assigned DSUs; 1,531 of these also have withheld stock. Latest BF masks reviewed stock and operator aggregates, but generic stock `sum` calls at `economics_engine.py:39–43` can produce zero for all-null unflagged input. This is an input-contract weakness, not a finding that the currently flagged pipeline publishes those zeros. No accepted well must mean “none accepted under this rule,” not “no well exists.” Missing spud dates also make recorded activity incomplete; zero recorded activity does not establish a dormant landbank. Report rejected, outside, unusable, unmatched and unclassified populations separately, with null-preserving aggregates and coverage denominators.

**P2 — Resolve before timing, economics or rig-demand claims**

9. **Stale/incomplete production and uncalibrated scores.** S12 has 5,448 accepted wells missing its 12-month benchmark; frozen missing values were filled with zero. Latest BF defaults production to unavailable and removes probability rules. Its 88/68/48/25 confidence values remain heuristic categories, not probabilities. V's playback ends in 2024 and cannot validate 2026 development timing or establish remaining EUR by itself.
10. **Inventory and future activity answer different questions.** Latest `activity_baseline` and `project_workload` project conditional workload independently of DSU coverage. They use source-dated activity and explicit operating days/time fractions, and can accept finite physical inventory separately. The observed feed is statewide, not automatically Bakken-only. These scenarios do not validate remaining locations or operator capital commitments.

## 5. Practical validation plan

### Freeze and reconcile inputs first

Use one declared vintage per run and retain HW, S12, BF-source and V comparisons separately. Freeze source archives, code hashes, CRS transformations, geometry/branch identifiers, status and production cutoffs, density scenarios and operator mappings. Keep exact input identity as well as tolerant geometric diagnostics. A newer source timestamp must not relabel an older survey or production series.

Create a small manually reviewed pilot before a basin-wide replacement. Start with these real diagnostic examples already present in the viewer:

| Viewer DSU / location | Known evidence | Validation question |
| --- | --- | --- |
| `dsu-5e86a06ae71c8929aae6`, T152N R96W sections 29/32, source record 6700 | S12 measured 1,282.12 acres versus 320.48 allocated; saved capacity 2, assigned 1, residual 1. Fourteen other September high-coverage paths were accepted elsewhere. October selection has 17 wells at the 660-ft rule. | Reconcile dates, targets, original footprint, overlapping orders, branch status and every occupied path. Geometric membership alone does not mean 17 valid completed wells in one target. |
| `dsu-8490cb7c4c2b884f9fd4`, T146N R94W sections 16/21 | S12 capacity/residual 2.7, assigned zero; eight high-coverage paths accepted elsewhere. October geometric group has eight wells. | Demonstrate why zero assigned is not a finding of undeveloped land. Explain the two 2,560-acre overlays before estimating any incremental corridor. |
| `dsu-0e6eb4434fe910558aed`, T155N R103W sections 15/22, source record 1 | S12 capacity 2.7, assigned 1; count residual 1.7 versus equivalent residual 2.2. October group includes permit 21240. | Reconcile physical count, classified MD, clipped XY footage and assumed future length. |

These are diagnostic cases, not a representative calibration sample or reviewed location forecasts. Add verified examples of a clean nonoverlapping 1,280, an elongated 1,920/2,560 long-lateral unit, a 3,840 unit, an irregular footprint, a cross-township lateral, a section-line layout, a mixed-operator/no-operator area, and known completed versus abandoned branches. Specific additional units and their completion evidence are **not yet selected**. Include both developed and lightly developed areas across regions; do not select only highly productive surviving wells.

For each pilot, produce one inspection map and a reconciled ledger with legal order/role, nominal/measured/accounting/union acres, physical wells, branch/completion status, verified/unknown target, full and clipped footage, equivalent depletion, operator basis, excluded records, candidate layouts and unresolved evidence. Validate with original orders and well/completion records, not solely the 3D box display.

### Required checks and acceptance criteria

| Check | Expected result |
| --- | --- |
| Area/CRS | EPSG:5070 measured areas independently checked against a suitable local projected or geodesic calculation. Suggested investigation threshold: differences above 0.1%, with tolerances documented and explainable. No degree-grid area is treated as exact. |
| Overlap conservation | Atomic face/accounting shares sum to the union within declared numeric tolerance. Adding an exact duplicate or an overlay order does not change unique land, observed footage or base physical opportunity. |
| Boundary consistency | A path with 9,200 of 10,000 ft inside contributes 9,200 ft to that analysis area; whole footage remains a separate field. Disjoint subarea footage reconciles to union footage. |
| Mixed lengths | Three 2/3/4-mile paths retain count 3 and equivalents 4.5. Conversion to a future length occurs once. All percentages declare the same capacity/depletion units. |
| Branches/targets | Known abandoned branches excluded only with evidence; simultaneous completed branches retained. Shared segments deduplicated within a physical branch system without merging separate wells or targets. Unknown state/bench stays unknown. |
| Section-line cases | Two adjacent base units plus an overlay do not add duplicate base acreage. Reviewed incremental locations add once, including already-drilled extra locations in total capacity and deducting their occupied footage once. |
| Missingness/identity | Blank operator, no classifier, absent survey, missing API, conflicting FileNo/API, absent production and failed joins remain distinguishable from genuine zero. Reordering inputs cannot change assignments. |
| Aggregation | One global physical-well count remains distinct from local intersection counts. Overlapping legal-unit/group production totals are not summed. Alternative candidate layouts cannot contribute the same future well twice. |
| Calibration | Compare observed target-specific footage/density and incremental performance across reviewed regional cohorts. Hold out spatial areas; do not treat densely drilled areas as proven optimum. Sparse samples retain a documented broad scenario or unavailable result. |
| Retrospective change | Freeze what was knowable at the baseline date, then compare verified later spuds/completions/first production. Newly observed GIS IDs are not new drilling. Use a sufficiently long follow-up for any proposed 12-month probability model. |

Existing tests in BF cover acreage conservation, length conversion, missing-length review, branch selection and the local worksheet. They were **inspected, not rerun** in this documentation-only review; this report makes no new full-suite pass claim. Existing V membership audit reports 14 tests and 60 independent clips; those are evidence of geometric association, not inventory validation.

## 6. Replacement calculation and density calibration design

1. **Keep the legal registry intact.** Store canonical units and order roles separately from an additive geographic reporting partition. Use township/section or another fixed partition for reporting, with geometry clipped to a declared eligible prospective mask. Avoid assigning land permanently to whichever legal polygon wins a priority rule. A reporting cell is not a drilling authorization.
2. **Build a target-aware spatial footage ledger.** Retain FileNo, root API, full API/UWI, branch and completion identifiers, source/date, geometry quality and status. Allocate verified completed lateral plan-view footage across the same boundaries used for area. Retain survey MD footage separately for engineering. Exact shared path duplication can be removed within the same physical well/target; never dissolve different wells or stacked targets into one occupied line. Where completion/target evidence is missing, label a mapped-footage proxy rather than reservoir depletion.
3. **Define a versioned density table.** Each row needs region, target, effective date, reference length, scenario, density or spacing, evidence cohort, sample size, uncertainty, exclusions and reviewer. Middle Bakken, upper Three Forks, middle/lower Three Forks and Pronghorn require supported distinctions; unknown targets remain a separate bucket. Regions should follow supported geology/development behavior, with townships serving as reporting geography rather than assumed homogeneous reservoirs.
4. **Calibrate scenarios from reviewed evidence.** Measure completed footage per eligible acre and across-lateral spacing by target in mature pilot areas, alongside incremental well/area production and completion vintage. Include unsuccessful/inactive outcomes and parent/child timing where available. Use low/base/high engineering scenarios reflecting evidence and constraints, not arbitrary percentiles of all current counts. Account for target interaction before summing target capacities. No numerical replacement defaults are selected in this first deliverable.
5. **Use compatible screening equations.** For analysis area `a`, target `b`, scenario `s`: `capacity_eq[a,b,s] = eligible_acres[a,b] / 1280 * density_eq_per_1280[region,b,s]`; `occupied_eq[a,b] = allocated_completed_plan_feet[a,b] / 10560`. Store the signed balance and separately `max(balance,0)`. Summing positive cell residuals differs from clamping a regional net balance; publish the chosen aggregation rule. This remains theoretical headroom, not a count of feasible wells.
6. **Create candidate locations and alternative layouts.** Apply evidence-backed target extent, order-specific setbacks, lateral-length feasibility, already occupied trajectories and incremental corridor roles. A three- or four-mile candidate may cross several reporting cells; give it one stable location ID and count it once. Maintain mutually exclusive alternative layouts. Review interference, leases/rights, surface access and operational/economic constraints as separate filters; absent evidence is not a pass.

The output should distinguish **theoretical equivalent capacity**, **screening residual**, **reviewed feasible physical locations**, **timing scenarios**, and **expected drilling workload**. Until feasibility is reviewed, label physical conversions “scenario throughput equivalents,” not “locations left to drill.”

## 7. Phased implementation plan

| Phase | Deliverable and acceptance gate | Preservation/comparison |
| --- | --- | --- |
| 0. Audit and freeze — this deliverable | Versioned findings, formula trace, inputs/missingness inventory, representative validation design and source fingerprints | Retain HW, S12, current viewer and latest BF source without changing results. |
| 1. Identity and evidence | Reconcile current-to-historical DSU identities; build FileNo/API/branch/completion links; remove silent length defaults in a new calculation path; explicit missingness and source-date coverage | Generate new dated tables alongside originals. Explain changed rows by identity, source refresh, method, length, status and attribution. No unexplained zero/unmatched conversion. |
| 2. Consistent area/footage prototype | Additive geographic ledger, conserved target-aware clipped footage, actual counts separately; independently checked projected acreage | Compare HW priority-grid, S12 equal-share/exclusive assignment, and same-footprint prototype on the same frozen pilot inputs. Keep density eight fixed for this controlled method comparison. |
| 3. Density and location pilot | Reviewed regional/target density scenarios, order-role ledger, explicit incremental section-line candidates and mutually exclusive 2/3/4-mile layouts | Compare the new calibrated cases against the fixed-eight equivalent comparison and retain the original historical count-based outputs; separate density effects from geometry effects. Promote only reviewed feasible candidates. |
| 4. Operator comparisons and validation | Separate reported legal operator, effective-dated ownership/working-interest evidence and commercial account mappings; publish unknown/unattributed shares and spatial holdout results | Rank comparable covered populations. Do not credit unattributed undeveloped land to a nearby operator or sum alternative layouts. |
| 5. Timing and rig-demand planning | Independently validated activity/timing assumptions and length/region-specific operating cycles; finite reviewed physical-location stock where available | Keep geological potential separate from capital/activity choices. Backtest using original as-of information; scenario ranges are not calibrated probabilities. |

For phase 5, convert modeled physical spuds to average rig workload using `sum(wells * operating days per well) / (period calendar days * operating-time fraction)`. Use cycle assumptions appropriate to the actual length mix, account for permits/DUCs/completions separately, and avoid reapplying a length multiplier already included in cycle time. The latest BF activity screen already supplies a separate conditional-workload framework; it must not make unresolved inventory appear validated.

## 8. Missing inputs and unresolved decisions

- Original HW spatial build code and exact source `Operator DSU` / `OGD horizontals with operator` shapefile snapshots, including grid origin, edge/tie rules and source dates. Workbook stored results cannot prove geometric reproduction.
- Verified per-well/branch completed or perforated intervals, sidetrack relationships, abandonment chronology, multi-lateral status and a consistent physical-well identity crosswalk.
- Formation/bench assignments supported by well records/geosteering/tops, with common depth/elevation references and prospective target limits. Raw TVD and the approximate Lodgepole-to-Three-Forks display box do not supply this.
- A reviewed representative calibration cohort, target-specific spacing/interference evidence, incremental recovery and suitable economics. Current playback through 2024 is insufficient for current production-based timing validation.
- Order-specific spacing, vertical limits, effective/superseded orders, corridor authorization and allowed location counts. Existing corpus/shape hints can aid review but are not a validated statewide capacity ledger.
- Undeveloped-acre operator/control evidence, effective-dated ownership/working-interest information, and the intended commercial-account crosswalk. Historical applicant and current display grouping cannot substitute for these.
- Permit validity, spud/completion/first-production history, capital/rig plans and operating-cycle evidence for a defensible drilling-demand model.
- Verified active BF environment paths if a runtime reproduction is required. The reviewed portable source and the live 3D viewer use different assets and do not prove a shared current runtime.
- Complete original input archives for reproducibility. The September 7 raw survey ZIP is absent at its manifest path, although 32 detailed derived point shards and branch products remain available. Some older GIS archives could not be read directly; their normalized Parquet files were read and hashed, while archive hashes remain manifest-reported. The historical/dataset audit records these distinctions.

These inputs remain explicitly missing or unvalidated. They have not been inferred from map appearance, zero assignments, operator proximity, or the number of depth clusters.

## 9. Reproducibility and preservation record

New review material is confined to this file and `work/inventory-methodology-2026-10-17/`. Existing published assets, workbooks, saved inventory, databases, source archives and application source were read only. No refresh, model rerun, workbook recalculation, test-suite execution, commit or publication was performed for this deliverable.

Key SHA-256 fingerprints:

| Artifact | SHA-256 |
| --- | --- |
| HW workbook | `1d86ae9cf276d97a788dbf5cf31a805f8261ea0df015d12846660789d14b9543` |
| S12 `dsu_inventory.json` | `9a9d91cda61e14431bf820e29a6f9920ecfe59c3970e16eeb1da514e8682ceec` |
| S12 inventory engine | `36cd06dc11e0d09ba7c125e4e394fac07151991e6c1bfe29bf2305491318d700` |
| Latest BF inventory engine | `2c73477d87cd05e765077418db2edae433648417834a0e55e540bd0ec66d768a` |
| Shared S12/BF spatial engine | `dd28e0ed27ce6dd2227cf7073166227237bbca07b10b0aa5d26b87ce85a32972` |
| V survey manifest | `328deaf1f1d2bf9c9d7d5e961cd25be653f082a51fb6966f13be9e495ef4599c` |

The [preservation manifest](../work/inventory-methodology-2026-10-17/preservation-check.json) captures 26 selected source/workbook/output fingerprints. Verification found no changes at completion of the documentation-only review. The subsequent authorized viewer implementation in section 11 intentionally changes application source, so those source-file fingerprints now differ; its separate legacy-data check verifies that the original numerical assets remain unchanged. The earlier read-only helper checks those 26 files, not every byte in the workspace. Local file/line references and transcribed hashes were also checked in the [report validation](../work/inventory-methodology-2026-10-17/report-validation.json); this is documentation verification, not validation of inventory estimates. Historical counts and geometric diagnostics retain their own manifests in [the earlier audit](../work/inventory-review-2026-10-17/). The source inventory and workbook audit in the new review folder provide cell-level supporting evidence and explicitly record the spatial-reproduction gap.

## 10. Research follow-up: lateral footage as the primary screening measure

**User follow-up, October 17, 2026:** assess whether a lateral-footage benchmark can yield a development percentage and estimated footage remaining, scaling from DSUs to townships. Recommendation: **yes, as a geometric screening model with explicit benchmark scenarios**. This follow-up changes documentation only; no new density was selected and no inventory was recalculated.

### Research support and limits

Lateral length per unit area has a direct research precedent. The University of Texas Bureau of Economic Geology's *Oil & Gas Water Use in Texas: Update to the 2011 Mining Water Use Report* maps cumulative lateral length per area and reports its reciprocal as an average spacing measure. This supports using footage density as a descriptive metric. That water-planning study does not validate Bakken remaining inventory. See [2012 report, printed pp. 18–19, Figure 6 and Table 3](https://www.twdb.texas.gov/publications/reports/contracted_reports/doc/0904830939_2012Update_MiningWaterUse.pdf).

Bakken-specific calibration still matters. [NDGS RI-135, printed pp. 14 and 20](https://www.dmr.nd.gov/ndgs/documents/publication_List/pdf/RISeries/RI-135.pdf) describes differing development by reservoir horizon in its study area and discusses reservoir communication between neighboring wells. The [combined RI-135/136 announcement](https://www.dmr.nd.gov/dmr/news/middle-three-forks-2nd-bench-bakken-petroleum-system-contains-hundreds-millions-barrels) reports variable incremental recovery from middle Three Forks development. Footage measures development intensity; it does not directly measure drained rock, remaining oil or economic opportunity.

### Calculation in feet

For a uniform region/target scenario, define:

```text
A = measured eligible acres within the analysis footprint
r = scenario benchmark, horizontal lateral feet per eligible acre
C = A * r                                      scenario footage capacity
Ld = qualifying as-drilled lateral feet clipped to the same footprint
Lc = verified completed lateral feet clipped to the same footprint

Drilling development index (%) = 100 * Ld / C
Completed development index (%) = 100 * Lc / C   requires adequate completion evidence
Signed drilling-footage balance = C - Ld
Positive footage headroom = max(C - Ld, 0)
```

Percentages are calculated from measured footage and the selected benchmark; do not assign an independent arbitrary percentage to each DSU. Capacity or observation coverage that is unknown must stay unavailable. Retain raw values above 100% and negative balances as review signals rather than hiding them with a cap.

`Lc` must be a subset of `Ld` on the same clipping/length basis, so `Lc <= Ld`. Where `C <= 0`, the capacity-based percentages are unavailable. Completion progress of already-drilled footage is a different ratio, `100 * Lc / Ld`, requiring `Ld > 0` and adequate interval-status coverage. With incomplete completion records, withhold that percentage or label a verified completed-footage lower bound alongside the unknown-status footage. A missing completion record is not proof of an uncompleted interval.

For mixed regions/targets, sum `eligible_acres * benchmark` over the declared spatial/target pieces. Stratigraphic capacity cannot be multiplied by a visual depth-group count. Unknown target footage remains separately reported; an aggregate regional scenario can be used provisionally if it is explicitly calibrated and labeled for that mixed population.

**Drilling and completion require separate ledgers.** A verified drilled-but-uncompleted lateral has already been drilled. Subtracting only completed footage would misclassify it as new drilling opportunity. Count qualifying as-drilled footage for drilling headroom, and track completed, drilled-awaiting-completion, proposed, abandoned and unknown intervals separately. Missing completion data does not establish a DUC. Do not automatically restore a plugged well's footage to undeveloped inventory or treat an abandoned sidetrack as a completed producing lateral.

Use horizontal plan-view feet for the acreage/spacing calculation. Retain survey MD, completed MD intervals and future drilling MD separately. A scenario's horizontal footage headroom is not yet an engineering estimate of actual MD required.

### Scaling example, without choosing a new benchmark

The original eight two-mile equivalents correspond arithmetically to `8 * 10560 / 1280 = 66` horizontal ft/acre. Keeping **66 only as a comparison assumption** gives:

| Illustrative footprint | Eligible acres | Scenario capacity at 66 ft/acre |
| --- | ---: | ---: |
| Base unit | 1,280 | 84,480 ft |
| Larger independent footprint | 2,560 | 168,960 ft |
| Nominal full township | 23,040 | 1,520,640 ft |

These are hypothetical capacity calculations, not measured local inventory. A 1,280-acre footprint with a hypothetical 50,000 qualifying drilled lateral feet would score 59.2% against this comparison and have 34,480 ft of positive scenario headroom. Converting eight wells into 84,480 ft does not validate the benchmark; the improvement comes from measuring real clipped footage and then calibrating the denominator.

A real township must use its measured eligible prospective acreage, which may be smaller than its total surveyed acreage. Township percentages are `100 * summed observed footage / summed capacity`, not an average of DSU percentages. Clipping a crossing lateral allocates footage across reporting boundaries without assigning the whole well to a single cell.

An ideal parallel, single-target layout can instead parameterize `r = 43560 / assumed across-lateral spacing in ft`. This is approximate strip geometry, not a measured drainage width or an order-specific placement rule. Multiple supported targets require separate assumptions. Irregular shapes, setbacks, curvature and fragmented gaps can make the resulting theoretical footage impossible to place as new trajectories.

### Overlapping DSUs and township totals

Calculate each original DSU independently for inspection, but do not add overlapping DSU headroom. Township/field/operator summaries require a single land union or disjoint reporting partition, with footage counted once within each supported physical well/target. Adding a duplicate record or an overlay polygon must not manufacture more land or base capacity.

This distinction matters particularly for 2,560-acre overlays: DMR describes overlapping units that support section-line wells between adjacent base units. Such a polygon does not automatically represent another independent 2,560 acres of development. Any incremental corridor opportunity needs its own reviewed role/candidate entry. See [DMR spacing-unit guidance](https://www.dmr.nd.gov/dmr/oilgas/wellpermitting).

Retain both local positive headroom and over-benchmark footage before regional aggregation. For example, two disjoint cells with 1,000-ft capacities and observations of 1,500 and 0 ft have 500 ft of regional net headroom, but 1,000 ft of summed local positive headroom. Those are different screening measures. An over-benchmark cell cannot physically consume empty space in a neighboring cell, while local gaps still may not fit a feasible trajectory.

### Practical next version

The existing development-area worksheet and current surveyed-lateral membership builder already provide useful clipping logic; their limitations are described in sections 2.5–2.6. A formal model should standardize acreage and line measurements in a declared projected coordinate system and preserve branch/target identities. The viewer builder's local tangent-plane footage should be compared against that basis before being adopted as the inventory ledger.

Start by reporting **mapped lateral feet**, **feet per eligible acre**, **footage relative to low/base/high benchmark scenarios**, **positive footage headroom**, and **data coverage**. Keep actual well counts alongside them. Call the first percentage a **mapped lateral development index** until as-drilled/completion/target states are verified. Calibrate benchmarks using manually reviewed developed DSUs in comparable regions and targets, including less successful outcomes and incremental production where available. A high observed density is not proof of optimal or complete development.

This approach can provide a useful and more length-consistent screening estimate now. Turning footage headroom into feasible locations or rig demand remains a subsequent step requiring trajectory layouts, rights/order constraints, branch/completion evidence, and operating-cycle assumptions. No defensible new statewide footage benchmark was established by this research.

## 11. Implemented viewer comparison, October 17, 2026

The user authorized implementation of DSU and township footage scenarios with Turbo coloring. New numerical inputs are separate assets: [footage ledger](../dist/data/inventory/footage.json) and [township boundaries](../dist/data/inventory/townships.geojson). Existing DSU GeoJSON, September inventory properties, well membership, survey manifest and production assets are unchanged. The source and local served package contain the new viewer modules; no remote publication was performed.

- [The builder](../work/footage-inventory-2026-10-17/build_footage.py) reconstructs survey plan coordinates, excludes invalid/large-gap classified segments, removes shared/retraced paths within each well, transforms to EPSG:5070, and clips to original DSU footprints. Township observations use the union of eligible Bakken DSUs intersected with dissolved township boundaries. No township total is obtained by summing DSU rows.
- [The model](../dist/footage-model.js) computes capacity, raw development percentage, signed balance, excess and positive remaining footage. Low/base/high presets are **49.5 / 66 / 82.5 ft/ac**, explicitly illustrative bounds of ±25% around the historical comparison. They are editable and retained as browser preferences. They remain aggregate target-unverified assumptions, not calibrated regional/bench defaults or confidence intervals.
- [The controller](../dist/footage.js) adds geography, metric and scenario selectors; a selected-area table shows all three scenarios together. DSU cards retain the September count-based comparison. Township cards state measured eligible acres, full acres and coverage share. Inventory includes all surveyed operators even when well display/production filters hide some operators.
- Turbo development colors use fixed 0–100 limits while inspector values above 100 remain intact. Footage colors share a whole-layer P98 upper bound across low/base/high, calculated from high-capacity headroom for the remaining metric. DSU and township scales are separate. Gray denotes unsupported/unavailable values, and true observed zeros remain numeric/colorable.
- Both numerical and geometry assets are tied to the exact survey manifest, current DSU file and township file by SHA-256. Invalid/overflowing scenario edits preserve the previous valid settings. Invalid restored preferences fall back to the labeled comparison presets. Switching datasets rejects incompatible footage assets rather than retaining stale colors.

The ledger contains 10,573 original DSU records and 2,047 dissolved township records. Of those townships, 466 have more than 1 m² of eligible area and are displayed; 13 further numerical slivers remain in the ledger with zero mapped footage. The source survey has 22,430 wells with usable lateral geometry and 68 without it. The eligible union contains approximately **207.38 million mapped plan feet**; the township ledger conserves that observed footage without duplication. The township source leaves about **1.916 acres** of the DSU union uncovered, containing zero observed footage. See [build audit](../work/footage-inventory-2026-10-17/build-audit.json).

Measurements are EPSG:5070 projected horizontal feet, not survey MD or verified completed interval footage. Independent sample comparisons with the earlier local-tangent membership measurements differ by approximately 0.58–0.80% due to projection scale. Keep this basis when calibrating benchmarks; geodesic/local-distance measurement is a possible subsequent refinement. Target identity, abandoned/simultaneously completed branches and completion coverage remain unverified. The displayed residual is scenario headroom, not independently established drillable footage.

Validation includes 20 pure model tests, 9 actual-controller tests, 12 geometry/data tests, strict real-asset validation, existing DSU rendering/selection tests and production/membership regressions. These cover unknown-versus-zero states, source identity, stale loads, overflow recovery, shared Turbo limits, holes/multipart/overlap clipping, township conservation and preserved legacy data. Browser checks exercised actual DSU/township cards, custom-density validation, scenarios, Turbo coloring and the old comparison. Detailed clipping checks are in [independent validation](../work/footage-inventory-2026-10-17/independent-clip-validation.json). Geometry checks validate the mapped-footage calculation, not the uncalibrated capacity benchmark.
