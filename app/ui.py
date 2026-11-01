"""Session-protected, server-rendered CRM views."""

import json
import re
from datetime import UTC
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import String, cast, func, select, union
from sqlalchemy.orm import aliased

from app.db import Association, ListMember, Metadata, Object
from app.dependencies import DB
from app.ui_sql import UINumber, UIPrefix, UIProperty
from app.ui_workspace import (
    company_ids,
    company_lineage,
    company_metrics,
    dormant_ids,
    last_won_dates,
    owned_ids,
    stats,
    workspace,
)

UI = {
    "today": "/",
    "assistant": "/assistant",
    "companies": "/companies",
    "contacts": "/contacts",
    "deals": "/deals",
    "tickets": "/tickets",
    "dormant": "/dormant-customers",
}


def ui_context(request: Request, session: DB):
    request.state.workspace = workspace(request, session)


router = APIRouter(dependencies=[Depends(ui_context)])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
ACTIVITIES = ("notes", "calls", "emails", "meetings")
LABELS = {
    "appointmentscheduled": "Appointment scheduled",
    "qualifiedtobuy": "Qualified",
    "presentationscheduled": "Presentation scheduled",
    "decisionmakerboughtin": "Decision maker engaged",
    "contractsent": "Contract sent",
    "closedwon": "Won",
    "closedlost": "Lost",
    "R1": "To renew",
    "R2": "Negotiating",
    "R3": "Renewed",
    "R4": "Not renewed",
    "assistenza_open": "Open",
    "assistenza_working": "In progress",
    "assistenza_waiting": "Waiting for customer",
    "assistenza_closed": "Closed",
}


def public_path(path):
    return (
        path in {"/", *UI.values()}
        or bool(re.fullmatch(r"/(companies|contacts|deals|tickets)/[0-9]+", path))
        or path.startswith("/ui-static/")
    )


def eur(value):
    if value in (None, ""):
        return "—"
    try:
        amount = Decimal(str(value or 0))
        if not amount.is_finite():
            return "—"
        return "€ " + f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (InvalidOperation, ValueError):
        return "—"


def name(obj):
    p = obj.properties
    return (
        p.get("name")
        or p.get("dealname")
        or p.get("subject")
        or " ".join(filter(None, [p.get("firstname"), p.get("lastname")]))
        or p.get("email")
        or "Untitled"
    )


templates.env.filters.update(eur=eur, record_name=name, stage=lambda s: LABELS.get(s, s or "—"))


def base(kind):
    return select(Object).where(Object.object_type == kind, Object.archived.is_(False))


def page_rows(session, query, after=None, order=None):
    if after:
        query = query.where(Object.id > after)
    rows = session.scalars(query.order_by(*(order or [Object.id])).limit(51)).all()
    return rows[:50], rows[49].id if len(rows) > 50 else None


def render(request, template, **context):
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    ws = request.state.workspace

    def ui_url(url):
        parts = urlsplit(str(url))
        params = dict(parse_qsl(parts.query))
        if ws["selected_user"].get("email"):
            params["user"] = ws["selected_user"]["email"]
        if ws["team"] and "team" not in params:
            params["team"] = "1"
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment)
        )

    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "nav": UI,
            "ui_url": ui_url,
            "session_expires": request.state.ui_session.expires_at.replace(tzinfo=UTC).isoformat(),
            **ws,
            **context,
        },
    )


def related_query(obj, kind):
    ids = select(Association.to_id).where(
        Association.from_type == obj.object_type,
        Association.from_id == obj.id,
        Association.to_type == kind,
    )
    return base(kind).where(Object.id.in_(ids))


def activity_query(obj):
    # Both directions are persisted. Use indexed association lookups, including
    # activities attached to this company's contacts or deals.
    direct = select(Association.to_id).where(
        Association.from_type == obj.object_type,
        Association.from_id == obj.id,
        Association.to_type.in_(ACTIVITIES),
    )
    if obj.object_type == "companies":
        links = aliased(Association)
        indirect = (
            select(Association.to_id)
            .join(
                links,
                (links.to_id == Association.from_id) & (links.to_type == Association.from_type),
            )
            .where(
                links.from_type == "companies",
                links.from_id == obj.id,
                links.to_type.in_(("contacts", "deals")),
                Association.to_type.in_(ACTIVITIES),
            )
        )
        ids = union(direct, indirect)
    else:
        ids = direct
    return select(Object).where(Object.id.in_(ids), Object.archived.is_(False))


def activity_stamp():
    return func.coalesce(
        func.nullif(UIProperty(Object.properties, "hs_timestamp"), ""),
        cast(Object.created_at, String),
    )


