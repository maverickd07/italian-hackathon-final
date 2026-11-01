# Relay CRM — Final choice sheet

We prioritized preserving business evidence, resolving identities and making writes transactional. The nine-file migration is deterministic code; AI is used only by the chat assistant. All counts below describe the supplied export. Examples illustrate general rules and are not hard-coded.

## 1. What you found in the data that the requests didn't say

**Case: Company identity spans different websites**

- Where: `aziende.csv`, `sito_web`, `note`, `ultima_modifica`, `id_azienda`.
- Example fields copied from source: `360623;officinemose.com;PI: 34340014470;23/02/2016 05:57:00` and `729413;officinemose-srl.it;P. IVA: IT 34340014470;03/02/2015 04:21:00`. Both are Officine Mosè S.r.l.s. These are selected source fields in the order ID, website, notes, modification timestamp.
- Scale: 19,698 non-deleted company rows form 17,386 identities; 2,060 duplicate groups. 835 duplicate VAT groups span different domains.
- Discovery: independently normalized domains and VAT, built connected components and inspected conflicting fields. Matching by name alone would merge unrelated companies; matching by domain alone would split these identities. Our first parser missed the short `PI:` label: an independent recount disagreed with our import (17,734 versus 17,386 companies), and comparing the results exposed 2,136 active source rows with missed VAT labels. We fixed the parser, repeated the local full import, and subsequently confirmed 17,386 companies online after the official migration.

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
- Scale: the literal won-stage interpretation produces 935 dormant companies. Excluding credit-only wins would impose an additional positive-value condition not stated in the request.
- Discovery: calculate and compare both scenarios. This is a documented interpretation, not an official expected-answer claim.

## 2. How you handled it and why

**Case: Company identity spans different websites**

- **What the CRM does:** Normalize domains and 11-digit VAT, exclude deleted rows, then merge connected identities transitively by either key. Keep the latest source ID and latest valid nonempty value per field; redirect legacy references and preserve contributed domains. Recognize `PI:`, `P.I.`, `P. I.`, `P.IVA` and `partita iva`.
- **Why:** A tax identity can operate several websites. Conversely, matching only names would conflate unrelated businesses. A valid older field must survive an empty newer field.
- **Ruled out:** Domain-only merging, name-only merging and rejecting an 11-digit VAT solely on checksum. R7 specifies eleven digits; checksum is an audit check, not an additional acceptance condition.
- **Verified:** The abbreviated labels recover 2,136 active source rows. All 10,399 VAT-bearing active rows pass checksum; merging produces 17,386 companies, 9,032 with VAT. Independent source reconciliation and synthetic transitive merges pass. Database uniqueness and concurrent-collision tests cover subsequent writes; duplicate VAT writes return 409.

**Case: Contacts contain repairable identity fields and stale references**

- **What the CRM does:** Repair clear email/phone swaps, choose the first valid email and merge by normalized email. Validate references before selecting latest valid fields. Keep explicit company links; otherwise match an email domain to an existing company, including its additional domains, excluding common personal providers.
- **Why:** A malformed latest reference should not hide a usable older link. A missing email should not erase the person.
- **Ruled out:** Creating multiple people from one multi-email source row, guessing an address, replacing explicit company associations, or creating companies from personal email domains. First-valid-email remains a documented interpretation.
- **Verified:** Independent comparison of all 64,212 contact-company link sets; targeted swapped-field, duplicate and invalid-newest-reference fixtures. Active contact email uniqueness also holds under concurrent upserts.

**Case: Owner IDs can refer to a rehired employee**

- **What the CRM does:** Resolve exact IDs, unique normalized names and unambiguous initials to active users. Map an inactive ID to an active user only when the normalized full-name match is unique. Otherwise leave the current owner empty. Retain `ruolo` and `responsabile`; historical activity authors retain their original email.
- **Why:** Current responsibility must use active employees, while past authorship is historical evidence.
- **Ruled out:** Assigning every departed employee's work to their manager, fuzzy name matching, and silently rewriting historical authors.
- **Verified:** Six unique inactive-to-active matches affect 2,586 active deals and 1,535 tickets. Ownership and inactive-user fixtures cover the rule. Metadata preservation has regression coverage.

**Case: Current stage and history are different kinds of evidence**

