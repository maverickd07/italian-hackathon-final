import hashlib
from datetime import UTC
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from app.db import Association, Metadata, Object, UniqueValue, now
from app.domain_matching import company_email_domain

# Extend this registry to support additional object types without new handlers/tables.
OBJECT_TYPES = {
    "contacts": ("contact", "0-1"),
    "companies": ("company", "0-2"),
    "deals": ("deal", "0-3"),
    "tickets": ("ticket", "0-5"),
    "notes": ("note", "0-46"),
    "calls": ("call", "0-48"),
    "emails": ("email", "0-49"),
    "meetings": ("meeting", "0-47"),
    "tasks": ("task", "0-27"),
    "products": ("product", "0-7"),
    "line_items": ("line_item", "0-8"),
}
ALIASES = {alias: name for name, aliases in OBJECT_TYPES.items() for alias in (name, *aliases)}

# Directional pairs from the official association type reference.
ASSOCIATION_PAIRS = [
    ("deals", "line_items", 19, 20, None),
    ("contacts", "calls", 193, 194, None),
    ("contacts", "emails", 197, 198, None),
    ("contacts", "meetings", 199, 200, None),
    ("contacts", "tasks", 203, 204, None),
    ("deals", "calls", 205, 206, None),
    ("deals", "emails", 209, 210, None),
    ("deals", "meetings", 211, 212, None),
    ("deals", "tasks", 215, 216, None),
    ("contacts", "companies", 1, 2, "Primary"),
    ("contacts", "companies", 279, 280, None),
    ("contacts", "deals", 4, 3, None),
    ("contacts", "tickets", 15, 16, None),
    ("deals", "companies", 5, 6, "Primary"),
    ("deals", "companies", 341, 342, None),
    ("tickets", "companies", 26, 25, "Primary"),
    ("tickets", "companies", 339, 340, None),
    ("deals", "tickets", 27, 28, None),
    ("contacts", "notes", 201, 202, None),
    ("companies", "notes", 189, 190, None),
    ("deals", "notes", 213, 214, None),
    ("tickets", "notes", 227, 228, None),
    ("companies", "companies", 13, 14, "Parent/child"),
    ("contacts", "contacts", 449, 449, None),
    ("companies", "companies", 450, 450, None),
    ("deals", "deals", 451, 451, None),
    ("tickets", "tickets", 452, 452, None),
]
ASSOCIATION_TYPES = {}
for source, target, forward, reverse, label in ASSOCIATION_PAIRS:
    ASSOCIATION_TYPES[forward] = (source, target, reverse, label)
    ASSOCIATION_TYPES[reverse] = (target, source, forward, label)


def canonical(value):
    if value not in ALIASES:
        raise HTTPException(400, f"Unknown object type: {value}")
    return ALIASES[value]


