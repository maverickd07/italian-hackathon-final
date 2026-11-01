# Project constraints

## User deployment freeze — VAT release db68bcd

The user authorized VAT chat `01a1209e-98d7-7492-a147-da2783067199` to perform
the ONLY Railway deployment: commit `db68bcd`, deployment
`83d3f46b-756b-4c68-83bc-d6627d9dc484`. No other chat or scheduled continuation
may deploy/redeploy or change Railway variables/start commands after this release
unless the human user explicitly supersedes this instruction. No reset, migration
or model call is authorized by this deployment request. Verify release evidence in
`analysis/vat-deployment-verification.json`; existing data is not re-migrated.

- Build a CRM with REST compatibility with HubSpot objects, search, and associations APIs. Never use the HubSpot name or logo anywhere in app UI (including API documentation UI).
- Scoring: 50 Brambilla business requirements R1-R12 (migration plus derived data, uniqueness and automations); 30 AI chat assistant; 10 API conformity; 10 durability. UI earns no automatic points but is judged for the top 6. See the supplied official brief in `BRIEF.md`; it supersedes pre-event hypotheses.
- The $10 LLM key budget covers the WHOLE day, including evaluation. The chat assistant is the ONLY AI feature. Migration must be deterministic code.
- Do not use the user's $10 model API key at all without their explicit permission. This includes manual calls, smoke tests, evaluations, and live chat. Building or deploying the app is not permission to use the key. Keep live model calls disabled until explicitly authorized; automated tests must always remain fake-only.
- Never call a real LLM in automated tests. Inject a fake client. No LLM calls are needed for the object API.
- Python 3.12, FastAPI, SQLAlchemy, uv. PostgreSQL in production; persistent SQLite is allowed for local development.
- Deploy on Railway. Production data must survive restarts and redeploys: use Railway PostgreSQL via DATABASE_URL, never ephemeral SQLite. Fail startup in Railway without PostgreSQL configured.
- Railway target: workspace `Hackathon`, project `final-weiyu-chen2-17fe61` (`827b9ca4-9440-45c1-80fb-7437d570e1aa`), environment `production`. Backend service is named `api`; database service is `Postgres`. Reuse these services; do not create duplicates. `api.DATABASE_URL` references `${{Postgres.DATABASE_URL}}`.
- Generic object store plus typed associations; keep object types extendable. Support both /crm/v3/objects and /crm/objects/2026-09, numeric IDs and singular aliases.
- Preserve arbitrary imported property values. Archive instead of deleting records. Transactions must prevent partial writes and lost concurrent updates.
- Read official API documentation before deciding conformity behavior. Test every endpoint and search operator with a fake/no LLM client, and run tests before committing.

## Official brief calibration (2026-10-09, Europe/Rome)

- Race: 10:30-15:30, five hours. Choice sheet: 15:00-15:30. Freeze at 15:30: no pushes, redeploys, or variable changes until evaluation ends. Awards at 16:30.
- Ranking is relative: top 6 by tests enter jury review. Final score for these six is 80% tests / 20% jury; jury reorders only those six. Jury axes: interface, data-case choices, product. Final top 3 give an eight-minute pitch. Do not use the earlier fixed-threshold-plus-20 or six-hour strategy.
- R1-R12 weights: companies 4, people 4, deals 6, products/line items 4, support 4, activity history 4, VAT uniqueness 4, 2025 revenue/class 6, dormant list 4, won-deal kickoff 4, lost-deal follow-up 3, contact-domain association 3. R1-R6 split points equally between records/fields and cases discovered in the source data.
- Source export: nine CSV files, about 675,000 rows. Evaluation uses a different export of the same size/rules. Never hard-code source rows or demo answers. Read the official `/Users/danielweiyuchen/Desktop/starter-v9/legacy/RICHIESTE.md` for exact names and transformations. This document and all nine source CSV files have now been independently inspected; delimiter is semicolon, encoding Windows-1252. Audit methodology and limits are in `analysis/README.md`.
- Model, only when user explicitly authorizes the key: OpenRouter `openai/gpt-6-luna`, environment variable `OPENROUTER_API_KEY`, $10 total including development and evaluation. Brief-specified model use does not override the user's prohibition on spending.
- Authentication: bearer token from the competition, stored in a service variable (e.g. CRM_TOKEN). Invalid/missing token => 401. Only GET /health and downloadable completed-export result links are unauthenticated. Never store tokens in code, repo or logs.
- GET /health => 200 with {"status":"ok","version":"2026-09","ui":{...}}. The ui map lists only implemented page routes.
- POST /__reset => 204, authenticated. Restore a fresh-account state: no records, default properties/pipelines/association types, rate-limit counters zero. Migration creates Brambilla-specific schemas/pipelines/list. Reset must be fast; tests invoke it hundreds of times.
- POST /__migrate accepts {"export_url":"..."}; download the supplied HTTP(S) URL including query parameters, regardless of filename. Return 204 only when migration, R8 figures and R9 list are ready. Five-minute hard timeout; measure on Railway and leave a wide margin.
- POST /__agente accepts context.now, context.user and full messages history each turn; no conversation state assumed on either side. Attachments contain text CSV data. Reply 200 with {"reply":"Italian text"}. Use context.now for relative dates and active utenti.csv identity for ownership, never the server clock.
- Assistant evaluation: reset and migrate a small clean nine-file export first; missing id_legacy records make affected requests worth zero. About 40 hidden requests, four concurrent conversations, 60 seconds/turn and 30 minutes total. Operations 20.1 points, questions 6.9, quality 3. Wrong changes on a request's records zero that request; untouched records are also checked. Clarify or abstain when appropriate.
- Default test timeout: 10 seconds. Automation effects R10/R11/R12 may take up to 15 seconds. Search visibility allowance: 15 seconds on migrated volume, 3 seconds in conformity tests.
- Durability requires successful migration: exact pagination/totals at full scale; concurrent updates/creates/email upserts without duplicates or lost values; persisted data across service restart. With 20 concurrent readers, p95 single-record reads <1 second and no 5xx.
- API conformity uses official version 2026-09 across objects, pipelines, association schemas, properties, search, activities/tasks, tickets, lists, products/line items/quotes, imports/exports and errors. Current CRUD/search/association scaffold is only a subset.
- Interface must be English; assistant replies Italian. Jury examines company page, deals board, dormant companies list and tickets. Choice sheet must explain discovered data cases, decisions and omissions.

