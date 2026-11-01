# R1–R13 acceptance tracking

Client authority: `starter-v9/legacy/RICHIESTE.md`, with `BRIEF.md` for the evaluation
contract. This is an implementation and evidence checklist, not a claim of official scores.
Final local gate: 175 tests pass on SQLite and PostgreSQL, plus a fresh full-source
PostgreSQL import with record-level checks against the independent CSV audit.
The current local candidate has NOT been deployed in this pass. Earlier deployment
`b8109d36-be1b-4de6-a42c-81de06e87662` has separate online migration/restart/read-load
evidence in `analysis/railway-live-verification.json`. Historical notes below do not
supersede the final gate or imply that current local files are already deployed.

| Requirement | Current implementation | Evidence / remaining limits |
|---|---|---|
| R1 Companies | Domain/VAT union, latest valid field values, additional domains | Full import 17,734; synthetic merged-field tests |
| R2 People | Clean/merge email, preserve source ID, redirect aliases | Full import 64,212; multiple-email choice remains an interpretation |
| R3 Deals | Amount/currency, pipelines/stages, active ownership, dates and associations | Full import 33,577; rehire and initials interpretation documented |
| R4 Products/lines | SKU merge, price fallback, Decimal per-line rounding, product references | 1,735 products / 41,014 lines; product link uses hs_product_id |
| R5 Support | Assistenza pipeline, state/priority/owner, explicit references | 21,329 tickets; historical timestamp contradictions preserved |
| R6 History | Four activity object types, text/date/author, surviving links | 359,603 activities including orphans |
| R7 VAT | Unique reservations in the database; conflict returns 409 | Parallel creation and failed-update rollback tested |
| R8 Revenue | Won 2025 totals, negative credits, fixed FX, class | 32,436,093.91 EUR reconciles to independent analysis |
| R9 Dormant | Won stage in any year, no 2025 activity through company contacts/deals | 954 under documented stage-only interpretation |
| R10 Won deal | One Assistenza/Aperto ticket, exact subject, owner and all company links | Direct create, patch, batch, concurrency, rollback, restart tested |
| R11 Lost deal | One NOT_STARTED task, exact subject, due exactly 180 days after entry | Re-entry, direct creation and due-date arithmetic tested |
| R12 Domain link | Link an unassociated contact to an existing company/domain alias | Import/live writes; explicit company link is preserved |
| R13 Assistant | Implemented with transactional tools and Italian replies; live calls disabled | Fake-model integration, rollback, isolation, 40 conversations at four concurrent; actual model understanding/latency remain untested |

R10/R11 run only after successful migration, on entry into the relevant default sales
stage. Unrelated edits to imported won/lost deals do not trigger actions. Migration uses
a separate bulk writer and cannot trigger live automations. Marker claims, generated
records, and associations commit together. Persistent claims survive restart, stage
re-entry and archive of the generated record. A transaction rollback removes the claim
and generated records together. Assistant execution supplies context_now in the
transaction; fake-model integration tests cover this path.

Remaining gates: upload the integrated tested candidate, verify that deployment's
public health/authentication and browser session flow, and separately obtain permission
before any real-model use. Email upsert, English browser UI/session authentication and
fake assistant operations now have local coverage. Property/pipeline/list writes and
imports/exports remain incomplete; passing tests do not establish full upstream conformity.
Keep migration interpretation limits from MIGRATION.md visible in the final choice sheet.

## Final local pass — 2026-10-09

- Fixed valid quote totals being incorrectly invalidated in R8 by malformed header
  amounts; quote EUR totals remain authoritative under R3/R4.
- Normalize contact lifecycle before duplicate-field merging, retaining an older
  valid lifecycle when the newest value cannot be parsed.
- Preserve utenti.csv role/reporting-line columns (`ruolo`, `responsabile`).
- Added 12 business cases with literal expected answers: transitive company merging,
  reference redirection, FX/year boundaries/credits/rounding, dormant year edges,
  reset/remigration/uniqueness, and the three regressions above.
- Independently matched all 17,734 company revenues/classes, 64,212 contact-company
  link sets, 11,659 quoted-deal totals and 954 dormant members. Full import: 539,204
  objects / 1,393,960 associations, 53.634s locally, excluding network. Temporary
  PostgreSQL schema removed after verification.
- 175/175 tests on each database, Ruff clean, four browser JavaScript files parse.
  Candidate source hashes were unchanged during both final regression suites.
- Evidence: `analysis/final-local-test-results.json`,
  `analysis/final-local-full-verification.json`, `analysis/final-local-tested-hashes.json`.
  These are self-authored checks under documented migration interpretations, not
  official hidden-export results or a measured competition score. No real model calls.

Robustness update: 90 tests passed on SQLite and PostgreSQL. Input-order invariance,
R8 boundary classes, distinct companies sharing a name, deleted-product quote lines,
and freemail-provider counterexamples are covered. The freemail counterexample exposed
and fixed a shared import/live R12 gap. This does not complete all robustness gates;
see MIGRATION.md for outstanding adversarial and deployment checks.

## Deployment update — 2026-10-09 11:58 Europe/Rome

New version deployed with `railway up` to the existing api/production service.
Deployment: `0f5c80e2-2b0e-49a8-beda-af7aac1b9406`.
Public `/health` returned HTTP 200 with `{"status":"ok","version":"2026-09","ui":{}}`.
The initial rollout exposed simultaneous worker catalog seeding; initialization now
uses a PostgreSQL transaction advisory lock. A concurrent-startup regression test was
added; the full suite passes 91 tests on both SQLite and PostgreSQL.
This supersedes earlier undeployed status notes. No reset, full Railway migration,
or model call was performed in this deployment verification.


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
