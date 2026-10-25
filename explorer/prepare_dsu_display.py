"""Add display-only nested DSU outlines and perimeter bands to NAD83 GeoJSON.

Usage (requires Shapely and pyproj, as used by Bakken Forward):
    python prepare_dsu_display.py input.geojson output.geojson

Existing feature geometry, IDs, source attributes, inventory and approximate
depth intervals are preserved. Only properties.display and metadata.displayOffsets
are added. Insets are fixed by published nominal acreage, independent of filters.
This is a presentation offset, not a setback, changed acreage or regulatory limit.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union


FEET_TO_METRES = .3048
INSET_ANCHORS = ((640, 0), (1280, 100), (1920, 220), (2560, 340), (3840, 460), (5120, 580))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def content_sha(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def inset_feet(value):
    """Reproduce Bakken Forward's nominal-acreage display lanes exactly."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value) or value <= 640:
        return 0.0
    if value > 5120:
        return 580 + 120 * math.log2(value / 5120)
    for (left_size, left_offset), (right_size, right_offset) in zip(INSET_ANCHORS, INSET_ANCHORS[1:]):
        if value <= right_size:
            fraction = (value - left_size) / (right_size - left_size)
            return left_offset + fraction * (right_offset - left_offset)
    raise AssertionError("Unreachable acreage interpolation")


def display_geometry(projected_source, nominal_acres, width_ft=50):
    """Return projected outer/band geometry, or a whole-feature outline fallback.

    Components are processed independently. If erosion removes either boundary
    of any component, the complete original feature remains selectable as an
    outline and the band is withheld; no component is silently dropped.
    """
    if not math.isfinite(width_ft) or width_ft <= 0:
        raise ValueError("Band width must be a finite positive number of feet")
    if projected_source.is_empty or projected_source.geom_type not in ("Polygon", "MultiPolygon") or not projected_source.is_valid:
        raise ValueError("Source display geometry must be a nonempty valid polygon")
    inset = inset_feet(nominal_acres)
    pieces = list(projected_source.geoms) if projected_source.geom_type == "MultiPolygon" else [projected_source]
    outers, bands = [], []
    for piece in pieces:
        outer = piece.buffer(-inset * FEET_TO_METRES, join_style=2) if inset else piece
        inner = piece.buffer(-(inset + width_ft) * FEET_TO_METRES, join_style=2)
        if outer.is_empty or inner.is_empty:
            return projected_source, None, True
        if not outer.is_valid or not inner.is_valid:
            raise ValueError("Invalid offset geometry; refusing to repair or alter source polygons")
        band = outer.difference(inner)
        if band.is_empty or not band.is_valid:
            raise ValueError("Invalid or empty perimeter band")
        outers.append(outer)
        bands.append(band)
    outline, band = unary_union(outers), unary_union(bands)
    if not outline.is_valid or not band.is_valid:
        raise ValueError("Invalid combined multipart display geometry")
    if not projected_source.covers(outline) or not projected_source.covers(band):
        raise ValueError("A display offset escaped its source footprint")
    return outline, band, False


def without_display(feature):
    return {**feature, "properties": {key: value for key, value in feature["properties"].items() if key != "display"}}


