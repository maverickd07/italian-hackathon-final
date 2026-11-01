"""Deterministic CRM tools using the same store/search/catalog functions as REST."""

import calendar
import csv
import io
import re
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.exc import IntegrityError

from app import catalog, normalize
from app.db import Association, Object, transaction
from app.schemas import Create, Search
from app.search import SEARCH_FIELDS, numeric, predicate, run_search
from app.store import (
    ASSOCIATION_TYPES,
    canonical,
    create_record,
    get_record,
    iso,
    link,
    update_record,
)

from .presentation import receipt_line, record_label

DEFAULTS = {
    "companies": ["name", "domain", "partita_iva", "fatturato_2025", "classe_cliente", "city"],
    "contacts": ["firstname", "lastname", "email", "phone", "lifecyclestage"],
    "deals": [
        "dealname",
        "amount",
        "deal_currency_code",
        "pipeline",
        "dealstage",
        "commerciale",
        "closedate",
    ],
    "tickets": ["subject", "content", "hs_pipeline", "hs_pipeline_stage", "assegnatario"],
    "products": ["name", "hs_sku", "price"],
    "line_items": ["name", "quantity", "price", "hs_discount_percentage", "hs_product_id"],
    "tasks": ["hs_task_subject", "hs_task_status", "hs_timestamp"],
}
NUMBERS = {"amount", "price", "quantity", "hs_discount_percentage", "fatturato_2025"}
DATES = {"closedate", "closed_date", "hs_timestamp"}
CSV_MAP = {
    "codice_articolo": "hs_sku",
    "descrizione": "name",
    "prezzo_listino": "price",
    "prezzo_unitario": "price",
    "quantita": "quantity",
    "sconto": "hs_discount_percentage",
    "ragione_sociale": "name",
    "sito_web": "domain",
    "citta": "city",
    "provincia": "state",
    "nome": "firstname",
    "cognome": "lastname",
    "telefono": "phone",
}


class Refusal(Exception):
    pass


def italian(value):
    if value is None or value == "":
        return "vuoto"
    return str(value)


def money(value):
    return f"{Decimal(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


