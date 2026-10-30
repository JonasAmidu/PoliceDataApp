# Operations panel and PostgreSQL

The panel source is public; access to the panel and its telemetry requires private
credentials. The default deployed path is `/admin`. No admin route is registered
until a signing secret and password or password hash are configured. The public app
and `/health` continue to work without admin settings or a database.

## Production setup

Run `bash private_admin/connect-digitalocean.sh` from a Python environment with
`requirements.txt` installed. The wizard guides you through creating or attaching
a persistent PostgreSQL database, restricting network access, initializing tables
and scoped accounts, generating admin credentials, setting encrypted runtime
variables, deploying and checking live data. It asks before initializing a database
and leaves database plan selection and purchase to you.

DigitalOcean App Platform containers have ephemeral filesystems. Keep PostgreSQL
in a managed database or on a separately administered server with persistent
storage and backups, rather than inside the app's web container. See
[DigitalOcean storage limits](https://docs.digitalocean.com/products/app-platform/details/limits/).
The checked-in app spec does not create or purchase a database.

Configure these on the web component under Settings → Environment Variables,
using runtime scope and Encrypt for credentials:

| Variable | Purpose |
| --- | --- |
| `ADMIN_PANEL_SECRET` | Random signing key of at least 32 characters |
| `ADMIN_PANEL_PASSWORD_HASH` | Werkzeug password hash; preserve all dollar signs |
| `ADMIN_PANEL_PATH` | Optional path, defaults to `/admin` |
| `TELEMETRY_DATABASE_URL` | Scoped writer connection for collection |
| `TELEMETRY_READ_DATABASE_URL` | Scoped reader connection for the panel |
| `TELEMETRY_ENABLED` | Set to `1` to collect activity |

`python -m private_admin.configure` generates credentials privately and writes
`production-admin.env` as a handoff for runtime settings. It preserves existing
local credentials. `ACCESS.txt` holds the password; never commit or paste it into
issues or logs. A password hash is also a secret and stays outside Git.
`ADMIN_PANEL_PASSWORD` is an alternative to a hash for encrypted runtime settings;
it must be at least 16 characters. Password or signing-key changes revoke sessions.

The provisioning helper writes `production-writer.env` and `production-reader.env`
and saves scoped accounts in `database_access.json`. It removes `setup.env` after
success. The reader is SELECT-only with read-only transactions. The writer can
read/write telemetry tables but cannot create tables. TLS is required for remote
connections. The panel can use the writer connection when a dedicated reader URL
is absent, but its queries still run in read-only transactions. Prefer the scoped
reader account. No connection string is returned to the browser.

After deployment, visit `/admin` over HTTPS and sign in. The panel shows PRODUCTION
when connected to PostgreSQL. It displays sessions, traffic, page views, response
times, route performance, browser/device breakdowns and recent errors. Without a
database, it reports that telemetry is not configured; it does not substitute local
data. Database failures return a generic error without credentials.

## Your own PostgreSQL

Any reachable PostgreSQL server with TLS and persistent storage can be used. Run
`private_admin/provision_database.py` with the setup URL in the ignored
`private_admin/setup.env` as `TELEMETRY_ADMIN_DATABASE_URL`. The setup role needs
table and role creation permissions; it is not the runtime account. Configure the
generated reader and writer URLs on the web app and restrict database networking
to the app and your administration machine.

For local development, put a strong `POSTGRES_PASSWORD` in the ignored root `.env`,
then run `docker compose -f compose.postgres.yaml up -d`. This starts PostgreSQL 16
on loopback port 5432, with database `police_telemetry`, setup user `police_owner`
and a named persistent volume. Supply its connection through hidden input to the
setup helper or ignored `setup.env`; local connections may use `sslmode=disable`.
Run the provisioning helper, then restart the app to load the generated reader
connection from `.env`. To collect local traffic, replace `TELEMETRY_ENABLED=0` in
`.env` with `1` and add the generated writer as `TELEMETRY_DATABASE_URL`.

The compose file is for local/self-hosted use, not an App Platform web-container
configuration. Maintain database backups separately; deleting its named volume
deletes the data.

## Authentication and privacy

Sessions expire after one hour. All admin cookies are HttpOnly, Secure and
SameSite=Strict by default, including behind a TLS-terminating proxy. Admin pages
and data are not cached, indexed or embedded in frames. Login and logout require
signed CSRF tokens; the login body and password size are bounded. Ten attempts per
direct client IP are allowed per 15 minutes. Throttling uses an IP HMAC in the
ignored instance database; it resets on container replacement and is local to
each instance. With multiple instances, add shared rate limiting at the edge.
Forwarded client IP headers are not trusted.

Telemetry stores no IP addresses, query strings, precise locations or raw user
agents. Browser categories and random tab sessions have seven-day retention;
active means seen within five minutes. Admin, health and asset requests are
excluded. Presence respects Do Not Track and Global Privacy Control. Overload and
outages can drop telemetry; it is not an audit log. PostgreSQL p95 is estimated
from latency buckets.

Local SQLite telemetry is available only through explicit Flask configuration
`ADMIN_LOCAL_TELEMETRY=True`. For a loopback HTTP development server, set
`ADMIN_COOKIE_SECURE=False` in local Flask configuration; keep production Secure.

## Secrets and verification

Git ignores environment files, settings.json, ACCESS.txt, database access files,
SQLite databases and previews. Only explicitly allowlisted files in private_admin
can be added normally. Never force-add generated files.

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python -m unittest discover -s private_admin -p 'test_*.py' -v
python private_admin/browser_smoke.py
```

Browser checks generate temporary credentials, exercise real login, CSRF, data
loading, charts, time ranges, mobile layout and logout. With
`TELEMETRY_TEST_DATABASE_URL` pointing to an isolated `police_telemetry_test`
database, they cover collection → PostgreSQL → read-only panel and scoped account
permissions. CI runs these PostgreSQL checks. Tests never require production secrets.
