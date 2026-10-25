# Drillback continuity and U-turn geometry review

Reviewed October 18, 2026. The initial analysis below records the exploratory
local review of the October 17 survey snapshot. The approved viewer integration
is recorded at the end; saved classifier v2.0, section scales, production,
lateral-footage ledger and inventory results remain unchanged.

## What the current classifier does

`outputs/wellbore-viewer/classifier.py:classify` operates independently on each
strictly increasing-MD source branch. Its initial local labels use inclination,
build rate and dogleg severity. The upper-deviation candidate then uses a
three-station median inclination, a 3-degree departure threshold, 75 ft of
horizontal departure relative to an excursion's local anchor, at least 150 ft MD
and three observations, and a 35-degree upper-context limit. It protects a
terminal build using a 70-degree landing context and an MD-window backtrack.
Station labels describe incoming segments; the initial event anchor remains its
original section.

The candidate mask is divided into new runs whenever inclination falls below
3 degrees. Each new run restarts its departure anchor. Non-drillback singleton
smoothing explicitly avoids filling a gap whose neighbors are red. These rules
can create red/blue/red intervals even when the entire trajectory remains part
of one shallow, continuous sideways movement.

`prepare_data.py:emit` preserves section boundaries in the overview. The renderer
uses those same incoming labels; overview reduction does not independently
invent section alternation. However, different source branches can overlap and
receive conflicting labels because their available upstream context differs.
Classification splits at survey gaps over 1,000 ft, while existing exported
linework still connects adjacent observations. The local review omits those
unsupported connections explicitly.

## Audited populations

The manifest SHA256 is
`328deaf1f1d2bf9c9d7d5e961cd25be653f082a51fb6966f13be9e495ef4599c`.

| Measurement | Current saved snapshot |
| --- | ---: |
| Source branches / retained stations | 48,929 / 5,495,609 |
| Branches containing a red interval | 10,070 |
| Branches containing multiple red runs | 907 |
| Blue-only interruptions between red runs | 1,023 |
| Blue interruptions shorter than 150 ft MD | 244 |
| Median blue interruption length | 376 ft MD |
| Blue interruptions at least 1,000 ft MD, with continuous survey evidence | 232 |

These are branch/segment audit counts, not counts of verified drilling
operations. Blue-gap inclination statistics are unweighted endpoint samples;
gap lengths sum supported incoming measured-depth differences. Do not confuse a
long blue-colored interval with missing survey observations.

All 12 curated baseline branches were replayed using the original matching DBF,
finite original azimuth, converter validity filtering, keep-last duplicate MD
policy, float64 projection and frozen thresholds. All saved labels, manifest
intervals and Float32 coordinates matched. Metric azimuth is intentionally
missing below 5 degrees, so it must never be silently filled to claim an exact
classifier replay.

## User example: file 35721, A. JOHNSON 5298 11-1 4B

Full API: `33053088220000`. Source branch IDs are generation-local: VERT 37706 and
LAT1 37705. Original-DBF replay matched all 243 observations exactly.

| VERT interval, ft MD | Current color | Evidence |
| --- | --- | --- |
| 4,439–6,138 | Red | Existing current-rule candidate seed |
| 6,138–6,988 | Blue | 850 ft, 9 incoming segments; inclination 2.82–3.98 degrees |
| 6,988–8,308 | Red | Second existing candidate seed |

Through the blue interval, horizontal displacement is 48.65 ft and horizontal
path length 48.76 ft. Departure from the first available station increases
monotonically from 108.98 to 157.06 ft. Brief inclination dips reset the rule's
anchor; the intervening six-station qualifying run then measures only 34.30 ft
against the restarted 75-ft requirement. This is a continuity/context issue,
not a missing-survey or overlapping-branch issue. VERT and LAT1 only meet at the
10,570-ft observation. The uppermost displayed point is the first available
survey station, not an inferred surface or casing boundary.

Joining only 150–300-ft blue interruptions would not fix this example.

## Separate issue: shared branch geometry

A bounded audit within the same permit and full API14 found 174 red/blue
shared-segment pairs across 166 wells. Both MD endpoints must match within
0.1 ft and both XYZ endpoints within 1 ft; point-like segments at most 1 ft are
excluded, and no interpolation is used. Of these pairs, 161 match exactly and
13 require the coordinate tolerance. This is a conservative lower bound.

