import csv
from contextlib import closing
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_well_bundle as builder


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def write_dbf(path, records):
    fields = [("fileno", "N", 10), ("api", "C", 14), ("well_name", "C", 30),
              ("operator", "C", 30), ("status", "C", 15), ("spud_date", "D", 8), ("td", "N", 10)]
    header_length, record_length = 33 + len(fields) * 32, 1 + sum(x[2] for x in fields)
    header = bytearray(32)
    header[0] = 3
    struct.pack_into("<IHH", header, 4, len(records), header_length, record_length)
    with path.open("wb") as out:
        out.write(header)
        for name, kind, width in fields:
            descriptor = bytearray(32)
            descriptor[:len(name)] = name.encode()
            descriptor[11], descriptor[16] = ord(kind), width
            out.write(descriptor)
        out.write(b"\r")
        for record in records:
            out.write(b" ")
            for name, kind, width in fields:
                value = str(record.get(name, "")).encode("utf-8")
                if len(value) > width: raise ValueError("Fixture field too long")
                out.write(value.rjust(width) if kind == "N" else value.ljust(width))
        out.write(b"\x1a")
    path.with_suffix(".cpg").write_text("UTF-8")


class WellBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="well-bundle-", dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.api1, self.api2, self.api3, self.api9 = [f"330010000{i}0000" for i in (1, 2, 3, 9)]
        self.records = [{"fileno": 1, "api": self.api1, "well_name": "Alpha, \"East\"", "operator": "Operator A", "status": "A", "td": 0},
                        {"fileno": 2, "api": self.api2, "well_name": "\\N", "operator": "Operator B", "status": "PA", "td": 12500, "spud_date": "20000102"}]
        self.dbf = self.source / "wells.dbf"
        write_dbf(self.dbf, self.records)
        (self.source / "tile.bin").write_bytes(struct.pack("<8f", 0, -100, 0, 4, 100, -100, 0, 4))
        self.manifest = {"version": 1, "sourceCRS": "NAD83", "origin": [-103, 48], "depthReference": "Relative TVD", "stations": 4,
            "sourceSnapshot": {"date": "2026-10-17"}, "classifier": {"version": "2.0"},
            "tiles": [{"id": "tile", "file": "tile.bin", "stations": 4}], "wells": [
                {"id": 0, "permit": "1", "api": self.api1, "branch": "LAT1", "tile": "tile", "offset": 0, "count": 2, "maxMD": 100, "maxTVD": 100},
                {"id": 1, "permit": "3", "api": self.api3, "branch": "VERT", "tile": "tile", "offset": 2, "count": 2, "maxMD": 100, "maxTVD": 100}]}
        self.manifest_path = self.source / "manifest.json"
        write_json(self.manifest_path, self.manifest)
        self.names_path = self.source / "names.json"
        self.refresh_names()
        self.dsu_path = self.source / "dsus.geojson"
        write_json(self.dsu_path, {"metadata": {"sourceCRS": "EPSG:4269"}, "features": [{"id": "dsu-a",
            "properties": {"id": "dsu-a", "formation": "Bakken", "acres": 1280, "sourceRecord": 1},
            "geometry": {"type": "Polygon", "coordinates": [[[-103,48],[-102,48],[-102,49],[-103,48]]]},
            "display": {"DO_NOT_COPY": True}}]})
        self.membership = {"sourceHashes": {"manifestSha256": builder.digest(self.manifest_path),
            "dsuFileSha256": builder.digest(self.dsu_path), "chunks": [{"id": "tile", "geometrySha256": builder.digest(self.source / "tile.bin")}]},
            "units": {"dsu-a": [{"permit": "1", "api10": self.api1[:10], "branchIds": [0],
                "intersectingBranchIds": [0], "insideFt": 100, "totalFt": 200, "fraction": .5}]}}
        self.membership_path = self.source / "membership.json"
        write_json(self.membership_path, self.membership)
        self.footage_path = self.source / "footage.json"
        write_json(self.footage_path, {"source_hashes": {"dsu_file_sha256": builder.digest(self.dsu_path)},
            "survey": {"manifest_sha256": builder.digest(self.manifest_path)}, "dsus": {"dsu-a": {"full_acres": 1279.25}}})
        self.production_meta = self.source / "production.json"
        write_json(self.production_meta, {"audit": {"sources": [{"name": "source0.csv", "path": "not-present-source0.csv"},
                                                               {"name": "source1.csv", "path": "not-present-source1.csv"}]}})
        self.db = self.source / "audit.sqlite"
        with closing(sqlite3.connect(self.db)) as c:
            c.execute("CREATE TABLE observations(permit TEXT,api TEXT,month INTEGER,pool TEXT,oil REAL,quality TEXT,source INTEGER,line INTEGER)")
            c.executemany("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)", [
                ("1",self.api1,200001,"A",16777217,"valid",0,2),
                ("1",self.api1,200001,"A",16777217,"valid",0,3),
                ("1",self.api1,200001,"B",5,"valid",1,2),
                ("1",self.api1,200002,"A",0,"valid",0,4),
                ("1",self.api1,200003,"A",20,"valid",0,5),
                ("1",self.api1,200003,"A",30,"valid",1,3),
                ("1",self.api1,200004,"A",5,"valid",0,6),
                ("1",self.api1,200004,"B",None,"missing",1,4),
                ("2",self.api2,202412,"A",7,"valid",0,7),
                ("9",self.api9,195201,"A",10,"valid",0,8),
                ("1",self.api9,200001,"A",100,"valid",0,9)])
            c.commit()
        self.kwargs = dict(wells_dbf=self.dbf, manifest_path=self.manifest_path, names_path=self.names_path,
            production_db=self.db, production_meta=self.production_meta, dsu_path=self.dsu_path,
            membership_path=self.membership_path, footage_path=self.footage_path)

    def refresh_names(self):
        write_json(self.names_path, {"survey": {"manifestSHA256": builder.digest(self.manifest_path)},
            "source": {"dbfSHA256": builder.digest(self.dbf)}})

    def tearDown(self):
        self.temp.cleanup()

    def build(self, name="release"):
        output = self.root / name
        return output, builder.build_bundle(output, **self.kwargs)

    def rows(self, output, table):
        with gzip.open(output / (table + ".csv.gz"), "rt", encoding="utf-8", newline="") as stream:
            return list(csv.reader(stream))

    def test_exact_production_zero_missing_conflicts_and_no_float32_loss(self):
        output, metadata = self.build()
        rows = {(r[0],r[1]):r for r in self.rows(output,"production")}
        self.assertEqual(rows["1","2000-01-01"][2], "16777222")
        self.assertEqual(json.loads(rows["1","2000-01-01"][4]), {"source_ids":[0,1],"pool_count":2,"observation_count":3,"duplicate_rows_collapsed":1})
        self.assertEqual(rows["1","2000-02-01"][2:4], ["0","reported"])
        self.assertEqual(rows["1","2000-03-01"][2:4], ["\\N","invalid"])
        self.assertEqual(rows["1","2000-04-01"][2:4], ["\\N","invalid"])
        self.assertNotIn(("1","2000-05-01"),rows)
        self.assertEqual(metadata["production"]["summary"], {"well_count":2,"well_months":5,"reported_months":3,"invalid_months":2,"total_oil_bbl":16777229})
        self.assertEqual(metadata["counts"]["production_quarantined_observations"],2)
        self.assertEqual(metadata["counts"]["production_quarantined_pairs"],2)
        self.assertEqual(metadata["production"]["months"], ["1952-01","2000-01","2000-02","2000-03","2000-04","2024-12"])
        identities = metadata["production"]["identities"]
        self.assertEqual(identities, {"1": self.api1, "2": self.api2})
        self.assertEqual(metadata["production"]["identity_sha256"], hashlib.sha256(builder.dump(identities).encode("utf-8")).hexdigest())

    def test_registry_only_and_manifest_only_wells_and_raw_null_text(self):
        output, metadata = self.build()
        wells = {r[0]:r for r in self.rows(output,"wells")}
        self.assertEqual(set(wells),{"1","2","3"})
        self.assertEqual(wells["1"][2], 'Alpha, "East"')
        self.assertIsNone(json.loads(wells["1"][6])["total_depth_ft"])
        self.assertEqual(json.loads(wells["2"][6])["spud_date"],"2000-01-02")
        self.assertEqual(json.loads(wells["3"][6])["metadata_status"],"registry_unavailable")
        raw=gzip.decompress((output/"wells.csv.gz").read_bytes()).decode()
        self.assertIn('"\\\\N"',raw)
        self.assertEqual(wells["2"][2],"\\\\N")
        self.assertIn(',\\N,',raw)
        self.assertEqual(metadata["counts"]["branches"],2)

    def test_membership_keeps_positive_overlap_below_ui_threshold_and_original_geometry(self):
        output, metadata = self.build()
        rows=self.rows(output,"memberships")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][2:5],[self.api1,"100","0.5"])
        self.assertFalse(json.loads(rows[0][5])["legal_assignment"])
        dsu=self.rows(output,"dsus")[0]
        self.assertEqual(dsu[2:4],["1280","1279.25"])
        self.assertNotIn("DO_NOT_COPY",dsu[4])
        self.assertIn("geometry",json.loads(dsu[4]))

    def test_conflicting_registry_identity_quarantines_branches_and_production(self):
        write_dbf(self.dbf,self.records+[dict(self.records[0],api=self.api9)])
        self.refresh_names()
        output,metadata=self.build()
        self.assertNotIn("1",{r[0] for r in self.rows(output,"wells")})
        self.assertEqual(self.rows(output,"memberships"),[])
        self.assertEqual(metadata["issue_counts"]["conflicting_registry_records"],1)
        self.assertEqual(metadata["counts"]["production_wells"],1)
        self.assertEqual(metadata["production"]["identities"], {"2": self.api2})

    def test_hash_mismatch_and_unknown_production_source_never_publish_ready(self):
        self.membership["sourceHashes"]["manifestSha256"]="0"*64
        write_json(self.membership_path,self.membership)
        with self.assertRaisesRegex(ValueError,"fingerprints"):
            self.build()
        self.assertFalse((self.root/"release").exists())
        self.membership["sourceHashes"]["manifestSha256"]=builder.digest(self.manifest_path)
        write_json(self.membership_path,self.membership)
        with closing(sqlite3.connect(self.db)) as c:
            c.execute("UPDATE observations SET source=99 WHERE line=2")
            c.commit()
        with self.assertRaisesRegex(ValueError,"source ID"):
            self.build()
        self.assertFalse((self.root/"release/release.json").exists())

    def test_immutable_deterministic_hashed_bundle_and_source_unchanged(self):
        before={key:builder.digest(path) for key,path in self.kwargs.items()}
        output,metadata=self.build()
        second,again=self.build("release-again")
        self.assertEqual(metadata["release_id"],again["release_id"])
        self.assertEqual(set(metadata["files"]),set(builder.FIELDS))
        for table,spec in metadata["files"].items():
            path=output/(table+".csv.gz")
            self.assertEqual(spec["sha256"],builder.digest(path))
            self.assertEqual(spec["rows"],len(self.rows(output,table)))
            self.assertEqual(path.read_bytes(),(second/path.name).read_bytes())
        self.assertEqual(before,{key:builder.digest(path) for key,path in self.kwargs.items()})
        self.assertEqual(json.loads((output/"release.json").read_text())["status"],"READY")
        self.assertNotIn(str(self.source),(output/"release.json").read_text())
        with self.assertRaises(FileExistsError):self.build()

    def test_refresh_context_and_no_inventory_are_recorded_before_ready(self):
        self.kwargs['footage_path'] = None
        self.kwargs['refresh_context'] = {'run_id': 'fixture-refresh', 'source_date_meaning': 'observed_at_not_verified_publication'}
        output, metadata = self.build()
        self.assertEqual(metadata['refresh'], self.kwargs['refresh_context'])
        self.assertEqual(metadata['measured_dsu_acres_status'], 'unavailable_inventory_not_rebuilt')
        self.assertEqual(self.rows(output, 'dsus')[0][2:4], ['1280', '\\N'])
        self.assertNotIn('footage', metadata['sources'])
        def fail_final_check():
            raise ValueError('verified source changed')
        self.kwargs['finalize_check'] = fail_final_check
        with self.assertRaisesRegex(ValueError, 'verified source changed'):
            self.build('not-ready')
        self.assertFalse((self.root / 'not-ready/release.json').exists())


if __name__ == "__main__":
    unittest.main()
