# Bakken Forward: local website + SQL preview

## Connected well profiles — October 17 update

The separate private Railway staging database now also contains a validated,
versioned connected-well read model: 44,005 wells, 48,929 survey branches,
10,573 original DSUs, 75,736 geometric overlaps and 3,011,237 historical
whole-well production months for 25,055 wells. Production ends December 2024;
premium access/new observations are pending. 504 unmatched production identities
remain quarantined. The original 80 research sample rows are intact.

Open `http://127.0.0.1:58522/profiles/?well=19033` after starting `python serve.py
--port 58522`. This is a **local SQLite mirror of the validated release**;
the private Railway API reads PostgreSQL. No public frontend/API domain or
database TCP proxy was added. Public site/DNS, customer accounts and billing
are unchanged. Earlier sections below describe the original research scaffold.

See [implementation and verified staging state](../../docs/connected-well-profiles-staging.md)
and [GIS refresh/classification runbook](../../docs/staging-refresh-review.md).
`refresh_gis.py` builds isolated survey candidates; `prepare_refreshed_wells.py`
validates a completed candidate and prepares a new SQL input bundle with existing
historical production. Neither schedules jobs nor activates SQL/public data.
Actual PostgreSQL reader verification is saved in
`railway-wells-reader-verification.json`; final settings are in
`railway-wells-staging-final.json`. Deployment
`f35ca92e-fd47-46c3-97ed-c272dd2d2efc` is successful with reader credentials only.

This is an isolated local concept for a **Bakken Forward / Research & regulatory**
section within Bakken Subsurface Analytics. The frontend stays local. A separate
private Railway staging project now hosts the API and PostgreSQL sample. Nothing
was pushed to GitHub or changed on the public website. Sign-in and customer
billing remain on hold.

Open `http://127.0.0.1:58519/forward/` for the research desk,
`http://127.0.0.1:58519/` for the homepage/navigation variation, or
`http://127.0.0.1:58519/setup/` for the staging setup walkthrough.

## Start locally

Use Python 3.12 from this directory. The local preview needs no new packages:

```powershell
python build_preview.py
python import_snapshot.py data/forward-snapshot.json
python serve.py --port 58519
```

Stop that server with Ctrl+C. `serve.py` binds only to `127.0.0.1`. It composes
the proposed pages, an actual read-only SQLite API, and the existing published
viewer assets from the parent workspace. Keep the parent site's `dist/` and the
prepared full survey manifest available; this is not yet a standalone export.

The SQL database at `data/forward.sqlite3` is a disposable **projection of the
allowlisted sample**, not a replacement for any original database. Importing is
an explicit command; API reads never create or repair a missing database. Both
SQLite and PostgreSQL readiness require a completed snapshot fingerprint.

## What is implemented

- Shared website navigation and a separate research route.
- Reported notices, historical order evidence and coverage/source views.
- SQL search, exact operator/type filters and bounded pagination.
- Inspectors with report/document dates, null event dates, source pages,
  quotations, review flags, available source URLs and document fingerprints.
- A preview-only well-to-viewer bridge: file number plus API where available;
  without an API, only one distinct full API identity may match that file.
- Missing/ambiguous geometry remains unmatched. Source DSUs are not joined to
  current viewer DSUs or treated as current legal authority.
- A read-only PostgreSQL adapter, WSGI boundary and Dockerfile, now exercised
  against the separate Railway staging database using a restricted reader.

`serve.py` inserts the local well-selection hook and Research return link in
HTTP responses only. Original viewer files and every prepared dataset remain
unchanged. The well-link resolver currently belongs to the local composition;
before remote deployment it needs a versioned, validated lookup or a reviewed
API implementation. The independent API Docker image does not bundle the 3D
viewer or pretend that local-only route is a deployed service.

## Evidence and coverage

The frozen export contains **40 notice records** from reports dated October 8–9,
2026; **14 checked historical provisions from four orders** dated 2013–2016;
and **26 unreviewed candidate orders** with candidate dates in January–February
2026. Forty order-evidence rows are not forty checked orders. The full source
coverage is shown separately: 1,338 stored notices/31 reports, 425 candidate
order records, and 36,283 corpus contents/179,979 pages. Full corpus text was
not copied. One source report lacks a readable date.

Order URLs are unknown in the selected stores and remain null. Daily-report
URLs are exact stored collector references, not links revalidated today.
Applicants, reported well operators, ownership, and current applicability are
separate concepts. Notice counts are neither unique-well counts nor drilling
commitments. Unknown values and missing dates are not zero activity.

Source review: private `calebdanielalbertson-design/Bakken-Forward` main at
`a404a0357b93db3befb0d503d9ab946a95cddb59` (October 10, 2026). The available local
checkout also contains later local changes, including direct reports and
PostgreSQL support. GitHub is source code, not a backup of the evidence stores.
Source dates and hashes are retained in the exported metadata. No collector,
feed refresh, original database, or source record was modified.

## API contract

- `GET /health`: readiness; an absent/unimported database returns 503.
- `GET /api/forward/meta`: snapshot, sample counts, filter options, storage mode.
- `GET /api/forward/records?kind=notices&q=&operator=&type=&offset=0&limit=25`:
  `{rows,total,offset,limit}`. Limit is 1–50; stable date/ID ordering.
- `GET /api/forward/records/{kind}/{id}`: original allowlisted record object.
- Local composition only: `GET /api/forward/well-link?permit=41914&api=`.

Mutating requests are rejected. Query values are parameterized and wildcard
characters are searched literally. Error responses do not expose connection
strings. Runtime database permissions must still enforce SELECT-only access.
CORS is an exact browser-origin allowlist, **not authentication**; the proposed
research read model is public if eventually launched.

