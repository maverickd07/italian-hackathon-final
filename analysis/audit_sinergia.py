"""Independent, read-only source audit. No network, database, or model calls.

Run with bundled Python: audit_sinergia.py SOURCE_DIRECTORY OUTPUT_JSON
Counts refer to this source snapshot, never migration constants.
"""
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlsplit


def text(value):
    return (value or "").strip()


def norm(value):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", text(value).lower())
                            if not unicodedata.combining(c)).split())


def deleted(row):
    return norm(row.get("cancellato")) in {"s", "si", "1"}


def date(value):
    value = text(value)
    if not value:
        return None
    if re.fullmatch(r"\d{5}(?:[.,]\d+)?", value):
        return datetime(1899, 12, 30) + timedelta(days=float(value.replace(",", ".")))
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
                "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(f"Unparsed date {value!r}")


def number(value, annual=False):
    value = norm(value)
    if not value:
        return None
    negative = "-" in value or ("(" in value and ")" in value)
    monthly = any(x in value for x in ("mese", "mensil"))
    multiplier = Decimal(1)
    if re.search(r"mln\b|milion[ei]\b", value):
        multiplier = Decimal(1000000)
    elif re.search(r"k\b|mila\b", value):
        multiplier = Decimal(1000)
    match = re.search(r"\d[\d.,\s]*", value)
    if not match:
        raise ValueError(f"Unparsed number {value!r}")
    token = re.sub(r"\s+", "", match[0]).rstrip(".,")
    if "," in token and "." in token:
        decimal_sep = "," if token.rfind(",") > token.rfind(".") else "."
        token = token.replace("." if decimal_sep == "," else ",", "").replace(decimal_sep, ".")
    elif "," in token or "." in token:
        sep = "," if "," in token else "."
        parts = token.split(sep)
        if len(parts[-1]) == 3 and all(len(part) == 3 for part in parts[1:]):
            token = "".join(parts)
        else:
            token = "".join(parts[:-1]) + "." + parts[-1]
    result = Decimal(token) * multiplier * (-1 if negative else 1)
    return result * 12 if annual and monthly else result


def domain(value):
    value = text(value).lower()
    if not value:
        return ""
    host = urlsplit(value if "://" in value else "//" + value).hostname or ""
    return host.removeprefix("www.").rstrip(".")


def vat(value):
    # Independent extraction: inspect the label before each numeric candidate,
    # rather than reusing the application's marker-and-number regex.
    found = []
    for match in re.finditer(r"[0-9](?:\s*[0-9])*", value):
        digits = "".join(match[0].split())
        if len(digits) != 11 or (match.end() < len(value) and value[match.end()].isalnum()):
            continue
        prefix = value[:match.start()].rstrip()
        prefix = re.sub(r"(?i)IT$", "", prefix).rstrip(" :=-.")
        label = re.search(r"(?i)(?<!\w)(?:partita\s*iva|p[.\s]*i(?:[.\s]*v[.\s]*a)?)$", prefix)
        if label:
            found.append(digits)
    return list(dict.fromkeys(found))


