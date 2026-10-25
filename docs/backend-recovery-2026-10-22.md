# Backend recovery and website connection

## Verified October 22, 2026

- Featured tours published successfully as Sites version 10, source `97d0400f35b5530ebd7611d76aeb91e11167d14a`, deployment `appgdep_6ada7c14bf948191b60fc961b4f6c807`. All four tours rendered successfully on bakkensubsurface.com.
- Earlier publishing failures were archive-upload timeouts before version saving, not website build errors. The unchanged artifact succeeded on retry. No precise network/root cause is established.
- The archive is 230,986,175 bytes. Viewer data accounts for 228,767,115 of the 235,122,299 static bytes. The tours themselves total 564,549 bytes. These are deployment sizes, not a measured per-visit download.
- The separately prepared combined oil/spud/frac timeline release remains unpublished. The tours release deliberately preserves the prior public viewer.
- Railway is separate from the public Sites hosting path. Its security incident requires credential recovery before a public backend connection, but it does not explain the OpenAI blob-upload timeouts.
- Railway CLI sign-in initially failed as unauthorized. Renewed the existing authorization with the same selected workspace Projects_Caleb and only the Bakken Subsurface Analytics project; no new project, SSH key, domain, database proxy or additional project access was created.
- A fresh scoped API check confirms staging has exactly Postgres plus bakken-forward-api. Production has zero services. API deployment remains the successful October 18 deployment. No temporary import owner reference or pre-deploy importer is configured.
- API uses forward_reader, a private database host, and a password supplied separately through PGPASSWORD. It has no public domain, TCP proxy or allowed browser origin. Postgres likewise has no public domain or TCP proxy.
- A read-only variable-name inventory found only database credentials and the expected application configuration in these two services. This is not a check of other Railway projects, nor proof of no compromise. No secret values were emitted or persisted by the review script.
- A bounded last-100-entry deployment log review found only October 18 entries for both services (API nine timestamped entries, database 36). No authentication-failure messages appeared in that narrow sample; it contains no incident-period coverage and cannot establish absence of misuse.

## Credential recovery gate

Railway's official incident guidance recommends Database → Config → Connection → Regenerate for the managed Postgres owner password. This changes the actual database password and its variables together and restarts the database. Browser credential-change rules require the user to perform this step. The correct staging Config page is open for handoff; no password reset has been performed by the agent.

The custom forward_reader role needs separate rotation; regenerating the managed postgres password must not be represented as rotating every database role. After the user resets the managed password:

1. Confirm database recovery and all dependent consumers. Keep the database private.
2. Rotate the custom reader credential through a narrowly scoped staging recovery operation, with new secrets only in memory or provider secret settings. Keep its grants SELECT-only and terminate old reader sessions. Verify role attributes and memberships.
3. Update the API's reader secret, redeploy with database-aware health checks, and run the existing real PostgreSQL verifier. Remove any temporary owner access before the final runtime deployment.
4. Review Railway audit/deployment logs, database authentication events, roles and expected table counts. Do not claim clean history from a short log tail. Confirm backups/restore options before relying on this backend in production.

Official guidance: https://blog.railway.com/p/security-disclosure-recommendation-rotate-postgresql-database-credentials

## Staging website connection

The existing bounded API and connected profile implementation are documented in connected-well-profiles-staging.md. Previously imported populations include 44,005 registry wells, 48,929 branch summaries, 10,573 original DSU footprints and 3,011,237 historical whole-well production months. These are prior verified counts, not a fresh database recount or current production coverage.

Keep the initial website connection in staging. Query well-name/file/API search, profile details, historical production and geometric DSU membership through a controlled HTTP API. Never send PostgreSQL credentials to browser code or open a public TCP database proxy. A public API origin or protected proxy still needs an explicit access design, authentication as applicable, request limits, caching, bounded responses and origin handling before exposure. No such public connection has been created in this step.

Preserve the viewer's prepared binary geometry transport. PostgreSQL is appropriate for searchable records and relationships; moving metadata into SQL alone does not eliminate large geometry assets from deployment. Separate immutable versioned geometry/metrics/production asset delivery from application code releases in a later hosting improvement. Do not migrate DNS or hosting platforms merely to work around a transient upload failure.

