# Partners PostgreSQL deployment readiness

Partners and CRM share a PostgreSQL cluster, but Partners uses only the `partners` schema. The Partners application role must have `CONNECT` on the database and `USAGE` plus the necessary table/sequence DML privileges on `partners`. It must not be a superuser, database owner, role with `CREATEROLE`/`CREATEDB`, or a member of the CRM application role; it must not have access to CRM financial tables. Run schema creation or upgrades with a separate schema owner/migration role, then start the application using the restricted role. Verify this using an actual login with the runtime role and queries against both schemas before enabling its timers.

For an application connection to a remote PostgreSQL host, require certificate verification (`sslmode=verify-full` and an appropriate trusted root certificate). Local Unix-domain socket connections may use peer authentication. Record `pg_hba.conf`, role grants, schema ownership and database connection policy in the private operations backup; `pg_dump --schema=partners` does not preserve cluster roles or their permissions.

Before any database cutover, take a fresh isolated-schema dump, test its recovery on a separate host, and preserve the previous SQLite archive and application release. An archive table-of-contents listing does not demonstrate a successful restore. To rehearse a **Partners-only** archive on a trusted disposable PostgreSQL recovery host as root:

```sh
bash deployment/verify-postgres-restore.sh /private/backups/partners.pgdump
```

This script creates and destroys a uniquely named test database, verifies that the archive contains only Partners objects, restores with failure-on-error, and checks the resulting schema. It must never be pointed at the production database. Keep an encrypted copy of the archive and private configuration outside the application server. Do not assume a Git rollback reverses schema changes, payouts, or data written after deployment. For rollback after schema changes, first stop writers, preserve a new incident snapshot, assess forward compatibility, and perform a separately approved restoration if needed.

The deployment timer automatically fetches `main` on servers where it has been enabled. Keep it disabled during PostgreSQL cutover until the isolated restore, role grants, TLS configuration and integration environment are validated. A `.pg-cutover-approved` file is an operator signal, not evidence that a restore occurred.

## Runtime Linux identity (explicit opt-in)

All four application runtime units run as the system identity `ta-partners`, not root. They are gated by `/etc/the-affiliates-partners/runtime-user-ready` and therefore cannot start before provisioning. The root-owned deployment service is separate because it installs systemd units and switches releases; keep its timer disabled until a deliberate deployment review. The deployment script still restarts the API when executed, so **do not run it until the runtime identity has been prepared**.

After reviewing ownership and backing up SQLite, run as root on the deployment host:

```sh
bash /opt/the-affiliates-partners/deployment/provision-runtime-user.sh --enable
systemctl daemon-reload
systemctl restart the-affiliates-partners-api.service
systemctl status the-affiliates-partners-api.service
```

The provisioning script creates a locked-down system account, grants group-read to the private `.env.local`, prepares `data` as mode `0700`, migrates the existing SQLite file ownership, verifies the runtime account can import settings/read source and writes the readiness marker last. Inspect existing SQLite file ownership and take a snapshot before running it. Ensure any custom `PARTNERS_DB_PATH` is writable by `ta-partners`; the script covers only the default data path. Production `.env.local` stays outside version control. Never expose its contents in stdout, shell history, or `systemctl show` outputs. After changing the deploy checkout, rerun the runtime checks; the marker is a local operator attestation and does not replace checks after updates. To fail closed, remove the readiness marker and stop the runtime services. Do not activate automatic deploy/dispatch timers until all integration and TLS requirements are met.
