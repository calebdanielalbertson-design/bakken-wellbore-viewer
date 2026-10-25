"""Build an immutable, reviewed-input SQL well-profile release; no cloud writes.

Reads the public Wells DBF, prepared viewer assets and exact production audit.
Writes only a NEW output directory. release.json is published last on success.
"""
from __future__ import annotations

import argparse
import collections
from contextlib import closing
from datetime import date
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import struct
import unicodedata

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
FULL = ROOT / "outputs/wellbore-viewer/full-dataset"
CONFIG = {"version": 1, "identity": "normalized state file number + complete API14",
          "membership": "positive classified-lateral plan overlap, not legal assignment",
          "production": "distinct valid pools once; any invalid/conflicting pool invalidates whole month",
          "geometry": "branch metadata and immutable tile references; no station rows"}
FIELDS = {
    "wells": ["file_number", "api", "well_name", "operator", "status", "search_text", "payload_json"],
    "branches": ["branch_id", "file_number", "api", "payload_json"],
    "dsus": ["dsu_id", "formation", "nominal_acres", "measured_acres", "payload_json"],
    "memberships": ["dsu_id", "file_number", "api", "overlap_ft", "overlap_share", "payload_json"],
    "production": ["file_number", "month", "oil_bbl", "quality", "payload_json"],
    "issues": ["issue_id", "kind", "file_number", "payload_json"],
}


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_number(value):
    text = str(value or "").strip()
    return str(int(text.split(".")[0])) if re.fullmatch(r"[0-9]+(?:\.0+)?", text) and int(text.split(".")[0]) > 0 else None


def api14(value):
    text = str(value or "").strip()
    if not re.fullmatch(r"[0-9 -]+", text):
        return None
    text = text.replace("-", "").replace(" ", "")
    return text if re.fullmatch(r"33[0-9]{12}", text) else None