## Current verification limits

- 91 self-authored tests passed on SQLite and PostgreSQL; these are not official competition scores or proof of full API conformity. Local full-source import produced 539,204 objects and 1,393,960 directional association rows; PostgreSQL import took 39.65s excluding network. See MIGRATION.md.
- Railway backend deployment succeeded and health/object-list reads worked. Deployment 0f5c80e2-2b0e-49a8-beda-af7aac1b9406 now has health version/ui, bearer auth, reset, deterministic R1-R9 migration, VAT uniqueness, R12 and read-only catalog/list APIs. R10/R11 are now implemented locally with transactional, persistent once-per-deal markers. Assistant and product UI remain unimplemented; see REQUIREMENTS.md. CRM_TOKEN presence was verified before deployment; public /health returned HTTP 200 with version 2026-09. Railway full migration remains untested.
- Source `BRIEF.md` is the full pasted official brief. The extracted starter is at `/Users/danielweiyuchen/Desktop/starter-v9`; `legacy/RICHIESTE.md` and `FAQ.md` have been read. The assistant examples, choice sheet, extracted BRIEF and repository README have also been reviewed for migration implementation.
- Independently audited all nine CSV files at `/Users/danielweiyuchen/Desktop/sinergia-export` with `analysis/audit_sinergia.py`; results and source hashes are in `analysis/sinergia-audit.json`. The Claude report is secondary evidence. In particular, excluding credit-only wins from R9 remains unconfirmed; scenario counts are not official expected answers. The audit is now supplemented by the implemented importer and local verification documented in MIGRATION.md; Railway migration is not yet verified.
- FAQ warns the competition form check resets and migrates data and invokes the assistant/model. Do not run that check without explicit model-key permission. Imported history must not trigger R10/R11; R11 means exactly 180 days. Invalid references become empty before duplicate-field merging; preserve the containing record.

## Migration tolerance update
- User requires field-level tolerance: invalid values become empty with persistent
  per-file/field/reason diagnostics in migration:last.log; preserve containing rows.
- Unknown activity types are retained as notes with original type. Missing/duplicate
  IDs use deterministic recovery IDs; unknown SKU must not merge unrelated products.
- Do not publish partial quote totals or derived revenue when required inputs fail.
- 99 tests passed on SQLite and PostgreSQL after these changes. Full-source totals
  remain 539,204 objects / 1,393,960 association rows; see MIGRATION.md for limits.
- Final tolerance verification supersedes the earlier counts: 101 tests passed on
  both SQLite and PostgreSQL; full-source local rerun took 43.50s. All 539,204
  property maps match the prior full import after normalizing absent/empty values
  and excluding the added source activity type. Railway full migration is still
  not verified. See analysis/migration-tolerance-verification.json.

## Active verification: strict authentication (user explicitly requested fix)
- Anonymous UI GETs were a confirmed contract conflict. Do not restore public_path
  bypass in app/main.py. All UI/static/API requests require the bearer token;
  only GET /health is exempt until signed export links are implemented.
- Concurrent email batch/upsert is implemented on both URL versions, with active
  contact email uniqueness enforced in the database. Preserve this during UI edits.
