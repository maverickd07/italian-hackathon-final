"""Deterministic Sinergia importer. No model calls. One atomic database transaction."""

import csv
import io
import json
import logging
import re
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, DecimalException
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from fastapi import HTTPException
from sqlalchemy import delete, insert, select
from sqlalchemy import text as sql
from sqlalchemy.schema import CreateIndex, DropIndex

from app.catalog import SALES, save, seed
from app.db import Association, ListMember, Metadata, Object, UniqueValue, now
from app.domain_matching import company_email_domain
from app.normalize import Union, date, deleted, domain, emails, norm, number, sku, stage, text, vat
from app.store import ASSOCIATION_TYPES, iso

FILES = {
    "aziende",
    "contatti",
    "opportunita",
    "listino",
    "righe_offerta",
    "ticket",
    "attivita",
    "utenti",
    "storico_fasi",
}
HEADERS = {
    "aziende": {
        "id_azienda",
        "ragione_sociale",
        "sito_web",
        "note",
        "citta",
        "provincia",
        "cancellato",
        "ultima_modifica",
    },
    "contatti": {
        "id_contatto",
        "nome",
        "cognome",
        "email",
        "telefono",
        "id_azienda",
        "tipo",
        "cancellato",
        "ultima_modifica",
    },
    "opportunita": {
        "id_opportunita",
        "titolo",
        "id_azienda",
        "contatti",
        "importo",
        "valuta",
        "pipeline",
        "fase",
        "data_chiusura",
        "id_commerciale",
        "cancellato",
        "ultima_modifica",
    },
    "listino": {
        "codice_articolo",
        "descrizione",
        "prezzo_listino",
        "cancellato",
        "ultima_modifica",
    },
    "righe_offerta": {
        "id_riga",
        "id_opportunita",
        "codice_articolo",
        "descrizione",
        "quantita",
        "prezzo_unitario",
        "sconto",
    },
    "ticket": {
        "id_ticket",
        "oggetto",
        "descrizione",
        "stato",
        "priorita",
        "id_contatto",
        "id_azienda",
        "aperto_il",
        "chiuso_il",
        "id_utente",
        "cancellato",
        "ultima_modifica",
    },
    "attivita": {
        "id_attivita",
        "tipo",
        "data",
        "testo",
        "id_contatto",
        "id_opportunita",
        "id_utente",
        "cancellato",
    },
    "utenti": {"id_utente", "nome", "cognome", "email", "ruolo", "responsabile", "attivo"},
    "storico_fasi": {"id_opportunita", "fase_nuova", "data_cambio"},
}