def folded(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def read_dbf(path):
    """Standard DBF fields, strict UTF-8 from the source CPG; read only."""
    path = Path(path)
    encoding = path.with_suffix(".cpg").read_text().strip() if path.with_suffix(".cpg").exists() else "utf-8"
    with path.open("rb") as stream:
        header = stream.read(32)
        count = struct.unpack_from("<I", header, 4)[0]
        start, size = struct.unpack_from("<HH", header, 8)
        fields, offset = [], 1
        while stream.tell() < start:
            first = stream.read(1)
            if first == b"\r":
                break
            field = first + stream.read(31)
            if len(field) != 32:
                raise ValueError("Truncated DBF field header")
            name = field[:11].split(b"\0")[0].decode("ascii")
            fields.append((name, chr(field[11]), field[16], field[17], offset))
            offset += field[16]
        if offset != size or path.stat().st_size < start + count * size:
            raise ValueError("Invalid DBF record layout")
        stream.seek(start)
        for index in range(count):
            record = stream.read(size)
            if record[:1] == b"*":
                continue
            row = {}
            for name, kind, width, decimals, offset in fields:
                value = record[offset:offset + width].decode(encoding).strip()
                if not value:
                    value = None
                elif kind in ("N", "F"):
                    value = float(value) if decimals else int(value)
                    if not math.isfinite(value):
                        raise ValueError("Nonfinite source DBF number")
                row[name] = value
            yield index + 1, row


class Writer:
    def __init__(self, directory, name):
        self.path = directory / (name + ".csv.gz")
        self.file = self.path.open("xb")
        self.gzip = gzip.GzipFile(filename="", mode="wb", fileobj=self.file, mtime=0)
        self.count = 0
        self.width = len(FIELDS[name])

    def row(self, values):
        if len(values) != self.width:
            raise ValueError("Unexpected row width")
        # The importer uses csv.reader, which discards quoted/unquoted status.
        # Escape any literal backslash-run followed by N by one extra slash.
        def encode(value):
            if value is None: return "\\N"
            text = str(value)
            if re.fullmatch(r"\\+N", text): text = "\\" + text
            return '"' + text.replace('"', '""') + '"'
        cells = [encode(value) for value in values]
        self.gzip.write((",".join(cells) + "\n").encode("utf-8"))
        self.count += 1

    def close(self):
        self.gzip.close()
        self.file.close()
        return {"sha256": digest(self.path), "rows": self.count, "bytes": self.path.stat().st_size}


def build_bundle(output, *, wells_dbf=ROOT / "work/nd-refresh-2026-10-17/sources/wells/OGD_Wells.dbf",
                 manifest_path=FULL / "manifest.json", names_path=FULL / "well-names.json",
                 production_db=ROOT / "work/nd-refresh-2026-10-17/production/production-audit.sqlite",
                 production_meta=FULL / "production.json",
                 dsu_path=ROOT / "dist/data/dsu/drilling-spacing-units.geojson",
                 membership_path=ROOT / "dist/data/dsu/dsu-well-membership.json",
                 footage_path=ROOT / "dist/data/inventory/footage.json",
                 refresh_context=None, finalize_check=None):
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise FileExistsError("Output must be a new directory")
    paths = {k: Path(v).resolve() for k, v in {
        "wells_dbf": wells_dbf, "survey_manifest": manifest_path, "well_names": names_path,
        "production_audit": production_db, "production_metadata": production_meta,
        "dsu_footprints": dsu_path, "dsu_membership": membership_path,
    }.items()}
    if footage_path is not None:
        paths["footage"] = Path(footage_path).resolve()
    if any(output == p or output.is_relative_to(p.parent) for p in paths.values()):
        raise ValueError("Output must be outside source asset folders")
    if Path(str(paths["production_audit"]) + "-wal").exists():
        raise ValueError("Use a stable production audit snapshot without an active WAL")
    hashes = {key: digest(path) for key, path in paths.items()}
    load = lambda key: json.loads(paths[key].read_bytes())
    manifest, names, production, dsus, membership = [load(k) for k in
        ("survey_manifest", "well_names", "production_metadata", "dsu_footprints", "dsu_membership")]
    footage = load("footage") if "footage" in paths else None
    if (names["survey"]["manifestSHA256"] != hashes["survey_manifest"]
            or names["source"]["dbfSHA256"] != hashes["wells_dbf"]):
        raise ValueError("Well-name sidecar is not bound to these Wells and survey sources")
    if (membership["sourceHashes"]["manifestSha256"] != hashes["survey_manifest"]
            or membership["sourceHashes"]["dsuFileSha256"] != hashes["dsu_footprints"]):
        raise ValueError("DSU membership source fingerprints do not match")
    if footage and (footage["source_hashes"]["dsu_file_sha256"] != hashes["dsu_footprints"]
                    or footage["survey"]["manifest_sha256"] != hashes["survey_manifest"]):
        raise ValueError("Measured DSU acreage is from a different release")
    if manifest.get("sourceCRS") != "NAD83" or dsus["metadata"].get("sourceCRS") != "EPSG:4269":
        raise ValueError("Expected explicit NAD83 source coordinates")
    source_catalog = []
    for index, source in enumerate(production.get("audit", {}).get("sources", [])):
        original = Path(source.get("path", ""))
        known = original.is_file()
        source_catalog.append({"id": index, "name": source["name"], "rows": source.get("rows"),
            "bytes": source.get("bytes"), "sha256": digest(original) if known else None,
            "fingerprint_status": "computed_from_local_original" if known else "original_unavailable",
            "coverage_months": sorted(source.get("months", {}))})
    tile_hashes = {}
    expected_tiles = {x["id"]: x["geometrySha256"] for x in membership["sourceHashes"].get("chunks", [])}
    for tile in manifest.get("tiles", []):
        filename = tile["file"]
        if Path(filename).name != filename:
            raise ValueError("Unexpected tile path")
        tile_hash = digest(paths["survey_manifest"].parent / filename)
        if tile["id"] in expected_tiles and tile_hash != expected_tiles[tile["id"]]:
            raise ValueError("Survey tile fingerprint changed")
        tile_hashes[tile["id"]] = tile_hash
    release_id = hashlib.sha256(dump({"inputs": hashes, "original_sources": source_catalog,
        "tiles": tile_hashes, "code": digest(__file__), "config": CONFIG,
        "refresh": refresh_context}).encode()).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    writers = {name: Writer(output, name) for name in FIELDS}
    issue_counts = collections.Counter()
    issue_ids = set()
    def issue(kind, number, payload):
        value = dump(payload)
        issue_id = hashlib.sha256(dump([kind, number, payload]).encode()).hexdigest()
        if issue_id in issue_ids:
            return
        issue_ids.add(issue_id)
        writers["issues"].row([issue_id, kind, number, value])
        issue_counts[kind] += 1
    try:
        grouped = collections.defaultdict(list)
        for record_number, row in read_dbf(paths["wells_dbf"]):
            number, api = file_number(row.get("fileno")), api14(row.get("api"))
            if not number or not api:
                issue("invalid_registry_identity", number, {"source_record": record_number, "raw_api": row.get("api")})
                continue
            grouped[number].append((api, record_number, row))
        wells, blocked = {}, set()
        for number, candidates in grouped.items():
            distinct = {(a, dump(r)) for a, _, r in candidates}
            if len(distinct) != 1:
                blocked.add(number)
                issue("conflicting_registry_records", number, {"apis": sorted({a for a, _, _ in candidates}), "source_records": [n for _, n, _ in candidates]})
                continue
            api, record_number, row = candidates[0]
            if len(candidates) > 1:
                issue("duplicate_registry_record", number, {"source_records": [n for _, n, _ in candidates]})
            spud = row.get("spud_date")
            try:
                spud = date.fromisoformat(spud).isoformat() if spud else None
            except (TypeError, ValueError):
                spud = None
            wells[number] = {"api": api, "name": row.get("well_name"), "operator": row.get("operator"),
                "status": row.get("status"), "payload": {"source": "public_wells_dbf", "source_record": record_number,
                    "metadata_status": "reported", "source_attributes": row, "spud_date": spud,
                    "total_depth_ft": row.get("td") if row.get("td") and row["td"] > 0 else None,
                    "latitude": row.get("latitude"), "longitude": row.get("longitude"), "coordinate_crs": "EPSG:4269"}}
        manifest_identities = collections.defaultdict(set)
        for branch in manifest["wells"]:
            number, api = file_number(branch["permit"]), api14(branch["api"])
            if number and api:
                manifest_identities[number].add(api)
        for number, apis in manifest_identities.items():
            if number not in wells and number not in blocked and len(apis) == 1:
                wells[number] = {"api": next(iter(apis)), "name": None, "operator": None, "status": None,
                    "payload": {"source": "survey_manifest_only", "metadata_status": "registry_unavailable"}}
                issue("manifest_only_well", number, {"api": next(iter(apis))})
        for number in sorted(wells, key=int):
            well = wells[number]
            search = folded(" ".join(str(x) for x in [number, well["api"], well["name"], well["operator"], well["status"]] if x is not None))
            writers["wells"].row([number, well["api"], well["name"], well["operator"], well["status"], search, dump(well["payload"])])
        branches, seen_branches = {}, set()
        for index, branch in enumerate(manifest["wells"]):
            if branch["id"] != index:
                raise ValueError("Manifest branch indices are not aligned")
            number, api = file_number(branch["permit"]), api14(branch["api"])
            if number not in wells or api != wells[number]["api"]:
                issue("unmatched_branch", number, {"manifest_index": index, "api": api, "branch": branch["branch"]})
                continue
            stable = hashlib.sha256(dump([number, api, branch["branch"]]).encode()).hexdigest()
            if stable in seen_branches:
                raise ValueError("Duplicate stable branch identity")
            seen_branches.add(stable)
            payload = dict(branch, manifest_index=index, geometry_sha256=tile_hashes.get(branch["tile"]),
                           geometry_units="ft", depth_reference=manifest.get("depthReference"),
                           geometry_axes="east X, downward negative Y (relative TVD), south Z",
                           section_lengths_status="not_imported")
            writers["branches"].row([stable, number, api, dump(payload)])
            branches[index] = (stable, number, api)
        dsu_ids = set()
        for feature in sorted(dsus["features"], key=lambda f: f["id"]):
            identifier, props = feature["id"], feature["properties"]
            if identifier in dsu_ids or props.get("id", identifier) != identifier:
                raise ValueError("Duplicate or inconsistent source DSU ID")
            dsu_ids.add(identifier)
            measured = footage["dsus"].get(identifier, {}).get("full_acres") if footage else None
            if measured is not None and (not math.isfinite(measured) or measured < 0):
                raise ValueError("Invalid measured DSU acres")
            payload = {key: props.get(key) for key in ("sourceRecord", "label", "spacingType", "caseNo", "orderNo", "mapSymbol", "referenceCode", "source")}
            payload.update(geometry=feature["geometry"], bbox=feature.get("bbox"), coordinate_crs="EPSG:4269",
                           relationship="source_footprint_not_legal_assignment", measured_area_crs="EPSG:5070" if measured is not None else None)
            writers["dsus"].row([identifier, props.get("formation"), props.get("acres"), measured, dump(payload)])
        if set(membership["units"]) != dsu_ids:
            raise ValueError("DSU membership inventory differs from footprints")
        for identifier in sorted(membership["units"]):
            seen = set()
            for row in sorted(membership["units"][identifier], key=lambda r: (int(r["permit"]), r["api10"])):
                number = file_number(row["permit"])
                if number in seen:
                    raise ValueError("Duplicate DSU/well membership")
                seen.add(number)
                inside, total, share = row["insideFt"], row["totalFt"], row["fraction"]
                if not all(math.isfinite(v) for v in (inside, total, share)) or not 0 < inside <= total + .1 or total <= 0 or abs(share - inside / total) > 1e-5:
                    raise ValueError("Invalid source membership measurements")
                linked = [branches.get(i) for i in row["branchIds"]]
                confirmed = (number in wells and wells[number]["api"].startswith(row["api10"]) and len(row["api10"]) == 10
                    and linked and all(b and b[1] == number and b[2] == wells[number]["api"] for b in linked)
                    and set(row["intersectingBranchIds"]) <= set(row["branchIds"]))
                if not confirmed:
                    issue("unmatched_membership", number, {"dsu_id": identifier, "api10": row["api10"]})
                    continue
                payload = {"method": "geometric_lateral_overlap", "legal_assignment": False, "total_plan_ft": total,
                    "branch_ids": [b[0] for b in linked], "intersecting_branch_ids": [branches[i][0] for i in row["intersectingBranchIds"]],
                    "threshold": "any_positive_overlap", "production_allocation": "none"}
                writers["memberships"].row([identifier, number, wells[number]["api"], inside, share, dump(payload)])
        months, orphan_groups = set(), collections.defaultdict(lambda: {"rows": 0, "source_ids": set(), "first_month": None, "last_month": None})
        production_counts = collections.Counter()
        production_wells, production_samples = set(), {}
        production_total = Decimal(0)
        current_key, pools = None, {}
        def emit_month():
            nonlocal production_total
            if current_key is None:
                return
            number, month = current_key
            invalid, total, sources, rows, collapsed = [], Decimal(0), set(), 0, 0
            for pool in pools.values():
                sources.update(pool["sources"]); rows += pool["rows"]
                if pool["invalid"] or len(pool["values"]) != 1:
                    invalid.append("invalid_pool" if pool["invalid"] else "conflicting_pool")
                else:
                    total += next(iter(pool["values"])); collapsed += pool["rows"] - 1
            quality = "invalid" if invalid else "reported"
            payload = {"source_ids": sorted(sources), "pool_count": len(pools), "observation_count": rows}
            if collapsed: payload["duplicate_rows_collapsed"] = collapsed
            if invalid: payload["reasons"] = dict(collections.Counter(invalid))
            oil_text = str(int(total)) if total == total.to_integral_value() else format(total, "f")
            writers["production"].row([number, month + "-01", None if invalid else oil_text, quality, dump(payload)])
            production_counts[quality] += 1
            production_wells.add(number)
            if not invalid:
                production_total += total
            sample_key = "invalid" if invalid else "zero" if total == 0 else "positive"
            if sample_key not in production_samples:
                production_samples[sample_key] = {"file_number": number, "month": month + "-01", "quality": quality,
                    "oil_bbl": None if invalid else int(total) if total == total.to_integral_value() else format(total, "f")}
        with closing(sqlite3.connect(paths["production_audit"].as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only=ON"); connection.execute("BEGIN")
            query = "SELECT permit,api,month,pool,oil,quality,source,line FROM observations ORDER BY CAST(permit AS INTEGER),month,pool,api,source,line"
            for number_raw, api_raw, period, pool, oil, quality, source_id, line in connection.execute(query):
                number, api = file_number(number_raw), api14(api_raw)
                if not isinstance(source_id, int) or not 0 <= source_id < len(source_catalog):
                    raise ValueError("Observation source ID is absent from the source catalog")
                period_text = str(period)
                try:
                    if not re.fullmatch(r"[0-9]{6}", period_text): raise ValueError()
                    month = date(int(period_text[:4]), int(period_text[4:]), 1).strftime("%Y-%m")
                except ValueError:
                    issue("invalid_production_month", number, {"source_id": source_id, "line": line, "period": period_text})
                    continue
                months.add(month)
                if number not in wells or api != wells[number]["api"]:
                    group = orphan_groups[(number, api)]
                    group["rows"] += 1; group["source_ids"].add(source_id)
                    group["first_month"] = min(group["first_month"] or month, month)
                    group["last_month"] = max(group["last_month"] or month, month)
                    continue
                key = (number, month)
                if current_key != key:
                    emit_month(); current_key, pools = key, {}
                state = pools.setdefault(pool or "missing-pool-identity", {"values": set(), "invalid": False, "sources": set(), "rows": 0})
                state["sources"].add(source_id); state["rows"] += 1
                try:
                    value = Decimal(str(oil))
                    if quality != "valid" or not pool or not value.is_finite() or value < 0:
                        raise InvalidOperation()
                    state["values"].add(value)
                except (InvalidOperation, ValueError):
                    state["invalid"] = True
            emit_month()
        for (number, api), group in sorted(orphan_groups.items(), key=lambda item: str(item[0])):
            group["source_ids"] = sorted(group["source_ids"])
            issue("unmatched_production_identity", number, dict(group, api=api))
        # Detect concurrent source changes before publishing a completed release.
        if any(digest(path) != hashes[key] for key, path in paths.items()):
            raise ValueError("An input changed during the build; release not published")
        if finalize_check is not None:
            finalize_check()
        files = {name: writer.close() for name, writer in writers.items()}
        production_identities = {number: wells[number]["api"] for number in sorted(production_wells, key=int)}
        metadata = {"version": 1, "status": "READY", "release_id": release_id,
            "label": "North Dakota connected well profiles", "source_date": manifest.get("sourceSnapshot", {}).get("date"),
            "source_date_meaning": manifest.get("sourceSnapshot", {}).get("dateMeaning", "source_snapshot_date"),
            "refresh": refresh_context,
            "measured_dsu_acres_status": "hash_bound_inventory" if footage else "unavailable_inventory_not_rebuilt",
            "files": files, "counts": {**{name: value["rows"] for name, value in files.items()},
                "production_wells": len(production_wells), "production_quarantined_pairs": len(orphan_groups),
                "production_quarantined_observations": sum(g["rows"] for g in orphan_groups.values())}, "columns": FIELDS,
            "sources": {key: {"sha256": value, "name": paths[key].name} for key, value in hashes.items()},
            "survey": {"manifest_sha256": hashes["survey_manifest"], "branch_count": len(manifest["wells"]),
                       "station_count": manifest["stations"], "origin": manifest["origin"], "crs": manifest["sourceCRS"], "tile_hashes": tile_hashes},
            "classifier": manifest.get("classifier"), "config": CONFIG, "issue_counts": dict(issue_counts),
            "production": {"months": sorted(months), "units": "bbl", "quality_counts": dict(production_counts),
                "identities": production_identities,
                "identity_sha256": hashlib.sha256(dump(production_identities).encode("utf-8")).hexdigest(),
                "summary": {"well_count": len(production_wells), "well_months": sum(production_counts.values()),
                    "reported_months": production_counts["reported"], "invalid_months": production_counts["invalid"],
                    "total_oil_bbl": int(production_total) if production_total == production_total.to_integral_value() else format(production_total, "f")},
                "validation_samples": list(production_samples.values()),
                "sources": source_catalog, "coverage": {"first_month": min(months) if months else None, "last_month": max(months) if months else None,
                    "calendar": "Explicit source months only; no interpolation or bridging historical gaps"},
                "limitations": ["Whole-well oil/condensate across distinct reported pools; never sum branches.",
                    "No record means unknown; reported zero remains zero; any invalid pool invalidates the whole well-month.",
                    "Exact audit REAL values are converted to decimal text; no float32 viewer values are used.",
                    "Per-month source IDs link to the fingerprinted audit; row-level line references remain in that local audit, not this package."]},
            "limitations": ["Geometric DSU overlap is nonexclusive, not legal assignment, bench attribution or production allocation.",
                "Current well metadata and survey branches do not describe historical ownership or branch existence.",
                "Relative TVD has no common reference-elevation correction.",
                "Unmatched production identities are quarantined; no profile is invented from production alone."]}
        pending = output / "release.json.tmp"
        pending.write_text(dump(metadata) + "\n", encoding="utf-8")
        os.replace(pending, output / "release.json")
        return metadata
    except BaseException:
        for writer in writers.values():
            try: writer.gzip.close(); writer.file.close()
            except Exception: pass
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    for flag in ("wells-dbf", "manifest-path", "names-path", "production-db", "production-meta", "dsu-path", "membership-path", "footage-path"):
        parser.add_argument("--" + flag, type=Path)
    args = vars(parser.parse_args())
    output = args.pop("output")
    result = build_bundle(output, **{key: value for key, value in args.items() if value is not None})
    print(json.dumps({"release_id": result["release_id"], "counts": result["counts"], "issue_counts": result["issue_counts"]}))


if __name__ == "__main__":
    main()