def emails(value):
    value = re.sub(r"\(at\)", "@", text(value), flags=re.I)
    value = re.sub(r"\s*@\s*", "@", value).lower()
    return list(dict.fromkeys(re.findall(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", value)))


def sku(value):
    return "BF-" + "".join(re.findall(r"\d", value)).zfill(5)


def stage(value):
    value = norm(value)
    match = re.match(r"(r[1-4]|0?[1-7])\b", value)
    if match:
        return match[1].upper() if match[1].startswith("r") else match[1].zfill(2)
    return {"contatto": "01", "qualifica": "02", "presentazione": "03", "decisione": "04",
            "contratto": "05", "vinta": "06", "persa": "07", "da rinnovare": "R1",
            "in trattativa": "R2", "rinnovato": "R3", "non rinnovato": "R4"}.get(value, "UNKNOWN:" + value)


class Union:
    def __init__(self, ids):
        self.parent = {key: key for key in ids}

    def root(self, key):
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def join(self, a, b):
        self.parent[self.root(a)] = self.root(b)


def main(source, destination):
    data, report, profiles = {}, {}, {}
    for path in sorted(source.glob("*.csv")):
        with path.open(encoding="cp1252", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            rows = list(reader)
            fields = reader.fieldnames
        data[path.stem] = rows
        malformed = sum(None in r or any(v is None for v in r.values()) for r in rows)
        assert not malformed, (path, malformed)
        profiles[path.stem] = {
            "rows": len(rows), "active": sum(not deleted(r) for r in rows),
            "deleted": sum(deleted(r) for r in rows), "columns": fields,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "malformed_rows": malformed,
            "blank_cells": {k: sum(not text(r[k]) for r in rows) for k in fields},
            "flags": dict(Counter(r.get("cancellato", "N/A") for r in rows)),
            "multiline_rows": sum(any("\n" in v for v in r.values()) for r in rows),
            "mojibake_marker_rows": sum(any("Ã" in v or "Â" in v for v in r.values()) for r in rows),
        }
        if fields[0].startswith("id_") and path.stem != "storico_fasi":
            profiles[path.stem]["duplicate_primary_ids"] = len(rows) - len({r[fields[0]] for r in rows})
    report["files"] = profiles
    report["total_rows"] = sum(len(rows) for rows in data.values())
    active = {k: [r for r in rows if not deleted(r)] for k, rows in data.items()}
    report["date_parse"] = {}
    for name, rows in data.items():
        for key in rows[0]:
            if key not in {"ultima_modifica", "data", "data_cambio", "data_chiusura", "aperto_il", "chiuso_il"}:
                continue
            bad, serial, valid = Counter(), 0, []
            for r in rows:
                value = text(r[key])
                serial += bool(re.fullmatch(r"\d{5}(?:[.,]\d+)?", value))
                try:
                    parsed = date(value)
                    if parsed:
                        valid.append(parsed)
                except ValueError:
                    bad[value] += 1
            report["date_parse"][f"{name}.{key}"] = {
                "excel_serials": serial, "unparsed": dict(bad),
                "min": str(min(valid)) if valid else None, "max": str(max(valid)) if valid else None,
            }

    # Merge company identities only by normalized domains and VAT, never by company name.
    companies = {r["id_azienda"]: r for r in active["aziende"]}
    union = Union(companies)
    keys, domains, vats = {}, defaultdict(list), defaultdict(list)
    for identifier, r in companies.items():
        d, vs = domain(r["sito_web"]), vat(r["note"])
        if d:
            domains[d].append(identifier)
        for v in vs:
            vats[v].append(identifier)
        for key in ([("domain", d)] if d else []) + [("vat", v) for v in vs]:
            if key in keys:
                union.join(identifier, keys[key])
            else:
                keys[key] = identifier
    groups = defaultdict(list)
    for identifier, r in companies.items():
        groups[union.root(identifier)].append(r)
    company_map, merged, tied = {}, {}, []
    for group in groups.values():
        ordered = sorted(group, key=lambda r: (date(r["ultima_modifica"]) or datetime.min, r["id_azienda"]), reverse=True)
        winner = ordered[0]["id_azienda"]
        if len(ordered) > 1 and date(ordered[0]["ultima_modifica"]) == date(ordered[1]["ultima_modifica"]):
            tied.append([r["id_azienda"] for r in ordered])
        merged[winner] = {key: next((text(r[key]) for r in ordered if text(r[key])), "") for key in ordered[0]}
        for r in group:
            company_map[r["id_azienda"]] = winner
    domain_map = {d: company_map[ids[0]] for d, ids in domains.items()}
    report["companies"] = {
        "live_rows": len(companies), "merged_companies": len(groups),
        "duplicate_groups": sum(len(g) > 1 for g in groups.values()), "largest_group": max(map(len, groups.values())),
        "domain_duplicate_groups": sum(len(ids) > 1 for ids in domains.values()),
        "vat_rows": sum(bool(vat(r["note"])) for r in companies.values()),
        "vat_duplicate_groups": sum(len(ids) > 1 for ids in vats.values()),
        "vat_groups_with_multiple_domains": sum(len({domain(companies[i]["sito_web"]) for i in ids}) > 1 for ids in vats.values() if len(ids) > 1),
        "conflicting_vat_groups": sum(len({v for r in g for v in vat(r["note"])}) > 1 for g in groups.values()),
        "latest_timestamp_ties": len(tied), "tie_examples": tied[:4],
        "cross_domain_example": next(([companies[i] for i in ids] for ids in vats.values()
                                      if len(ids) > 1 and len({domain(companies[i]["sito_web"]) for i in ids}) > 1), []),
    }

    # Contacts: choose first valid address as an explicitly provisional policy.
    contacts = {r["id_contatto"]: r for r in active["contatti"]}
    contact_groups = defaultdict(list)
    swapped, multi, invalid, fixed = [], [], [], []
    for identifier, r in contacts.items():
        choices = emails(r["email"])
        if not choices and emails(r["telefono"]) and re.fullmatch(r"[+\d\s()./-]+", text(r["email"])):
            choices = emails(r["telefono"])
            swapped.append(identifier)
        if len(choices) > 1:
            multi.append({"id": identifier, "email": r["email"], "company": r["id_azienda"], "choices": choices})
        if text(r["email"]) and not choices:
            invalid.append(r["email"])
        if choices and choices[0] != text(r["email"]).lower():
            fixed.append(identifier)
        contact_groups[("email", choices[0]) if choices else ("id", identifier)].append(r)
    contact_map, contact_company, email_map = {}, {}, {}
    overwritten_invalid_reference, matching_domain, free_domain_hits = 0, 0, 0
    free = {"gmail.com", "hotmail.it", "hotmail.com", "outlook.it", "outlook.com", "yahoo.it", "yahoo.com", "libero.it", "tiscali.it"}
    for key, group in contact_groups.items():
        ordered = sorted(group, key=lambda r: (date(r["ultima_modifica"]) or datetime.min, r["id_contatto"]), reverse=True)
        winner = ordered[0]["id_contatto"]
        company = next((company_map[text(r["id_azienda"])] for r in ordered if text(r["id_azienda"]) in company_map), None)
        if company and text(ordered[0]["id_azienda"]) and text(ordered[0]["id_azienda"]) not in company_map:
            overwritten_invalid_reference += 1
        if not company and key[0] == "email":
            d = key[1].split("@")[-1]
            if d in domain_map:
                free_domain_hits += d in free
                if d not in free:
                    company = domain_map[d]
                    matching_domain += 1
        contact_company[winner] = company
        if key[0] == "email":
            email_map[key[1]] = winner
        for r in group:
            contact_map[r["id_contatto"]] = winner
    report["contacts"] = {
        "live_rows": len(contacts), "first_email_policy_merged_count": len(contact_groups),
        "duplicate_email_groups": sum(len(g) > 1 for g in contact_groups.values()),
        "rows_in_duplicate_groups": sum(len(g) for g in contact_groups.values() if len(g) > 1),
        "swapped_email_phone": len(swapped), "multi_email_rows": len(multi), "multi_email_examples": multi[:5],
        "nonempty_invalid_email": len(invalid), "invalid_examples": Counter(invalid).most_common(10),
        "repaired_or_multiple_email": len(fixed), "invalid_latest_company_with_older_valid": overwritten_invalid_reference,
        "r12_added_after_merge": matching_domain, "free_email_domains_matching_company": free_domain_hits,
        "company_domain_choice_not_first": sum(any(e.split("@")[1] == domain(companies[r["company"]]["sito_web"])
                for e in r["choices"][1:]) and r["choices"][0].split("@")[1] != domain(companies[r["company"]]["sito_web"])
                for r in multi if r["company"] in companies),
    }

    users = {r["id_utente"]: r for r in data["utenti"]}
    employed = {i: r for i, r in users.items() if norm(r["attivo"]) in {"s", "si", "1"}}
    rehire = {}
    for identifier, r in users.items():
        if identifier in employed:
            continue
        matches = [i for i, u in employed.items() if norm(u["nome"] + " " + u["cognome"]) == norm(r["nome"] + " " + r["cognome"])]
        if len(matches) == 1:
            rehire[identifier] = matches[0]
    report["users"] = {"total": len(users), "active": len(employed), "rehired": rehire,
                       "inactive_without_rehire": [i for i in users if i not in employed and i not in rehire]}
    for table, key in (("opportunita", "id_commerciale"), ("ticket", "id_utente")):
        refs = Counter(text(r[key]) for r in active[table])
        report["users"][table] = {"rehired_owner_rows": sum(refs[i] for i in rehire),
            "inactive_without_rehire_rows": sum(refs[i] for i in users if i not in employed and i not in rehire),
            "unknown_or_name_owner_rows": sum(n for i, n in refs.items() if i and i not in users),
            "unknown_examples": [(i, n) for i, n in refs.items() if i and i not in users][:12]}

    # Referential integrity: source-row populations are explicit (not post-merge).
    report["references"] = {}
    for src, col, target, pk in [
        ("contatti", "id_azienda", "aziende", "id_azienda"),
        ("opportunita", "id_azienda", "aziende", "id_azienda"),
        ("ticket", "id_contatto", "contatti", "id_contatto"),
        ("ticket", "id_azienda", "aziende", "id_azienda"),
        ("attivita", "id_contatto", "contatti", "id_contatto"),
        ("attivita", "id_opportunita", "opportunita", "id_opportunita"),
        ("righe_offerta", "id_opportunita", "opportunita", "id_opportunita"),
    ]:
        all_ids = {r[pk] for r in data[target]}
        live_ids = {r[pk] for r in active[target]}
        counts = Counter()
        for r in active[src]:
            ref = text(r[col])
            counts["blank" if not ref else "missing" if ref not in all_ids else "deleted" if ref not in live_ids else "valid"] += 1
        report["references"][f"{src}.{col}"] = dict(counts)

    # Products and line arithmetic use Decimal and per-line cent rounding.
    product_groups = defaultdict(list)
    for r in active["listino"]:
        product_groups[sku(r["codice_articolo"])].append(r)
    products = {key: max(rows, key=lambda r: date(r["ultima_modifica"]) or datetime.min)
                for key, rows in product_groups.items()}
    all_skus = {sku(r["codice_articolo"]) for r in data["listino"]}
    deals = {r["id_opportunita"]: r for r in active["opportunita"]}
    line_totals, exact_totals = defaultdict(Decimal), defaultdict(Decimal)
    line_counts, line_stats, line_errors = Counter(), Counter(), []
    for r in data["righe_offerta"]:
        if r["id_opportunita"] not in deals:
            line_stats["skipped_missing_or_deleted_deal"] += 1
            continue
        code = sku(r["codice_articolo"])
        product = products.get(code)
        if not product:
            line_stats["deleted_product_reference" if code in all_skus else "missing_product_reference"] += 1
        try:
            price = number(r["prezzo_unitario"])
            if price is None:
                line_stats["missing_price"] += 1
                price = number(product["prezzo_listino"]) if product else None
            if price is None:
                raise ValueError("no fallback price")
            quantity = number(r["quantita"])
            discount = number(r["sconto"]) or Decimal(0)
            if 0 < discount < 1 and "%" not in r["sconto"]:
                line_stats["fractional_discount"] += 1
                discount *= 100
            raw_total = quantity * price * (1 - discount / 100)
            total = raw_total.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
            line_totals[r["id_opportunita"]] += total
            exact_totals[r["id_opportunita"]] += raw_total
            line_counts[r["id_opportunita"]] += 1
            line_stats["fractional_quantity"] += quantity != quantity.to_integral_value()
            line_stats["missing_description"] += not text(r["descrizione"])
            line_stats["importable_lines"] += 1
        except Exception as exc:
            line_errors.append({"id": r["id_riga"], "error": str(exc), "row": r})
    report["products_lines"] = {"active_product_rows": len(active["listino"]),
        "products_after_sku_merge": len(products), "duplicate_sku_groups": sum(len(g) > 1 for g in product_groups.values()),
        "line_stats": dict(line_stats), "line_errors_count": len(line_errors), "line_errors": line_errors[:5]}

    histories = defaultdict(list)
    for r in data["storico_fasi"]:
        histories[r["id_opportunita"]].append((date(r["data_cambio"]), stage(r["fase_nuova"])))
    amount_errors, close_missing, close_recovered, stage_differences = [], [], [], 0
    credit, monthly, comparisons, mismatch_examples = [], [], Counter(), []
    won_companies, positive_won_companies, noncredit_won_companies = set(), set(), set()
    revenue = defaultdict(Decimal)
    credit_nonnegative, won_undated, line_fx = [], [], Counter()
    for identifier, r in deals.items():
        s = stage(r["fase"])
        hist = sorted(histories.get(identifier, []))
        stage_differences += bool(hist and hist[-1][1] != s)
        closed = date(r["data_chiusura"])
        if s in {"06", "07", "R3", "R4"} and closed is None:
            close_missing.append(identifier)
            matches = [dt for dt, hs in hist if hs == s]
            if matches:
                closed = max(matches)
                close_recovered.append(identifier)
        is_credit = bool(re.match(r"(?:storno|nota\s+di\s+credito|nc)\b", norm(r["titolo"])))
        if is_credit:
            credit.append(identifier)
        is_monthly = bool(re.search(r"mese|mensil", norm(r["importo"])))
        if is_monthly:
            monthly.append(identifier)
        try:
            raw_amount = number(r["importo"], annual=True)
        except Exception as exc:
            amount_errors.append({"id": identifier, "raw": r["importo"], "error": str(exc)})
            continue
        currency = norm(r["valuta"])
        money_text = norm(r["importo"])
        if currency in {"$", "usd"} or (not currency and ("$" in money_text or "usd" in money_text)):
            fx, currency = Decimal(".92"), "USD"
        elif currency in {"£", "gbp"} or (not currency and ("£" in money_text or "gbp" in money_text)):
            fx, currency = Decimal("1.17"), "GBP"
        else:
            fx, currency = Decimal(1), "EUR"
        amount = line_totals.get(identifier, raw_amount)
        if identifier in line_totals:
            line_fx[currency] += 1
            if raw_amount is not None:
                delta = line_totals[identifier] - raw_amount
                comparisons["exact" if delta == 0 else "within_2_cents" if abs(delta) <= Decimal(".02") else "larger_difference"] += 1
                if delta and len(mismatch_examples) < 8:
                    mismatch_examples.append({"id": identifier, "source": str(raw_amount), "line_sum": str(line_totals[identifier]), "delta": str(delta), "currency": currency})
        # R4: quote-line prices are EUR, independently of the deal header currency.
        if identifier in line_totals:
            fx = Decimal(1)
        if is_credit and amount is not None and amount >= 0:
            credit_nonnegative.append(identifier)
        company = company_map.get(text(r["id_azienda"]))
        if company and s in {"06", "R3"}:
            won_companies.add(company)
            if not is_credit:
                noncredit_won_companies.add(company)
            if amount is not None and amount > 0:
                positive_won_companies.add(company)
            if closed is None:
                won_undated.append(identifier)
            if closed and closed.year == 2025 and amount is not None:
                revenue[company] += amount * fx
    report["deals"] = {"active": len(deals), "monthly_amount_rows": len(monthly),
        "monthly_outside_renewals": sum(norm(deals[i]["pipeline"]) != "rinnovi" for i in monthly),
        "credit_note_rows": len(credit), "credit_nonnegative": credit_nonnegative,
        "credit_stages": dict(Counter(stage(deals[i]["fase"]) for i in credit)),
        "missing_closedate_closed_deals": len(close_missing), "closedate_recovered": len(close_recovered),
        "unrecoverable_closedate_ids": sorted(set(close_missing) - set(close_recovered))[:10],
        "current_stage_differs_from_latest_history": stage_differences,
        "won_without_close_date": len(won_undated), "amount_errors": amount_errors[:10],
        "amount_error_count": len(amount_errors), "quote_deals": len(line_totals),
        "quote_amount_comparison": dict(comparisons), "quote_mismatch_examples": mismatch_examples,
        "quote_deals_currency": dict(line_fx), "unknown_stages": dict(Counter(stage(r["fase"]) for r in deals.values() if stage(r["fase"]).startswith("UNKNOWN"))),
    }

    # R9 sensitivity: compare literal stage criterion vs credit-note exclusion.
    activity_companies, activity_stats, activity_types = set(), Counter(), Counter()
    for r in active["attivita"]:
        activity_types[norm(r["tipo"])] += 1
        contact = contact_map.get(text(r["id_contatto"]))
        deal = deals.get(text(r["id_opportunita"]))
        activity_stats["no_valid_contact_or_deal"] += not contact and not deal
        activity_stats["inactive_historical_author"] += r["id_utente"] in users and r["id_utente"] not in employed
        if date(r["data"]).year != 2025:
            continue
        activity_stats["year_2025"] += 1
        if contact and contact_company[contact]:
            activity_companies.add(contact_company[contact])
        if deal and text(deal["id_azienda"]) in company_map:
            activity_companies.add(company_map[text(deal["id_azienda"])] )
    rounded_revenue = {i: revenue[i].quantize(Decimal(".01"), rounding=ROUND_HALF_UP) for i in merged}
    classes = Counter("A" if v >= 100000 else "B" if v >= 20000 else "C" if v > 0 else "blank" for v in rounded_revenue.values())
    report["activities"] = {"stats": dict(activity_stats), "normalized_types": dict(activity_types)}
    report["derived_scenarios_NOT_official_expected"] = {
        "assumptions": "First extracted email; active products only; ROUND_HALF_UP per line; latest history entry matching terminal stage fills missing close date; negative credits retained; no owner/association guessing.",
        "revenue_total_sum_of_company_rounded": str(sum(rounded_revenue.values())), "company_classes": dict(classes),
        "companies_with_2025_activity": len(activity_companies),
        "dormant_stage_only": len(won_companies - activity_companies),
        "dormant_excluding_credit_only_wins": len(noncredit_won_companies - activity_companies),
        "dormant_positive_amount_wins": len(positive_won_companies - activity_companies),
        "credit_rule_changes_company_ids": sorted((won_companies - activity_companies) - (noncredit_won_companies - activity_companies))[:20],
    }
    ticket_stats = Counter()
    for r in active["ticket"]:
        contact = contact_map.get(text(r["id_contatto"]))
        company = company_map.get(text(r["id_azienda"]))
        body = text(r["descrizione"])
        m = re.match(r"Da:\s*([^\r\n]+)", body, re.I)
        if m:
            sender = emails(m[1])
            ticket_stats["sender_header"] += 1
            if not contact:
                ticket_stats["sender_header_no_valid_contact"] += 1
                ticket_stats["sender_matches_existing_contact"] += bool(sender and sender[0] in email_map)
        ticket_stats["contact_but_no_company"] += bool(contact and not company)
        if text(r["chiuso_il"]):
            ticket_stats["close_before_open"] += date(r["chiuso_il"]) < date(r["aperto_il"])
    report["tickets"] = {"stats": dict(ticket_stats), "statuses": dict(Counter(r["stato"] for r in active["ticket"])),
        "priorities": dict(Counter(r["priorita"] for r in active["ticket"]))}
    # Detect repairable encoding damage without rewriting source text or guessing replacements.
    encoding_stats = Counter()
    for rows in data.values():
        for row in rows:
            for value in row.values():
                if not any(marker in value for marker in ("Ã", "Â")):
                    continue
                encoding_stats["marker_cells"] += 1
                try:
                    repaired = value.encode("cp1252").decode("utf-8")
                    encoding_stats["whole_cell_strict_repair_candidates"] += repaired != value
                except (UnicodeEncodeError, UnicodeDecodeError):
                    encoding_stats["requires_segment_inspection"] += 1
    report["encoding"] = dict(encoding_stats)
    report["source_unchanged"] = all(
        hashlib.sha256((source / (name + ".csv")).read_bytes()).hexdigest() == profile["sha256"]
        for name, profile in profiles.items()
    )
    assert report["source_unchanged"], "Source changed during audit"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"files", "date_parse"}}, ensure_ascii=False, indent=2))
    # Optional in-process consumer: these expectations use raw CSV analysis only,
    # never app.migration or app.normalize. They are not an official scoring oracle.
    return {
        "report": report,
        "company_revenue": {i: str(value) for i, value in rounded_revenue.items()},
        "dormant": sorted(won_companies - activity_companies),
        "contact_company": contact_company,
        "quote_totals": {i: str(value) for i, value in line_totals.items()},
    }


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