class CRMTools:
    def __init__(self, engine, context, attachments, deadline, cancelled):
        self.engine, self.context, self.attachments = engine, context, attachments
        self.deadline, self.cancelled = deadline, cancelled
        self.observed = {}
        self.read_attachments = set()
        self.receipt = None

    def check(self):
        if self.cancelled.is_set() or time.monotonic() >= self.deadline:
            raise TimeoutError()

    @contextmanager
    def db(self, write=False):
        self.check()
        with transaction(self.engine, write=write) as session:
            if session.bind.dialect.name == "postgresql":
                ms = max(1, min(1500, int((self.deadline - time.monotonic()) * 1000)))
                session.execute(text(f"SET LOCAL statement_timeout = {ms}"))
                session.execute(text("SET LOCAL lock_timeout = 1000"))
                session.execute(text("SELECT pg_advisory_xact_lock_shared(74102902)"))
            else:
                session.execute(text("PRAGMA busy_timeout=1000"))
            session.info["context_now"] = self.context["now"]
            yield session
            self.check()

    def active(self, session, email):
        return any(
            str(u.get("email", "")).lower() == email.lower()
            and normalize.norm(u.get("attivo", "")) in {"s", "si", "1"}
            for u in catalog.values(session, "users")
        )

    def identity(self):
        with self.db() as s:
            if not self.active(s, self.context["user"]):
                raise Refusal("L’utente indicato non è un utente attivo del CRM. Nessuna modifica.")

    def fields(self, kind, args):
        return list(
            dict.fromkeys(
                ["id_legacy"]
                + args.get(
                    "properties",
                    DEFAULTS.get(
                        kind,
                        [
                            "hs_timestamp",
                            "hs_note_body",
                            "hs_call_body",
                            "hs_email_text",
                            "hs_meeting_body",
                            "autore",
                        ],
                    ),
                )
            )
        )[:20]

    def compact(self, row, fields):
        props = row.properties if isinstance(row, Object) else row["properties"]
        identifier = row.id if isinstance(row, Object) else row["id"]
        kind = row.object_type if isinstance(row, Object) else None
        if kind:
            self.observed.setdefault((kind, identifier), {}).update(
                {k: props.get(k) for k in fields}
            )
        # Long activity bodies cannot consume the whole model budget.
        return {
            "id": identifier,
            "properties": {k: str(props[k])[:1200] for k in fields if k in props},
        }

    def remember_search(self, kind, result, fields):
        for row in result["results"]:
            self.observed.setdefault((kind, row["id"]), {}).update(
                {k: row["properties"].get(k) for k in fields}
            )
        result["results"] = [self.compact(r, fields) for r in result["results"]]
        return result

    def owned(self):
        owner = self.context["user"].lower()
        source = Object.__table__.alias("owned_source")
        return exists(
            select(Association.from_id)
            .join(source, source.c.id == Association.from_id)
            .where(
                Association.to_id == Object.id,
                Association.to_type == "companies",
                source.c.archived.is_(False),
                or_(
                    and_(
                        source.c.object_type == "deals",
                        func.lower(source.c.properties["commerciale"].as_string()) == owner,
                    ),
                    and_(
                        source.c.object_type == "tickets",
                        func.lower(source.c.properties["assegnatario"].as_string()) == owner,
                    ),
                ),
            )
        )

    def conditions(self, kind, args, s):
        body = Search.model_validate({k: v for k, v in args.items() if k in Search.model_fields})
        conditions = [Object.object_type == kind, Object.archived.is_(False)]
        groups = [
            and_(*(predicate(f, kind, s.bind.dialect.name) for f in g.filters))
            for g in body.filterGroups
            if g.filters
        ]
        if groups:
            conditions.append(or_(*groups))
        conditions.extend(predicate(f, kind, s.bind.dialect.name) for f in body.filters)
        if body.query:
            conditions.append(
                or_(
                    *(
                        func.lower(Object.properties[k].as_string()).contains(
                            body.query.lower(), autoescape=True
                        )
                        for k in SEARCH_FIELDS[kind]
                    )
                )
            )
        if args.get("mine"):
            if kind != "companies":
                raise Refusal("Il filtro miei clienti si applica alle aziende.")
            conditions.append(self.owned())
        return conditions

    def execute(self, name, args):
        self.check()
        if name == "relative_date":
            if ("days" in args) == ("months" in args):
                raise Refusal("Specificare giorni oppure mesi.")
            dt = self.context["now"]
            if "days" in args:
                dt += timedelta(days=int(args["days"]))
            else:
                m = dt.year * 12 + dt.month - 1 + int(args["months"])
                year, month = divmod(m, 12)
                dt = dt.replace(
                    year=year,
                    month=month + 1,
                    day=min(dt.day, calendar.monthrange(year, month + 1)[1]),
                )
            return {"date": iso(dt)}
        if name == "attachment":
            rows = self.csv_rows(args)
            index = int(args["index"])
            self.read_attachments.add(index)
            offset = max(0, int(args.get("after", 0)))
            return {
                "total": len(rows),
                "results": rows[offset : offset + 20],
                "next": offset + 20 if offset + 20 < len(rows) else None,
            }
        if name == "apply_csv":
            return self.apply_csv(args)
        if name == "apply":
            return self.apply(args.get("operations", []))
        with self.db() as s:
            if name == "users":
                rows = [
                    {
                        "email": u.get("email"),
                        "name": (u.get("nome", "") + " " + u.get("cognome", "")).strip(),
                        "active": normalize.norm(u.get("attivo", "")) in {"s", "si", "1"},
                    }
                    for u in catalog.values(s, "users")
                ]
                query = str(args.get("query", "")).lower()
                rows = [r for r in rows if query in (r["name"] + " " + str(r["email"])).lower()]
                offset = max(0, int(args.get("after", 0)))
                return {
                    "total": len(rows),
                    "results": rows[offset : offset + 20],
                    "next": offset + 20 if offset + 20 < len(rows) else None,
                }
            if name == "pipelines":
                return {
                    "results": [
                        {
                            "id": p["id"],
                            "label": p["label"],
                            "stages": [{"id": v["id"], "label": v["label"]} for v in p["stages"]],
                        }
                        for p in catalog.values(s, "pipelines:" + canonical(args["kind"]))
                    ][:20]
                }
            if name == "lists":
                if args.get("id"):
                    return catalog.list_members(
                        str(args["id"]), s, after=args.get("after"), limit=20
                    )
                return catalog.search_lists(
                    {
                        "query": args.get("query", ""),
                        "count": 20,
                        "offset": int(args.get("after", 0)),
                    },
                    s,
                )
            kind = canonical(args.get("kind", "companies"))
            fields = self.fields(kind, args)
            if name == "search":
                body = {k: v for k, v in args.items() if k in Search.model_fields}
                body.update(limit=20, properties=fields)
                return self.remember_search(
                    kind, run_search(s, kind, Search.model_validate(body)), fields
                )
            if name == "get":
                row = get_record(s, kind, str(args["id"]))
                result = self.compact(row, fields)
                for target in args.get("associations", []):
                    target = canonical(target)
                    offset = max(0, int(args.get("after", 0)))
                    q = (
                        select(Object)
                        .join(Association, Association.to_id == Object.id)
                        .where(
                            Association.from_id == row.id,
                            Association.to_type == target,
                            Object.archived.is_(False),
                        )
                        .distinct()
                    )
                    total = s.scalar(select(func.count()).select_from(q.subquery()))
                    related = s.scalars(q.order_by(Object.id).offset(offset).limit(20)).all()
                    result.setdefault("associations", {})[target] = {
                        "total": total,
                        "results": [self.compact(r, self.fields(target, {})) for r in related],
                        "next": offset + 20 if offset + 20 < total else None,
                    }
                return result
            if name == "customers":
                fields = self.fields("companies", args)
                q = select(Object).where(
                    Object.object_type == "companies", Object.archived.is_(False), self.owned()
                )
                total = s.scalar(select(func.count()).select_from(q.subquery()))
                offset = max(0, int(args.get("after", 0)))
                rows = s.scalars(q.order_by(Object.id).offset(offset).limit(20)).all()
                return {
                    "total": total,
                    "results": [self.compact(r, fields) for r in rows],
                    "next": offset + 20 if offset + 20 < total else None,
                }
            if name == "aggregate":
                conditions = self.conditions(kind, args, s)
                count = s.scalar(select(func.count()).select_from(Object).where(*conditions))
                result = {"count": count}
                if args.get("property"):
                    field = args["property"]
                    if field not in NUMBERS:
                        raise Refusal("La proprietà non è numerica.")
                    if field == "amount":
                        currencies = s.scalars(
                            select(Object.properties["deal_currency_code"].as_string())
                            .where(*conditions)
                            .distinct()
                        ).all()
                        if len(currencies) > 1:
                            raise Refusal("Valute diverse: specificare una valuta nel filtro.")
                    expr = numeric(Object.properties[field].as_string(), s.bind.dialect.name)
                    total, valid = s.execute(
                        select(func.sum(expr), func.count(expr)).where(*conditions)
                    ).one()
                    result.update(sum=money(total or 0), missing=count - valid, property=field)
                return result
        raise Refusal("Strumento sconosciuto.")

    def normalize_props(self, props):
        result = {}
        for key, value in props.items():
            if isinstance(value, (dict, list)):
                raise Refusal("Valore di proprietà non valido.")
            raw = str(value) if value is not None else ""
            if key in NUMBERS and raw:
                # JSON numbers / canonical decimal strings are already normalized.
                n = (
                    Decimal(raw)
                    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw)
                    else normalize.number(raw)
                )
                if not n.is_finite():
                    raise Refusal("Numero non valido.")
                raw = str(n)
            elif key in DATES and raw:
                try:
                    dt = datetime.fromisoformat(raw)
                except ValueError:
                    dt = normalize.date(raw)
                raw = iso(dt.replace(tzinfo=dt.tzinfo or self.context["now"].tzinfo))
            elif key == "partita_iva" and raw:
                found = normalize.vat("partita iva: " + raw)
                if len(found) != 1 or not re.fullmatch(
                    r"(?:IT\s*)?(?:\d\s*){11}", raw.strip(), re.IGNORECASE
                ):
                    raise Refusal("Partita IVA non valida: servono undici cifre.")
                raw = found[0]
            elif key == "hs_sku" and raw:
                raw = normalize.sku(raw)
                if not raw:
                    raise Refusal("Codice articolo non valido.")
            elif key == "domain":
                raw = normalize.domain(raw)
            elif key == "email" and raw:
                addresses = normalize.emails(raw)
                if len(addresses) != 1:
                    raise Refusal("Email assente o ambigua.")
                raw = addresses[0]
            result[key] = raw
        return result

    def validate_props(self, s, kind, props, previous):
        for key in ("commerciale", "assegnatario"):
            if props.get(key) and not self.active(s, props[key]):
                raise Refusal("Il responsabile indicato non è un utente attivo. Nessuna modifica.")
        if kind in {"deals", "tickets"}:
            pkey, skey = (
                ("pipeline", "dealstage")
                if kind == "deals"
                else ("hs_pipeline", "hs_pipeline_stage")
            )
            if pkey in props or skey in props:
                merged = {**previous, **props}
                pid = merged.get(pkey) or ("default" if kind == "deals" else "0")
                pipelines = catalog.values(s, "pipelines:" + kind)
                pipeline = next((p for p in pipelines if p["id"] == pid), None)
                if pipeline is None or (
                    merged.get(skey) and merged[skey] not in {v["id"] for v in pipeline["stages"]}
                ):
                    raise Refusal("Pipeline o fase non valida. Nessuna modifica.")

    def validate_property_names(self, s, kind, props):
        valid = {
            p["name"]
            for p in catalog.values(s, "properties:" + kind)
            if not p.get("archived", False)
        }
        unknown = set(props) - valid
        if unknown:
            raise Refusal(
                "Proprietà non riconosciute per "
                + kind
                + ": "
                + ", ".join(sorted(unknown))
                + ". Proprietà valide: "
                + ", ".join(sorted(valid))
                + ". Nessuna modifica eseguita."
            )

    def require_seen(self, kind, identifier, props=None):
        seen = self.observed.get((kind, identifier))
        if seen is None or (props is not None and not set(props) <= set(seen)):
            raise Refusal("Leggere prima il record e tutti i campi da modificare.")
        return seen

    def apply(self, operations):
        if not isinstance(operations, list) or not 1 <= len(operations) <= 200:
            raise Refusal("Specificare da 1 a 200 operazioni atomiche.")
        changes, refs, verified_links = [], {}, []
        try:
            with self.db(write=True) as s:
                if not self.active(s, self.context["user"]):
                    raise Refusal("L’utente non è più attivo. Nessuna modifica eseguita.")
                # Preflight every write before touching any record or automation.
                # REST/import retain their extensible property handling.
                for item in operations:
                    if item.get("op") in {"create", "update"}:
                        self.validate_property_names(
                            s, canonical(item["kind"]), item.get("properties", {})
                        )
                for item in operations:
                    self.check()
                    kind = canonical(item["kind"])
                    op = item["op"]
                    identifier = str(item.get("id", ""))
                    is_new = identifier.startswith("$") and identifier[1:] in refs
                    identifier = (
                        refs.get(identifier[1:], identifier)
                        if identifier.startswith("$")
                        else identifier
                    )
                    props = self.normalize_props(item.get("properties", {}))
                    if op in {"update", "associate"}:
                        seen = (
                            {}
                            if is_new
                            else self.require_seen(
                                kind, identifier, props if op == "update" else None
                            )
                        )
                        row = get_record(s, kind, identifier, lock=True)
                        if (
                            op == "update"
                            and not is_new
                            and any(row.properties.get(k) != seen[k] for k in props)
                        ):
                            raise Refusal(
                                "Il record è cambiato nel frattempo: rileggere prima di modificarlo."
                            )
                    if op == "create":
                        self.validate_props(s, kind, props, {})
                        for assoc in item.get("associations", []):
                            for spec in assoc["types"]:
                                definition = ASSOCIATION_TYPES.get(spec["associationTypeId"])
                                if not definition:
                                    raise Refusal("Associazione non valida.")
                                self.require_seen(definition[1], str(assoc["to"]["id"]))
                        row = create_record(
                            s,
                            kind,
                            Create(properties=props, associations=item.get("associations", [])),
                        )
                        if item.get("ref"):
                            refs[item["ref"]] = row.id
                        changes.append((kind, row.id, "creato", {}, props))
                    elif op == "update":
                        self.validate_props(s, kind, props, row.properties)
                        before = {k: row.properties.get(k) for k in props}
                        update_record(s, row, props)
                        changes.append((kind, row.id, "aggiornato", before, props))
                    elif op == "associate":
                        target_kind = canonical(item["to_kind"])
                        target_id = str(item["to_id"])
                        target_new = target_id.startswith("$") and target_id[1:] in refs
                        target_id = (
                            refs.get(target_id[1:], target_id)
                            if target_id.startswith("$")
                            else target_id
                        )
                        if not target_new:
                            self.require_seen(target_kind, target_id)
                        target = get_record(s, target_kind, target_id)
                        link(s, row, target, int(item["type_id"]))
                        verified_links.append((row.id, target.id, int(item["type_id"])))
                        changes.append(
                            (
                                kind,
                                row.id,
                                "associato",
                                {},
                                {"associazione": record_label(target)},
                            )
                        )
                    else:
                        raise Refusal("Operazione non supportata. Nessuna modifica.")

                s.flush()
                # Expire and re-read from the DB, after all operations and automations.
                s.expire_all()
                lines = []
                for kind, identifier, verb, before, requested in changes:
                    row = get_record(s, kind, identifier)
                    lines.append(receipt_line(row, verb, before, requested))
                for source_id, target_id, type_id in verified_links:
                    if not s.scalar(
                        select(Association.from_id).where(
                            Association.from_id == source_id,
                            Association.to_id == target_id,
                            Association.type_id == type_id,
                        )
                    ):
                        raise Refusal("Associazione non verificata. Nessuna modifica eseguita.")
                self.check()
            # Commit has succeeded before reporting anything as done.
            self.receipt = "Operazione completata e verificata.\n" + "\n".join(lines[:20])
            if len(lines) > 20:
                self.receipt += f"\nTotale: {len(lines)} operazioni verificate."
            return {"reply": self.receipt}
        except IntegrityError as exc:
            raise Refusal(
                "Conflitto: partita IVA già presente o vincolo di unicità. Nessuna modifica eseguita."
            ) from exc

    def csv_rows(self, args):
        index = int(args["index"])
        if not 0 <= index < len(self.attachments):
            raise Refusal("Allegato inesistente.")
        attachment = self.attachments[index]
        if attachment.get("content_type") not in (
            None,
            "text/csv",
            "text/plain",
            "application/csv",
        ):
            raise Refusal("Serve un allegato CSV testuale.")
        content = attachment["content"].lstrip("\ufeff")
        if len(content) > 200000:
            raise Refusal("Allegato troppo grande: massimo 200 righe per operazione.")
        reader = csv.DictReader(io.StringIO(content), delimiter=";", strict=True)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise Refusal("Intestazioni CSV mancanti o duplicate.")
        mapping = args.get("mapping", {})
        rows = []
        for raw in reader:
            if len(rows) >= 200 or None in raw or any(v is None for v in raw.values()):
                raise Refusal("CSV non valido o oltre 200 righe. Nessuna modifica.")
            if normalize.deleted(raw):
                continue
            props = {}
            for col, value in raw.items():
                key = mapping.get(col, CSV_MAP.get(col, col))
                if key in {"ultima_modifica", "cancellato"}:
                    continue
                value = normalize.text(value)
                # CSV numbers use Sinergia notation, unlike JSON tool arguments.
                if key in NUMBERS and value:
                    residue = re.sub(r"[\d\s.,()+%€$£/\-]", "", normalize.norm(value))
                    residue = re.sub(
                        r"milioni|milione|mensili|mensile|almese|mese|mila|mln|eur|usd|gbp|conf|pz|kg|k|m",
                        "",
                        residue,
                    )
                    if residue:
                        raise Refusal("Numero CSV non valido. Nessuna modifica eseguita.")
                    value = str(normalize.number(value))
                props[key] = value
            rows.append(self.normalize_props(props))
        return rows

    def apply_csv(self, args):
        if int(args["index"]) not in self.read_attachments:
            raise Refusal("Leggere prima l’allegato.")
        kind = canonical(args["kind"])
        match = args.get("match_property", "hs_sku" if kind == "products" else "id_legacy")
        operations, unique = [], set()
        with self.db() as s:
            for props in self.csv_rows(args):
                value = props.get(match)
                if not value or value in unique:
                    raise Refusal("Chiave CSV mancante o duplicata. Nessuna modifica.")
                unique.add(value)
                result = run_search(
                    s,
                    kind,
                    Search(
                        filters=[{"propertyName": match, "operator": "EQ", "value": value}],
                        properties=list(props),
                        limit=2,
                    ),
                )
                if result["total"] > 1:
                    raise Refusal("Più record corrispondono alla chiave CSV. Specificare quale.")
                if result["total"] == 0:
                    if not args.get("create_missing", False):
                        raise Refusal(
                            f"Il record {value} non esiste. Vuoi crearlo? Nessuna modifica eseguita."
                        )
                    operations.append({"op": "create", "kind": kind, "properties": props})
                else:
                    self.remember_search(kind, result, list(props))
                    operations.append(
                        {
                            "op": "update",
                            "kind": kind,
                            "id": result["results"][0]["id"],
                            "properties": props,
                        }
                    )
        return self.apply(operations)
