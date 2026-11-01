# Final integrated release — 2026-10-09, Europe/Rome

**Latest status (15:11): f2df2f8 / fa1d5842-3e75-4ff8-8eb0-dea915f1b5db deployed before 15:10. 218 tests PASS on each database. Post-fix official Form check 6/6, examples 10/10, migration 81.06s, no failures. Both live CSV scenarios PASS; fixture archived; health 200; assistant ENABLED. Code/configuration now frozen. Earlier sections retain historical evidence.**

Release acceptance finished at approximately 14:02. Application deployment and final online verification are complete. Official Choice sheet submission opens at 15:00 and is scheduled as a one-time continuation of the integration chat; it is NOT yet submitted. Freeze is 15:30: no pushes, redeploys or variable changes until evaluation ends.

## Version identity

- Final application commit: `95bc5f5` (integration base `44030f2`).
- Final Railway deployment: `feec912b-c7b0-40e5-8648-3eaa217bc17e`, SUCCESS.
- Workspace/project/environment: Hackathon / final-weiyu-chen2-17fe61 / production.
- Project ID: `827b9ca4-9440-45c1-80fb-7437d570e1aa`; existing services `api` and `Postgres` reused.
- Application source matches `analysis/final-candidate-hashes.json` exactly on the final deployment; see `analysis/final-deployed-source.json`.
- Earlier online full-import/performance evidence belongs to `b8109d36-be1b-4de6-a42c-81de06e87662`.
- Deployment found at takeover was `4570b576-aa60-4f70-9fce-77e9dea97065`; it lacked the latest integration.
- Intermediate rollout `ac300ac2-437f-4972-9244-6d47911c6e3c` exposed a real-browser HTTPS origin failure. It is superseded. The final patch accepts only the configured Railway public HTTPS domain behind the internal HTTP proxy; arbitrary forwarded hosts do not bypass CSRF.
- Later repository commits containing only this delivery evidence/choice sheet do not require or imply another app deployment. There is no Git remote configured; no remote push is claimed.

## Local acceptance

The application code initially matched the recorded 175/175 SQLite and 175/175 PostgreSQL baseline. Those full suites were not mechanically repeated. Changed Claude retirement tests plus browser/assistant integration were checked with 20 passing cases on each database. The necessary HTTPS proxy patch then passed 13 relevant cases on each database, including foreign-Origin rejection. Counts overlap and are not additive.

New cross-layer acceptance goes through browser session + CSRF -> UI assistant -> fake model -> shared business store -> database, and re-reads the outcome through search, REST and rendered detail. It verifies one generated win ticket and repeated browser-write idempotence. Existing unchanged evidence covers exact 180-day lost tasks, full messages/context/CSV, ambiguous/missing/illegal targets, stale reads, transaction/automation rollback, concurrent independent fields and email upsert. Ruff and diff whitespace checks pass.

Evidence: `analysis/final-integration-local.json`, `analysis/final-proxy-fix.json`, `tests/test_final_integration.py`, `analysis/final-local-test-results.json`, `analysis/final-local-full-verification.json`. Tests use isolated databases/fake models. An initial PostgreSQL attempt was blocked by local network sandbox permissions, then rerun successfully with network access; it was not an application failure.

## Final online acceptance

- Public `/health`: 200, version `2026-09`, all seven implemented UI routes listed.
- Correct Bearer: 200; missing/wrong Bearer: 401 for both object URL versions and OpenAPI. Browser session cookies alone do not authenticate official APIs.
- Real HTTPS browser login succeeds. Company detail, deals board, dormant list and tickets load in Chrome with no application page errors and zero assistant requests. All declared page routes also passed HTTP checks.
- Full company pagination: 17,734 records over 178 pages, no duplicate or omitted IDs. Search totals match all ten imported object types.
- Before restart: 20 concurrent readers, 200/200 HTTP 200, p95 129.2ms, maximum 184.4ms.
- After restart: 20 concurrent readers, 200/200 HTTP 200, p95 129.9ms, maximum 147.1ms. Health, API authentication and HTTPS browser login pass again.
- Marked acceptance records: 20 concurrent distinct-field updates retain every field; 20 concurrent email upserts create exactly one contact and retain every field.
- Failed batch rolls back its prior win transition and generated ticket. Repeated session/CSRF win writes generate exactly one ticket. UI detail and REST readback match; generated association is readable through the API.
- Five acceptance-only records across both rollouts are archived. They remain as auditable test artifacts, with two directional test-association rows. No business record was reset, deleted, reimported or overwritten.
- Original business data fingerprints are unchanged: 539,204 objects, 1,393,960 directional associations and 954 dormant-list members. Including archived acceptance artifacts, there are 539,209 objects and 1,393,962 associations.
- Actual restart confirmed by changed `/proc/1/stat` start time, with full fingerprints identical before/after. Zero duplicate active contact emails.

