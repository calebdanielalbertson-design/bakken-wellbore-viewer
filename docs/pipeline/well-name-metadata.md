# Optional well-name metadata

`prepare_well_names.py` reads the official ND DMR Wells DBF in read-only mode and
writes a separate `well-names.json` beside a prepared survey. It uses only Python's
standard library. Survey manifests, geometry, metrics, operators, production and
DSU datasets remain unchanged.

```sh
python prepare_well_names.py local-data/OGD_Wells.dbf full-dataset --source-date 2026-10-17
python -m unittest discover -s tests -p test_prepare_well_names.py -v
```

Supply the `.cpg` beside the DBF to retain the source encoding. The October 17,
2026 source declares UTF-8. `--encoding` can explicitly override it; cp1252 is used
only when the CPG is absent and that choice is recorded. Decoding errors are not
silently replaced. The source fields are `fileno`, `api`, and `well_name` (80
characters in this snapshot). The formatted `api_no` field is not used to guess
missing identifiers. The source is available from the [DMR GIS download
page](https://gis.dmr.nd.gov/gisdownload.asp).

`--expected-manifest-sha256 HASH` optionally requires one precise survey snapshot.
`--out` accepts another path ending in `well-names.json`; the filename restriction
prevents accidental replacement of an existing manifest or metric file. Source
hashes are checked again before the sidecar is written.

## Schema

```json
{
  "version": 1,
  "survey": {
    "manifestSHA256": "64 lowercase hex characters",
    "branchCount": 48929,
    "stations": 5495609,
    "sourceCRS": "NAD83",
    "origin": [-102.99897097700921, 47.91137672734358],
    "sourceDate": "2026-10-17"
  },
  "source": {
    "sourceURL": "https://gis.dmr.nd.gov/downloads/oilgas/shapefile/OGD_Wells.zip",
    "sourceDate": "2026-10-17",
    "dbfSHA256": "64 lowercase hex characters",
    "nameField": "well_name",
    "permitField": "fileno",
    "apiField": "api",
    "encoding": "utf-8",
    "encodingSource": "CPG"
  },
  "names": {"0": "ALEXANDER 1-25"},
  "coverage": {},
  "notes": []
}
```

`names` keys are **stable manifest branch IDs**, serialized as JSON object keys,
not array positions. Only matched nonblank names appear. Consumers must verify
the exact manifest SHA-256 and survey metadata before using the index. Absent
entries mean unavailable metadata, not proof that a well is unnamed. Old survey
manifests without `sourceSnapshot.date` declare `survey.sourceDate: null`; this
must not be filled from the later Wells snapshot date.

The join first requires normalized permit plus exact API14. Otherwise it can use
the same permit plus API10 only when every matching source candidate has one
identical nonblank raw name. Exact duplicates with the same name are safe;
conflicting names, blank names and invalid/mismatched identities remain missing.
There is no permit-only, name-similarity, row-position or spatial fallback. Exact
API14 matches take precedence over ambiguity elsewhere in the base API family.
Internal punctuation, case and spacing are preserved. Names containing control
characters are withheld. These are dated reported names, not historical name or
ownership observations.

`coverage.byReason` distinguishes exact and base matches, missing permits/APIs,
API mismatches, missing names and conflicting exact/base names. It contains only
reasons present in that run. `sourceRecords` retains source parsing counts.

## October 17, 2026 preparation

The 44,005-row source DBF has SHA-256
`7c8d9b715d65f0af936cb8f48bdc497d62d5ccaebc869f2fba5246f72495dce6`.
All current source branches matched exact permit+API14; no API10 fallback or
missing-name guesses were needed.

| Survey | Named branches | Named permit/API10 wells | JSON bytes | Gzip bytes |
| --- | ---: | ---: | ---: | ---: |
| Full | 48,929 / 48,929 | 22,498 | 1,478,927 | 294,199 |
| Sample | 376 / 376 | 197 | 13,744 | 2,893 |
| Showcase | 65 / 65 | 31 | 2,933 | 1,140 |

The full index contains 22,495 distinct name strings for 22,498 well identities.
**A name is not a unique key.** Search results must retain permit/API identity and
must not merge separate wells simply because their reported names are identical.
Example searches include `ALEXANDER`, `ECKERT`, `RAVIN` and `JORE FEDERAL`, subject
to the selected dataset's actual coverage.

Preparation checked all 482 pre-existing files in the three source dataset
directories before and after; all hashes remained unchanged. Eight portable tests
cover exact/base precedence, conflicts, missing identities without fallback,
stable noncontiguous IDs, UTF-8/deleted DBF rows, truncated records, manifest guards,
and immutable existing bytes. These tests validate metadata preparation, not
historical completeness or legal identity.