def activity_date(value):
    from datetime import UTC, datetime

    if not value:
        return "—"
    try:
        dt = (
            datetime.fromtimestamp(float(value) / 1000, UTC)
            if str(value).isdigit()
            else datetime.fromisoformat(str(value))
        )
        return dt.strftime("%d %b %Y · %H:%M")
    except (ValueError, OverflowError, OSError):
        return str(value)


templates.env.filters["activity_date"] = activity_date


def overdue(value, clock):
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(str(value))
        return (dt if dt.tzinfo else dt.replace(tzinfo=clock.tzinfo)) < clock
    except (TypeError, ValueError):
        return False


templates.env.filters["overdue"] = overdue


def activity_page(session, obj, before=None):
    query = activity_query(obj)
    stamp = activity_stamp()
    if before:
        if "|" not in before:
            raise HTTPException(400, "Invalid activity cursor")
        timestamp, identifier = before.rsplit("|", 1)
        query = query.where((stamp < timestamp) | ((stamp == timestamp) & (Object.id < identifier)))
    result = session.execute(
        query.add_columns(stamp).order_by(stamp.desc(), Object.id.desc()).limit(51)
    ).all()
    cursor = str(result[49][1]) + "|" + result[49][0].id if len(result) > 50 else None
    return [row[0] for row in result[:50]], cursor


@router.get("/", include_in_schema=False)
def home(
    request: Request,
    session: DB,
    callbacks_after: str | None = None,
    kickoffs_after: str | None = None,
    dormant_after: str | None = None,
):
    ws = request.state.workspace
    owners = ws["owners"]
    deals = base("deals").where(Object.id.in_(owned_ids("deals", owners)))
    open_deals = deals.where(
        func.coalesce(UIProperty(Object.properties, "dealstage"), "").not_in(
            ("closedwon", "closedlost", "R3", "R4")
        )
    )
    year = ws["clock"].year
    won = deals.where(
        UIProperty(Object.properties, "dealstage").in_(("closedwon", "R3")),
        UIProperty(Object.properties, "closedate") >= f"{year}-01-01",
        UIProperty(Object.properties, "closedate") < f"{year + 1}-01-01",
    )
    tickets = base("tickets").where(
        Object.id.in_(owned_ids("tickets", owners)),
        func.coalesce(UIProperty(Object.properties, "hs_pipeline_stage"), "").not_in(
            ("assistenza_closed", "4")
        ),
    )
    companies = base("companies").where(
        Object.id.in_(company_ids(owners)), Object.id.in_(dormant_ids())
    )
    kpis = {
        "open_deals": stats(session, open_deals),
        "won": stats(session, won),
        "tickets": stats(session, tickets)[0],
        "dormant": stats(session, companies)[0],
    }
    tasks = base("tasks").where(
        UIProperty(Object.properties, "hs_task_subject").like("Richiamare: %"),
        func.coalesce(UIProperty(Object.properties, "hs_task_status"), "") != "COMPLETED",
        Object.id.in_(
            select(Association.to_id).where(
                Association.from_type == "deals",
                Association.to_type == "tasks",
                Association.from_id.in_(owned_ids("deals", owners)),
            )
        ),
    )
    due = UIProperty(Object.properties, "hs_timestamp")
    from datetime import timedelta

    tasks = tasks.where(due < (ws["clock"].date() + timedelta(days=1)).isoformat())
    if callbacks_after:
        try:
            timestamp, identifier = json.loads(callbacks_after)
        except (ValueError, TypeError):
            raise HTTPException(400, "Invalid task cursor")
        tasks = tasks.where((due > timestamp) | ((due == timestamp) & (Object.id > identifier)))
    task_rows = session.scalars(tasks.order_by(due, Object.id).limit(51)).all()
    callbacks_cursor = (
        json.dumps([task_rows[49].properties.get("hs_timestamp", ""), task_rows[49].id])
        if len(task_rows) > 50
        else None
    )
    kickoffs, kickoffs_cursor = page_rows(
        session,
        tickets.where(
            UIProperty(Object.properties, "subject").like("Avvio fornitura - %"),
            UIProperty(Object.properties, "hs_pipeline_stage") == "assistenza_open",
        ),
        kickoffs_after,
    )
    customers, dormant_cursor = page_rows(session, companies, dormant_after)
    bars = session.execute(
        select(
            UIProperty(Object.properties, "dealstage"),
            func.count(),
            func.sum(UINumber(Object.properties, "amount")),
        )
        .where(*deals._where_criteria, UIProperty(Object.properties, "pipeline") == "default")
        .group_by(UIProperty(Object.properties, "dealstage"))
    ).all()
    meta = session.get(Metadata, ("pipelines:deals", "default"))
    totals = {stage: (count, value) for stage, count, value in bars}
    maximum = max([count for _, count, _ in bars], default=1) or 1
    pipeline = [
        {
            "id": stage["id"],
            "label": LABELS.get(stage["id"], stage["label"]),
            "count": totals.get(stage["id"], (0, 0))[0],
            "value": totals.get(stage["id"], (0, 0))[1],
            "width": round(totals.get(stage["id"], (0, 0))[0] / maximum * 100),
        }
        for stage in (meta.value["stages"] if meta else [])
    ]
    return render(
        request,
        "today.html",
        title="Today",
        kpis=kpis,
        callbacks=task_rows[:50],
        callbacks_cursor=callbacks_cursor,
        kickoffs=kickoffs,
        kickoffs_cursor=kickoffs_cursor,
        customers=customers,
        dormant_cursor=dormant_cursor,
        last_won=last_won_dates(session, customers),
        pipeline_bars=pipeline,
    )


