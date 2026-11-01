# API ownership and integration tracking

Updated 2026-10-09, Europe/Rome. Owner chat: API处理.
Scope authorized by user: project progress tracking, CRM REST API conformity,
and official OpenRouter integration. This is a repository engineering ledger.

## Evidence baseline

- Latest recorded local verification: 175 tests on SQLite and 175 on PostgreSQL,
  zero failures; see `analysis/final-local-test-results.json` and
  `analysis/final-local-tested-hashes.json`. This chat has inspected those reports,
  not rerun those suites. Subsequent edits require relevant revalidation.
- Railway evidence belongs to deployment b8109d36-be1b-4de6-a42c-81de06e87662:
  migration 87.564s, reset 0.646s, 200/200 concurrent reads successful,
  p95 166.1ms, restart/redeploy fingerprints preserved. This is not evidence
  that current local UI, assistant or business fixes are deployed.
- Business verification chat reports independent full-source reconciliation;
  Agent chat reports 36 fake-model cases on both databases. Counts overlap with
  whole-repository suites and must not be added together.
- UI chat's latest animation stress-test turn was interrupted; its final
  browser verification remains unconfirmed.

## Initial code inventory

| Surface | Observed implementation | Next verification |
|---|---|---|
| Objects | CRUD, batch read/create/update/upsert/archive; two URL versions | Compare request/response details and errors against 2026-09 specs |
| Search | Shared search implementation and existing operator tests | Audit all operators, boundaries, ordering and pagination |
| Associations | Existing object/batch routes and read-only type/label catalogs | Map 2026-09 paths and schema mutation gaps |
| Pipelines | Read list, pipeline and stages | Creation/update/archive and individual stage coverage missing from catalog router |
| Properties | Read list and individual property | Mutation/group/unique-property contracts need implementation audit |
| Lists | Search, read, memberships | Creation/update/membership mutations need implementation audit |
| Imports/exports | Competition migration endpoint exists | General official imports/exports APIs remain unverified/unimplemented |
| Authentication | Official APIs use Bearer; browser routes use session/CSRF | Preserve separation and reset behavior |
| Official model | OpenRouter transport fixes model to openai/gpt-6-luna | Fake transport contract tests, failure/usage handling, then separately authorized live acceptance |

Read the exact versioned official endpoint specifications before changing behavior:
https://developers.hubspot.com/docs/llms.txt
The index contains multiple versions; use 2026-09 as required by BRIEF.md.

## Work order

1. Map highest-weight API gaps first: deals/pipelines, contacts, associations,
   search and properties. Add focused no-model regression cases for fixes.
2. Verify OpenRouter request/response and failure behavior without network/model
   spending. Keep assistant business logic aligned with the Agent workstream.
3. Record changed files and relevant test evidence per patch; check shared files
   before edits because other chats use this checkout.
4. Before any future deployment, compare tested hashes with working files and
   establish a single integrated candidate. Preserve the competition freeze.

## Authorization boundaries

- No Railway deploy, variable changes, reset or production data writes authorized
  by the current ownership request.
- No official model spending authorized. Configuring the integration must not
  enable live calls. Automated tests always use fake clients/transports.
- Other-chat Claude connection reports do not establish official-model acceptance.
- Reading chat progress is authorized; sending instructions to other chats is not.
- This ledger is a point-in-time record. A separate thread reminder checks for
  deployment/submission readiness every 10 minutes and only notifies at a relevant
  milestone: remove Claude test configuration/services and switch to the organizer
  OpenRouter integration. The user requested this reminder; no cleanup is authorized
  for immediate execution. Inventory clues: `analysis/claude-key-inventory.json`,
  port 8765 (`devtools.run_claude_ui`), former port 8001 (`devtools.run_claude`),
  and `ANTHROPIC_API_KEY` process configuration. Verify current state at cleanup time.


## Model configuration cutover — 2026-10-09 13:36 Europe/Rome

- User authorized removing Claude and configuring the organizer API, explicitly
  choosing no live model calls. User added the official key and triggered deployment.
- Railway deployment 4570b576-aa60-4f70-9fce-77e9dea97065 reports SUCCESS.
  Public health returns 200 and the authenticated schema contains /__agente.
  OPENROUTER_API_KEY is present; ASSISTANT_LIVE_ENABLED=false; no CLAUDE_ or
  ANTHROPIC_ service variables exist. No key value was displayed.
- Stopped confirmed local Claude UI process 25508. Restarted port 8765 with
  app.main:app and .env.local; local health 200. Live calls remain disabled.
- Both Claude launchers now exit; Claude transport is permanently disabled.
  Fake protocol helpers/tests and old test data are retained. No provider-side
  credential revocation or chat-history deletion was performed.
- Local assistant/Claude regression: 43 tests passed; Ruff passed. The retired
  transport is tested outside the pytest environment guard with network forbidden.
- These devtools/test edits were not uploaded by this chat. Production excludes
  devtools. No model request, production reset or migration was performed.
- Configuration cutover is complete. Real-model acceptance remains pending
  explicit spending authorization. Do not treat health as a model connectivity test.


## Claude residual cleanup

User authorized credential cleanup without rewriting Git or conversation history.
No real Claude credential found in scanned project/config/temp files or stored Git
blobs (including unreferenced blobs). No matching running process or launchctl
Claude variable. Railway has no Claude variables; official key and CRM_TOKEN kept.
Direct uvicorn sandbox factory now refuses non-test startup; both legacy launchers
and Claude transport remain disabled. Removed three stale devtools bytecode files.
55 relevant fake-model/auth tests passed; Ruff passed. No deployment/model calls or
CRM data changes. Five session files plus two Codex history/log databases retain
credentials; left untouched as requested. Exact paths and scan exclusions are in
analysis/claude-cleanup-audit.json. Provider-side key revocation was not performed.


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
