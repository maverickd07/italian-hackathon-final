# Relay CRM API

Python 3.12 / FastAPI / SQLAlchemy. PostgreSQL production storage and persistent SQLite local fallback. No LLM dependencies or calls in the object API. Deterministic migration, bearer authentication, reset, and migration catalog reads are implemented locally. Chat remains unimplemented. See MIGRATION.md for evidence, choices and verification limits.

## Local development

```sh
uv sync
uv run uvicorn app.main:app --reload
uv run pytest -q tests/test_api_conformity.py
```

Set `CRM_TOKEN` before using authenticated endpoints (including `/docs`); missing configuration returns 401. `/health` remains public.

The default database is `./crm.db`, which survives process restarts. Set `DATABASE_URL` to use PostgreSQL. API documentation: `/docs`; database readiness: `/health`.

## Implemented contract

Both `/crm/v3/objects/{objectType}` and `/crm/objects/2026-09/{objectType}` support:

- List: default 10, maximum 100; `after`, `properties`, `archived`, `associations`.
- Read/create/update/archive. GET/PATCH support `idProperty`. DELETE archives and returns 204.
- Search: all 13 requested operators, AND within groups / OR between groups, free-text query, property projection, one sort rule, default 10 / maximum 200, integer offset cursor. Archived records are excluded. Token searches support `*` wildcards. Numeric comparisons use numeric ordering; timestamp metadata accepts ISO timestamps or epoch milliseconds.
- Batch read/create/update/archive: up to 100 inputs. Successful writes commit before the response. Batches are atomic: any invalid input rolls back the entire batch.
- Association create/delete by type ID, paged retrieval, creation inline with an object, and associated IDs on object read/list. Known association directions are stored together, so reverse reads work.

Aliases: `contacts/contact/0-1`, `companies/company/0-2`, `deals/deal/0-3`, `tickets/ticket/0-5`, `notes/note/0-46`.

Additional association routes:

- `/crm/v3/associations/{fromType}/{toType}/types`
- `/crm/v3/associations/{fromType}/{toType}/batch/{create,read,archive}`
- `/crm/v4/associations/{fromType}/{toType}/labels`
- `/crm/associations/2026-09/{fromType}/{toType}/labels`
- Modern object association PUT with a type array and DELETE without a type ID.

Legacy association reads return `id/type`; modern reads return `toObjectId/associationTypes`. Standard association type IDs for supported objects are registered in `app/store.py`; custom association schemas/labels are not implemented.

Properties preserve arbitrary JSON values. Every record always returns ID, created date, and the object-specific modified date in `properties`. System metadata is read-only through REST. Migration should use a dedicated deterministic import layer to preserve source IDs/timestamps, rather than overwrite metadata through ordinary create/update.

This is the requested generic contract, not the complete upstream product: full property/schema mutation and history, account-specific required fields, owners APIs, pipeline mutation, custom association labels, and partial-success batch responses remain incomplete. Migration-specific property/pipeline/list reads and bearer authentication are now available.

## Durability and concurrency

- PostgreSQL JSONB storage; SQLite JSON fallback.
- Foreign keys and composite association keys; idempotent association writes.
- PostgreSQL row locks prevent lost property updates. SQLite serializes writes with `BEGIN IMMEDIATE`, WAL and a busy timeout.
- Archive preserves the record and its relationships.
- Startup creates missing tables under a PostgreSQL advisory lock. It never drops data. Use versioned schema migrations for future schema changes.
- PostgreSQL type/archive/ID and JSONB GIN indexes; search filters/counts/sorts execute in SQL.

## Railway

The included `Dockerfile` and `railway.json` configure Python 3.12, a locked uv install, two web workers, dynamic `PORT`, health checks and restart policy.

1. Authenticate with `railway login`, then link/create the intended project.
2. Add a persistent Railway PostgreSQL service.
3. Set the API service's `DATABASE_URL` to the database service reference `${{Postgres.DATABASE_URL}}` (adjust service name if different).
4. Deploy this directory with `railway up` and generate an API service domain.
5. Verify `/health`; create a record, redeploy, and read it back.

The API refuses to start on Railway without a PostgreSQL URL. Production never falls back to ephemeral SQLite.

Live deployment (2026-10-09): workspace `Hackathon`, project `final-weiyu-chen2-17fe61`, environment `production`, backend service `api`, database service `Postgres` with its persistent volume. Public base URL: https://api-production-bb05d.up.railway.app . `/health` returned HTTP 200 with `{"status":"ok"}`. The API service references `${{Postgres.DATABASE_URL}}`. No model key was configured or used. This describes the existing deployed scaffold. The newer local authentication/reset/migration implementation is not deployed; `/__agente` remains unimplemented.

## PostgreSQL tests

The same conformity suite can use a disposable PostgreSQL database:

```sh
TEST_DATABASE_URL='postgresql+psycopg://user:password@localhost:5432/test_db' \
  uv run pytest -q tests/test_api_conformity.py
```

Each test creates and drops its own randomly named schema. It does not clear existing tables. Restart and SQLite-specific checks additionally use isolated temporary database files. Outbound httpx requests are blocked by the test fixture; real LLM usage is prohibited.

## Official API references checked before implementation