File 36042 is useful for inspection: VERT 38276 is red and STK1 38275 blue over
the same 6,170–6,645-ft interval. Their local inclinations are identical; STK1
begins partway through the VERT excursion and lacks its upstream evidence.
Show a single branch first, then its siblings. Gap filling cannot resolve
competing classifications on coincident branches. A future shared-geometry
event policy must preserve branch provenance rather than merge all branches.

## Local interval-overlay experiment

`work/drillback-review/episode_overlay.py` leaves the saved classification intact.
It experiments with a separate red episode envelope, joining **only blue
segments bounded by existing red seeds on the same continuous branch**.

The trial uses a maximum blue interruption of 1,200 ft MD. It protects a sustained
return to inclination at most 2 degrees for at least 300 ft and three measured
observations. These are review parameters, not calibrated standards. It never
changes initial blue, final blue, curve, lateral, directional or unknown base
sections; never creates red in an unflagged branch; and never crosses a missing,
nonincreasing or over-1,000-ft survey step. An offset-but-vertical interval can
still be a true recovery; distance back to the wellhead is not required.

| Maximum blue interruption | Changed branches | Joined interruptions | Additional red display coverage, ft MD |
| --- | ---: | ---: | ---: |
| 150 ft | 234 | 244 | 22,727 |
| 300 ft | 462 | 495 | 78,830 |
| 600 ft | 612 | 684 | 165,046 |
| 1,200 ft, trial | 706 | 804 | 266,185 |

The 1,200-ft trial joins A. Johnson's 850-ft interruption and preserves its
observed initial and final blue stem. It protects 18 otherwise size-eligible
interruptions for sustained near-vertical recovery. The table is a sensitivity
analysis of red display coverage, not additional drilling, completed footage or
new remaining inventory. Eleven synthetic safety checks pass. The UI provides
all four alternatives rather than presenting the trial as a final algorithm.

Preferred longer-term design: derive an upper-deviation **event** with separate
entry and recovery evidence, then display it over the unchanged local section
labels. This can support geometric subtypes such as return-to-near-vertical,
open/sustained upper deviation, and compound/turning deviation. Do not infer a
sidetrack, drilling back, abandonment or completion from these shapes alone.
Closed excursions above 35 degrees and an upper tangent flowing into the main
landing remain known areas for further review, not solved by this bounded
gap-joining experiment.

## U-turn lateral candidates

`work/drillback-review/uturn_audit.py` evaluates continuous near-horizontal XY
geometry within one branch. It requires 75–105-degree inclination, at least
150-degree reversal between supported incoming/outgoing legs, and measured
intermediate turning observations. Stable legs are evaluated at 1,000 ft MD
with a 500-ft fallback; plan straightness must be at least 0.92. The turn search
is limited to 5,000 ft MD. Large survey gaps and implausible XY steps are
excluded. Signed turn consistency distinguishes a simple U from compound
steering; a near-vertical azimuth swing or 0/360 wrap does not qualify.

Of 48,929 branches, 26,087 contain at least one supported near-horizontal block.
The screen found **18 candidate events, on 18 branches and 18 unique full-API
wells**. Every detected case supports 1,000-ft legs and measured turn stations.
This is not an exhaustive count of all U-turn wells or a calibrated accuracy
claim. Shape boundaries use within-block interpolation for analysis; the local
viewer draws the original measured polyline.

| File | Well / source branch | Supported reversal |
| --- | --- | ---: |
| 41330 | Owan 5402 43-26 3BU / STK1 | 179.947 degrees |
| 41925 | ANDERSON 5402 12-18 2BJ / STK1 | 179.709 degrees |
| 39925 | Switchback 5-21UTFH / LAT1 | 179.634 degrees |

Keep U-turn as a separate trajectory-shape flag, with an optional cyan overlay
and filter. Preserve lateral base sections for DLS, footage, target analysis and
production joins. Do not count opposing branches of one well as a U-turn without
a continuous supported turn on one branch. Five actual opposed-sibling controls
and twelve synthetic tests are recorded in the U-turn audit.

## Review workflow and next decisions

The standalone loopback lab in `work/drillback-review/` shows current/proposed
views, source-station inclination, colored incoming-segment strips, adjustable
interruption limits and optional related branches. File 35721 is the first case.
Its 18 U-turn examples show the original geometry and a separate candidate
support overlay. No public app, staging SQL, source DBF or saved output is edited.

Local browser validation passed at desktop and 390-pixel mobile widths, with no
console errors or failed requests. All 15 prepared examples matched the Python
overlay at all four interruption thresholds (60 comparisons). Linked cameras,
branch context, search and the U-turn plan view were exercised. The eleven
episode safety checks and twelve U-turn synthetic checks also pass. These
validate implementation consistency, not geological or operational accuracy.