@router.get("/assistant", include_in_schema=False)
def assistant_page(request: Request):
    return render(request, "assistant.html", title="Assistant")


@router.get("/companies", include_in_schema=False)
@router.get("/contacts", include_in_schema=False)
def directory(
    request: Request,
    session: DB,
    q: str = Query("", max_length=120),
    after: str | None = None,
    customer_class: str = "all",
    view: str = "all",
):
    kind = request.url.path.strip("/")
    query = base(kind)
    if kind == "companies":
        if customer_class in ("A", "B", "C"):
            query = query.where(UIProperty(Object.properties, "classe_cliente") == customer_class)
        elif customer_class == "dormant":
            query = query.where(Object.id.in_(dormant_ids()))
        elif customer_class != "all":
            raise HTTPException(400, "Unknown customer class")
        if view == "my":
            query = query.where(Object.id.in_(company_ids(request.state.workspace["owners"])))
    if q.strip():
        # Prefix matching must be correct under PostgreSQL locale collations.
        fields = ("name", "domain") if kind == "companies" else ("firstname", "lastname", "email")
        term = q.strip().lower()
        matches = union(
            *(
                select(Object.id).where(
                    Object.object_type == kind,
                    Object.archived.is_(False),
                    (UIPrefix(Object.properties, field) >= term)
                    & (UIPrefix(Object.properties, field) < term + "\U0010ffff"),
                )
                for field in fields
            )
        )
        query = query.where(Object.id.in_(matches))
    if kind == "companies":
        revenue = UINumber(Object.properties, "fatturato_2025")
        if after:
            try:
                amount, identifier = json.loads(after)
                amount = Decimal(amount)
                if not amount.is_finite():
                    raise ValueError()
            except (ValueError, TypeError, InvalidOperation):
                raise HTTPException(400, "Invalid company cursor")
            query = query.where(
                (revenue < amount) | ((revenue == amount) & (Object.id > identifier))
            )
        result = session.execute(
            query.add_columns(revenue).order_by(revenue.desc(), Object.id).limit(51)
        ).all()
        cursor = json.dumps([str(result[49][1]), result[49][0].id]) if len(result) > 50 else None
        rows = [item[0] for item in result[:50]]
    else:
        rows, cursor = page_rows(session, query, after)
    return render(
        request,
        "directory.html",
        title=kind.title(),
        kind=kind,
        rows=rows,
        cursor=cursor,
        q=q,
        customer_class=customer_class,
        view=view,
        metrics=company_metrics(
            session, request.state.workspace["owners"] if view == "my" else None
        )
        if kind == "companies"
        else None,
        lineage=company_lineage(session, rows) if kind == "companies" else {},
    )


@router.get("/companies/{identifier}", include_in_schema=False)
@router.get("/contacts/{identifier}", include_in_schema=False)
@router.get("/deals/{identifier}", include_in_schema=False)
@router.get("/tickets/{identifier}", include_in_schema=False)
def detail(
    request: Request,
    identifier: str,
    session: DB,
    tab: str = "contacts",
    after: str | None = None,
    before: str | None = None,
    provenance_page: int = Query(1, ge=1),
):
    kind = request.url.path.split("/")[1]
    obj = session.scalar(base(kind).where(Object.id == identifier))
    if obj is None:
        raise HTTPException(404, "Record not found")
    tabs = {
        "companies": ["contacts", "deals", "tickets", "activity"],
        "contacts": ["companies", "deals", "tickets", "activity"],
        "deals": ["companies", "contacts", "tickets", "activity"],
        "tickets": ["companies", "contacts", "deals", "activity"],
    }[kind]
    if tab not in tabs:
        tab = tabs[0]
    rows, cursor = (
        activity_page(session, obj, before)
        if tab == "activity"
        else page_rows(session, related_query(obj, tab), after)
    )
    provenance = (
        session.get(Metadata, ("company_provenance", obj.properties.get("id_legacy", "")))
        if kind == "companies"
        else None
    )
    return render(
        request,
        "detail.html",
        title=name(obj),
        obj=obj,
        kind=kind,
        tabs=tabs,
        tab=tab,
        rows=rows,
        cursor=cursor,
        provenance=provenance.value if provenance else None,
        provenance_page=provenance_page,
        provenance_start=(provenance_page - 1) * 50,
    )


