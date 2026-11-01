# Deterministic migration implementation

## Evidence reviewed

Implementation reconciles the repository README and BRIEF with all supplied starter
Markdown files: BRIEF.md, FAQ.md, legacy/RICHIESTE.md, assistant/examples.md and
CHOICE-SHEET.md. It also considers the Claude report at
`/Users/danielweiyuchen/Desktop/sinergia-analysis/数据分析报告.md` and the independent
`analysis/audit_sinergia.py` results. Official client requirements take precedence
where recommendations conflict. Neither report is a hidden-test answer key.

API references checked:

- [Association directions and IDs](https://developers.hubspot.com/docs/api-reference/latest/crm/associations/associate-records/guide)
- [Pipeline and stage responses](https://developers.hubspot.com/docs/api-reference/latest/crm/pipelines/guide)
- [List search and memberships](https://developers.hubspot.com/docs/api-reference/latest/crm/lists/guide)
- [Property schemas](https://developers.hubspot.com/docs/api-reference/latest/crm/properties/guide)
- [Product-backed and standalone line items](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/line-items/guide)

## Operational contract

Configure CRM_TOKEN in the api service before deploying this version. Requests require
`Authorization: Bearer <CRM_TOKEN>` except GET /health. Missing configuration fails
closed (401); health remains available. No real model client or model calls exist.

- GET /health returns status, version 2026-09 and an empty ui map.
- POST /__reset removes records, associations, users, lists, unique-value reservations,
  and migration-specific schemas. It restores the currently supported default catalog.
- POST /__migrate accepts an HTTP(S) export_url including query parameters. It downloads
  the ZIP without forwarding the CRM token and reads nine Windows-1252 semicolon CSVs.
  CSV filenames can be nested in the archive; the ZIP URL need not end in .zip.
- All migration writes commit in one transaction. Bad source data rolls back the entire
  import. A nonempty CRM returns 409 rather than overwriting existing records.
- PostgreSQL COPY and bounded activity batches handle the volume. Reset/migration take
  an exclusive transaction advisory lock; other API transactions use a shared lock.
  Health bypasses that lock so a long import does not block readiness checks.
- Core objects, metadata, users and list membership persist in the configured database.
  Source files are never altered. Test downloads are injected fakes.

## Normalization and business choices

1. Exclude deleted rows before any identity merging. Repair strictly reversible encoding
   damage, trim outer whitespace, parse observed civil dates and Excel serial dates.
2. Merge companies transitively by normalized domain or VAT. Keep latest source ID;
   each field takes its latest nonempty value. Preserve additional domains and normalized
   11-digit VAT. A database-backed reservation enforces VAT uniqueness under concurrent writes.
3. Repair email/phone swaps, extract a first valid email, and merge contacts by that email.
   An invalid company reference becomes empty before field merging. Alias every old ID
   to its retained object. Domain matching includes additional domains, never replaces
   an existing contact-company link and never creates a company.
4. Normalize SKUs and merge non-deleted product versions field by field. Line items on
   deleted deals are excluded. Surviving lines remain even if the product is missing or
   deleted; hs_product_id is set only for surviving products. Product references use
   hs_product_id, as specified in the line-item API. Missing price/description use the
   surviving product. Unresolvable price/quantity fails the import rather than inventing money.
5. Parse monetary separators, multipliers, suffix minus and parenthesized negatives.
   Annualize monthly renewal amounts. Normalize fractional discounts and round each
   line half-up to cents before summing. Quote totals override raw deal amounts.
6. Keep the current deal stage authoritative. Fill missing terminal close dates from
   the most recent history entry matching that stage. No imported deal triggers R10/R11.
7. Assign deals/tickets only to active users. Resolve uniquely matched names/initials;
   remap an inactive ID to one uniquely matching active full name (rehire). Otherwise
   leave ownership empty; do not guess a manager. Historical activity authors keep their email.
8. Ticket associations use explicit source IDs. Do not infer links from sender text or
   a contact's company. Preserve contradictory historical timestamps, including the
   161 observed tickets whose close date precedes opening.
9. Compute 2025 revenue on merged company identities with fixed USD/GBP rates, retaining
   negative credits. Round the company total, then classify A/B/C/empty.
10. R9 uses the explicit won-stage criterion in any year and absence of 2025 activity
    through either contacts or deals. Credit-only won-stage companies are not silently
    excluded; the supplied data yields 954 versus 803 if that extra exclusion is added.

First-valid-email choice, unique rehire/name matching, and civil-date timezone are
interpretations, not proven hidden-test expectations. Naive source clock values are
represented with UTC offsets without shifting the original clock/date; no timezone
was specified in the source. These choices belong in the choice sheet.

## Verification (local, 2026-10-09)

90 automated tests passed on SQLite and PostgreSQL 17. They cover existing API routes,
auth fail-closed behavior, nine-file import, source alias redirection, per-line rounding,
rehire resolution, dates, indirect activity, negative credits, catalog/list reads, bad
source rollback, reset/reimport, concurrent VAT conflicts and contact domain matching.
All automated outbound HTTP is blocked; archive downloads are fake.

Full nine-file source import:

| Result | Count |
|---|---:|
| Companies | 17,734 |
| Contacts | 64,212 |
| Products | 1,735 |
| Deals | 33,577 |
| Line items | 41,014 |
| Tickets | 21,329 |
| Notes | 143,410 |
| Calls | 107,761 |
| Emails | 72,232 |
| Meetings | 36,200 |
| Total objects | 539,204 |
| Directional association rows | 1,393,960 |

Local SQLite import: 24.75s; local PostgreSQL COPY import: 39.65s. These timings cover
local files and transaction commit, not remote download or Railway execution.
Source snapshot totals reconcile to the independent analysis: revenue 32,436,093.91 EUR,
954 dormant companies, no duplicate VAT, no duplicate (type, id_legacy), no missing
required id_legacy. The 1,393,960 association rows include both directions.

After restarting the local PostgreSQL container, all companies paginated exactly once
(17,734) and search returned the same total. 200 API reads at concurrency 20 had local
p95 0.0615 seconds and no errors. This is not an internet/Railway latency measurement.

## Remaining limits

This version has not been deployed or benchmarked on Railway. CRM_TOKEN was absent at
last presence-only check. Full schema-management/list-management API conformity is
not implemented: added catalog/list endpoints support reading migration outcomes.
The default property catalog is a supported subset, not a complete fresh-account clone.
R10/R11 live automations are now implemented and tested; see REQUIREMENTS.md.
Concurrent email upserts, the assistant and product UI remain outstanding. Full exported ZIP transfer and Railway restart/load checks remain to run.
Do not run the official form check without model-key permission: it resets data and
invokes the assistant. No model key was configured or used during this work.

## Adversarial checks added

`tests/test_robustness.py` adds 17 cases: three input-order permutations in one
metamorphic test, eight R8 boundary amounts, same-name/different-domain companies,
six personal-email provider cases tested through both import and live API, and
surviving quote lines referencing a deleted product. Expectations are specified in
fixtures, not calculated by calling production normalization functions.

The provider-company counterexample initially failed. The importer and live R12 path
now share an explicit freemail-domain exclusion policy. The list includes observed
providers and common variants, not an exhaustive worldwide registry. Explicit company
associations remain untouched. This source snapshot had no provider-domain company
matches, so prior snapshot counts are not changed by this exclusion.
Reference: https://knowledge.hubspot.com/object-settings/automatically-create-and-associate-companies-with-contacts

Remaining robustness gates: renamed/generated IDs and randomized synthetic datasets;
independent record/field/association comparison of full exports; malformed-download,
timeout and concurrent-reset scenarios; actual Railway full-import/load/restart timing;
R13 fake-client action safety and untouched-record assertions after it is implemented.
Real model behavior cannot be validated by fake tests. It requires a separately
authorized, bounded manual check; automated tests always remain fake-only.

## Deployment update — 2026-10-09 11:58 Europe/Rome

New version deployed with `railway up` to the existing api/production service.
Deployment: `0f5c80e2-2b0e-49a8-beda-af7aac1b9406`.
Public `/health` returned HTTP 200 with `{"status":"ok","version":"2026-09","ui":{}}`.
The initial rollout exposed simultaneous worker catalog seeding; initialization now
uses a PostgreSQL transaction advisory lock. A concurrent-startup regression test was
added; the full suite passes 91 tests on both SQLite and PostgreSQL.
This supersedes earlier undeployed status notes. No reset, full Railway migration,
or model call was performed in this deployment verification.

## Field-level tolerance (2026-10-09)

The current user instruction supersedes the earlier fail-on-bad-value policy.
Unparseable dates, numeric values/notation, stages, websites, product codes and
flags become empty. Unknown ticket states/priorities and contact lifecycle values
are empty. Invalid emails are empty. Free text remains free text. Unknown activity
types are preserved as notes with `source_activity_type`; no history row is dropped.
Missing/duplicate source IDs receive deterministic file/row recovery identifiers.
Unknown product codes do not collapse into a fabricated BF-00000 product. Orphan
quote lines remain unassociated; lines pointing to explicitly deleted deals are
still excluded under the source rules.

An invalid explicit line price does not silently fall back to the price list.
An uncomputable line amount makes its deal total empty rather than publishing a
partial sum. Related 2025 revenue/class is empty when required inputs are invalid.
Storage creation/update timestamps remain required system metadata and use import
time when no valid source timestamp exists; business timestamps remain empty.

Diagnostics are persisted in `crm_metadata`, namespace `migration`, key `last`,
under `log`: total cases, counts by file/field/reason, and up to 50 row-number
samples. The same summary is written to the application logger. Raw input values
are not written to logs. Supported numeric input magnitude is bounded at 1e12
(after annualization) to avoid pathological arithmetic; larger values are logged
and empty. Arithmetic failures also produce empty derived amounts.

Missing/unreadable CSVs still abort atomically. Authentication, malformed request,
nonempty-account protection (409), download limits and infrastructure errors remain
errors: the importer never reports 204 for data that was not committed.

Verification: 99 tests passed on SQLite and on local PostgreSQL, with outbound
model/network clients blocked in tests. Added all-columns-garbage -> 204, bad values
after buffer flush, partial-total prevention, duplicate/missing IDs, unknown SKU,
numeric garbage containing digits, and unreadable CSV rollback cases. Full supplied
export: 539,204 objects and 1,393,960 directional associations; latest local SQLite
run 52.80 seconds (includes additional concurrent local work; excludes download).
This is local evidence, not a Railway full-import latency measurement or an
independent official expected-answer oracle.

Full-record comparison against the previous local PostgreSQL import found only
empty-class representation changes and four companies with originally missing deal
amounts. The latter exposed an over-broad conservative rule; corrected it to retain
R8 zero revenue for originally empty amounts. Only malformed inputs/failed derived
calculations invalidate revenue. Added a dedicated regression test. Recovery IDs
are internal lookup keys; `id_legacy` retains the original source ID, including
empty/duplicate source IDs, rather than inventing legacy identity.

Final verification: 101 tests passed on SQLite and PostgreSQL. Full-source rerun
43.50s locally, same object/association counts. Compared all 539,204 object property
maps with the prior full PostgreSQL import: no differences after normalizing
absent/empty values and excluding the newly preserved activity source-type field.
This checks regression, not correctness against an independent official oracle.

## Railway evidence and bulk-index optimization

The first real public migration request completed with HTTP 204 in 299.586s,
using a private SSH upload and a loopback HTTP source (not external WAN download).
This leaves effectively no safety margin against the competition's 300s limit.
The full database had 539,204 objects, 1,393,960 associations and 954 dormant-list
members; zero duplicate active contact emails. Public search totals matched all
10 migrated object types. Company pagination returned 17,734 unique IDs over 178
pages. 200 public record reads at concurrency 20: 200/200 HTTP 200, p95 0.159679s.

Performance correction: UI indexes are now scoped to their relevant object types.
During an exclusive PostgreSQL migration, non-unique object/association query
indexes are dropped transactionally and rebuilt before success; primary, foreign
key and unique constraints remain active. ANALYZE runs before the 204 response.
DDL rollback restores indexes if a source is unreadable. All 137 current tests
passed on SQLite and PostgreSQL before deploying this optimization. A fresh
Railway timing is required; do not present the local timing as the online timing.

### Final online verification (2026-10-09)

Tested deployment: `b8109d36-be1b-4de6-a42c-81de06e87662`.
- Optimized public `/__migrate`: **204 in 87.564s** (previously 299.586s).
  Source was the supplied archive, privately transferred, downloaded via loopback
  HTTP with a filename-independent URL/query string. External WAN source-download
  latency is not included in this transport setup.
- `/__reset`: 204 in 0.646s. Replayed only verification-created data after a fresh
  complete content-fingerprint match. Source future dates were preserved.
- 539,204 objects, 1,393,960 directional associations, 954 dormant-list memberships;
  no duplicate active contact emails. Public search totals match every imported type.
- Full company pagination: 178 pages, 17,734 unique records, no omissions/duplicates.
- After optimization and restart: 200/200 public reads succeeded at concurrency 20;
  p50 64.6ms, p95 **166.1ms**, max 210.1ms, no 5xx.
- Full object (including properties/timestamps), association and membership SHA256
  fingerprints survived both a redeploy and an actual API-process restart unchanged.
- 137 tests passed on both SQLite and PostgreSQL for the deployed snapshot. Source
  hashes are saved in `analysis/railway-tested-app-hashes.json`; detailed results
  are in `analysis/railway-live-verification.json`.
- Temporary remote archive/server and Railway SSH key were removed. No real model
  was called; ASSISTANT_LIVE_ENABLED remained false.

Other tasks subsequently changed local UI/login and assistant files. Those later
changes are not part of this tested deployment and must not inherit these results
without appropriate verification. This proves the measured scenarios, not an
official business-correctness percentage or complete API conformance.
# Final local integration gate — 2026-10-09

175 tests passed on both SQLite and PostgreSQL, including 12 new business fixtures.
The final pass fixed three issues: valid quote totals must still contribute to revenue
when the source deal-header amount is invalid; invalid latest contact lifecycle must
not erase an older valid lifecycle; user role/reporting-line fields must survive import.

A fresh isolated PostgreSQL import took 53.634s excluding network, producing 539,204
objects and 1,393,960 directional associations. Independent raw-CSV calculations matched
all 17,734 company revenues/classes, 64,212 contact-company link sets, 11,659 quote totals
and 954 dormant members. This validates those fields under documented interpretation
choices, not every field of the hidden evaluation export. The separate audit now explicitly
uses EUR for quote-line totals as R4 requires, irrespective of deal-header currency.

Reproduce with `python -m analysis.final_local_verification`, setting SOURCE_DIRECTORY
and a local TEST_DATABASE_URL. It creates and removes a random schema, touches no existing
database data and makes no network/model calls. Machine evidence is in
`analysis/final-local-full-verification.json` and `analysis/final-local-test-results.json`.
Current app/test hashes are in `analysis/final-local-tested-hashes.json`. This local
candidate has not been deployed in this pass; older online evidence below remains
specific to its recorded deployment.


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