Before promoting a classifier revision:

1. Review A. Johnson and the curated long-return, straight-vertical and main-build
   controls. Decide which interruptions belong to the same upper-deviation event.
2. Review shared-branch cases independently from within-branch fragmentation.
3. Verify several U-turn candidates and negative controls against original
   surveys, checking branch continuity and any available completion information.
4. Agree on event/subtype names and recovery evidence. Retain base sections and
   event annotations separately, with versioned parameters and provenance.
5. Rebuild and compare metrics/sidecars in a fresh candidate snapshot; do not
   overwrite existing outputs or make live inventory changes implicitly.

Missing ground truth includes independently reviewed event boundaries, intended
well plan, completion/abandonment status, and measured intervals not present in
the GIS. No such values were invented here.

Reproduce locally:

```powershell
python work/drillback-review/audit_current.py
python work/drillback-review/audit_overlap.py
python work/drillback-review/uturn_audit.py
python work/drillback-review/build_review.py
python work/drillback-review/serve_review.py
```

Existing exploratory JSON files should be copied or assigned new output names
before rerunning an audit. The scripts do not modify the input survey dataset.

## Approved viewer display treatment, October 18

The user accepted A. Johnson's continuous red interval and requested cyan across
the whole U-turn lateral, labeled **U-turn laterals**. The viewer now uses a
separate `well-shape-overlays.json` sidecar. Both full-detail incoming endpoints
and the original retained overview rows are explicit, with exact manifest,
overview, branch identity and layout validation. Invalid or stale metadata is
rejected as a whole; saved sections remain available as a baseline.

The sidecar joins 804 blue interruptions on 706 branches, including A. Johnson's
850-ft gap. Eighteen U-turn branches receive cyan across 3,235 supported lateral
segments (228,596 ft MD). Cyan is restricted to saved lateral segments in the
detector-valid continuous horizontal block, preserving vertical, curve and other
sections and never propagating to siblings. Owan's full lateral display extends
from 18,450 to 31,328 ft MD, instead of just its reversal support interval.

The main viewer's Well section mode uses these display refinements by default.
Its “Use trajectory refinements” checkbox restores the saved colors for
comparison; the U-turn legend controls cyan lateral visibility independently.
Operator/DLS/other metric colors, base section scaling, production quantities,
DSU/township membership and footage inventories retain their original inputs.
U-turn centerlines remain cyan with missing production, but no production width
is invented. Faint/hidden path context continues to take precedence.

Builder: `work/drillback-review/build_display_overlays.py`. It reconstructs all
627,516 overview rows exactly and rejects mixed or unsupported overlay spans.
Twenty synthetic checks, the exact A. Johnson interval and all 18 U-turn fixture
checks pass. All 450 original dataset, DSU and inventory files were hashed before
and after building and remained unchanged. The sidecar SHA256 is
`668051ab47275799cbb05b916984245840974e9a8b6435e7a76748f55722222b`.
After a survey refresh, rerun the detector and builder against the new snapshot
and review the results; snapshot-local branch IDs must never be reused alone.

The packaged public viewer passed real GPU checks for cyan production ribbons,
cyan centerlines without production, metric/operator overrides, faint/hidden
context, independent U-turn visibility, baseline comparison and A. Johnson's
exact nine changed endpoints. The static release reconstructed and verified all
450 compressed logical assets. The homepage is byte-for-byte unchanged.
Mobile plan fitting now accounts for unobscured canvas space. At 390 × 844, all
Owan stations project inside the clear area with the bend visible; trajectory
pivot, pan, resized aspect and desktop symmetric framing checks pass.

Published as Site version 6 on October 18, 2026, from source commit
`48ea036f98bdb3cb7a2674739d6643a68d599d26`. The deployment succeeded. Exact
`app.js`, `well-shapes.js`, transport-index hashes and reconstructed sidecar bytes
were verified through `https://bakkensubsurface.com/`; the result is retained in
`work/drillback-review/published-release.json`.

The final publication is version 7, source commit
`08f432c45708db9b8824dade06a6b8bfa8b95d0b`, which corrects punctuation encoding
found during the live browser smoke check. The feature logic and all survey/data
assets are identical to version 6. A UTF-8 punctuation guard is now included in
the static release validator. Final custom-domain source and sidecar checks pass.
