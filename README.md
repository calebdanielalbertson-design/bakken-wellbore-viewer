# Bakken Subsurface Analytics

Interactive 3D exploration of North Dakota oil-and-gas well data: well trajectories, operators, drilling spacing units (DSUs), townships, historical production playback, and featured engineering tours.

- Public site: <https://bakkensubsurface.com>
- Data source: [ND DMR GIS downloads](https://gis.dmr.nd.gov/gisdownload.asp)

```
DMR GIS / production files → Python processing + validation → versioned datasets → browser viewer (Three.js) and PostgreSQL/API
```

The viewer renders prepared geometry files (millions of survey stations), so the browser never talks to PostgreSQL directly. PostgreSQL backs the searchable connected-well profiles API.

## Repository layout

| Folder | What it is | Consolidated from (Caleb's workspace) |
| --- | --- | --- |
| `site/` | Public website source as last released: homepage, viewer, Bakken Subsurface 3D (`/3d/`), EOR projects, methodology, four featured tours. `site/dist/` is what Sites serves. | `sites/bakken-featured-release/` (live as of Oct 21, 2026) |
| `explorer/` | Development viewer (`explorer/viewer/`) plus the Python data-preparation pipeline: classification, survey metrics, operators, production, DSUs, footage inventory, well names. | `outputs/wellbore-viewer/` |
| `backend/` | Connected well profiles: Python API (Gunicorn on Railway), PostgreSQL schema and importers, profile frontend, GIS refresh. | `work/bakken-forward-preview/` |
| `deploy/railway/` | Railway staging configuration, verification, reader rotation and protected-preview launch scripts. | `work/railway-staging-context/` |
| `docs/` | Methodology, data-quality limitations, refresh procedures, deployment and recovery notes. | `docs/` + earlier GitHub docs |

Useful entry points: `explorer/viewer/app.js` (viewer coordination), `explorer/classifier.py` (section classification), `explorer/prepare_data.py` / `prepare_metrics.py` (geometry and derived measures), `backend/backend.py` / `wells_backend.py` (API routing and reads), `backend/wells_schema.sql`, `backend/profiles/profiles.js`, `backend/staging_gateway.py` (API auth), `backend/railway_preview.py` (local proxy that keeps the API token out of browser code).

## Data is not in Git

Prepared datasets are hundreds of MB, so they live in a private S3-compatible bucket (Cloudflare R2) as versioned archives. `datasets.json` records each archive's version and SHA-256, so every clone gets exactly the data the code was tested with.

```
pip install -r scripts/requirements-data.txt
python scripts/datasets.py status    # what's present locally
python scripts/datasets.py fetch     # download, verify and install everything
```

Fetching needs bucket credentials in environment variables (ask Caleb for a read-only key). See [docs/data.md](docs/data.md) for the variables, publishing a new data version, and what each dataset holds. The backend databases are not published yet.

## Running locally

Python 3.11+.

**Development viewer** (needs `explorer/full-dataset/`):

```
cd explorer
pip install -r requirements.txt
python serve.py
```

**Public site** (needs `site/dist/viewer/data/`):

```
cd site
python -m http.server 58518 --bind 127.0.0.1 --directory dist
```

**Backend / connected profiles** (see `backend/README.md`):

```
cd backend
pip install -r requirements.txt
python build_preview.py
python import_snapshot.py data/forward-snapshot.json
python serve.py --port 58519
```

**Tests** (Python 3.11+ and Node.js 20+):

```
python scripts/run_tests.py          # everything that works on a fresh clone
python scripts/run_tests.py --data   # also checks that need prepared viewer data
```

Every pull request runs the same suite plus a secret scan (`.github/workflows/checks.yml`).

**Where scripts look for things.** Backend and deploy scripts resolve locations through `backend/workspace_paths.py`, relative to the repo. Override with `BAKKEN_EXPLORER_DIR`, `BAKKEN_SITE_DIST`, `BAKKEN_WORK_DIR` (scratch area, default `work/`, git-ignored) or `RAILWAY_CLI`.

## Staging API

Railway project *Bakken Subsurface Analytics*, environment `staging`, services `Postgres` and `bakken-forward-api`. Base URL `https://bakken-forward-api-staging.up.railway.app` (e.g. `GET /api/wells?q=CHLOE&limit=20`, `/api/wells/{file_no}`, `/production`, `/dsus`, `/api/wells/meta`). Requests need a bearer token. The app's database account is read-only and Postgres has no public endpoint.

**Secrets never go in Git.** Keep them in Railway/Sites settings or local environment variables.

## How changes ship

1. Branch from `main`, open a pull request.
2. Review against staging (backend) or a local preview (site).
3. Merge, then publish `site/dist/` to Sites.

## Interpretation notes

- Well branches are not separate producing wells.
- DSU overlap is geometric, not legal allocation.
- Production is historical imported data (through Dec 2024), not a live DMR feed. FracFocus is not connected to the staging API.
- Inventory footage densities are illustrative scenarios, not forecasts.

## Known issues

- `docs/bakken-inventory-methodology.md` cites code from a separate `bakken-forward` source folder that isn't in this repo yet.
- An unpublished combined production/spud/frac timeline exists outside `main` and still needs reconciling with the featured-tour release. Its tests (`backend/viewer/test_timeline_controller.mjs`, `backend/viewer/test_preview_hooks.py`) come with it.
