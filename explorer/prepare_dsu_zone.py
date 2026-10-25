"""Prepare approximate display depths for unchanged ND DMR DSU footprints.

This is a visualization helper, not a formation surface model or a regulatory
vertical-boundary determination. The DSU GeoJSON and survey manifest are read
only. Existing converted TVD picks are never replaced with measured depth.

Run with Python containing pyproj for exact EPSG:32121 -> NAD83 conversion:
    python prepare_dsu_zone.py --dsus units.geojson --manifest full-dataset/manifest.json --tops converted-tops.csv --output zones.json

Without pyproj, --coordinates manifest uses matching VERT branch bounding-box
centres as approximate source locations. The selected coordinate mode and all
input hashes are retained in the audit.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import heapq
import json
import math
from pathlib import Path
import statistics


WORKSPACE = Path(__file__).resolve().parent
PICK_DATE = "2026-09-07"
REFERENCE = "Approximate TVD ft; provisional KB reference"
ELIGIBLE_CODES = {"M-MDLP", "D-BB"}
RESOLVED = {"single_branch", "shared_path_agreement"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite_number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def project_reference(lon, lat, manifest):
    """Match dist/reference-plane.js, including its NAD83 ellipsoid and ft scale."""
    lon0, lat0 = map(math.radians, manifest["origin"])
    lon, lat = map(math.radians, (lon, lat))
    flattening = 1 / (298.257222101 if manifest["sourceCRS"] == "NAD83" else 298.257223563)
    eccentricity2 = flattening * (2 - flattening)

    def ecef(lo, la):
        n = 6378137 / math.sqrt(1 - eccentricity2 * math.sin(la) ** 2)
        return n * math.cos(la) * math.cos(lo), n * math.cos(la) * math.sin(lo), n * (1 - eccentricity2) * math.sin(la)

    centre, point = ecef(lon0, lat0), ecef(lon, lat)
    delta = [a - b for a, b in zip(point, centre)]
    east = -math.sin(lon0) * delta[0] + math.cos(lon0) * delta[1]
    north = -math.sin(lat0) * math.cos(lon0) * delta[0] - math.sin(lat0) * math.sin(lon0) * delta[1] + math.cos(lat0) * delta[2]
    return east / .3048, -north / .3048


class PointIndex:
    """A small bounded-radius grid; global fallback uses the same exact distances."""
    def __init__(self, points, cell_size):
        self.points = points
        self.cell_size = cell_size
        self.cells = collections.defaultdict(list)
        for point in points:
            self.cells[self.key(point["x"], point["z"])].append(point)

    def key(self, x, z):
        return math.floor(x / self.cell_size), math.floor(z / self.cell_size)

    def nearest(self, x, z, count, radius=None):
        if radius is None:
            candidates = self.points
        else:
            xmin, zmin = self.key(x - radius, z - radius)
            xmax, zmax = self.key(x + radius, z + radius)
            candidates = [p for ix in range(xmin, xmax + 1) for iz in range(zmin, zmax + 1) for p in self.cells.get((ix, iz), ())]
        distances = ((math.hypot(p["x"] - x, p["z"] - z), p["file"], p) for p in candidates)
        if radius is not None:
            distances = (entry for entry in distances if entry[0] <= radius)
        return heapq.nsmallest(count, distances, key=lambda entry: (entry[0], entry[1]))


def manifest_anchors(manifest):
    groups = collections.defaultdict(list)
    for well in manifest["wells"]:
        groups[str(well["permit"])].append(well)
    vertical = {}
    for permit, wells in groups.items():
        options = [w for w in wells if str(w["branch"]).upper() == "VERT"]
        if options:
            # Prefer the longest independent vertical survey, deterministically.
            selected = max(options, key=lambda w: (w["maxMD"], -w["id"]))
            bounds = selected["bounds"]
            vertical[permit] = ((bounds[0] + bounds[3]) / 2, (bounds[2] + bounds[5]) / 2)
    return groups, vertical


def read_controls(path, manifest, coordinate_mode, counters):
    permits, vertical = manifest_anchors(manifest)
    transformer = None
    if coordinate_mode == "source":
        try:
            from pyproj import Transformer
        except ImportError as error:
            raise RuntimeError("Source coordinates require pyproj. Use system Python or explicitly choose --coordinates manifest.") from error
        transformer = Transformer.from_crs(32121, 4269, always_xy=True)
    controls = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            counters["pickRowsRead"] += 1
            code = row["formation_code"]
            if code not in ELIGIBLE_CODES:
                counters["otherFormationCode"] += 1
                continue
            permit = str(int(row["FileNo"]))
            if permit not in permits:
                counters["pickWellAbsentFromCurrentSurvey"] += 1
                continue
            if row["status"] not in RESOLVED or row["elevation_source"] != "KBElev":
                counters["pickUnresolvedOrNotKB"] += 1
                continue
            tvd, gap = finite_number(row["tvd_ft"]), finite_number(row["survey_gap_ft"])
            if tvd is None or not 0 < tvd < 20000 or gap is None or not 0 <= gap <= 500:
                counters["pickInvalidDepthOrGap"] += 1
                continue
            if transformer:
                easting, northing = finite_number(row["easting_m"]), finite_number(row["northing_m"])
                if easting is None or northing is None:
                    counters["pickMissingCoordinates"] += 1
                    continue
                lon, lat = transformer.transform(easting, northing)
                if not (-105 < lon < -95 and 45 < lat < 50):
                    counters["pickCoordinatesOutsideRegion"] += 1
                    continue
                x, z = project_reference(lon, lat, manifest)
            else:
                if permit not in vertical:
                    counters["pickNoMatchingVerticalAnchor"] += 1
                    continue
                x, z = vertical[permit]
            key = (permit, code)
            if key in controls:
                counters["duplicatePickIdentity"] += 1
                if abs(controls[key]["depth"] - tvd) > .01:
                    raise ValueError("Conflicting retained picks for the same well and formation")
                continue
            controls[key] = {"x": x, "z": z, "depth": tvd, "file": permit}
            counters["retained" + code] += 1

    pairs = []
    for permit in sorted(permits):
        top, bottom = controls.get((permit, "M-MDLP")), controls.get((permit, "D-BB"))
        if top and bottom:
            thickness = bottom["depth"] - top["depth"]
            if 100 <= thickness <= 2500:
                pairs.append({"x": top["x"], "z": top["z"], "top": top["depth"], "bottom": bottom["depth"], "file": permit})
            else:
                counters["sameWellPairOutside100to2500Ft"] += 1
    counters["acceptedSameWellPairs"] = len(pairs)
    tops = [value for (permit, code), value in controls.items() if code == "M-MDLP"]
    bottoms = [value for (permit, code), value in controls.items() if code == "D-BB"]

    # Count once per well, rather than overweighting wells with more branches.
    laterals = []
    for permit, wells in sorted(permits.items()):
        options = [well for well in wells if 3000 < well["maxTVD"] < 15000 and well["maxMD"] - well["maxTVD"] > 3000]
        if not options:
            continue
        well = max(options, key=lambda w: (w["maxMD"] - w["maxTVD"], w["maxMD"], -w["id"]))
        bounds = well["bounds"]
        laterals.append({"file": permit, "x": (bounds[0] + bounds[3]) / 2, "z": (bounds[2] + bounds[5]) / 2, "depth": well["maxTVD"]})
    counters["retainedLongLateralWells"] = len(laterals)
    return tops, bottoms, pairs, laterals


def median(entries, field):
    return statistics.median(entry[2][field] for entry in entries)


def estimate(x, z, indexes, sample_count, radius, manifest_date, counters):
    top_index, bottom_index, pair_index, lateral_index = indexes
    pairs = pair_index.nearest(x, z, sample_count, radius)
    if pairs:
        top, bottom = median(pairs, "top"), median(pairs, "bottom")
        if not 100 <= bottom - top <= 2500:
            # Medians preserve interval bounds mathematically; keep the check explicit.
            raise ValueError("Median paired interval failed its thickness bound")
        method, used, source_date = "local_paired_tops", pairs, PICK_DATE
    else:
        tops = top_index.nearest(x, z, sample_count, radius)
        if tops:
            top = median(tops, "depth")
            bottoms = bottom_index.nearest(x, z, sample_count, radius)
            if bottoms and 100 <= median(bottoms, "depth") - top <= 2500:
                bottom = median(bottoms, "depth")
                method, used = "local_separate_tops", tops + bottoms
            else:
                if bottoms:
                    counters["nearbyBottomOutside100to2500Ft"] += 1
                bottom = top + 800
                method, used = "lodgepole_plus_800ft", tops
            source_date = PICK_DATE
        else:
            laterals = lateral_index.nearest(x, z, sample_count)
            if laterals:
                middle = median(laterals, "depth")
                top, bottom = middle - 800, middle + 200
                method, used, source_date = "lateral_minus800_plus200", laterals, manifest_date
            else:
                top, bottom = 9000, 10000
                method, used, source_date = "regional_9000_10000", [], None
    if not (math.isfinite(top) and math.isfinite(bottom) and 0 < top < bottom):
        raise ValueError("Invalid approximate display interval")
    distances = [entry[0] * .3048 / 1000 for entry in used]
    return {"topFt": round(top, 1), "bottomFt": round(bottom, 1), "method": method,
            "sourceDate": source_date, "reference": REFERENCE, "nSamples": len(used),
            "nearestKm": round(min(distances), 2) if distances else None,
            "furthestKm": round(max(distances), 2) if distances else None}


def prepare(dsus_path, manifest_path, picks_path, output_path, coordinates="source", radius_km=25, sample_count=5):
    input_paths = {"dsus": Path(dsus_path), "surveyManifest": Path(manifest_path), "formationPicks": Path(picks_path)}
    hashes = {name: digest(path) for name, path in input_paths.items()}
    dsus = json.loads(input_paths["dsus"].read_text(encoding="utf-8"))
    manifest = json.loads(input_paths["surveyManifest"].read_text(encoding="utf-8"))
    if dsus["metadata"]["sourceCRS"] != "EPSG:4269" or manifest["sourceCRS"] != "NAD83":
        raise ValueError("This helper requires the existing matching NAD83 data")
    if not 0 < radius_km <= 100 or not 1 <= sample_count <= 25:
        raise ValueError("Unsupported local-neighbour settings")
    counters = collections.Counter()
    controls = read_controls(picks_path, manifest, coordinates, counters)
    radius_ft = radius_km * 1000 / .3048
    indexes = [PointIndex(points, radius_ft) for points in controls]
    manifest_date = manifest.get("sourceSnapshot", {}).get("date")
    zones = {}
    for feature in dsus["features"]:
        uid = feature["id"]
        if uid != feature["properties"]["id"] or uid in zones:
            raise ValueError("Missing or duplicate current viewer DSU identity")
        xmin, ymin, xmax, ymax = feature["bbox"]
        x, z = project_reference((xmin + xmax) / 2, (ymin + ymax) / 2, manifest)
        zones[uid] = estimate(x, z, indexes, sample_count, radius_ft, manifest_date, counters)
    methods = dict(collections.Counter(zone["method"] for zone in zones.values()))
    metadata = {
        "label": "Approximate Lodgepole–Three Forks display interval",
        "sourceDate": PICK_DATE, "reference": REFERENCE,
        "coordinateMode": "EPSG:32121 to NAD83 to viewer origin" if coordinates == "source" else "matching VERT branch bounding-box centres",
        "queryLocation": "centre of each unchanged DSU geographic bounding box",
        "localRadiusKm": radius_km, "nearestSampleCount": sample_count,
        "topCode": "M-MDLP", "bottomProxyCode": "D-BB",
        "bottomMeaning": "Birdbear top is used as an approximate proxy for Three Forks base",
        "inputHashes": hashes, "featureCount": len(zones), "methodCounts": methods,
        "limitations": [
            "All intervals are approximate display zones, not measured DSU formation boundaries or legal vertical limits.",
            "Source MD and survey TVD were provisionally treated as feet from KB; reference and elevation datum are unverified.",
            "The existing viewer uses relative TVD with a common zero, without reference-elevation correction.",
            "Only resolved converted TVD picks from current survey wells, KB references and survey gaps no greater than 500 ft are used; MD is never substituted for TVD.",
            "Nearest local same-well Lodgepole/Birdbear pairs are preferred; otherwise local Lodgepole and Birdbear medians are screened for 100–2500 ft thickness.",
            "Where local base picks are unavailable or inconsistent, Lodgepole top plus 800 ft is an assumed thickness.",
            "Without local Lodgepole controls, nearest five long-lateral maximum TVDs set an illustrative interval 800 ft above and 200 ft below their median; these are not measured tops.",
            "Where no long-lateral control exists, 9000–10000 ft is an explicitly regional illustrative fallback.",
            "No geological surface is fitted, no datum transformation is inferred, and DSU geometry, source attributes and overlaps remain unchanged."
        ]}
    result = {"version": 1, "metadata": metadata, "zones": zones}
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    audit = {"inputs": {name: str(path.resolve()) for name, path in input_paths.items()},
             "inputHashes": hashes, "outputSha256": digest(output_path), "featureCount": len(zones),
             "bytes": output_path.stat().st_size, "coordinateMode": metadata["coordinateMode"],
             "counters": dict(counters), "methodCounts": methods,
             "topRangeFt": [min(z["topFt"] for z in zones.values()), max(z["topFt"] for z in zones.values())],
             "bottomRangeFt": [min(z["bottomFt"] for z in zones.values()), max(z["bottomFt"] for z in zones.values())],
             "allIntervalsFinitePositiveOrdered": all(0 < z["topFt"] < z["bottomFt"] for z in zones.values()),
             "sourceFilesUnchanged": all(digest(path) == hashes[name] for name, path in input_paths.items())}
    output_path.with_suffix(".audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    if not audit["sourceFilesUnchanged"]:
        raise RuntimeError("Source files changed during preparation")
    print(json.dumps(audit, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsus", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--tops", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--coordinates", choices=["source", "manifest"], default="source")
    parser.add_argument("--radius-km", type=float, default=25)
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    prepare(args.dsus, args.manifest, args.tops, args.output, args.coordinates, args.radius_km, args.samples)
