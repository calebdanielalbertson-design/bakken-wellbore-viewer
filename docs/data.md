# Prepared datasets

The viewers render prepared files (survey geometry tiles, metrics, operators, production, DSUs, logs). They are too large for Git, so each dataset is stored as one versioned `.tar.gz` archive in a private S3-compatible bucket. `datasets.json` in the repo root records, for each dataset, the version, bucket key, SHA-256, archive size and file count. Code and data change together through pull requests.

| Dataset | Installed at | Contents |
| --- | --- | --- |
| `site-viewer-data` | `site/dist/viewer/data/` | Public site viewer data as released (split gzip parts, reference, showcase) |
| `explorer-full-dataset` | `explorer/full-dataset/` | Full ND survey geometry, metrics, operators, well names, production |
| `explorer-viewer-data` | `explorer/viewer/data/` | Dev viewer layers: DSUs, footage inventory, reference plane, sample, showcase |
| `explorer-gamma-data` | `explorer/gamma-data/` | Gamma-ray / cement-bond log catalogs, survey index, averaged cache (the `.py` services beside them are in Git) |

The backend databases (`wells.sqlite3`, FracFocus, activity snapshot) are not published yet. Raw GIS refresh runs are never published, because they are regenerated from DMR downloads.

## Credentials

Set these as environment variables. Never put them in a file inside the repo.

| Variable | Value |
| --- | --- |
| `BAKKEN_DATA_BUCKET` | bucket name |
| `BAKKEN_DATA_ENDPOINT` | Cloudflare R2: `https://<account-id>.r2.cloudflarestorage.com` (leave unset for AWS S3) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | bucket API key. Collaborators get **read-only** keys; only the publisher has write access |
| `AWS_REGION` | optional, defaults to `auto` (right for R2) |

Windows PowerShell, for the current window only:

```powershell
$env:BAKKEN_DATA_BUCKET = "bakken-datasets"
$env:BAKKEN_DATA_ENDPOINT = "https://<account-id>.r2.cloudflarestorage.com"
$env:AWS_ACCESS_KEY_ID = "<key id>"
$env:AWS_SECRET_ACCESS_KEY = "<secret>"
```

## Getting the data

```
pip install -r scripts/requirements-data.txt
python scripts/datasets.py fetch              # all datasets
python scripts/datasets.py fetch explorer-full-dataset
python scripts/datasets.py status
```

Fetch downloads to a temporary file, checks the SHA-256 against `datasets.json`, and only then swaps the folder into place. A failed or tampered download changes nothing. It won't replace a folder that already has data unless you pass `--force`.

## Publishing a new data version

1. Regenerate the data with the `explorer/prepare_*.py` scripts (see `explorer/README.md`).
2. Pack it under a new version, usually the DMR source date:
   `python scripts/datasets.py pack explorer-full-dataset --version 2026-11-15`
   This writes `work/datasets/<name>-<version>.tar.gz` and updates `datasets.json`.
3. Upload with write credentials: `python scripts/datasets.py push explorer-full-dataset`.
   Uploads never overwrite an existing version. A changed dataset always gets a new version.
4. Commit `datasets.json` in a pull request together with any code that depends on the new data.

Old versions stay in the bucket, so any past commit can still fetch the data it was built against.