Evidence: `analysis/final-online-http.json`, `analysis/final-browser-verification.json`, `analysis/final-before-restart-data.json`, `analysis/final-after-restart-data.json`, `analysis/final-postrestart-http.json`, `analysis/final-release-summary.json`.

## Access and configuration

Open https://api-production-bb05d.up.railway.app/login and enter the organizer CRM token privately. The server creates an HttpOnly/Secure session; no credential is embedded in frontend source. The business identity selector provides view/assistant context, not employee authentication.

- Company example: `/companies/1`; deals `/deals`; dormant `/dormant-customers`; tickets `/tickets`.
- Judges visiting directly will see sign-in. They must have the organizer token or an already authenticated browser session. No anonymous business access or public write bypass was introduced.
- Entrypoint `app.main:app`; local preview absent in production and code rejects it on Railway.
- `DATABASE_URL` was checked both resolved and unrendered: exact `${{Postgres.DATABASE_URL}}` reference.
- CRM_TOKEN and OPENROUTER_API_KEY presence checked without printing values.
- `ASSISTANT_LIVE_ENABLED=false`; no Claude/Anthropic service variables, production devtools excluded.
- Docker build context is allowlisted to application/build inputs. Reference folders, raw CSV, local databases, secrets, tests and devtools are not copied into the runtime image.
- Temporary Railway SSH key was revoked; its local key and agent were removed. Source-only rollback archive remains at `/tmp/relay-preintegration-source.tar.gz` (hash in `analysis/final-integration-local.json`).

Before freeze, rollback uses Railway deployment history to redeploy the recorded prior image/source. Do not reset or restore the database as part of application rollback: this release adds browser-session storage and retains business data. After 15:30, no deployment/variable changes until evaluation ends.

## Known gaps and authorization still needed

1. Real organizer-model acceptance is NOT authorized and was NOT run. While live calls remain disabled, the assistant cannot perform model-driven evaluation conversations. Enabling it and any bounded manual smoke check require the user's separate explicit permission. Automated tests must always remain fake-only.
2. Do not run official Form check: it performs reset/migration and calls the model.
3. Latest importer was fully checked locally, but final deployment was not given a destructive fresh full migration. Historical 87.564s Railway migration used loopback source transport and an older version; do not claim it is final-version WAN timing.
4. The retained production import has 85 user metadata rows without `ruolo`/`responsabile`; manager/team context is therefore unavailable there until an authorized data refresh. The current importer preserves these fields for subsequent migrations. Existing ownership data was retained.
5. General properties/pipelines/lists mutation, general imports/exports and other catalog/schema API surfaces are incomplete. Tests are self-authored, not an official score.
6. First-valid-email, unique rehire/name matching, naive civil timestamps and credit-only dormant membership remain documented interpretations.

## Submission

The official dashboard confirms the deploy URL is already registered. Choice sheet is not open before 15:00. `CHOICE-SHEET.md` is a prepared draft below the 20,000-character cap with source examples, counts, choices, omissions, assistant behavior and jury URLs. The 15:00 same-chat continuation is automation `15-00`; keep the computer and Codex app running for local scheduled work. If model authorization or other facts change first, update the sheet before saving. Verify the saved platform text. Never describe scheduling as successful submission.

## Additional strength testing — 2026-10-09 14:08 Europe/Rome

