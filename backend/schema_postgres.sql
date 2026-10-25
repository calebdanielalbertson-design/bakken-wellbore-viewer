-- Apply explicitly to a NEW, dedicated prototype database as its owner.
-- The API never runs this file. Unknown source fields remain JSONB.
BEGIN;
CREATE TABLE forward_metadata (
    id integer PRIMARY KEY CHECK (id = 1),
    app_name text NOT NULL CHECK (app_name = 'bakken-forward-preview'),
    schema_version integer NOT NULL CHECK (schema_version = 1),
    payload jsonb NOT NULL,
    source_sha256 text NOT NULL
);
CREATE TABLE forward_records (
    kind text NOT NULL CHECK (kind IN ('orders', 'notices')),
    id text NOT NULL,
    date_value text,
    operator_value text,
    type_value text,
    search_text text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE INDEX forward_records_date ON forward_records(kind, date_value DESC, id);
CREATE INDEX forward_records_operator ON forward_records(kind, operator_value);
CREATE INDEX forward_records_type ON forward_records(kind, type_value);
INSERT INTO forward_metadata(id,app_name,schema_version,payload,source_sha256)
VALUES (1,'bakken-forward-preview',1,'{}'::jsonb,'');
COMMIT;

-- Recommended separation: provision a dedicated LOGIN read role out of band,
-- with its password kept in Railway secrets. Do not give the web service the
-- owner/import credentials. Substitute your actual database and role names:
-- GRANT CONNECT ON DATABASE dedicated_forward_database TO forward_reader;
-- GRANT USAGE ON SCHEMA public TO forward_reader;
-- GRANT SELECT ON TABLE forward_metadata, forward_records TO forward_reader;
-- ALTER ROLE forward_reader SET default_transaction_read_only = on;
-- The importer uses a separate owner role only during an explicit import.
-- No credentials, role creation or broad grants are embedded in this scaffold.
