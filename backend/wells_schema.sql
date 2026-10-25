-- Dedicated connected-well read model. Existing Forward tables are untouched.
CREATE TABLE well_app (
  id integer PRIMARY KEY CHECK (id=1),
  app_name text NOT NULL CHECK (app_name='bakken-well-profiles'),
  schema_version integer NOT NULL CHECK (schema_version=1)
);
INSERT INTO well_app VALUES (1,'bakken-well-profiles',1);
CREATE TABLE well_production_versions (
  production_id text PRIMARY KEY, row_count bigint NOT NULL CHECK(row_count>=0),
  payload jsonb NOT NULL
);
CREATE TABLE well_production_identities (
  production_id text NOT NULL REFERENCES well_production_versions(production_id),
  file_number text NOT NULL, api text NOT NULL CHECK(api ~ '^33[0-9]{12}$'),
  PRIMARY KEY(production_id,file_number)
);
CREATE TABLE well_releases (
  release_id text PRIMARY KEY,
  imported_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  manifest_sha256 text NOT NULL,
  production_id text NOT NULL REFERENCES well_production_versions(production_id),
  payload jsonb NOT NULL
);
CREATE TABLE well_active (
  id integer PRIMARY KEY CHECK (id=1),
  release_id text NOT NULL REFERENCES well_releases(release_id)
);
CREATE TABLE well_registry (
  release_id text NOT NULL REFERENCES well_releases(release_id),
  file_number text NOT NULL, api text, well_name text, operator text, status text,
  search_text text NOT NULL, payload jsonb NOT NULL,
  PRIMARY KEY(release_id,file_number)
);
CREATE INDEX well_registry_name ON well_registry(release_id,well_name,file_number);
CREATE TABLE well_branches (
  release_id text NOT NULL, branch_id text NOT NULL, file_number text NOT NULL,
  api text NOT NULL, payload jsonb NOT NULL,
  PRIMARY KEY(release_id,branch_id),
  FOREIGN KEY(release_id,file_number) REFERENCES well_registry(release_id,file_number)
);
CREATE INDEX well_branches_file ON well_branches(release_id,file_number);
CREATE TABLE well_dsus (
  release_id text NOT NULL REFERENCES well_releases(release_id), dsu_id text NOT NULL,
  formation text, nominal_acres numeric, measured_acres numeric,
  payload jsonb NOT NULL, PRIMARY KEY(release_id,dsu_id),
  CHECK(nominal_acres IS NULL OR (nominal_acres>=0 AND nominal_acres<'Infinity'::numeric)),
  CHECK(measured_acres IS NULL OR (measured_acres>=0 AND measured_acres<'Infinity'::numeric))
);
CREATE TABLE well_memberships (
  release_id text NOT NULL, dsu_id text NOT NULL, file_number text NOT NULL,
  api text NOT NULL, overlap_ft double precision NOT NULL,
  overlap_share double precision NOT NULL, payload jsonb NOT NULL,
  PRIMARY KEY(release_id,dsu_id,file_number,api),
  FOREIGN KEY(release_id,dsu_id) REFERENCES well_dsus(release_id,dsu_id),
  FOREIGN KEY(release_id,file_number) REFERENCES well_registry(release_id,file_number),
  CHECK(overlap_ft>0 AND overlap_ft<'Infinity'::float8),
  CHECK(overlap_share>0 AND overlap_share<=1.000001)
);
CREATE INDEX well_memberships_file ON well_memberships(release_id,file_number);
CREATE TABLE well_production (
  production_id text NOT NULL REFERENCES well_production_versions(production_id), file_number text NOT NULL, month date NOT NULL,
  oil_bbl numeric, quality text NOT NULL CHECK(quality IN ('reported','invalid')),
  payload jsonb NOT NULL, PRIMARY KEY(production_id,file_number,month),
  FOREIGN KEY(production_id,file_number) REFERENCES well_production_identities(production_id,file_number),
  CHECK(EXTRACT(DAY FROM month)=1),
  CHECK((quality='reported' AND oil_bbl IS NOT NULL AND oil_bbl>=0 AND oil_bbl<'Infinity'::numeric)
     OR (quality='invalid' AND oil_bbl IS NULL))
);
CREATE TABLE well_issues (
  release_id text NOT NULL REFERENCES well_releases(release_id), issue_id text NOT NULL,
  kind text NOT NULL, file_number text, payload jsonb NOT NULL,
  PRIMARY KEY(release_id,issue_id)
);