- Railway full migration/durability verification is in progress; do not reset or
  redeploy the service during those measurements from another task.

## Completed Railway verification (2026-10-09)
- Online measurement is complete for deployment b8109d36-be1b-4de6-a42c-81de06e87662.
  `/__migrate` 204 in 87.564s after scoped/deferred indexes (before: 299.586s).
  `/__reset` 204 in 0.646s. 539,204 objects, 1,393,960 associations, 954 list members.
- Complete fingerprints unchanged across redeploy AND verified API-process restart.
  20 concurrent readers / 200 requests: all 200, p95 166.1ms; exact company pagination.
- 137 tests passed on SQLite and PostgreSQL at deployment. The archive was supplied
  privately over SSH and downloaded by the API over loopback HTTP; WAN source
  download latency remains outside this timing. No model calls; temporary SSH key revoked.
- The preceding temporary no-redeploy warning applied while measurements ran; they
  have now ended. Later local login/UI/assistant changes are not included in the
  tested deployment. Check analysis/railway-tested-app-hashes.json before claiming
  local and deployed versions match. Do not overwrite or silently weaken the user's
  authentication requirements to make a conflicting test pass.

## Browser sign-in update (explicit user authorization)
- UI pages now require database-backed browser sessions; `/login` and `/ui-static/`
  are public without business data. This supersedes the blanket static/UI Bearer
  requirement above. Official APIs remain strictly Bearer-only; session cookies
  never authenticate them. UI writes require session and synchronizer CSRF checks.
- The business identity selector is view/assistant context, not employee login.
- Current UI work is local-only. Do not deploy, change Railway variables, reset
  data or enable live model calls. Private local configuration is Git-ignored.

## Final local integration verification (2026-10-09)
- 175 tests pass on SQLite and PostgreSQL, including current browser-session UI,
  assistant fake clients, email upsert and 12 added independent business fixtures.
- Fixed R8 valid quote/header-garbage handling, contact lifecycle merging, and lost
  utenti.csv role/reporting-line columns. Do not remove those regression cases.
- Fresh local full import: 539,204 objects / 1,393,960 associations, 53.634s excluding
  network. Independent raw-CSV audit matched every company revenue/class (17,734),
  contact-company link set (64,212), quoted-deal total (11,659) and dormant member (954).
- Current tested file hashes: analysis/final-local-tested-hashes.json. No concurrent
  source edits were detected during final suites. Later edits invalidate this snapshot.
- No deployment or model call in this pass. Actual model understanding and missing
  API surface remain limitations. REQUIREMENTS.md now distinguishes current local
  evidence from earlier Railway evidence; do not treat historical stale notes as status.


## Final integrated release — 2026-10-09 14:02 Europe/Rome

Final app commit `95bc5f5`, Railway deployment `feec912b-c7b0-40e5-8648-3eaa217bc17e`.
User explicitly authorized final integration/deployment; older local-only notes are superseded for this release.
Health/auth/browser/200-read load/concurrent writes/restart accepted on this exact deployment.
Post-restart p95 129.9ms at concurrency 20, 200/200 successful. Original business data
fingerprints unchanged; five marked test records archived. No model calls or reset.
Live model remains disabled. Latest importer has local evidence; existing production
user metadata lacks roles/reporting lines from the earlier import. See DELIVERY.md and
analysis/final-release-summary.json for version-specific evidence and limitations.
Choice sheet is prepared; 15:00 submission continuation scheduled, not yet submitted.


## VAT correction — 2026-10-09, local verification

Fixed missing `PI:`, `P.I.` and `P. I.` source labels in `app/normalize.py`.
The independent raw-source audit now extracts numeric candidates first, separately
from the application parser; every source row agrees. Of 19,698 active company
rows, 2,136 previously missed PI rows are recovered. R7 requires eleven digits;
checksum is audited, not a new rejection condition. All 10,399 VAT-bearing active
rows pass checksum.

Fresh isolated local PostgreSQL import: 17,386 companies (9,032 with VAT),
538,856 total objects, 1,393,960 directional associations, 935 dormant members;
57.541s excluding network. Revenue remains EUR 32,436,093.91. All company
revenue/classes, 64,212 contact-company link sets, 11,659 quote totals and dormant
members match the corrected raw-source calculation. Full fake-only suites:
208 passed on SQLite and 208 on PostgreSQL, including 23 VAT cases.

Evidence: `analysis/vat-source-audit.json`, `analysis/vat-full-verification.json`,
`analysis/vat-test-results.json`. Choice sheet statistics updated. This is a local
fix, not a deployment or production data refresh; historical online measurements
remain valid only for their recorded deployment. Existing production records do
not re-merge merely by deploying the code. No model calls or production writes.
