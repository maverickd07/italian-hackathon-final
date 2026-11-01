# Relay CRM — choice sheet draft

Prepared from the supplied nine-file export and official requirements. Counts describe this export, not the hidden evaluation export. Rules are deterministic and do not hard-code these examples. This draft is for the platform's Choices field (limit 20,000 characters).

## 1. What you found in the data that the requests didn't say

**Case: Company identity spans different websites**

- Where: `aziende.csv`, `sito_web`, `note`, `ultima_modifica`, `id_azienda`.
- Example fields copied from source: `254208;DELLAVALLEAUTOMAZIONEGROUP.IT;p.iva IT95675678528;14/09/2020 15:11:00` and `180310;dellavalleautomazione.eu;P.IVA 95675678528;04/11/2019 04:36:00`. Both are Della Valle Automazione S.r.l.
- Scale: 19,698 non-deleted company rows form 17,386 identities; 2,060 duplicate groups. 835 duplicate VAT groups span different domains.
- Discovery: independently normalized domains and VAT, built connected components and inspected conflicting fields. Matching by name alone would merge unrelated companies; matching by domain alone would split these identities.

**Case: Contacts contain repairable identity fields and stale references**

- Where: `contatti.csv`, `email`, `telefono`, `id_azienda`, `ultima_modifica`.
- Example: contact `1629112` has `gallo.enrico@fratellinegri89.it e enrico.gallo@hotmail.it` in its email field, company `711883`. Other raw values include `n.d.`, `da chiedere`, `NO EMAIL` and incomplete addresses.
- Scale: 125 email/phone swaps, 111 multiple-email rows, 3,296 nonempty invalid email fields; 269 duplicate groups have an invalid newest company reference but an older valid one. 70,589 non-deleted rows become 64,212 people; domain matching adds 2,955 links after merging.
- Discovery: parse candidate addresses, compare the phone column, group normalized email, and validate references against surviving company IDs before merging.

**Case: Owner IDs can refer to a rehired employee**

- Where: `utenti.csv` identity, activity flag and reporting fields; deal/ticket owner IDs.
- Example: `U22;Niccolò;Bassi;niccolo.bassi@brambillaforniture.it;Commerciale;U03;NO` and `U84;Niccolò;Bassi;n.bassi@brambillaforniture.it;Commerciale;U02;s`.
- Scale: 6 unique inactive-to-active full-name matches, affecting 2,586 active deals and 1,535 tickets. There are 85 source users, 65 active.
- Discovery: compare normalized full names across inactive and active IDs, then count referenced source owners. Some other owner fields contain names or initials instead of IDs.

**Case: Current stage and history are different kinds of evidence**

- Where: `opportunita.csv`, `fase`, `data_chiusura`; `storico_fasi.csv`, `fase_nuova`, `data_cambio`.
- Example: opportunity `81511329` has phase `07` and an empty close date. Its matching history row is `81511329;05 - Contratto;Persa;20/11/2019 13:15:28;U38`.
- Scale: 2,656 active closed deals lack a close date; all have matching terminal-stage history. 3,259 active deals have a current stage different from their latest history entry. The export also contains 2,330 Excel-serial close dates.
- Discovery: join history by source deal ID and compare both its most recent event and its most recent event matching the current stage.

**Case: Money has units, credits, quote fallbacks and line-level rounding**

- Where: `opportunita.csv` amount/currency/pipeline; `righe_offerta.csv` quantity/price/discount/SKU; `listino.csv`.
- Examples: opportunity `17577703` has amount `51.315,91 mensili`, currency `Euro`, pipeline `RINNOVI`, stage `RINNOVATO`. Quote line `2112705146` for deal `60920941` has SKU `60141`, quantity `5`, empty unit price and discount `25 %`.
- Scale: 810 active monthly renewal amounts and 980 active negative credit notes. Surviving lines include 2,640 missing prices, 5,736 missing descriptions, 6,725 fractional discounts and 2,527 fractional quantities. 858 reference absent SKUs; 1,222 reference deleted-only products. 1,722 lines belong to deleted deals.
- Discovery: audit notation patterns, join surviving product versions and recompute line totals independently with Decimal arithmetic.

**Case: Incomplete links and contradictory history must not erase records**

