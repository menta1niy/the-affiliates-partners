# PostgreSQL runtime schema gate

The API uses the `partners` schema. Provision the schema during a maintenance
step with a separate migration credential:

```sh
PARTNERS_DATABASE_URL='postgresql://MIGRATOR@HOST/DB' python -m database.prepare_schema --confirm-ddl
```

Do not use the migration credential for the running API. Create a dedicated
login role and grant `CONNECT` on the database, `USAGE` on schema `partners`,
`SELECT, INSERT, UPDATE, DELETE` on its tables and `USAGE, SELECT` on its
sequences. Do not grant `CREATE` on the schema or table ownership. Grant access
to future objects via the migrator's `ALTER DEFAULT PRIVILEGES` as needed.
Keep `public` / CRM schemas inaccessible to the Partners runtime role.

Configure the API environment with the DML-only `PARTNERS_DATABASE_URL` and
`PARTNERS_PG_SCHEMA_READY=true` and `PARTNERS_REQUIRE_POSTGRES=true`. After an
approved cutover, enable both boolean flags in the service environment (or
`.env.local`) alongside the PostgreSQL URL. The required-Postgres flag prevents
accidental fallback to SQLite if the URL is missing or blank. The schema-ready
flag independently requires a URL; both accept only `true` or `false` (case
insensitive; unset is false). Invalid values cause startup/database access to
fail instead of permitting a silent fallback. On the first DB operation, the API checks
required tables, columns and indexes with read-only queries. It fails closed
when the schema is missing or unreadable. Running the preparation command is
an explicit administrative step; it is never performed in schema-ready mode.

For local development, leaving `PARTNERS_PG_SCHEMA_READY` unset retains
automatic initial schema creation. Never use this mode with the restricted
production credential. This guide does not enable or change any service.