class Source:
    def __init__(self, source):
        self.issues = Counter()
        self.samples = []
        self.deleted_ids = defaultdict(set)
        self.archive = None
        if isinstance(source, Path) and source.is_dir():
            self.paths = {p.stem: p for p in source.glob("*.csv")}
        else:
            self.archive = zipfile.ZipFile(source)
            names = [
                n
                for n in self.archive.namelist()
                if not n.endswith("/")
                and Path(n).suffix.lower() == ".csv"
                and not n.startswith("__MACOSX/")
            ]
            if sum(i.file_size for i in self.archive.infolist()) > 1024 * 1024 * 1024:
                raise ValueError("Uncompressed export exceeds 1 GiB")
            self.paths = {}
            for name in names:
                stem = Path(name).stem
                if stem in self.paths:
                    raise ValueError("Duplicate CSV in archive: " + stem)
                self.paths[stem] = name
        if not FILES.issubset(self.paths):
            self.close()
            raise ValueError("Export must contain all nine CSV files")

    def close(self):
        if self.archive:
            self.archive.close()

    def issue(self, file, field, reason, row=None):
        self.issues[(file, field, reason)] += 1
        if len(self.samples) < 50:
            self.samples.append({"file": file, "field": field, "reason": reason, "row": row})

    def report(self):
        return {
            "total": sum(self.issues.values()),
            "cases": [
                {"file": f, "field": c, "reason": r, "count": n}
                for (f, c, r), n in sorted(self.issues.items())
            ],
            "samples": self.samples,
        }

    def rows(self, name):
        binary = (
            self.archive.open(self.paths[name]) if self.archive else self.paths[name].open("rb")
        )
        dates = {
            "ultima_modifica",
            "data_chiusura",
            "data_cambio",
            "aperto_il",
            "chiuso_il",
            "data",
        }
        numbers = {"importo", "prezzo_listino", "prezzo_unitario", "quantita", "sconto"}
        ids = {
            "aziende": "id_azienda",
            "contatti": "id_contatto",
            "opportunita": "id_opportunita",
            "utenti": "id_utente",
            "ticket": "id_ticket",
            "attivita": "id_attivita",
            "righe_offerta": "id_riga",
        }
        seen = set()
        with io.TextIOWrapper(binary, encoding="cp1252", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";", strict=True)
            if not reader.fieldnames:
                raise ValueError("Unreadable CSV header: " + name)
            for field in HEADERS[name] - set(reader.fieldnames):
                self.issue(name, field, "missing_column")
            try:
                for index, raw in enumerate(reader, 2):
                    row = {k: text(raw.get(k)) for k in HEADERS[name]}
                    if deleted(row):
                        if name in ids:
                            self.deleted_ids[name].add(row[ids[name]])
                        continue
                    invalid = []
                    for field, value in row.items():
                        if "\x00" in value:
                            row[field] = ""
                            invalid.append(field)
                            self.issue(name, field, "nul_byte", index)
                    if None in raw or any(v is None for v in raw.values()):
                        self.issue(name, "row", "column_count", index)
                    for field, value in list(row.items()):
                        if not value:
                            continue
                        try:
                            if field in dates:
                                date(value)
                            elif field in numbers:
                                residue = re.sub(r"[\d\s.,()+%€$£/\-]", "", norm(value))
                                residue = re.sub(
                                    r"milioni|milione|mensili|mensile|almese|mese|mila|mln|eur|usd|gbp|conf|pz|kg|k|m",
                                    "",
                                    residue,
                                )
                                if residue:
                                    raise ValueError("unknown numeric notation")
                                parsed = number(value, annual=True)
                                if not parsed.is_finite() or abs(parsed) > Decimal("1e12"):
                                    raise ValueError("number outside supported precision")
                            elif field in {"fase", "fase_nuova"}:
                                if stage(value).startswith("UNKNOWN:"):
                                    raise ValueError("unknown stage")
                            elif field == "sito_web":
                                host = domain(value)
                                if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host):
                                    raise ValueError("invalid domain")
                            elif field == "codice_articolo" and (
                                not re.search(r"\d", value) or len(value) > 200
                            ):
                                raise ValueError("invalid product code")
                            elif field in {"cancellato", "attivo"} and norm(value) not in {
                                "s",
                                "si",
                                "1",
                                "n",
                                "no",
                                "0",
                            }:
                                raise ValueError("unknown flag")
                        except (ValueError, OverflowError, DecimalException):
                            row[field] = ""
                            invalid.append(field)
                            self.issue(name, field, "unparseable", index)
                    if name == "utenti" and row["email"]:
                        parsed_email = emails(row["email"])
                        if not parsed_email:
                            self.issue(name, "email", "invalid_email", index)
                        row["email"] = parsed_email[0] if parsed_email else ""
                    if name in ids:
                        field = ids[name]
                        row["_source_id"] = row[field]
                        if not row[field] or row[field] in seen or len(row[field]) > 200:
                            self.issue(name, field, "missing_or_duplicate_id", index)
                            row[field] = f"__import_row_{name}_{index}"
                        seen.add(row[field])
                    row["_invalid"] = invalid
                    row["_row"] = index
                    yield row
            except csv.Error as exc:
                raise ValueError("Unreadable CSV: " + name) from exc


def download(url):
    if urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).hostname:
        raise HTTPException(400, "export_url must be an HTTP(S) URL")
    # Never forward CRM Authorization to the export host. Keep query parameters intact.
    output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")  # noqa: SIM115 -- ownership transfers to caller
    try:
        with urlopen(url, timeout=40) as response:
            if urlsplit(response.url).scheme not in {"http", "https"}:
                raise ValueError("Unsupported download redirect")
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > 256 * 1024 * 1024:
                    raise ValueError("Compressed export exceeds 256 MiB")
                output.write(block)
        output.seek(0)
        return output
    except Exception:
        output.close()
        raise