## Railway staging: created October 17, 2026 (Chicago)

[Open the staging project](https://railway.com/project/e2cc4cb2-b22f-4ea4-99ed-329befa4cf60?environmentId=78d48523-3b40-4010-8d4f-10c04d69fe23).

| Resource | Current state |
| --- | --- |
| Workspace / plan | Projects_Caleb / existing Hobby, unchanged |
| Project | Bakken Subsurface Analytics, private |
| Environment | staging, created empty; production remains unused |
| PostgreSQL | Postgres 18.6, private network, persistent postgres-volume |
| Database resource caps | 1 vCPU / 0.5 GB RAM; these are not dollar spending caps |
| API | bakken-forward-api, Docker, no public domain or TCP proxy |
| Data | 40 orders/provisions and 40 notices; bounded sample, not a live feed |
| Runtime database role | forward_reader, SELECT on two projection tables |
| Public website / DNS | unchanged |

The frontend at localhost still uses its original local SQLite projection.
It is **not connected to Railway**. No staging web URL, public API, account
system, payment system, collector or scheduled refresh was added.

The source was deployed by the authenticated official Railway CLI from the
allowlisted folder `~/Documents/Codex/bakken-staging-api/20261017-v2`.
The eight runtime/schema/snapshot files plus manifest exclude original databases,
the document corpus, frontend, credentials and viewer assets. No GitHub source
or automatic deploy trigger was connected. `prepare_staging_bundle.py` requires
the reviewed snapshot hash and refuses to overwrite a bundle.

The approved one-time pre-deploy import ran **inside Railway's private network**:

```text
python import_snapshot.py data/forward-snapshot.json --postgres --init-postgres --create-reader --verify-reader-api --confirm-postgres-import
```

It created only the dedicated projection schema, imported the fingerprinted
snapshot and provisioned the marked reader role. Real PostgreSQL verification
confirmed health, metadata, order/notice lists and details, reader identity,
default read-only transactions, and no effective table-write/schema-create or
database-create privileges. Unknown fields, dates and source review flags were
retained. This is not a full Bakken Forward migration.

After bootstrap, the pre-deploy command and `BAKKEN_IMPORT_DATABASE_URL` were
removed. A fresh stable deployment then passed `/health` with only reader
credentials. `DATABASE_URL` names forward_reader and the private host, without
an embedded password. `PGPASSWORD` was generated in memory and sent directly
to Railway via CLI stdin; no secret was printed or written into the bundle.
TLS is required (`sslmode=require`) on the private connection; this setting
does not itself verify a server hostname/certificate chain.

The temporary SSH-key path was abandoned after automatic approval rejected
registration; no new SSH key was registered and the unused local key was
removed. The user explicitly approved the CLI authorization and, separately,
the reader credential/private import. No credentials belong in this document.

New services cannot opt into the legacy `railway.toml` configuration. Actual
settings were applied in Railway: detected Dockerfile, `/health`, no import hook
after bootstrap. The TOML file remains a labeled legacy reference only.

Latest verified stable deployment: `49e32eaf-92e7-443e-a6eb-e5efeb29c1bc`.
Snapshot SHA-256: `b5cc02c7db49168d43fb2f38d31f561c8d3162cd9e8b6d21ffa5cf168e29beee`.
Sanitized verification is in `railway-staging-verification.json`; the original
local-only baseline remains in `validation.json` for comparison.

### Walkthrough and next release gate

1. Open the project and keep the environment dropdown on **staging**.
2. Select **Postgres → Database** to inspect the two tables. **Metrics** shows
   actual resource use; **Settings → Public access** should remain disabled.
3. Select **bakken-forward-api → Deployments** for health/build results. Both
   services should be Online; no public database or API URL was generated.
4. Railway's current Hobby dashboard requires Pro for new volume backups,
   automated schedules and point-in-time recovery. No upgrade was purchased.
   This derived sample is reproducible locally; restore/failure exercises and
   a durable backup policy are required before important non-reproducible data.
5. Next, choose and test a protected staging frontend/API access path, add the
   versioned well-link lookup, review source freshness and complete a restore
   exercise. CORS is not authentication. Public navigation, origins and DNS
   remain a separately reviewed release step.
6. Refreshes should publish validated, versioned snapshots with source dates
   and explicit failure status. Do not put collection jobs in the web process.

Railway bills actual resource usage under the existing Hobby plan, rather than
charging these resource maxima as reserved capacity. No guaranteed monthly
project cost is established yet. Review project Usage after a representative
test period. No workspace-wide spending limit was altered, because that could
stop the user's unrelated projects.

The full Bakken Forward checkout already has a richer PostgreSQL importer and
four schema families (`main`, `regulatory`, `area`, `reports`). Its current
container is AWS-oriented, with RDS certificate and fixed Streamlit-port
assumptions; deploying it unchanged is not this thin API plan. Keep the
collector/review workflow independent, then decide whether to migrate those
full schemas or publish a validated read model from them. No scheduled job is
installed here.

References: [Railway PostgreSQL](https://docs.railway.com/databases/postgresql),
[private pre-deploy steps](https://docs.railway.com/deployments/pre-deploy-command),
[environment isolation](https://docs.railway.com/guides/isolate-staging-production),
[pricing](https://railway.com/pricing).

## Validation

```powershell
python -m unittest discover -s tests -v
```

Backend tests cover read-only access, import ownership/readiness, nulls,
provenance preservation, pagination, literal search, parameter validation,
mutation rejection, and exact CORS. Bridge tests cover ambiguity and source-file
boundaries. All 44 local checks pass. Local PostgreSQL adapter tests use mocks;
the separate Railway pre-deploy verification also exercised the real database.
