"""Transactional post-migration deal automations; never called by the importer."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import Association, Metadata, Object, now


def deal_transition(session, deal, previous=None):
    from app.store import iso, link

    if deal.object_type != "deals" or session.get(Metadata, ("migration", "last")) is None:
        return
    current = (deal.properties.get("pipeline") or "default", deal.properties.get("dealstage"))
    before = (
        ((previous.get("pipeline") or "default"), previous.get("dealstage"))
        if previous is not None
        else None
    )
    if (
        current == before
        or current[0] != "default"
        or current[1] not in {"closedwon", "closedlost"}
    ):
        return
    rule = "R10" if current[1] == "closedwon" else "R11"
    identifier = str(uuid4().int)
    insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    claimed = session.execute(
        insert(Metadata)
        .values(namespace="automation", key=deal.id + ":" + rule, value={"recordId": identifier})
        .on_conflict_do_nothing()
        .returning(Metadata.key)
    ).scalar_one_or_none()
    if claimed is None:
        return
    instant = session.info.get("context_now") or now()
    title = deal.properties.get("dealname") or ""
    if rule == "R10":
        props = {
            "subject": "Avvio fornitura - " + title,
            "hs_pipeline": "assistenza",
            "hs_pipeline_stage": "assistenza_open",
            "assegnatario": deal.properties.get("commerciale") or "",
        }
        kind, association = "tickets", 27
    else:
        props = {
            "hs_task_subject": "Richiamare: " + title,
            "hs_timestamp": iso(instant + timedelta(days=180)),
            "hs_task_status": "NOT_STARTED",
        }
        kind, association = "tasks", 215
    generated = Object(
        id=identifier,
        object_type=kind,
        properties=props,
        created_at=instant,
        updated_at=instant,
        archived=False,
    )
    session.add(generated)
    session.flush()
    link(session, deal, generated, association)
    if rule == "R10":
        companies = (
            session.scalars(
                select(Object)
                .join(Association, Association.to_id == Object.id)
                .where(
                    Association.from_id == deal.id,
                    Association.from_type == "deals",
                    Association.to_type == "companies",
                    Object.archived.is_(False),
                )
            )
            .unique()
            .all()
        )
        for company in companies:
            link(session, generated, company, 26)