def timestamp(value):
    parsed = date(value) if value else None
    # Source carries local civil dates without offsets. Preserve those clock values as UTC.
    return parsed.replace(tzinfo=UTC) if parsed else None


def decimal(value):
    return format(value, "f") if value is not None else ""


def merge(rows, key):
    ordered = sorted(
        rows,
        key=lambda r: (date(r.get("ultima_modifica")) or datetime.min, r.get(key, "")),  # noqa: DTZ901 -- source civil dates
        reverse=True,
    )
    return {k: next((r[k] for r in ordered if r.get(k) not in (None, "")), "") for k in ordered[0]}


def indexed(rows, key):
    result = {}
    for r in rows:
        identifier = r[key]
        result[identifier] = r
    return result


class Writer:
    def __init__(self, session):
        self.session = session
        self.pending = defaultdict(list)
        self.counter = 0
        self.counts = Counter()

    def flush(self, table):
        rows = self.pending[table]
        if not rows:
            return
        conn = self.session.connection()
        if conn.dialect.name == "postgresql":
            columns = list(rows[0])
            statement = "COPY " + table.__tablename__ + " (" + ",".join(columns) + ") FROM STDIN"
            with (
                conn.connection.driver_connection.cursor() as cursor,
                cursor.copy(statement) as copy,
            ):
                for row in rows:
                    copy.write_row(
                        [
                            json.dumps(row[c], ensure_ascii=False)
                            if isinstance(row[c], dict)
                            else row[c]
                            for c in columns
                        ]
                    )
        else:
            self.session.execute(insert(table), rows)
        rows.clear()

    def add(self, table, row):
        self.pending[table].append(row)
        if len(self.pending[table]) >= 2000:
            if table is Association:
                self.flush(Object)
            self.flush(table)

    def object(self, kind, props, created=None, updated=None):
        self.counter += 1
        identifier = str(self.counter)
        self.add(
            Object,
            {
                "id": identifier,
                "object_type": kind,
                "properties": {
                    k: v for k, v in props.items() if v not in (None, "") or k == "classe_cliente"
                },
                "created_at": created or now(),
                "updated_at": updated or created or now(),
                "archived": False,
            },
        )
        self.counts[kind] += 1
        return identifier

    def link(self, from_id, to_id, type_id):
        if not from_id or not to_id:
            return
        source, target, reverse, _ = ASSOCIATION_TYPES[type_id]
        self.add(
            Association,
            {
                "from_type": source,
                "from_id": from_id,
                "to_type": target,
                "to_id": to_id,
                "type_id": type_id,
            },
        )
        self.add(
            Association,
            {
                "from_type": target,
                "from_id": to_id,
                "to_type": source,
                "to_id": from_id,
                "type_id": reverse,
            },
        )

    def finish(self):
        self.flush(Object)
        for table in list(self.pending):
            self.flush(table)


class Users:
    def __init__(self, rows):
        self.rows = indexed(rows, "id_utente")
        self.active = {i: r for i, r in self.rows.items() if norm(r["attivo"]) in {"s", "si", "1"}}
        self.names = defaultdict(list)
        for i, r in self.active.items():
            self.names[norm(r["nome"] + " " + r["cognome"])].append(i)

    def owner(self, value):
        r = self.rows.get(value)
        if r:
            if value in self.active:
                return r["email"].lower()
            ids = self.names[norm(r["nome"] + " " + r["cognome"])]
        else:
            tokens = re.findall(r"\w+", norm(value))
            ids = []
            for i, u in self.active.items():
                first, last = norm(u["nome"]), norm(u["cognome"])
                if (
                    norm(value) == u["email"].lower()
                    or len(tokens) == 2
                    and (
                        (tokens[0] in (first, first[:1]) and tokens[1] == last)
                        or (tokens[1] in (first, first[:1]) and tokens[0] == last)
                    )
                ):
                    ids.append(i)
        return self.active[ids[0]]["email"].lower() if len(ids) == 1 else ""

    def author(self, value):
        return self.rows.get(value, {}).get("email", "").lower()


