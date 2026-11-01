"""Persisted migration schemas and read APIs used to inspect imported data."""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.db import ListMember, Metadata
from app.dependencies import DB
from app.store import OBJECT_TYPES, canonical, iso, now

SALES = dict(
    zip(
        ["01", "02", "03", "04", "05", "06", "07"],
        [
            "appointmentscheduled",
            "qualifiedtobuy",
            "presentationscheduled",
            "decisionmakerboughtin",
            "contractsent",
            "closedwon",
            "closedlost",
        ],
    )
)


def pipeline(identifier, label, labels, ids, probabilities=None):
    timestamp = iso(now())
    return {
        "id": identifier,
        "label": label,
        "displayOrder": 0,
        "archived": False,
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "stages": [
            {
                "id": sid,
                "label": name,
                "displayOrder": i,
                "archived": False,
                "createdAt": timestamp,
                "updatedAt": timestamp,
                "metadata": (
                    {
                        "probability": str(probabilities[i]),
                        "isClosed": str(probabilities[i] in (0, 1)).lower(),
                    }
                    if probabilities
                    else {"ticketState": "CLOSED" if i == len(ids) - 1 else "OPEN"}
                ),
            }
            for i, (name, sid) in enumerate(zip(labels, ids))
        ],
    }


def save(session, namespace, key, value):
    session.merge(Metadata(namespace=namespace, key=key, value=value))


def seed(session, migrated=False):
    save(
        session,
        "pipelines:deals",
        "default",
        pipeline(
            "default",
            "Sales Pipeline",
            [
                "Appointment Scheduled",
                "Qualified To Buy",
                "Presentation Scheduled",
                "Decision Maker Bought-In",
                "Contract Sent",
                "Closed Won",
                "Closed Lost",
            ],
            list(SALES.values()),
            [0.2, 0.4, 0.6, 0.8, 0.9, 1, 0],
        ),
    )
    save(
        session,
        "pipelines:tickets",
        "0",
        pipeline(
            "0",
            "Support Pipeline",
            ["New", "Waiting on contact", "Waiting on us", "Closed"],
            ["1", "2", "3", "4"],
        ),
    )
    fields = {
        "companies": ["name", "domain", "hs_additional_domains", "city", "state"],
        "contacts": ["firstname", "lastname", "email", "phone", "lifecyclestage"],
        "deals": ["dealname", "amount", "deal_currency_code", "pipeline", "dealstage", "closedate"],
        "tickets": [
            "subject",
            "content",
            "hs_pipeline",
            "hs_pipeline_stage",
            "hs_ticket_priority",
            "closed_date",
        ],
        "products": ["name", "hs_sku", "price"],
        "line_items": [
            "name",
            "quantity",
            "price",
            "hs_discount_percentage",
            "hs_product_id",
            "amount",
        ],
        "notes": ["hs_timestamp", "hs_note_body"],
        "calls": ["hs_timestamp", "hs_call_body"],
        "emails": ["hs_timestamp", "hs_email_text"],
        "meetings": ["hs_timestamp", "hs_meeting_body"],
        "tasks": ["hs_timestamp", "hs_task_subject", "hs_task_status"],
    }
    if migrated:
        save(
            session,
            "pipelines:deals",
            "rinnovi",
            pipeline(
                "rinnovi",
                "Rinnovi",
                ["Da rinnovare", "In trattativa", "Rinnovato", "Non rinnovato"],
                ["R1", "R2", "R3", "R4"],
                [0.2, 0.6, 1, 0],
            ),
        )
        save(
            session,
            "pipelines:tickets",
            "assistenza",
            pipeline(
                "assistenza",
                "Assistenza",
                ["Aperto", "In lavorazione", "In attesa del cliente", "Chiuso"],
                [
                    "assistenza_open",
                    "assistenza_working",
                    "assistenza_waiting",
                    "assistenza_closed",
                ],
            ),
        )
        fields["companies"] += ["partita_iva", "fatturato_2025", "classe_cliente"]
        fields["deals"] += ["commerciale"]
        fields["tickets"] += ["assegnatario"]
        for kind in ("notes", "calls", "emails", "meetings"):
            fields[kind] += ["autore"]
        for kind in fields:
            if kind not in ("products", "tasks"):
                fields[kind] += ["id_legacy"]
    for kind, names in fields.items():
        for name in names + [
            "hs_object_id",
            "createdate",
            "lastmodifieddate" if kind == "contacts" else "hs_lastmodifieddate",
        ]:
            numeric = name in {
                "amount",
                "price",
                "quantity",
                "hs_discount_percentage",
                "fatturato_2025",
            }
            timestamp = name in {
                "createdate",
                "closedate",
                "closed_date",
                "hs_timestamp",
                "lastmodifieddate",
                "hs_lastmodifieddate",
            }
            save(
                session,
                "properties:" + kind,
                name,
                {
                    "name": name,
                    "label": name,
                    "groupName": OBJECT_TYPES[kind][0] + "information",
                    "type": "number" if numeric else "datetime" if timestamp else "string",
                    "fieldType": "number" if numeric else "date" if timestamp else "text",
                    "hasUniqueValue": name == "partita_iva",
                    "archived": False,
                    "options": [],
                },
            )


