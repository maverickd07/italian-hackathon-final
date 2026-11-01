import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import Numeric, String, and_, case, cast, exists, func, not_, or_, select

from app.db import Association, Object
from app.store import canonical, last_modified, serialize

NUMERIC_PATTERN = r"^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$"
SEARCH_FIELDS = {
    "contacts": ["email", "firstname", "lastname", "phone", "company", "website"],
    "companies": ["name", "domain", "phone", "website"],
    "deals": ["dealname", "description"],
    "tickets": ["subject", "content"],
    "notes": ["hs_note_body"],
    "calls": ["hs_call_body"],
    "emails": ["hs_email_text"],
    "meetings": ["hs_meeting_body"],
    "tasks": ["hs_task_subject"],
    "products": ["name", "hs_sku"],
    "line_items": ["name"],
}


def regexp(expr, pattern, dialect):
    return expr.op("~" if dialect == "postgresql" else "REGEXP")(pattern)


def numeric(expr, dialect):
    return case((regexp(expr, NUMERIC_PATTERN, dialect), cast(expr, Numeric)))


def property_expr(name, kind):
    if name == "hs_object_id":
        return Object.id
    if name in {"createdate", "hs_createdate"}:
        return Object.created_at
    if name in {last_modified(kind), "hs_lastmodifieddate"}:
        return Object.updated_at
    return Object.properties[name].as_string()


def date_value(value):
    try:
        if re.fullmatch(NUMERIC_PATTERN, value):
            return datetime.fromtimestamp(float(value) / 1000, UTC)
        result = datetime.fromisoformat(value)
        return result.astimezone(UTC) if result.tzinfo else result.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError):
        raise HTTPException(400, "Invalid timestamp filter")


def predicate(f, kind, dialect):
    name, op = f.propertyName, f.operator
    if name.startswith("associations."):
        target = canonical(name.split(".", 1)[1])
        base = select(Association.from_id).where(
            Association.from_id == Object.id,
            Association.from_type == kind,
            Association.to_type == target,
        )
        if op in {"HAS_PROPERTY", "NOT_HAS_PROPERTY"}:
            condition = exists(base)
        elif op in {"EQ", "NEQ"}:
            condition = exists(base.where(Association.to_id == f.value))
        elif op in {"IN", "NOT_IN"}:
            condition = exists(base.where(Association.to_id.in_(f.values)))
        else:
            raise HTTPException(400, "Unsupported association filter operator")
        return not_(condition) if op in {"NEQ", "NOT_IN", "NOT_HAS_PROPERTY"} else condition
    expr = property_expr(name, kind)
    is_date = name in {"createdate", "hs_createdate", last_modified(kind), "hs_lastmodifieddate"}
    present = expr.is_not(None) if is_date else and_(expr.is_not(None), expr != "")
    if op == "HAS_PROPERTY":
        return present
    if op == "NOT_HAS_PROPERTY":
        return not_(present)
    if is_date:
        value = date_value(f.value) if f.value is not None else None
        high = date_value(f.highValue) if f.highValue is not None else None
        values = [date_value(v) for v in f.values] if f.values is not None else None
    else:
        # Enumeration values are case sensitive; free-text properties are case insensitive.
        enum = name in {
            "dealstage",
            "pipeline",
            "lifecyclestage",
            "hs_pipeline",
            "hs_pipeline_stage",
            "hs_ticket_priority",
        }
        expr = expr if enum else func.lower(expr)
        value = f.value if enum or f.value is None else f.value.lower()
        high = f.highValue if enum or f.highValue is None else f.highValue.lower()
        values = f.values if enum or f.values is None else [v.lower() for v in f.values]
        if op in {"LT", "LTE", "GT", "GTE", "BETWEEN"}:
            try:
                number = Decimal(value)
                if not number.is_finite():
                    raise InvalidOperation
                high_number = Decimal(high) if high is not None else None
                if high_number is not None and not high_number.is_finite():
                    raise InvalidOperation
            except InvalidOperation:
                pass  # ISO dates and text compare lexically when not numeric.
            else:
                expr, value, high = numeric(expr, dialect), number, high_number
    if op in {"CONTAINS_TOKEN", "NOT_CONTAINS_TOKEN"}:
        if is_date:
            raise HTTPException(400, "Token filters require text properties")
        pattern = "(^|[^a-z0-9_])" + re.escape(value).replace(r"\*", ".*") + "($|[^a-z0-9_])"
        condition = regexp(expr, pattern, dialect)
        return and_(present, not_(condition) if op == "NOT_CONTAINS_TOKEN" else condition)
    if op == "BETWEEN":
        condition = expr.between(value, high)
    elif op in {"IN", "NOT_IN"}:
        condition = expr.in_(values) if op == "IN" else expr.not_in(values)
    else:
        condition = {
            "EQ": lambda: expr == value,
            "NEQ": lambda: expr != value,
            "LT": lambda: expr < value,
            "LTE": lambda: expr <= value,
            "GT": lambda: expr > value,
            "GTE": lambda: expr >= value,
        }[op]()
    return and_(present, condition)


def run_search(session, kind, body):
    dialect = session.bind.dialect.name
    conditions = [Object.object_type == kind, Object.archived.is_(False)]
    groups = [
        and_(*(predicate(f, kind, dialect) for f in g.filters))
        for g in body.filterGroups
        if g.filters
    ]
    if groups:
        conditions.append(or_(*groups))
    conditions.extend(predicate(f, kind, dialect) for f in body.filters)
    if body.query:
        query = body.query.lower()
        conditions.append(
            or_(
                *(
                    func.lower(Object.properties[key].as_string()).contains(query, autoescape=True)
                    for key in SEARCH_FIELDS[kind]
                )
            )
        )
    total = session.scalar(select(func.count()).select_from(Object).where(*conditions))
    q = select(Object).where(*conditions)
    for sort in body.sorts:
        if isinstance(sort, str):
            name, descending = sort.lstrip("-"), sort.startswith("-")
        else:
            name, descending = sort.propertyName, sort.direction == "DESCENDING"
        if not name:
            raise HTTPException(400, "Sort property must not be empty")
        expr = property_expr(name, kind)
        if name not in {"createdate", "hs_createdate", last_modified(kind), "hs_lastmodifieddate"}:
            num = numeric(cast(expr, String), dialect)
            q = q.order_by((num.desc() if descending else num.asc()).nulls_last())
        q = q.order_by((expr.desc() if descending else expr.asc()).nulls_last())
    if not body.sorts:
        q = q.order_by(Object.created_at)
    q = q.order_by(Object.id).offset(body.after).limit(body.limit)
    rows = session.scalars(q).all()
    result = {"total": total, "results": [serialize(obj, body.properties) for obj in rows]}
    if body.after + len(rows) < total:
        result["paging"] = {"next": {"after": str(body.after + len(rows))}}
    return result