@router.get("/deals", include_in_schema=False)
def deals(
    request: Request,
    session: DB,
    pipeline: str = "default",
    commerciale: str = Query("", max_length=120),
    stage: str = "",
    after: str | None = None,
    view: str = "all",
):
    if pipeline not in ("default", "rinnovi"):
        raise HTTPException(400, "Unknown pipeline")
    meta = session.get(Metadata, ("pipelines:deals", pipeline))
    stages = meta.value["stages"] if meta else []
    query = base("deals").where(UIProperty(Object.properties, "pipeline") == pipeline)
    if view == "my":
        query = query.where(Object.id.in_(owned_ids("deals", request.state.workspace["owners"])))
    if commerciale:
        query = query.where(UIProperty(Object.properties, "commerciale") == commerciale)
    columns = []
    for s in stages:
        sq = query.where(UIProperty(Object.properties, "dealstage") == s["id"])
        rows, cursor = page_rows(session, sq, after if stage == s["id"] else None)
        # Amounts are normalized numeric strings by the importer and normal API validation.
        from sqlalchemy import Numeric, case, cast

        amount = UIProperty(Object.properties, "amount")
        safe = case(
            (
                amount.op("~" if session.bind.dialect.name == "postgresql" else "REGEXP")(
                    r"^-?[0-9]+(\.[0-9]+)?$"
                ),
                cast(amount, Numeric),
            ),
            else_=0,
        )
        total = session.scalar(select(func.sum(safe)).where(*sq._where_criteria)) or 0
        columns.append(
            {
                "id": s["id"],
                "label": LABELS.get(s["id"], s["label"]),
                "rows": rows,
                "cursor": cursor,
                "total": total,
            }
        )
    return render(
        request,
        "deals.html",
        title="Deals",
        columns=columns,
        pipeline=pipeline,
        commerciale=commerciale,
    )


@router.get("/tickets", include_in_schema=False)
def tickets(
    request: Request,
    session: DB,
    stage: str = "",
    priority: str = "",
    assegnatario: str = Query("", max_length=120),
    after: str | None = None,
    view: str = "all",
):
    query = base("tickets").where(UIProperty(Object.properties, "hs_pipeline") == "assistenza")
    if view == "my":
        query = query.where(Object.id.in_(owned_ids("tickets", request.state.workspace["owners"])))
    for field, value in [
        ("hs_pipeline_stage", stage),
        ("hs_ticket_priority", priority),
        ("assegnatario", assegnatario),
    ]:
        if value:
            query = query.where(UIProperty(Object.properties, field) == value)
    rows, cursor = page_rows(session, query, after)
    return render(
        request,
        "tickets.html",
        title="Support tickets",
        rows=rows,
        cursor=cursor,
        stage=stage,
        priority=priority,
        assegnatario=assegnatario,
    )


@router.get("/dormant-customers", include_in_schema=False)
def dormant(request: Request, session: DB, after: str | None = None, view: str = "all"):
    ids = select(ListMember.record_id).where(ListMember.list_id == "1")
    query = base("companies").where(Object.id.in_(ids))
    if view == "my":
        query = query.where(Object.id.in_(company_ids(request.state.workspace["owners"])))
    rows, cursor = page_rows(session, query, after)
    dates = {}
    for obj in rows:
        won = related_query(obj, "deals").where(
            UIProperty(Object.properties, "dealstage").in_(("closedwon", "R3"))
        )
        last_won = session.scalar(
            select(func.max(UIProperty(Object.properties, "closedate"))).where(*won._where_criteria)
        )
        activity = activity_query(obj)
        last_activity = session.scalar(
            select(func.max(activity_stamp())).where(*activity._where_criteria)
        )
        dates[obj.id] = (last_won, last_activity)
    return render(
        request, "dormant.html", title="Dormant customers", rows=rows, cursor=cursor, dates=dates
    )