def iso(value):
    return (
        value.replace(tzinfo=value.tzinfo or UTC)
        .astimezone(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def last_modified(kind):
    return "lastmodifieddate" if kind == "contacts" else "hs_lastmodifieddate"


def system_properties(obj):
    return {
        "hs_object_id": obj.id,
        "createdate": iso(obj.created_at),
        last_modified(obj.object_type): iso(obj.updated_at),
    }


def serialize(obj, properties=None):
    stored = obj.properties
    props = (
        dict(stored) if properties is None else {k: stored[k] for k in properties if k in stored}
    )
    props.update(system_properties(obj))
    return {
        "id": obj.id,
        "properties": props,
        "createdAt": iso(obj.created_at),
        "updatedAt": iso(obj.updated_at),
        "archived": obj.archived,
    }


def get_record(session, kind, identifier, id_property=None, archived=False, lock=False):
    q = select(Object).where(Object.object_type == kind, Object.archived == archived)
    if not id_property or id_property == "hs_object_id":
        q = q.where(Object.id == identifier)
    else:
        expr = Object.properties[id_property].as_string()
        q = q.where(
            func.lower(expr) == identifier.lower() if id_property == "email" else expr == identifier
        )
    if lock:
        q = q.with_for_update()
    rows = session.scalars(q.limit(2)).all()
    if not rows:
        raise HTTPException(404, f"{kind} record not found: {identifier}")
    if len(rows) > 1:
        raise HTTPException(409, f"Property {id_property} is not unique for this value")
    return rows[0]


def checked_properties(props, kind):
    readonly = {"hs_object_id", "createdate", "lastmodifieddate", "hs_lastmodifieddate"}
    if readonly.intersection(props):
        raise HTTPException(
            400,
            "System properties are read-only; use the migration layer to preserve source metadata",
        )
    result = dict(props)
    if kind == "contacts" and "email" in result:
        value = result["email"]
        if value is not None and not isinstance(value, str):
            raise HTTPException(400, "email must be a string")
        result["email"] = (value or "").strip().lower()
    return result


def create_record(session, kind, body):
    obj = Object(
        id=str(uuid4().int),
        object_type=kind,
        properties=checked_properties(body.properties, kind),
        created_at=now(),
        updated_at=now(),
        archived=False,
    )
    session.add(obj)
    session.flush()
    reserve_vat(session, obj)
    for association in body.associations:
        for spec in association.types:
            definition = ASSOCIATION_TYPES.get(spec.associationTypeId)
            if not definition or definition[0] != kind:
                raise HTTPException(400, "Invalid association type for this object")
            target = get_record(session, definition[1], association.to.id)
            link(session, obj, target, spec.associationTypeId)
    associate_contact_domain(session, obj)
    from app.automations import deal_transition

    deal_transition(session, obj)
    return obj


def update_record(session, obj, props):
    previous = dict(obj.properties)
    obj.properties = {**obj.properties, **checked_properties(props, obj.object_type)}
    obj.updated_at = now()
    reserve_vat(session, obj)
    associate_contact_domain(session, obj)
    from app.automations import deal_transition

    deal_transition(session, obj, previous)
    session.flush()
    return obj


def archive_record(session, obj):
    obj.archived = True
    obj.updated_at = now()
    session.flush()


def reserve_vat(session, obj):
    if obj.object_type != "companies":
        return
    session.execute(delete(UniqueValue).where(UniqueValue.record_id == obj.id))
    value = obj.properties.get("partita_iva")
    if value:
        session.add(
            UniqueValue(
                object_type="companies",
                property_name="partita_iva",
                value=str(value),
                record_id=obj.id,
            )
        )
    session.flush()


def associate_contact_domain(session, obj):
    if obj.object_type != "contacts":
        return
    if session.scalar(
        select(Association.from_id)
        .where(Association.from_id == obj.id, Association.to_type == "companies")
        .limit(1)
    ):
        return
    email = obj.properties.get("email", "")
    domain = company_email_domain(email)
    if not domain:
        return
    # Exact domain or one complete token in the semicolon-separated additional domains.
    from sqlalchemy import or_

    companies = session.scalars(
        select(Object)
        .where(
            Object.object_type == "companies",
            Object.archived.is_(False),
            or_(
                func.lower(Object.properties["domain"].as_string()) == domain,
                (
                    ";" + func.lower(Object.properties["hs_additional_domains"].as_string()) + ";"
                ).contains(";" + domain + ";", autoescape=True),
            ),
        )
        .limit(2)
    ).all()
    if len(companies) == 1:
        link(session, obj, companies[0], 1)


def link(session, source, target, type_id):
    definition = ASSOCIATION_TYPES.get(type_id)
    if not definition or definition[:2] != (source.object_type, target.object_type):
        raise HTTPException(400, "Association type does not match object types")
    insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    # Unique composite keys plus ON CONFLICT make retries and concurrent linking idempotent.
    for src, dst, tid in [(source, target, type_id), (target, source, definition[2])]:
        session.execute(
            insert(Association)
            .values(
                from_type=src.object_type,
                from_id=src.id,
                to_type=dst.object_type,
                to_id=dst.id,
                type_id=tid,
            )
            .on_conflict_do_nothing()
        )


def unlink(session, source, target, type_id=None):
    if type_id is not None:
        definition = ASSOCIATION_TYPES.get(type_id)
        if not definition or definition[:2] != (source.object_type, target.object_type):
            raise HTTPException(400, "Association type does not match object types")
        reverse = definition[2]
    else:
        reverse = None
    for src, dst, tid in [(source, target, type_id), (target, source, reverse)]:
        q = delete(Association).where(
            Association.from_type == src.object_type,
            Association.from_id == src.id,
            Association.to_type == dst.object_type,
            Association.to_id == dst.id,
        )
        if tid is not None:
            q = q.where(Association.type_id == tid)
        session.execute(q)


def association_name(type_id):
    source, target, _, _label = ASSOCIATION_TYPES[type_id]
    name = f"{OBJECT_TYPES[source][0]}_to_{OBJECT_TYPES[target][0]}"
    if type_id in {279, 280, 339, 340, 341, 342}:
        name += "_unlabeled"
    return name


def association_rows(session, source, target_type):
    return session.scalars(
        select(Association)
        .join(Object, Object.id == Association.to_id)
        .where(
            Association.from_type == source.object_type,
            Association.from_id == source.id,
            Association.to_type == target_type,
            Object.archived.is_(False),
        )
        .order_by(Association.to_id, Association.type_id)
    ).all()


def association_results(rows, modern=False):
    if not modern:
        return [{"id": row.to_id, "type": association_name(row.type_id)} for row in rows]
    grouped = {}
    for row in rows:
        grouped.setdefault(row.to_id, []).append(
            {
                "category": "HUBSPOT_DEFINED",
                "typeId": row.type_id,
                "label": ASSOCIATION_TYPES[row.type_id][3],
            }
        )
    return [
        {"toObjectId": int(identifier), "associationTypes": types}
        for identifier, types in grouped.items()
    ]


def with_associations(session, obj, properties=None, associations=None):
    result = serialize(obj, properties)
    if associations:
        result["associations"] = {}
        for value in associations:
            kind = canonical(value)
            rows = association_rows(session, obj, kind)
            if rows:
                result["associations"][kind] = {"results": association_results(rows)}
    return result


def upsert_records(session, kind, items):
    """Serialize identities before lookup; lock existing rows before merging fields."""
    prepared = []
    for item in items:
        prop = item.idProperty
        identifier = item.id.strip().lower() if prop == "email" else item.id
        if not identifier:
            raise HTTPException(400, "Upsert identifier cannot be empty")
        if not (kind == "contacts" and prop == "email"):
            meta = session.get(Metadata, ("properties:" + kind, prop))
            if not meta or not meta.value.get("hasUniqueValue"):
                raise HTTPException(400, "idProperty must be a unique property")
        properties = checked_properties(item.properties, kind)
        if prop in properties and properties[prop] != identifier:
            raise HTTPException(400, "id and identifier property disagree")
        properties[prop] = identifier
        key = int.from_bytes(
            hashlib.sha256((kind + "\0" + prop + "\0" + identifier).encode()).digest()[:8],
            "big",
            signed=True,
        )
        prepared.append((item, prop, identifier, properties, key))
    if session.bind.dialect.name == "postgresql":
        for key in sorted({p[4] for p in prepared}):
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    # Lock matching records in deterministic order before any mutation.
    found = {}
    for _, prop, identifier, _, _ in prepared:
        try:
            found[(prop, identifier)] = get_record(session, kind, identifier, prop)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
    if found:
        locked = session.scalars(
            select(Object)
            .where(Object.id.in_(sorted({o.id for o in found.values()})))
            .order_by(Object.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        by_id = {o.id: o for o in locked}
        found = {k: by_id[o.id] for k, o in found.items() if not by_id[o.id].archived}
    results = []
    from app.schemas import Create

    for item, prop, identifier, properties, _ in prepared:
        obj = found.get((prop, identifier))
        created = obj is None
        if obj is None:
            try:
                with session.begin_nested():
                    obj = create_record(session, kind, Create(properties=properties))
            except IntegrityError:
                # An ordinary create can race the first upsert. Its unique-index win
                # becomes an update, without rolling back the whole outer transaction.
                obj = get_record(session, kind, identifier, prop, lock=True)
                obj = update_record(session, obj, properties)
                created = False
        else:
            obj = update_record(session, obj, properties)
        found[(prop, identifier)] = obj
        result = {**serialize(obj), "new": created}
        if item.objectWriteTraceId is not None:
            result["objectWriteTraceId"] = item.objectWriteTraceId
        results.append(result)
    return results