- [List contacts: default 10](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/contacts/get-contacts)
- [Contacts guide: maximum 100 per list request](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/contacts/guide)
- [Object API: CRUD, aliases, association writes, batches](https://developers.hubspot.com/docs/api-reference/legacy/crm/using-object-apis)
- [Search: operators, sorts, limits and cursors](https://developers.hubspot.com/docs/api-reference/latest/crm/search-the-crm)
- [Associations: endpoints and directional type IDs](https://developers.hubspot.com/docs/api-reference/latest/crm/associations/associate-records/guide)

## Verification performed

- Full suite: 90 passed with SQLite and 90 passed with PostgreSQL 17 (58 original conformity checks plus 32 migration/auth/business/robustness checks). See `MIGRATION.md` for full-source import and local performance results.
- Ruff lint/format checks passed.
- Deployment Docker image built successfully; two-worker startup and database health check passed.
- Synthetic CRM record survived an API container restart and recreation against the same PostgreSQL database.
- No LLM calls or spend. Test runner emits one upstream Starlette/httpx deprecation warning.

## Deployment update — 2026-10-09 11:58 Europe/Rome

New version deployed with `railway up` to the existing api/production service.
Deployment: `0f5c80e2-2b0e-49a8-beda-af7aac1b9406`.
Public `/health` returned HTTP 200 with `{"status":"ok","version":"2026-09","ui":{}}`.
The initial rollout exposed simultaneous worker catalog seeding; initialization now
uses a PostgreSQL transaction advisory lock. A concurrent-startup regression test was
added; the full suite passes 91 tests on both SQLite and PostgreSQL.
This supersedes earlier undeployed status notes. No reset, full Railway migration,
or model call was performed in this deployment verification.

## Local Relay CRM UI

The same FastAPI process serves Jinja2 pages at `/companies`, `/contacts`, `/deals`,
`/tickets`, and `/dormant-customers`; `/health` advertises these routes. No frontend
build or separate deployment is required. Lists use 50-record pages, and directory
search matches case-insensitive name/domain/email prefixes using expression indexes.
Company profiles include source merge lineage captured by new migrations.

For the full migrated local preview:

```sh
DATABASE_URL=sqlite:////tmp/relay-ui-preview.db uv run uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Browser pages require sign-in at `/login`. The server validates the submitted CRM
token, rotates to a random database-backed session, and stores only that identifier
in an HttpOnly, SameSite=Lax cookie. Sessions expire after eight hours; logout
revokes them across workers. HTTPS (or a production Railway environment) enables
Secure cookies. Session rows live in the shared database, not worker memory.
Only `/login`, public static resources and `/health` are accessible anonymously.
Business pages use `Cache-Control: no-store`.

The local UI includes **Today** at `/`, personal/team views, `/assistant`, and a
floating Relay companion. The **Business identity** switcher chooses an active
employee as view/assistant context; it is not employee authentication. Its selection
is remembered in `localStorage`. Conversation history stays in tab `sessionStorage`
and is cleared at logout/expiry. Legacy browser tokens are removed.

Browser deal updates use `/ui-api/deals/{id}` and the same locked update/automation
logic as the official PATCH. Chat uses `/ui-api/assistant`, forwarding full messages,
CSV attachment text, offset ISO time and selected employee email to the existing
assistant handler. All UI writes require the session's synchronizer CSRF token and
reject cross-origin requests. Official API routes, including `/__agente`, accept
only a valid Bearer token; a browser session never grants API access. No page render
calls a model. `ASSISTANT_LIVE_ENABLED` remains false for local review.

Private local configuration is loaded explicitly, without a frontend secret:

```sh
uv run uvicorn app.main:app --host 127.0.0.1 --port 8765 --env-file .env.local --workers 2 --no-access-log
```

`.env.local` is Git-ignored and has mode 0600. It configures the server token,
the existing local preview database and disabled live assistant calls. Never put
a token in source, tests, command arguments, URLs or browser storage. Tests use an
independent fake credential and fake models against temporary databases.

The preview database's existing users were enriched with `ruolo` and `responsabile`
from the original local `utenti.csv`, because those fields were absent from the
stored catalog. This enrichment only changed the local preview data; it did not
change migration code or the assistant backend. Future datasets need those two
catalog fields to display role-based team views; otherwise the UI falls back to
an active user and personal views.

Smoke and scope checks: `uv run pytest tests/test_ui.py tests/test_ui_workspace.py -q`.

### Authentication and concurrent upsert correction

Official APIs continue to require `Authorization: Bearer <CRM_TOKEN>`, apart from
GET `/health` and any separately implemented authorized export download links.
Browser authentication uses the isolated session routes described above. Live
assistant calls remain disabled.

Both objects URL versions now support `POST /contacts/batch/upsert` with
`inputs: [{id, idProperty: "email", properties}]`, including `new` and optional
`objectWriteTraceId` in results. Email identity is case-insensitive. Per-identity
transaction locks and a partial unique database index prevent duplicate active
contacts across upserts, ordinary creates and email changes. Existing fields not
provided by an upsert remain intact, as required by the competition's concurrent
no-lost-values checks. The upstream contacts guide warns that partial email
upserts are unsupported; this preservation behavior is an intentional competition
robustness choice, not a claim of exact parity for that caveat.
Reference: https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/contacts/guide