- Where: activity contact/deal/author fields; ticket references and timestamps.
- Example: ticket `981012` has `aperto_il=2020-03-10 17:24:40`, `chiuso_il=2020-03-08 09:32:49`, empty contact ID and company `906569`. Its description starts `Da: cinzia.pagani@outlook.it`.
- Scale: 17,656 surviving activities lack both a valid contact and a valid deal; 84,416 retain inactive historical authors. 161 tickets close before opening. Text-based sender matching could suggest 456 otherwise missing contact links.
- Discovery: validate explicit foreign references separately from record validity; compare timestamps without rewriting the source.

**Case: Credit-only wins affect the dormant list**

- Where: won deal stages, company identity links and 2025 activity paths through contacts/deals.
- Scale: the literal won-stage interpretation produces 935 dormant companies. Adding an exclusion for credit-only wins produces 792, a difference of 143.
- Discovery: calculate and compare both scenarios. This is a documented interpretation, not an official expected-answer claim.

## 2. How you handled it and why

**Company identity spans different websites**

Normalize websites and 11-digit VAT; merge transitively by either identity. Recognize `PI:`, `P.I.` and `P. I.` as well as `P.IVA`/`partita iva`. The fix recovers 2,136 active source rows previously missed; 9,032 merged companies have VAT. R7 specifies 11 digits, so checksum is audited rather than a rejection rule; all 10,399 VAT-bearing active source rows pass it. Exclude deleted source rows first. Keep the latest source ID, select the latest valid nonempty value per field, preserve contributed domains and redirect all merged legacy references. Never merge by company name alone. VAT uniqueness is enforced transactionally by the database and duplicate writes return 409. Verified with synthetic transitive-merge cases, concurrent collisions and the full 17,386-company local reconciliation.

**Contacts contain repairable identity fields and stale references**

Repair clear email/phone swaps; extract the first valid address and merge by normalized email. Invalid references become empty before field-level merging, so an invalid newest reference cannot suppress an older valid one. Missing identity does not cause a containing row to disappear. Preserve existing explicit company associations. An unassociated email domain can link only to an existing company, including additional domains; common personal-email providers are excluded. Verified all 64,212 contact-company link sets independently. First-valid-email selection is an interpretation; we do not claim it is the only possible policy.

**Owner IDs can refer to a rehired employee**

Resolve exact IDs, unique normalized full names and unambiguous initials to active users. An inactive ID can map to one uniquely matching active full name. Otherwise leave the current owner empty; do not guess the manager. Historical activity authors preserve their original email. Keep `ruolo` and `responsabile` for business context. This follows the active-owner rule while preserving authorship evidence. Synthetic ownership, inactive-user rejection and source audits cover the behavior.

**Current stage and history are different kinds of evidence**

Keep the current stage authoritative. Fill a missing terminal close date from the newest history entry matching that terminal stage, not from an arbitrary last event. Parse observed civil formats and Excel serials. Source timezone is unspecified: retain civil date/clock values without shifting them. Verified date boundaries, year/class calculations and all source missing-close-date recoveries. Imported history never triggers won/lost automations.

**Money has units, credits, quote fallbacks and line-level rounding**

Parse observed separators, signs, multipliers and monthly renewal units deterministically. Annualize explicit monthly renewal values. Merge active products by normalized SKU. Keep a surviving line even when its product is absent/deleted, with no invented product association; use a surviving product only for missing price/description. Normalize percentage/fractional discounts, round each line half-up to cents, then sum. Quote totals in EUR override header amounts. Do not resurrect deleted deals/products. Preserve credits; calculate company 2025 revenue with USD=0.92 EUR and GBP=1.17 EUR, round the company sum and apply the exact A/B/C thresholds. A bad required input yields an empty dependent total, never a partial amount. Verified all 11,659 quoted-deal totals and every company's revenue/class against an independent raw-CSV calculation: total EUR 32,436,093.91 for this source.

**Incomplete links and contradictory history must not erase records**

Retain the containing record, omit invalid references and preserve contradictory historical dates. Do not infer ticket relationships from sender text. Normalize known activity synonyms; unknown types are retained as notes with their original type. Invalid fields become empty with persistent file/field/reason diagnostics in `migration:last.log`; unknown/missing IDs get deterministic internal recovery identities while `id_legacy` preserves source identity. Unknown SKUs do not merge unrelated products. Unreadable/missing source files still fail the entire transaction. These choices preserve evidence without inventing facts; synthetic corrupt-field, orphan, rollback and recovery-ID cases exercise them.

