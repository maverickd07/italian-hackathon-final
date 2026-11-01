"""Read-only user identity and indexed ownership queries for the UI."""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, union
from sqlalchemy.orm import aliased

from app.db import Association, ListMember, Metadata, Object
from app.ui_sql import UINumber, UIProperty

ACTIVE = ("s", "si", "sì", "1", "true")
MANAGERS = ("Responsabile di zona", "Direttore commerciale")


def active_users():
    return select(Metadata).where(
        Metadata.namespace == "users", func.lower(UIProperty(Metadata.value, "attivo")).in_(ACTIVE)
    )


def identity(session, email="", after=""):
    query = active_users()
    selected = (
        session.scalar(
            query.where(func.lower(UIProperty(Metadata.value, "email")) == email.lower()).limit(1)
        )
        if email
        else None
    )
    if selected is None:
        selected = session.scalar(
            query.where(UIProperty(Metadata.value, "ruolo") == "Commerciale")
            .order_by(Metadata.key)
            .limit(1)
        )
    if selected is None:
        selected = session.scalar(query.order_by(Metadata.key).limit(1))
    page = query.where(Metadata.key > after) if after else query
    users = session.scalars(page.order_by(Metadata.key).limit(51)).all()
    cursor = users[49].key if len(users) > 50 else None
    return selected.value if selected else {}, [r.value for r in users[:50]], cursor


def workspace(request, session):
    selected, users, cursor = identity(
        session, request.query_params.get("user", ""), request.query_params.get("users_after", "")
    )
    manager = selected.get("ruolo") in MANAGERS
    team = manager and request.query_params.get("team") == "1"
    owners = [selected["email"].lower()] if selected.get("email") else []
    if team:
        reports = session.scalars(
            active_users().where(
                UIProperty(Metadata.value, "responsabile") == selected.get("id_utente", "")
            )
        ).all()
        owners += [r.value["email"].lower() for r in reports if r.value.get("email")]
    return {
        "selected_user": selected,
        "active_users": users,
        "users_cursor": cursor,
        "can_team": manager,
        "team": team,
        "owners": owners,
        "clock": datetime.now(ZoneInfo("Europe/Rome")),
    }


def owned_ids(kind, owners):
    field = "commerciale" if kind == "deals" else "assegnatario"
    return select(Object.id).where(
        Object.object_type == kind,
        Object.archived.is_(False),
        UIProperty(Object.properties, field).in_(owners),
    )


def company_ids(owners):
    return union(
        *(
            select(Association.to_id).where(
                Association.from_type == kind,
                Association.to_type == "companies",
                Association.from_id.in_(owned_ids(kind, owners)),
            )
            for kind in ("deals", "tickets")
        )
    )


def dormant_ids():
    return select(ListMember.record_id).where(ListMember.list_id == "1")


def stats(session, query, field="amount"):
    return session.execute(
        select(func.count(), func.coalesce(func.sum(UINumber(Object.properties, field)), 0)).where(
            *query._where_criteria
        )
    ).one()


def company_metrics(session, owners=None):
    cls = UIProperty(Object.properties, "classe_cliente")
    from sqlalchemy import case

    conditions = [Object.object_type == "companies", Object.archived.is_(False)]
    if owners is not None:
        conditions.append(Object.id.in_(company_ids(owners)))
    row = session.execute(
        select(
            func.count(),
            *(func.sum(case((cls == c, 1), else_=0)) for c in ("A", "B", "C")),
            func.coalesce(func.sum(UINumber(Object.properties, "fatturato_2025")), 0),
        ).where(*conditions)
    ).one()
    dormant = session.scalar(
        select(func.count())
        .select_from(Object)
        .where(
            *conditions,
            Object.id.in_(dormant_ids()),
        )
    )
    return dict(zip(("count", "A", "B", "C", "revenue", "dormant"), (*row, dormant)))


def company_lineage(session, rows):
    legacy = [row.properties.get("id_legacy", "") for row in rows]
    source = session.scalars(
        select(Metadata).where(Metadata.namespace == "company_provenance", Metadata.key.in_(legacy))
    ).all()
    provenance = {r.key: r.value for r in source}
    result = {}
    for row in rows:
        p = row.properties
        item = provenance.get(p.get("id_legacy", ""), {})
        result[row.id] = {
            "merged": len(item.get("merged_ids", [])) + 1 if item.get("merged_ids") else 0,
            "domains": len([d for d in p.get("hs_additional_domains", "").split(";") if d]),
        }
    return result


def last_won_dates(session, rows):
    # A single bounded association query for all 50 displayed companies.
    deals = aliased(Object)
    query = (
        select(Association.to_id, func.max(UIProperty(deals.properties, "closedate")))
        .join(deals, deals.id == Association.from_id)
        .where(
            Association.from_type == "deals",
            Association.to_type == "companies",
            Association.to_id.in_([r.id for r in rows]),
            deals.object_type == "deals",
            deals.archived.is_(False),
            UIProperty(deals.properties, "dealstage").in_(("closedwon", "R3")),
        )
        .group_by(Association.to_id)
    )
    return dict(session.execute(query).all())