Same deployed application, no code change or redeploy. 1,000 single-record HTTPS reads
at concurrency 20: 1,000/1,000 HTTP 200, p95 131.6ms, max 820.9ms. A further 300 mixed
record/search/pagination reads at concurrency 20 all returned 200; each group p95
was below 140ms. Health remains 200 and all active object totals are unchanged.
No production business writes or model calls in this pass.

Four new isolated stress fixtures pass on both SQLite and PostgreSQL: 60 stage updates
retain every independent field and produce one ticket/one task; 80 email upserts across
both API versions create one contact; 40 concurrent failing batches fully roll back;
80 fake assistant conversations at concurrency 8 preserve unrelated records. This
excludes actual provider latency/understanding. Evidence: analysis/release-strength-summary.json
and analysis/release-strength-online.json; reproduction: tests/test_release_stress.py.


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


## VAT release deployed — 2026-10-09 14:30 Europe/Rome

User explicitly authorized one `railway up` for commit `db68bcd`. Deployment
`83d3f46b-756b-4c68-83bc-d6627d9dc484` succeeded from a clean commit snapshot.
Public `/health` returned 200 and an authenticated versioned company GET returned
200. The upload's 45 build inputs match the commit, including the corrected VAT
parser, and build logs confirm `COPY app ./app`. The user explicitly accepted upload/build evidence only; direct container source
inspection was not performed and no SSH key was added. See `analysis/vat-deployment-verification.json`.
No reset, migration or model call occurred. Existing production records therefore
remain from the earlier import. Other chats and the submission automation are
instructed not to deploy/redeploy after this release without new human authority.


## Authorized real-model manual acceptance — 2026-10-09 14:42 Europe/Rome

User authorized official model testing, target $2 and hard ceiling $2.50, then
explicitly declined Form check. No reset/migration or Form check was run.
`ASSISTANT_LIVE_ENABLED=true` was applied to the existing VAT release without
uploading source; Railway configuration rollout `d10cc0b4-64ae-4620-b0d6-c37d9a51d3ce`
succeeded. The real assistant remains enabled for evaluation as requested.

Four sequential manual scenarios used the official model and validated live active
users. Revenue/class passed (EUR 25,192.87, B, 4.193s). Duplicate VAT FAILED
(5.906s): model supplied `vat_number` rather than `partita_iva` and created
company `175595075180485946213386433698994571970`; that exact test company was
soft-archived and active company count restored to 17,734. Ambiguity passed
(10.340s), with all 369 matching Rossi deals unchanged and no ticket/task count
change. Explicit won-deal write passed (5.728s): deal 83688 changed only stage
and modification timestamp; exactly one kickoff ticket
`133756761042959603613638034162606394962` was created for Michele Tagliabue.
The other Bellini & Lo Russo deal was unchanged. The authorized won state and
kickoff ticket are retained. No source fix or code deployment was performed.

Evidence and actual provider usage snapshots: `analysis/manual-model-acceptance.json`.
Provider usage updates are delayed; interval deltas must not be attributed as exact
individual scenario costs. This run is manual paid acceptance, NOT an automated test.
The assistant property-name bypass is a known unresolved defect and is recorded
in the choice sheet; fixing/deploying it requires lifting the current code-deploy freeze.


## Assistant catalog fix — 2026-10-09 14:48 Europe/Rome

Supersedes the unresolved field-name defect above. Commit `689cfda` changes only
assistant tools/prompt plus regression tests; REST and migration were not changed.
Unknown property names are rejected against each object's non-archived property
catalog before ANY batch create/update, returning valid names. Prompt identifies
`partita_iva` as the unique company VAT field. Full suites: 211 passed on SQLite
and 211 on isolated local PostgreSQL, fake-only; Ruff passed. An initial sandbox
PostgreSQL attempt could not connect; the authorized network-capable full run passed.