def prepare(input_path, output_path, width_ft=50):
    input_path, output_path = Path(input_path), Path(output_path)
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Choose a separate output path; original input is read only")
    input_sha = sha(input_path)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection" or data.get("metadata", {}).get("sourceCRS") != "EPSG:4269":
        raise ValueError("Expected original NAD83 DSU FeatureCollection (EPSG:4269)")
    features = data["features"]
    if not features:
        raise ValueError("The DSU collection is empty")
    if any("display" in feature["properties"] for feature in features):
        raise ValueError("Use the original combined input; display geometry already exists")
    old_metadata_sha = content_sha(data["metadata"])
    before_feature_sha = content_sha(features)
    before_ids = [feature["id"] for feature in features]
    if len(set(before_ids)) != len(before_ids):
        raise ValueError("Current viewer feature IDs must be unique")
    project = Transformer.from_crs(4269, 5070, always_xy=True).transform
    unproject = Transformer.from_crs(5070, 4269, always_xy=True).transform
    counters = collections.Counter()
    counts_by_size = collections.defaultdict(collections.Counter)
    fallback_ids = []
    max_inset = 0.0
    for feature in features:
        if feature["id"] != feature["properties"]["id"]:
            raise ValueError("Feature ID differs from its existing viewer property ID")
        source_geo = shape(feature["geometry"])
        if source_geo.is_empty or not source_geo.is_valid or source_geo.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError("Original source polygon is invalid; it will not be repaired implicitly")
        projected_source = transform(project, source_geo)
        acres = feature["properties"].get("acres")
        inset = inset_feet(acres)
        max_inset = max(max_inset, inset)
        outline, band, fallback = display_geometry(projected_source, acres, width_ft)
        if fallback:
            # Keep the exact original coordinate object on the fallback path.
            outline_geo, band_geo = feature["geometry"], None
            fallback_ids.append(feature["id"])
        else:
            geographic_outline = transform(unproject, outline)
            geographic_band = transform(unproject, band)
            if not geographic_outline.is_valid or not geographic_band.is_valid:
                raise ValueError("Display geometry became invalid in NAD83")
            outline_geo, band_geo = mapping(geographic_outline), mapping(geographic_band)
        feature["properties"]["display"] = {
            "insetFt": round(inset, 6), "bandWidthFt": float(width_ft),
            "outlineGeometry": outline_geo, "bandGeometry": band_geo, "fallback": fallback}
        counters["sourceFeatures"] += 1
        counters["fallbackOriginalOutline" if fallback else "nestedPerimeterBand"] += 1
        counters["validDisplayOutline"] += 1
        if band_geo is not None:
            counters["validDisplayBand"] += 1
        if source_geo.geom_type == "MultiPolygon":
            counters["multipartSourceFeatures"] += 1
        counts_by_size[str(acres)]["fallback" if fallback else "nested"] += 1
    after_feature_sha = content_sha([without_display(feature) for feature in features])
    if before_feature_sha != after_feature_sha:
        raise AssertionError("Existing feature content changed")
    if old_metadata_sha != content_sha(data["metadata"]):
        raise AssertionError("Existing metadata changed")
    metadata = {
        "version": 1, "style": "Nested display outlines and perimeter bands",
        "sourceSha256": input_sha, "sourceFeaturesSha256": before_feature_sha,
        "inputCRS": "EPSG:4269", "bufferCRS": "EPSG:5070", "outputCRS": "EPSG:4269",
        "joinStyle": "mitre", "bandWidthFt": float(width_ft),
        "insetsByNominalAcresFt": {str(acres): offset for acres, offset in INSET_ANCHORS},
        "otherSizes": "Linear interpolation between anchors; sizes <=640 use zero; sizes >5120 use 580 + 120*log2(acres/5120).",
        "featureCount": len(features), "counts": dict(counters),
        "limitations": [
            "These are display offsets, not regulatory setbacks, lease-line corridors, changed acreage or changed legal boundaries.",
            "Nominal published acreage fixes each display lane; filtering never moves the lanes.",
            "Original feature geometry, IDs, source attributes, overlaps, inventory and approximate depth intervals remain unchanged.",
            "A 50 ft band by default is the difference between inward offsets at inset and inset+50 ft, calculated in a metre-based projection.",
            "If either erosion removes any original polygon component, the whole feature uses its exact original outline and no filled band.",
            "Any optional vertical separation in the viewer is also display only; source approximate formation intervals are retained."
        ]}
    data["metadata"]["displayOffsets"] = metadata
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    audit = {
        "inputFile": input_path.name, "outputFile": output_path.name,
        "inputSha256": input_sha, "outputSha256": sha(output_path),
        "originalFeatureContentSha256": before_feature_sha,
        "preservedFeatureContentSha256": after_feature_sha,
        "allOriginalFeatureContentPreserved": before_feature_sha == after_feature_sha,
        "inputUnchanged": sha(input_path) == input_sha,
        "allStableIdsPreserved": before_ids == [feature["id"] for feature in data["features"]],
        "featureCount": len(features), "bytes": output_path.stat().st_size,
        "maxInsetFt": max_inset, "counts": dict(counters),
        "countsByNominalAcres": {key: dict(value) for key, value in sorted(counts_by_size.items())},
        "fallbackIds": fallback_ids}
    if not audit["inputUnchanged"]:
        raise AssertionError("Input changed while preparing display geometry")
    output_path.with_suffix(".display-audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2))
    return data, audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--band-width-ft", type=float, default=50)
    args = parser.parse_args()
    prepare(args.input, args.output, args.band_width_ft)