pipelines = APIRouter()
properties = APIRouter()
lists = APIRouter()


def values(session, namespace):
    return [
        r.value
        for r in session.scalars(
            select(Metadata).where(Metadata.namespace == namespace).order_by(Metadata.key)
        )
    ]


def one(session, namespace, key):
    row = session.get(Metadata, (namespace, key))
    if row is None:
        raise HTTPException(404, "Metadata not found")
    return row.value


@pipelines.get("/{kind}")
def get_pipelines(kind: str, session: DB):
    return {"results": values(session, "pipelines:" + canonical(kind))}


@pipelines.get("/{kind}/{identifier}")
def get_pipeline(kind: str, identifier: str, session: DB):
    return one(session, "pipelines:" + canonical(kind), identifier)


@pipelines.get("/{kind}/{identifier}/stages")
def get_stages(kind: str, identifier: str, session: DB):
    return {"results": one(session, "pipelines:" + canonical(kind), identifier)["stages"]}


@properties.get("/{kind}")
def get_properties(kind: str, session: DB):
    return {"results": values(session, "properties:" + canonical(kind))}


@properties.get("/{kind}/{name}")
def get_property(kind: str, name: str, session: DB):
    return one(session, "properties:" + canonical(kind), name)


@lists.post("/search")
def search_lists(body: dict, session: DB):
    rows = [
        r
        for r in values(session, "lists")
        if body.get("query", "").lower() in r["name"].lower()
        and (not body.get("objectTypeId") or r["objectTypeId"] == body["objectTypeId"])
        and (not body.get("processingTypes") or r["processingType"] in body["processingTypes"])
    ]
    offset, count = max(0, int(body.get("offset", 0))), min(500, max(1, int(body.get("count", 20))))
    return {
        "lists": rows[offset : offset + count],
        "results": rows[offset : offset + count],
        "total": len(rows),
        "offset": offset + count,
        "hasMore": offset + count < len(rows),
    }


@lists.get("/{identifier}/memberships")
def list_members(
    identifier: str, session: DB, after: str | None = None, limit: int = Query(100, ge=1, le=250)
):
    one(session, "lists", identifier)
    q = select(ListMember).where(ListMember.list_id == identifier)
    if after:
        q = q.where(ListMember.record_id > after)
    rows = session.scalars(q.order_by(ListMember.record_id).limit(limit + 1)).all()
    result = {"results": [{"recordId": r.record_id} for r in rows[:limit]]}
    if len(rows) > limit:
        result["paging"] = {"next": {"after": rows[limit - 1].record_id}}
    return result


@lists.get("/{identifier}")
def get_list(identifier: str, session: DB):
    return {"list": one(session, "lists", identifier)}