- **What the CRM does:** Keep the current deal stage authoritative. Recover a missing terminal close date from the newest history entry matching that terminal stage. Parse observed civil formats and Excel serial dates. Preserve source clock values without timezone shifts.
- **Why:** The latest history row sometimes disagrees with the current record. A matching terminal event is stronger evidence for a missing terminal date than an arbitrary last event.
- **Ruled out:** Overwriting current stages from history, inventing close dates from modification dates, or assuming an undocumented timezone. Importing old wins/losses never triggers new kickoff/follow-up automations.
- **Verified:** All 2,656 missing terminal close dates have matching history. Boundary-date and automation-suppression fixtures pass; revenue/class calculations were independently reconciled.

**Case: Money has units, credits, quote fallbacks and line-level rounding**

- **What the CRM does:** Parse money with Decimal; annualize explicit monthly renewals. Merge active products by normalized SKU. Preserve orphan quote lines without an invented product link. Use a surviving product for missing price/description, normalize discounts, round each line half-up to cents and then sum. Valid EUR quote totals override header amounts. Preserve credits; compute 2025 company revenue using USD=0.92 EUR and GBP=1.17 EUR and the required A/B/C thresholds.
- **Why:** Units change the meaning of an amount, credits are legitimate negative revenue, and the quote lines provide a reproducible total. Rounding only the grand total would give different results.
- **Ruled out:** Dropping credits, resurrecting deleted products/deals, treating missing prices as zero or publishing a partial total when a required input is invalid. Invalid required inputs leave the dependent result empty.
- **Verified:** All 11,659 quoted-deal totals and all 17,386 company revenue/classes match a separate raw-CSV calculation. Total 2025 revenue is EUR 32,436,093.91. Fixtures cover fractional quantities/discounts, monthly units, missing inputs and valid quotes with malformed headers.

**Case: Incomplete links and contradictory history must not erase records**

- **What the CRM does:** Preserve containing records, omit invalid references and retain contradictory historical timestamps. Normalize known activity synonyms; retain unknown activity types as notes with the original type. Invalid fields become empty with persistent file/field/reason diagnostics in `migration:last.log`. Missing/duplicate IDs use deterministic recovery identities; preserve source identity in `id_legacy`.
- **Why:** A broken relationship is not evidence that the business event never happened. Repair should be traceable and should not invent facts.
- **Ruled out:** Dropping entire rows, guessing ticket contacts from sender text, rewriting closure dates, or collapsing unrelated unknown SKUs. Unreadable/missing required source files still fail the whole migration transaction.
- **Verified:** Synthetic corrupt-field, orphan, unknown-type, recovery-ID and rollback cases pass. Full migration preserves 538,856 objects and 1,393,960 directional association rows for this export.

**Case: Credit-only wins affect the dormant list**

- **What the CRM does:** Include companies with at least one Vinta/Rinnovato in any year and no 2025 activity through their contacts or deals, using merged company identities. Create the static `Clienti dormienti` list.
- **Why:** The request specifies a won-stage condition, not a minimum positive amount.
- **Ruled out:** An extra exclusion for credit-only wins. It would remove companies without an explicit requirement; we disclose the ambiguity instead.
- **Verified:** All 935 members match the independent calculation. A regression case checks that activity on a merged duplicate company prevents dormant membership.

## 3. What you didn't do

- **API coverage:** Object CRUD/batches/upsert/search, associations and supported catalog/list reads are implemented on both URL families. General property/pipeline/list mutation, general imports/exports and some association-schema surfaces remain incomplete. We prioritized migration correctness, shared business rules and transactional writes over full breadth. We do not claim full API conformity.
- **Unresolved interpretations:** First-valid-email selection, unique rehire/name matching, civil timestamps and credit-only dormant membership are explicit choices. Personal-domain exclusions are not exhaustive. Contradictory dates and orphan events remain visible; sender-text ticket links are not inferred.
- **Assistant CSV fix:** Manual real-model tests found a `KeyError` on CSV price updates: the model returned flat tool arguments where the router expected an `args` envelope; no partial write occurred. Commit `f2df2f8` accepts flat and wrapped arguments and rejects malformed or mixed formats. Both full suites passed 218 tests. Deployed before 15:10; the official Form check re-run at 15:07 passed 6/6 (10/10 examples, migration 81.06 s), and a real-model CSV retest passed for both a valid update and a mixed batch with no partial write. CSV operations are limited to 200 rows per atomic operation.
- **Repeat requests:** Won/lost automation uses persistent once-per-deal markers. General create requests have no request-level idempotency key, so repeated natural-language creates are not guaranteed to deduplicate.
- **Verification boundary:** Final application commit `f2df2f8`, deployment `fa1d5842-3e75-4ff8-8eb0-dea915f1b5db`. The official check started at 15:07 Europe/Rome and passed 6/6, with 10/10 examples, public-export migration in 81.06 seconds and an assistant reply within 60 seconds. The final release passed 218 self-authored tests on each of SQLite and PostgreSQL; automated AI tests use fake clients. These checks are not hidden business scores or proof of full API conformity. Full independent field reconciliation was local; online counts after the earlier official migration confirmed 17,386 companies, 64,212 contacts, 33,577 deals and 21,329 tickets. The CSV fix did not change migration code.
- **With one more hour, in order:** Extend the highest-value missing versioned API operations; broaden adversarial unknown-export and manual assistant intent coverage within the model budget; refine refusal wording. In the mixed CSV retest, the assistant correctly made no changes but unnecessarily offered to create the missing SKU despite the instruction not to create products.