**Credit-only wins affect the dormant list**

Use the stated stage criterion: at least one Vinta/Rinnovato in any year and no 2025 activity through company contacts or deals. Do not silently add a positive-value or credit-only exclusion. The resulting static `Clienti dormienti` list contains 935 members, individually reconciled to the independent audit. This ambiguity remains explicit for the jury.

## 3. What you didn't do

- Full API conformity is incomplete. Object CRUD/batches/upsert/search, associations and supported catalog/list reads exist on both URL families, but general property/pipeline/list mutation, general imports/exports and some association-schema surfaces are missing. The default catalog is a subset.
- R1–R12 and deterministic assistant tools have self-authored tests, not an official score. The hidden export can expose new cases. Personal-domain exclusions and owner/name/timezone interpretations are not exhaustive.
- Authorized manual acceptance with the official model covered revenue/class, ambiguous-deal clarification, a precise won-deal update and duplicate-VAT refusal. The initial duplicate-VAT case exposed an invented `vat_number` field. The erroneous test company was archived; assistant-only catalog validation now rejects unknown fields before any batch write, and the prompt specifies `partita_iva`. After 211 fake-only tests passed on each database, commit `689cfda` was deployed once. The real-model duplicate-VAT retest correctly refused, with no company created and the existing record unchanged. Real assistant calls remain enabled for evaluation. These few scenarios do not establish general language accuracy.
- Additional live robustness testing exposed a CSV limitation: both a valid one-row canonical-SKU price update and a mixed existing/missing-SKU batch returned a generic error; application logs recorded `KeyError`. Neither partially updated the target product. The root cause was subsequently reproduced: the provider returned flat tool arguments while the router required an `args` envelope. Assistant-only commit `f2df2f8` accepts both validated shapes and rejects malformed arguments. All 218 fake-only tests pass on both SQLite and PostgreSQL, including decimal CSV updates and missing-SKU atomicity; deployed successfully before 15:10. Post-deploy real-model re-acceptance passed: one-row decimal price update in 3.361s; missing-SKU batch refused in 2.826s with the existing product unchanged and no new product. The marked fixture was archived. Assistant CSV updates are limited to 200 rows per atomic operation. Repeated creates have no automatic request-level idempotency because the contract supplies no request key. Won/lost automation itself is persistently once-per-deal.
- The official Form check ran once on the final assistant-catalog release and passed all six checks, including 10/10 example tests and a public-export migration in 81.84 seconds. Post-check counts are 17,386 companies, 64,212 contacts, 33,577 deals and 21,329 tickets. This replaces the old production dataset; the earlier absence of imported role/reporting-line fields described the previous import. Full field-level and durability evidence remains version-specific: the check is not the hidden business score.
- With another hour: prioritize remaining high-value versioned API operations and adversarial unknown-export cases; broaden manual assistant intent coverage within the evaluation budget.

## 4. The assistant

- Capabilities: CRM search/read/associations, complete SQL aggregates, ownership-based customer questions, create/update/associate operations, CSV product/record updates and relative-date calculations. Replies and mutation receipts are Italian; the interface is English.
- Mechanics: stateless full `messages`, `context.now`, active `context.user` and text CSV attachments per request. Fixed official OpenRouter model, no fallback. It calls the same `app.store` and `app.search` rules as REST, including VAT uniqueness, domain association and won/lost automation.
- Clarify/refuse: ambiguous or absent records, inactive owners, invalid stages, stale read values and invalid CSV batches. Unknown property names are rejected against the object property catalog before any assistant batch write, with valid names reported in the error. Interpretation of ambiguity and intent still depends on the model; deterministic checks provide additional boundaries.
- Damage prevention: fresh reads of affected records/fields, locks and stale-value checks; a single mutation transaction; rollback includes generated tickets/tasks and their once-only markers. Re-read results before commit, then emit deterministic Italian receipts. No later model step can make additional writes. `context.now` controls dates; lost-deal tasks use exactly 180 days. No database transaction spans model latency.
- Evidence: 36 fake-model assistant cases across SQLite and PostgreSQL, including 40 conversations with four concurrent, plus browser-to-assistant-to-database integration. These overlap with the 175-test baseline and must not be added as separate totals. Automated tests remain fake-only. A separate authorized four-scenario manual run used the official model; three passed initially, and the duplicate-VAT defect was corrected and its single retest passed. See `analysis/manual-model-acceptance.json`.