Exactly one `railway up` deployed `6edbcc40-33ed-4389-b612-447d6cefb653`, SUCCESS
before 14:48. Health returned 200. Only duplicate-VAT was retested with a real
model (4.238s): correct refusal identifying the existing company; active company
count stayed 17,734, zero named test companies, existing company unchanged.
Real assistant remains enabled. Form check is pending the browser's action-time
confirmation; no Form check/reset/migration has yet been performed.
Evidence: `analysis/assistant-catalog-release.json` and
`analysis/manual-model-acceptance.json`. No further code deployment authorized.


## Official Form check completed — 2026-10-09 14:51 Europe/Rome

The user gave action-time confirmation; the platform Run the check button was
clicked exactly once at 14:48. Result: all 6 checks PASS, zero failures.
`/__migrate`: **81.84 seconds** as reported by the official platform.
Examples: **10/10**. Health/version, bearer auth, reset 204 and assistant sample
within 60 seconds passed. No rerun and no subsequent source/config change.

Post-check live counts: 17,386 companies, 64,212 contacts, 33,577 deals,
21,329 tickets and 0 tasks. The platform's reset/migration replaced the old
production dataset, including the prior manual test mutations. The VAT-corrected
company count is now present online. Earlier statements about no fresh WAN
migration and old production data are superseded by this check.

OpenRouter actual reported account use at 14:50:52: $0.00221195; remaining
$9.99778805. Calls remain enabled for evaluation. Billing can settle with delay;
no further manual model calls will be made. Code deployment completed before
14:58; all requested execution completed well before the 15:10 cutoff.
Choice sheet updated, not submitted by this chat. Evidence:
`analysis/official-form-check-result.json`.


## Additional robustness — 2026-10-09 14:59 Europe/Rome

User clarified budget as retaining at least $9, NOT spending $9. No new deploy,
configuration edit, reset or Form check. Final-version post-migration load:
5,600 measured requests including warmup, all 200; 20-reader single-record p95
139.3ms, 40-reader p95 383.4ms. Pagination exact, auth/UI checks passed,
active totals and 50 sampled records unchanged.

Ten manual live-model turns: four concurrent revenue/class queries correct;
unknown-field mixed write refused without mutation; lost-deal task due exactly
180 days and repeat request did not duplicate. Two canonical-SKU CSV scenarios
FAILED with generic errors; a captured log reported `KeyError`. A separate earlier
CSV fixture used noncanonical SKUs that collapsed to the same normalized SKU;
that attempt is invalid for the intended test and not a product failure.
The CSV failures remain unresolved; no further model retries or deployments.

All three marked fixtures and generated task were soft-archived; active baseline
counts restored and health 200. Remaining archived test objects are deliberate
audit evidence, not active business records. See `analysis/post-form-strength.json`
and `analysis/post-form-manual-robustness.json`. Choice sheet discloses CSV limits.

## CSV fix and final acceptance — 2026-10-09 15:11 Europe/Rome

User authorized one time-boxed assistant-only fix and deployment. Direct model
diagnostic reproduced flat attachment tool arguments, while the router indexed
the missing `args` envelope. `app/assistant/router.py` now validates wrapped or
flat arguments; malformed/unknown/missing keys are refused. No REST API or
migration code changed. Seven new regressions cover valid decimals, missing-SKU
atomicity and malformed envelopes. Full suites: 218 SQLite + 218 PostgreSQL PASS;
Ruff PASS. Commit f2df2f8 deployed once; Railway SUCCESS was observed at 15:06,
health 200 and live-enabled variable verified at 15:07.

After explicit action-time confirmation, the official check ran once for this
release at 15:07: 6/6 PASS, examples 10/10, public migration 81.06s, no failures.
The earlier 14:48 check remains separate historical evidence.

Post-check manual real-model CSV re-acceptance: valid price 10.00 -> 12.34 in
3.361s; mixed existing/missing SKU request refused in 2.826s, existing record
unchanged and absent product not created. Response unnecessarily offered to
create the missing SKU, but did not create or update anything. Marked fixture
soft-archived (204), absent from active reads (404), final health 200.

Evidence: analysis/csv-envelope-release.json, analysis/csv-first-call-diagnostic.json,
analysis/csv-form-check-result.json, analysis/csv-live-reacceptance.json.
No further deploy or configuration changes. Assistant remains enabled.