Validate the frontend against unavailable API, unknown production, empty results and release mismatches. Display release/source dates and retain existing snapshots for comparison. Historical production is not current premium DMR production; the supplied gaps and missing gas/water fields remain unknown, not zero. Automatic DMR refreshes remain a separately reviewed workflow.

## Current status

Public tours: live and verified. Website-to-Railway connection: not activated.

## Recovery after user password regeneration

The user confirmed managed PostgreSQL password regeneration on October 22. The private recovery deployment `fc8858f3-4523-43e5-bbe8-05a5e1a1dec1` succeeded. It connected using the regenerated owner reference, rotated `forward_reader` using a locally generated secret supplied through stdin to Railway, terminated existing reader sessions, and verified the new reader login. The ALTER ROLE statement used a SCRAM verifier, not the plaintext password. No password was written to workspace files or command arguments.

At 21:30 UTC the real-database verifier passed: 44,005 wells; 48,929 branches; 10,573 DSUs; 75,736 memberships; 504 issues; 3,011,237 production months covering 25,055 wells, totaling 5,846,896,506 oil barrels. It also checked search/profile/production/DSU APIs, reader permissions, zero-versus-missing semantics and the retained 80-record research sample. These are historical imported records, not newly obtained premium production.

The temporary owner reference and pre-deploy rotation command were removed. Final deployment `b389084a-2ce8-44b7-98bf-39047e32a796` from `work/connected-wells-deploy/20261022-reader-only` succeeded, with all real-database checks passing again at 21:34:45 UTC. It excludes recovery code and retains read-only verification at startup. The temporary recovery deployment is REMOVED. Both database and API remain private. Recovery does not establish that no incident-related access occurred, and backup/restore review remains outstanding before public backend activation.

## Protected connected preview — October 22

Superseding the earlier API-private-only status: user authorized connecting a protected staging website preview. Deployment `6f0674c1-32ca-461b-8b59-0fb6f6d54f65` succeeded and reran database verification at 22:10:41 UTC. Only after success, enabled the API HTTPS hostname `https://bakken-forward-api-staging.up.railway.app`, port 8080. PostgreSQL still has no public domain or TCP proxy; production still has zero services. No changes to bakkensubsurface.com or its DNS.

`work/bakken-forward-preview/staging_gateway.py` requires a generated bearer token on every data route, fails closed if it is absent from configuration, allows only GET well endpoints, and bounds concurrent requests to four per worker (eight with two workers). The public `/health` route returns readiness only. This is limited staging access, not a customer authentication/rate-limiting system. Tokens are stored in Railway secret settings and passed through stdin during setup; never embedded in browser assets or URLs.

`railway_preview.py` serves the existing branded profiles on loopback `http://127.0.0.1:58529/profiles/`. Its server forwards well requests over HTTPS using the token in process memory, refuses redirects, checks Host/Origin/Fetch-Site, bounds response size/time, and never falls back to SQLite. Existing viewer geometry remains local/static. FracFocus is explicitly unavailable in this connected preview because it has not been imported to Railway. Historical production and spatial-relationship caveats remain visible.

Start with the authorized CLI session:

```powershell
& '~/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' work/railway-staging-context/launch_protected_preview.py https://bakken-forward-api-staging.up.railway.app
```

The launcher retrieves the token into memory, verifies missing/wrong token returns 401, verifies PostgreSQL storage and representative live endpoints, then starts the loopback server. Close that process to stop the local preview. Revoke/replace BAKKEN_PREVIEW_TOKEN and redeploy to revoke HTTP access; remove the API service domain to fully remove external routing. Never roll back to an unprotected backend while the domain exists.

Validation: four gateway tests passed; live unauthenticated/wrong-token rejection passed; CHLOE name and 35721 number search plus profile/production/DSU HTTP checks passed. Browser review confirmed CHLOE's 152 reported months/two branches/four DSUs and A. Johnson's 59 months/two branches/three DSUs. Empty search, hostile Host, cross-origin and cross-site rejection passed. Screenshot: `work/railway-staging-context/connected-profile-preview.jpg`. Local session retained for the user's requested review. This preview is usable on this computer, not a shared staging website or public release.