## VAT verification update — local, 2026-10-09

The VAT-corrected full import completed in 57.541 seconds excluding network, in disposable local PostgreSQL. All 17,386 company revenue/classes, 64,212 contact-company link sets, 11,659 quote totals and 935 dormant members match the corrected independent raw-source audit. Revenue remains EUR 32,436,093.91. This correction was deployed at 14:30 and subsequently exercised by the official platform migration, which refreshed production and confirmed 17,386 companies. The full independent field-level reconciliation above was local; the official check is separate evidence. Evidence: `analysis/vat-full-verification.json` and `analysis/vat-source-audit.json`.

## Where to look

- Verified delivery evidence: deployment `feec912b-c7b0-40e5-8648-3eaa217bc17e` passed health/version, bearer authentication and browser login checks after an actual API-process restart. With 20 concurrent readers, all 200 measured requests returned 200; p95 was 129.9 ms. Complete object, association and list-member fingerprints were identical before and after restart. The HTTPS reverse-proxy login issue was fixed while retaining session/CSRF checks. These are measured checks, not an official durability score or a fresh full-import benchmark. Evidence is retained in `analysis/final-postrestart-http.json`, `analysis/final-before-restart-data.json`, `analysis/final-after-restart-data.json` and `analysis/final-proxy-fix.json`.
- CRM: https://api-production-bb05d.up.railway.app/ (redirects to `/login`; enter the organizer CRM token privately).
- Company example: https://api-production-bb05d.up.railway.app/companies/1 (current supplied export only; IDs may change after evaluation migration).
- Deals: https://api-production-bb05d.up.railway.app/deals
- Dormant companies: https://api-production-bb05d.up.railway.app/dormant-customers
- Tickets: https://api-production-bb05d.up.railway.app/tickets
- Official APIs require Bearer authentication; browser cookies never authenticate them. Browser writes require both a session and CSRF validation. The identity selector is business context, not employee authentication.
- No public repository URL is configured. Source and detailed verification reports are retained in the project repository.


## Official checks — 2026-10-09, Europe/Rome

Previous checked application commit `689cfda`, deployment `6edbcc40-33ed-4389-b612-447d6cefb653`. Latest assistant-only CSV argument fix: commit `f2df2f8`, deployment `fa1d5842-3e75-4ff8-8eb0-dea915f1b5db`, health 200 and live assistant enabled. Its official check started at 15:07: 6/6 PASS, examples 10/10, migration 81.06s, no failed checks. CSV live re-acceptance also passed both scenarios; the fixture was archived. Evidence: `analysis/csv-envelope-release.json`, `analysis/csv-form-check-result.json`, `analysis/csv-live-reacceptance.json`.
The official platform check started at 14:48 and completed with 6/6 passing:
health/version; token accepted and absent token rejected; reset 204; migration
of the public export in 81.84 seconds; example tests 10/10; and assistant sample
within 60 seconds. No failed checks. This is a form/contract check, not a hidden
business score. Real assistant remains enabled with the required model.
The official reset/migration replaced the earlier dataset and removed the manual
acceptance mutations. Supporting evidence: `analysis/official-form-check-result.json`,
`analysis/assistant-catalog-release.json`, `analysis/manual-model-acceptance.json`.


## Additional final-version robustness evidence

After the official migration, bounded read-only load completed 100 warmup requests,
3,000 single-record reads at concurrency 20 (p95 139.3ms), 1,000 at concurrency 40
(p95 383.4ms), and 1,500 mixed reads at concurrency 20, all successful. Complete
company pagination returned 17,386 distinct records; counts and sampled records
were unchanged. Four concurrent real-model company questions returned the correct
revenue/class without cross-talk. A mixed valid/unknown-field request changed
nothing. A marked disposable deal generated one lost-deal task at exactly
context.now + 180 days; repeating the request generated no second task.
All four disposable objects (including the generated task) were archived, restoring
the original active counts. Two canonical-SKU CSV calls failed as disclosed above;
an earlier noncanonical-SKU fixture was invalid and is excluded from acceptance.
No code/configuration changes or additional official check occurred in this pass.
Evidence: `analysis/post-form-strength.json`, `analysis/post-form-manual-robustness.json`.