## 4. The assistant

- **What it can do:** Search/read CRM records and associations, compute complete SQL aggregates, answer ownership-based customer questions, create/update/associate records and calculate relative dates. CSV inspection and atomic updates support up to 200 rows per operation. Replies and mutation receipts are Italian; the UI is English.
- **How it works:** Every turn supplies full `messages`, `context.now`, active `context.user` and any text CSV attachments; no server-side conversation memory is assumed. The required OpenRouter `openai/gpt-6-luna` selects tools, with no fallback model. Tools call the same store/search and business rules as REST. Migration never uses a model. Real assistant calls are enabled for evaluation.
- **When it asks or refuses:** Ambiguous/missing targets, inactive owners, invalid stages, stale values and invalid CSV batches need clarification or rejection. Every assistant write validates property names against the object catalog. This was added after a real model invented `vat_number`; the valid field is `partita_iva`. The corrected duplicate-VAT retest refused creation and left the existing company unchanged.
- **How it avoids damage:** Read affected records and fields first, use locks and stale-value checks, then commit one transaction containing both requested changes and generated automation records/markers. Any failure rolls the transaction back. Re-read results before commit and return a deterministic Italian receipt; no later model step performs more writes. No database transaction remains open while waiting for the model. Relative dates use `context.now`; lost follow-ups are exactly 180 days later.
- **Business automation:** After migration, entering Vinta in the sales pipeline, including direct creation there, creates one open Assistenza kickoff ticket, assigned to the deal owner and linked to the deal and its companies. Entering Persa creates one linked NOT_STARTED follow-up task due exactly 180 days later. Persistent markers prevent repeats even after leaving and re-entering a stage; imported history does not trigger them. Domain association uses the same rules through UI, assistant and REST.
- **Observed acceptance:** Manual real-model checks covered revenue/class, ambiguous-deal clarification, precise won-deal writes, duplicate-VAT refusal after the catalog fix, four concurrent revenue questions, unknown-field rejection and a lost follow-up at exactly +180 days without duplication on repeat. After the router fix, real-model CSV tests verified a price update from 10.00 to 12.34 and complete refusal of a mixed existing/missing-SKU batch; the marked test product was then archived. Automated fake-client tests cover rollback, concurrency and browser-to-assistant-to-database integration. These bounded scenarios do not establish general language accuracy.

## Where to look

- **CRM:** https://api-production-bb05d.up.railway.app/ — sign in at `/login` with the organizer token, entered privately.
- **Company example:** https://api-production-bb05d.up.railway.app/companies/1 — an example for the supplied export; record IDs can change with a different migration.
- **Deals board:** https://api-production-bb05d.up.railway.app/deals
- **Dormant customers:** https://api-production-bb05d.up.railway.app/dormant-customers
- **Tickets:** https://api-production-bb05d.up.railway.app/tickets
- **Authentication:** Official APIs require Bearer authentication; browser sessions do not authenticate them. Browser writes require a session plus CSRF validation. The employee selector supplies business context, not employee login.
- **Measured reliability:** On the earlier catalog release `689cfda` after official migration, 3,000 single-record reads at concurrency 20 had p95 139.3ms; 1,000 at concurrency 40 had p95 383.4ms. All 5,600 requests including warmup and mixed reads succeeded, with exact company pagination. Full fingerprint preservation across process restart was separately verified on the earlier integrated release; those historical load/restart measurements were not repeated on final commit `f2df2f8`.
- **Repository:** No public repository URL is configured. Source audits, tests and release-specific evidence are retained locally: `analysis/vat-full-verification.json`, `analysis/vat-source-audit.json`, `analysis/post-form-strength.json`, `analysis/post-form-manual-robustness.json`, `analysis/csv-envelope-release.json`, `analysis/csv-form-check-result.json` and `analysis/csv-live-reacceptance.json`.
