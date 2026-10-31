# Partners PostgreSQL deployment readiness

Partners and CRM share a PostgreSQL cluster, but Partners uses only the `partners` schema. The Partners application role must have `CONNECT` on the database and `USAGE` plus the necessary table/sequence DML privileges on `partners`. It must not be a superuser, database owner, role with `CREATEROLE`/`CREATEDB`, or a member of the CRM application role; it must not have access to CRM financial tables. Run schema creation or upgrades with a separate schema owner/migration role, then start the application using the restricted role. Verify this using an actual login with the runtime role and queries against both schemas before enabling its timers.

For an application connection to a remote PostgreSQL host, require certificate verification (`sslmode=verify-full` and an appropriate trusted root certificate). Local Unix-domain socket connections may use peer authentication. Record `pg_hba.conf`, role grants, schema ownership and database connection policy in the private operations backup; `pg_dump --schema=partners` does not preserve cluster roles or their permissions.

Before any database cutover, take a fresh isolated-schema dump, test its recovery on a separate host, and preserve the previous SQLite archive and application release. An archive table-of-contents listing does not demonstrate a successful restore. To rehearse a **Partners-only** archive on a trusted disposable PostgreSQL recovery host as root:

```sh
bash deployment/verify-postgres-restore.sh /private/backups/partners.pgdump
```

This script creates and destroys a uniquely named test database, verifies that the archive contains only Partners objects, restores with failure-on-error, and checks the resulting schema. It must never be pointed at the production database. Keep an encrypted copy of the archive and private configuration outside the application server. Do not assume a Git rollback reverses schema changes, payouts, or data written after deployment. For rollback after schema changes, first stop writers, preserve a new incident snapshot, assess forward compatibility, and perform a separately approved restoration if needed.

The deployment timer automatically fetches `main` on servers where it has been enabled. Keep it disabled during PostgreSQL cutover until the isolated restore, role grants, TLS configuration and integration environment are validated. A `.pg-cutover-approved` file is an operator signal, not evidence that a restore occurred.
