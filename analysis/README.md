# Independent Sinergia source audit

Read-only audit of `/Users/danielweiyuchen/Desktop/sinergia-export`, checked against
`/Users/danielweiyuchen/Desktop/starter-v9/legacy/RICHIESTE.md` and `FAQ.md`.
No network, model, production database, deployment, or source-file writes.
Run `python3 analysis/audit_sinergia.py SOURCE_DIRECTORY analysis/sinergia-audit.json`.
The JSON records source SHA-256 hashes and all counts. Counts describe this snapshot;
never hard-code them as migration rules or hidden evaluation expectations.

## Populations

| Source | Raw rows | Non-deleted rows | Derived candidate objects |
|---|---:|---:|---:|
| aziende | 20,497 | 19,698 | 17,734 after domain/VAT union |
| contatti | 73,391 | 70,589 | 64,212 under first-valid-email policy |
| opportunita | 35,020 | 33,577 | 33,577 |
| listino | 1,922 | 1,852 | 1,735 normalized SKUs |
| righe_offerta | 42,736 | 42,736 | 41,014 with a surviving deal |
| ticket | 22,000 | 21,329 | 21,329 |
| attivita | 370,316 | 359,603 | 359,603 |
| storico_fasi | 110,706 | 110,706 | Supporting history |
| utenti | 85 | 85 | 65 currently employed; all retained as lookup data |

Total raw rows: 676,673. CSV parsing found no malformed row shapes.

## Migration decisions supported by the audit

- Company deduplication needs transitive union by normalized domain and VAT.
  540 duplicated VAT groups span multiple domains. Preserve additional domains.
- Contact source has 125 email/phone swaps, 111 multiple-email rows, and 3,296
  nonempty invalid email fields. First-valid-email selection is provisional.
  In 269 duplicate groups the latest company reference is invalid but an older one
  is valid: normalize references before selecting the latest populated field.
- Under the stated contact policy, domain association adds 2,955 company links.
- There are 6 apparent rehires matched by normalized full name; 2,586 active deals
  reference their old user IDs. Identity matching needs explicit migration logic.
  Other inactive users must not own current deals/tickets; historical authors stay.
- 2,656 active closed deals lack close dates. Every one has a stage-history entry
  matching its current terminal stage. There are 2,330 Excel-serial close dates in
  the full source. Current stage differs from latest history on 3,259 active deals;
  do not blindly replace the current stage with the final history row.
- 810 active renewal amounts are monthly. 980 active credit notes are negative.
- Decimal arithmetic, fractional-discount normalization and per-line cent rounding
  produce exact agreement for all 11,659 surviving deals with quote lines.
  This does not reproduce the earlier reported rounding discrepancy in this population.
- 1,722 lines belong to deleted deals and are excluded. Of surviving lines, 2,640
  need price fallback, 5,736 lack descriptions, 858 reference absent SKUs and 1,222
  reference deleted-only products. Keep surviving lines; missing product references
  must not revive deleted products. Audit arithmetic has zero unresolved line errors.
- 17,656 surviving activities have neither a valid contact nor a valid deal;
  keep the activity and omit invalid links. 84,416 reference inactive historical authors.
- Tickets include 161 closing dates before opening dates. Preserve source evidence;
  do not invent replacement dates. Sender-email matching could link 456 tickets with
  missing contact references, but R5 specifies the references in the ticket: do not
  infer those links without stronger evidence.
- Encoding markers occur in company/contact/ticket text. JSON reports strict
  whole-field repair candidates separately from cases requiring segment inspection;
  marker detection alone is not authorization to rewrite every matching string.

## Derived results are scenarios, not an oracle

With the script's documented assumptions, stage-based R9 yields 954 companies;
excluding credit-only wins yields 803, a difference of 151. R9 does not explicitly
state this exclusion. Do not silently add it based on the previous Claude report.
R8 totals/classes are also recorded as scenario results, pending full migration
normalization and identity validation. The first-valid-email policy is not proven
by an official expected result. This script is an audit, not a production importer.

## Operational implications

Import raw staging rows, normalize, resolve identities/aliases, create objects and
associations, then calculate R8/R9. Keep source IDs in `id_legacy`. Do not trigger
R10/R11 on historical import. R11 is 180 days, not calendar-month arithmetic.
Benchmark the eventual importer separately against the five-minute Railway limit.
The official form check resets data, migrates, and calls the model; it must not run
without the user's explicit permission to use the model key.