def reset(session):
    if session.bind.dialect.name == "postgresql":
        session.execute(
            sql("TRUNCATE associations, objects, crm_metadata, list_members, unique_values")
        )
    else:
        for model in (Association, ListMember, UniqueValue, Object, Metadata):
            session.execute(delete(model))
    seed(session)


def migrate(session, source):
    if session.scalar(select(Object.id).limit(1)) is not None:
        raise HTTPException(409, "Migration requires an empty CRM; reset explicitly first")
    deferred_indexes = []
    if session.bind.dialect.name == "postgresql":
        # The caller holds the exclusive migration advisory lock. Keep primary,
        # unique and FK constraints; defer only non-unique query indexes.
        deferred_indexes = sorted(
            (
                index
                for table in (Object.__table__, Association.__table__)
                for index in table.indexes
                if not index.unique
            ),
            key=lambda index: index.name,
        )
        for index in deferred_indexes:
            session.execute(DropIndex(index, if_exists=True))
    writer = Writer(session)
    seed(session, migrated=True)
    users = Users(source.rows("utenti"))
    for i, r in users.rows.items():
        save(session, "users", i, r)
    companies = indexed(source.rows("aziende"), "id_azienda")
    union = Union(companies)
    seen = {}
    for i, r in companies.items():
        r["domain"] = domain(r["sito_web"])
        r["vat"] = (vat(r["note"]) or [""])[0]
        for key in [("domain", r["domain"]), ("vat", r["vat"])]:
            if key[1]:
                if key in seen:
                    union.join(i, seen[key])
                else:
                    seen[key] = i
    groups = defaultdict(list)
    for i, r in companies.items():
        groups[union.root(i)].append(r)
    company_alias, company_data, domain_map = {}, {}, {}
    for rows in groups.values():
        r = merge(rows, "id_azienda")
        domains = sorted({x["domain"] for x in rows if x["domain"]})
        company_data[r["id_azienda"]] = {
            "id_legacy": r.get("_source_id", r["id_azienda"]),
            "name": r["ragione_sociale"],
            "domain": r["domain"],
            "hs_additional_domains": ";".join(d for d in domains if d != r["domain"]),
            "city": r["citta"],
            "state": r["provincia"],
            "partita_iva": r["vat"],
        }
        save(
            session,
            "company_provenance",
            r["id_azienda"],
            {
                "kept": r["id_azienda"],
                "merged_ids": sorted(
                    x["id_azienda"] for x in rows if x["id_azienda"] != r["id_azienda"]
                ),
                "domains": [
                    {"legacy_id": x["id_azienda"], "domain": x["domain"]}
                    for x in rows
                    if x["id_azienda"] != r["id_azienda"] and x["domain"]
                ],
            },
        )
        for x in rows:
            company_alias[x["id_azienda"]] = r["id_azienda"]
        for d in domains:
            domain_map[d] = r["id_azienda"]
    lifecycle = {
        "lead": "lead",
        "prospect": "opportunity",
        "cliente": "customer",
        "ex cliente": "other",
        "ex-cliente": "other",
    }
    contact_groups = defaultdict(list)
    for r in source.rows("contatti"):
        choices = emails(r["email"])
        if not choices and emails(r["telefono"]) and re.fullmatch(r"[+\d\s()./-]+", r["email"]):
            r["email"], r["telefono"] = r["telefono"], r["email"]
            choices = emails(r["email"])
        if r["email"] and not choices:
            source.issue("contatti", "email", "invalid_email", r["_row"])
        r["email"] = choices[0] if choices else ""
        r["id_azienda"] = company_alias.get(r["id_azienda"], "")
        # Invalid typed values are empty before latest-populated-field merging.
        r["lifecycle"] = lifecycle.get(norm(r["tipo"]), "")
        if r["tipo"] and not r["lifecycle"]:
            source.issue("contatti", "tipo", "unknown_lifecycle", r["_row"])
        contact_groups[("email", r["email"]) if r["email"] else ("id", r["id_contatto"])].append(r)
    contact_alias, contact_data = {}, {}
    for rows in contact_groups.values():
        r = merge(rows, "id_contatto")
        if not r["id_azienda"] and r["email"]:
            r["id_azienda"] = domain_map.get(company_email_domain(r["email"]), "")
        contact_data[r["id_contatto"]] = r
        for x in rows:
            contact_alias[x["id_contatto"]] = r["id_contatto"]
    product_groups = defaultdict(list)
    for r in source.rows("listino"):
        product_groups[
            sku(r["codice_articolo"]) if r["codice_articolo"] else f"__unknown_{r['_row']}"
        ].append(r)
    product_data = {code: merge(rows, "codice_articolo") for code, rows in product_groups.items()}
    histories = defaultdict(list)
    for r in source.rows("storico_fasi"):
        histories[r["id_opportunita"]].append((date(r["data_cambio"]), stage(r["fase_nuova"])))
    deals = indexed(source.rows("opportunita"), "id_opportunita")
    lines = []
    totals = defaultdict(Decimal)
    invalid_totals = set()
    for r in source.rows("righe_offerta"):
        if r["id_opportunita"] in source.deleted_ids["opportunita"]:
            continue
        product = product_data.get(sku(r["codice_articolo"]), {})
        price = number(r["prezzo_unitario"])
        if price is None and "prezzo_unitario" not in r["_invalid"]:
            price = number(product.get("prezzo_listino", ""))
        quantity = number(r["quantita"])
        discount = None if "sconto" in r["_invalid"] else (number(r["sconto"]) or Decimal(0))
        if discount is not None and 0 < discount < 1 and "%" not in r["sconto"]:
            discount *= 100
        amount = None
        if price is not None and quantity is not None and discount is not None:
            try:
                amount = (price * quantity * (1 - discount / 100)).quantize(
                    Decimal(".01"), rounding=ROUND_HALF_UP
                )
            except DecimalException:
                source.issue("righe_offerta", "amount", "arithmetic_overflow", r["_row"])
        if amount is None:
            invalid_totals.add(r["id_opportunita"])
            source.issue("righe_offerta", "amount", "unavailable_input", r["_row"])
        else:
            totals[r["id_opportunita"]] += amount
        r["properties"] = {
            "id_legacy": r.get("_source_id", r["id_riga"]),
            "name": r["descrizione"] or product.get("descrizione", ""),
            "quantity": decimal(quantity),
            "price": decimal(price),
            "hs_discount_percentage": decimal(discount),
            "amount": decimal(amount),
        }
        lines.append(r)
    revenue = defaultdict(Decimal)
    won = set()
    unknown_revenue = set()
    for i, r in deals.items():
        s = stage(r["fase"])
        if s not in SALES and s not in {"R1", "R2", "R3", "R4"}:
            s = ""
        closed = date(r["data_chiusura"])
        if not closed and "data_chiusura" not in r["_invalid"] and s in {"06", "07", "R3", "R4"}:
            candidates = [d for d, st in histories[i] if st == s and d is not None]
            closed = max(candidates) if candidates else None
        amount = (
            None
            if i in invalid_totals
            else totals[i]
            if i in totals
            else number(r["importo"], annual=norm(r["pipeline"]) == "rinnovi")
        )
        currency = norm(r["valuta"])
        if currency in {"usd", "$"} or (
            not currency and ("$" in r["importo"] or "usd" in norm(r["importo"]))
        ):
            currency = "USD"
        elif currency in {"gbp", "£"} or (
            not currency and ("£" in r["importo"] or "gbp" in norm(r["importo"]))
        ):
            currency = "GBP"
        elif currency in {"", "eur", "€", "euro"}:
            currency = "EUR"
        else:
            source.issue("opportunita", "valuta", "unknown_currency", r["_row"])
            currency = ""
        if i in totals:
            currency = "EUR"
        pipeline = norm(r["pipeline"])
        if pipeline not in {"", "vendite", "rinnovi", "default"}:
            source.issue("opportunita", "pipeline", "unknown_pipeline", r["_row"])
        r["company"] = company_alias.get(r["id_azienda"], "")
        r["properties"] = {
            "id_legacy": r.get("_source_id", i),
            "dealname": r["titolo"],
            "amount": decimal(amount),
            "deal_currency_code": currency if amount is not None else "",
            "pipeline": "rinnovi"
            if pipeline == "rinnovi"
            else "default"
            if pipeline in {"", "vendite", "default"}
            else "",
            "dealstage": SALES.get(s, s),
            "closedate": iso(closed) if closed else "",
            "commerciale": users.owner(r["id_commerciale"]),
        }
        if r["company"] and s in {"06", "R3"}:
            won.add(r["company"])
            if "data_chiusura" in r["_invalid"] or (
                closed
                and closed.year == 2025
                and (
                    i in invalid_totals
                    or (i not in totals and "importo" in r["_invalid"])
                    or not currency
                )
            ):
                unknown_revenue.add(r["company"])
            if closed and closed.year == 2025 and amount is not None and currency:
                revenue[r["company"]] += (
                    amount
                    * {"EUR": Decimal(1), "USD": Decimal(".92"), "GBP": Decimal("1.17")}[currency]
                )
    company_ids = {}
    for i, props in company_data.items():
        try:
            amount = revenue[i].quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        except DecimalException:
            amount = Decimal(0)
            unknown_revenue.add(i)
            source.issue("aziende", "fatturato_2025", "arithmetic_overflow")
        props.update(
            fatturato_2025=decimal(amount),
            classe_cliente="A"
            if amount >= 100000
            else "B"
            if amount >= 20000
            else "C"
            if amount > 0
            else "",
        )
        if i in unknown_revenue:
            props.update(fatturato_2025="", classe_cliente="")
            source.issue("aziende", "fatturato_2025", "unavailable_deal_input")
        # Keep explicitly empty class for zero/negative turnover.
        identifier = writer.object(
            "companies", props, updated=timestamp(companies[i]["ultima_modifica"])
        )
        company_ids[i] = identifier
        if props["partita_iva"]:
            writer.add(
                UniqueValue,
                {
                    "object_type": "companies",
                    "property_name": "partita_iva",
                    "value": props["partita_iva"],
                    "record_id": identifier,
                },
            )
    contact_ids = {}
    for i, r in contact_data.items():
        contact_ids[i] = writer.object(
            "contacts",
            {
                "id_legacy": r.get("_source_id", i),
                "firstname": r["nome"],
                "lastname": r["cognome"],
                "email": r["email"],
                "phone": r["telefono"],
                "lifecyclestage": r["lifecycle"],
            },
            updated=timestamp(r["ultima_modifica"]),
        )
        writer.link(contact_ids[i], company_ids.get(r["id_azienda"]), 1)
    product_ids = {}
    for code, r in product_data.items():
        product_ids[code] = writer.object(
            "products",
            {
                "hs_sku": code if not code.startswith("__unknown_") else "",
                "name": r["descrizione"],
                "price": decimal(number(r["prezzo_listino"])),
            },
            updated=timestamp(r["ultima_modifica"]),
        )
    deal_ids = {}
    for i, r in deals.items():
        deal_ids[i] = writer.object(
            "deals", r["properties"], updated=timestamp(r["ultima_modifica"])
        )
        writer.link(deal_ids[i], company_ids.get(r["company"]), 5)
        contacts = {
            contact_alias[c] for c in re.split(r"[;,\s]+", r["contatti"]) if c in contact_alias
        }
        for c in contacts:
            writer.link(deal_ids[i], contact_ids[c], 3)
    for r in lines:
        r["properties"]["hs_product_id"] = product_ids.get(sku(r["codice_articolo"]), "")
        identifier = writer.object("line_items", r["properties"])
        writer.link(deal_ids.get(r["id_opportunita"]), identifier, 19)
    ticket_states = {
        "nuovo": "open",
        "aperto": "open",
        "in lavorazione": "working",
        "lavorazione": "working",
        "in attesa": "waiting",
        "in attesa cliente": "waiting",
        "in attesa del cliente": "waiting",
        "attesa cliente": "waiting",
        "chiuso": "closed",
        "risolto": "closed",
    }
    for r in source.rows("ticket"):
        priority = norm(r["priorita"])
        priority = next(
            (
                v
                for k, v in [
                    ("bassa", "LOW"),
                    ("media", "MEDIUM"),
                    ("normale", "MEDIUM"),
                    ("alta", "HIGH"),
                    ("urgente", "URGENT"),
                ]
                if k in priority
            ),
            "",
        )
        if r["priorita"] and not priority:
            source.issue("ticket", "priorita", "unknown_priority", r["_row"])
        state = ticket_states.get(norm(r["stato"]))
        if not state:
            source.issue("ticket", "stato", "unknown_state", r["_row"])
        identifier = writer.object(
            "tickets",
            {
                "id_legacy": r.get("_source_id", r["id_ticket"]),
                "subject": r["oggetto"],
                "content": r["descrizione"],
                "hs_pipeline": "assistenza",
                "hs_pipeline_stage": "assistenza_" + state if state else "",
                "hs_ticket_priority": priority,
                "closed_date": iso(timestamp(r["chiuso_il"])) if r["chiuso_il"] else "",
                "assegnatario": users.owner(r["id_utente"]),
            },
            created=timestamp(r["aperto_il"]),
            updated=timestamp(r["ultima_modifica"]),
        )
        writer.link(identifier, contact_ids.get(contact_alias.get(r["id_contatto"])), 16)
        writer.link(identifier, company_ids.get(company_alias.get(r["id_azienda"])), 26)
    activity_types = {
        **dict.fromkeys(["nota", "appunto"], "notes"),
        **dict.fromkeys(["chiamata", "telefonata", "tel."], "calls"),
        **dict.fromkeys(["email", "e-mail", "mail"], "emails"),
        **dict.fromkeys(["riunione", "incontro", "meeting", "visita"], "meetings"),
    }
    bodies = {
        "notes": "hs_note_body",
        "calls": "hs_call_body",
        "emails": "hs_email_text",
        "meetings": "hs_meeting_body",
    }
    activity_links = {
        "notes": (202, 214),
        "calls": (194, 206),
        "emails": (198, 210),
        "meetings": (200, 212),
    }
    active_companies = set()
    for r in source.rows("attivita"):
        kind = activity_types.get(norm(r["tipo"]))
        if not kind:
            source.issue("attivita", "tipo", "unknown_type_preserved_as_note", r["_row"])
            kind = "notes"
        dt = timestamp(r["data"])
        identifier = writer.object(
            kind,
            {
                "id_legacy": r.get("_source_id", r["id_attivita"]),
                "hs_timestamp": iso(dt) if dt else "",
                "source_activity_type": r["tipo"],
                bodies[kind]: r["testo"],
                "autore": users.author(r["id_utente"]),
            },
            created=dt,
        )
        c = contact_alias.get(r["id_contatto"])
        d = deals.get(r["id_opportunita"])
        writer.link(identifier, contact_ids.get(c), activity_links[kind][0])
        writer.link(identifier, deal_ids.get(r["id_opportunita"]), activity_links[kind][1])
        if dt and dt.year == 2025:
            if c and contact_data[c]["id_azienda"]:
                active_companies.add(contact_data[c]["id_azienda"])
            if d and d["company"]:
                active_companies.add(d["company"])
    dormant = won - active_companies
    save(
        session,
        "lists",
        "1",
        {
            "listId": "1",
            "listVersion": 1,
            "name": "Clienti dormienti",
            "objectTypeId": "0-2",
            "processingType": "MANUAL",
            "processingStatus": "COMPLETE",
            "createdAt": iso(now()),
            "updatedAt": iso(now()),
            "additionalProperties": {"hs_list_size": str(len(dormant))},
        },
    )
    for i in dormant:
        writer.add(ListMember, {"list_id": "1", "record_id": company_ids[i]})
    writer.finish()
    for index in deferred_indexes:
        session.execute(CreateIndex(index))
    if deferred_indexes:
        session.execute(sql("ANALYZE objects"))
        session.execute(sql("ANALYZE associations"))
    save(
        session,
        "migration",
        "last",
        {
            "counts": dict(writer.counts),
            "dormant": len(dormant),
            "completedAt": iso(now()),
            "log": source.report(),
        },
    )
    logging.getLogger(__name__).info("Migration completed: %s", json.dumps(source.report()))
    return dict(writer.counts)
