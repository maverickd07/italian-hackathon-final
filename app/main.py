import logging
import os
import secrets
import zipfile
from asyncio import to_thread
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException

from app.db import Metadata, Object, init_db, make_engine, now, transaction
from app.dependencies import DB, batch_result
from app.schemas import (
    BatchArchive,
    BatchCreate,
    BatchRead,
    BatchUpdate,
    BatchUpsert,
    Create,
    Search,
    Update,
)
from app.search import run_search
from app.store import (
    ASSOCIATION_TYPES,
    archive_record,
    association_name,
    association_results,
    association_rows,
    canonical,
    create_record,
    get_record,
    link,
    serialize,
    unlink,
    update_record,
    upsert_records,
    with_associations,
)
from app.ui_auth import router as ui_auth_router

logger = logging.getLogger(__name__)


def csv(value):
    return (
        [item.strip() for item in value.split(",") if item.strip()] if value is not None else None
    )


router = APIRouter()


@router.get("/{object_type}")
def list_objects(
    object_type: str,
    session: DB,
    limit: int = Query(10, ge=1, le=100),
    after: str | None = None,
    properties: str | None = None,
    archived: bool = False,
    associations: str | None = None,
):
    kind = canonical(object_type)
    q = select(Object).where(Object.object_type == kind, Object.archived == archived)
    if after is not None:
        # The cursor points at the next unread ID. Keyset paging survives archives.
        if not after.isdigit():
            raise HTTPException(400, "Invalid after cursor")
        q = q.where(Object.id >= after)
    rows = session.scalars(q.order_by(Object.id).limit(limit + 1)).all()
    result = {
        "results": [
            with_associations(session, obj, csv(properties), csv(associations))
            for obj in rows[:limit]
        ]
    }
    if len(rows) > limit:
        result["paging"] = {"next": {"after": rows[limit].id}}
    return result


@router.post("/{object_type}", status_code=201)
def create_object(object_type: str, body: Create, session: DB):
    return serialize(create_record(session, canonical(object_type), body))


@router.post("/{object_type}/search")
def search_objects(object_type: str, body: Search, session: DB):
    return run_search(session, canonical(object_type), body)


@router.post("/{object_type}/batch/read")
def batch_read(object_type: str, body: BatchRead, session: DB, archived: bool = False):
    started, kind = now(), canonical(object_type)
    return batch_result(
        [
            serialize(
                get_record(session, kind, item.id, body.idProperty, archived), body.properties
            )
            for item in body.inputs
        ],
        started,
    )


@router.post("/{object_type}/batch/create", status_code=201)
def batch_create(object_type: str, body: BatchCreate, session: DB):
    started, kind = now(), canonical(object_type)
    return batch_result(
        [serialize(create_record(session, kind, item)) for item in body.inputs], started
    )


@router.post("/{object_type}/batch/update")
def batch_update(object_type: str, body: BatchUpdate, session: DB):
    started, kind = now(), canonical(object_type)
    # Resolve and lock records in stable ID order to avoid opposing batch lock orders.
    records = [(item, get_record(session, kind, item.id, item.idProperty)) for item in body.inputs]
    ids = sorted({record.id for _, record in records})
    locked = {
        obj.id: obj
        for obj in session.scalars(
            select(Object)
            .where(Object.id.in_(ids))
            .order_by(Object.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    if any(obj.archived for obj in locked.values()):
        raise HTTPException(404, "A record was archived during the batch update")
    return batch_result(
        [
            serialize(update_record(session, locked[obj.id], item.properties))
            for item, obj in records
        ],
        started,
    )


@router.post("/{object_type}/batch/upsert")
def batch_upsert(object_type: str, body: BatchUpsert, session: DB):
    started = now()
    return batch_result(upsert_records(session, canonical(object_type), body.inputs), started)


@router.post("/{object_type}/batch/archive", status_code=204)
def batch_archive(object_type: str, body: BatchArchive, session: DB):
    kind = canonical(object_type)
    for item in sorted(body.inputs, key=lambda item: item.id):
        obj = session.scalar(
            select(Object).where(Object.object_type == kind, Object.id == item.id).with_for_update()
        )
        if obj is not None:
            archive_record(session, obj)
    return Response(status_code=204)


@router.get("/{object_type}/{object_id}")
def read_object(
    object_type: str,
    object_id: str,
    session: DB,
    properties: str | None = None,
    idProperty: str | None = None,
    archived: bool = False,
    associations: str | None = None,
):
    obj = get_record(session, canonical(object_type), object_id, idProperty, archived)
    return with_associations(session, obj, csv(properties), csv(associations))


@router.patch("/{object_type}/{object_id}")
def patch_object(
    object_type: str, object_id: str, body: Update, session: DB, idProperty: str | None = None
):
    obj = get_record(session, canonical(object_type), object_id, idProperty, lock=True)
    return serialize(update_record(session, obj, body.properties))


@router.delete("/{object_type}/{object_id}", status_code=204)
def delete_object(object_type: str, object_id: str, session: DB):
    kind = canonical(object_type)
    obj = session.scalar(
        select(Object).where(Object.object_type == kind, Object.id == object_id).with_for_update()
    )
    if obj is not None:
        archive_record(session, obj)
    return Response(status_code=204)


@router.get("/{object_type}/{object_id}/associations/{to_type}")
def read_associations(
    object_type: str,
    object_id: str,
    to_type: str,
    request: Request,
    session: DB,
    limit: int = Query(100, ge=1, le=500),
    after: int = Query(0, ge=0),
):
    source = get_record(session, canonical(object_type), object_id)
    rows = association_rows(session, source, canonical(to_type))
    modern = "/2026-09/" in request.url.path
    results = association_results(rows, modern=modern)
    result = {"results": results[after : after + limit]}
    if after + limit < len(results):
        result["paging"] = {"next": {"after": str(after + limit)}}
    return result


@router.put("/{object_type}/{object_id}/associations/{to_type}/{to_id}/{type_id}")
def create_association(
    object_type: str, object_id: str, to_type: str, to_id: str, type_id: int, session: DB
):
    source = get_record(session, canonical(object_type), object_id)
    target = get_record(session, canonical(to_type), to_id)
    link(session, source, target, type_id)
    return with_associations(session, source, associations=[target.object_type])


@router.delete(
    "/{object_type}/{object_id}/associations/{to_type}/{to_id}/{type_id}", status_code=204
)
def remove_association(
    object_type: str, object_id: str, to_type: str, to_id: str, type_id: int, session: DB
):
    source = get_record(session, canonical(object_type), object_id)
    target = get_record(session, canonical(to_type), to_id)
    unlink(session, source, target, type_id)
    return Response(status_code=204)


def create_app(database_url=None):
    @asynccontextmanager
    async def lifespan(app):
        engine = make_engine(database_url)
        init_db(engine)
        app.state.engine = engine
        app.state.export_downloader = __import__("app.migration", fromlist=["download"]).download
        with transaction(engine, write=True) as session:
            # Multiple workers may finish DDL together; seed under the same exclusive
            # lock as reset/migration, with the existence check inside the lock.
            if engine.dialect.name == "postgresql":
                session.execute(text("SELECT pg_advisory_xact_lock(74102902)"))
            if session.get(Metadata, ("pipelines:deals", "default")) is None:
                from app.catalog import seed

                seed(session)
        yield
        engine.dispose()

    app = FastAPI(title="Relay CRM API", version="0.1.0", lifespan=lifespan)

    from app.assistant.router import router as assistant_router

    app.include_router(assistant_router)
    app.include_router(ui_auth_router)

    def error(status, message, category):
        return JSONResponse(
            status_code=status,
            content={
                "status": "error",
                "message": message,
                "correlationId": str(uuid4()),
                "category": category,
            },
        )

    @app.middleware("http")
    async def authenticate(request, call_next):
        from app.ui import public_path
        from app.ui_auth import (
            COOKIE,
            clear_cookie,
            local_preview,
            login_redirect,
            preview_redirect,
            read_session,
            safe_next,
            valid_csrf,
        )

        if request.method == "GET" and request.url.path == "/health":
            return await call_next(request)
        path = request.url.path
        static = path.startswith("/ui-static/") and request.method in {"GET", "HEAD"}
        ui = public_path(path) and not path.startswith("/ui-static/")
        browser_api = path.startswith("/ui-api/")
        if path == "/login" or static or ui or browser_api:
            if path != "/login" and not static:
                row = await to_thread(read_session, request)
                if not row or not row.authenticated:
                    if ui and request.method == "GET":
                        if local_preview(request):
                            return await to_thread(
                                preview_redirect,
                                request,
                                safe_next(
                                    path + ("?" + request.url.query if request.url.query else "")
                                ),
                            )
                        return login_redirect(request, expired=bool(request.cookies.get(COOKIE)))
                    response = error(
                        401, "Your session expired. Please sign in again.", "AUTHENTICATION_ERROR"
                    )
                    clear_cookie(response, request)
                    response.headers["Cache-Control"] = "no-store"
                    return response
                request.state.ui_session = row
                if request.method not in {"GET", "HEAD", "OPTIONS"} and not valid_csrf(
                    request, request.headers.get("x-csrf-token", "")
                ):
                    response = error(
                        403,
                        "The security check failed. Reload the page and try again.",
                        "CSRF_ERROR",
                    )
                    response.headers["Cache-Control"] = "no-store"
                    return response
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            if not static:
                response.headers["Cache-Control"] = "no-store"
            return response
        expected = os.getenv("CRM_TOKEN", "")
        supplied = request.headers.get("authorization", "")
        if not expected or not secrets.compare_digest(
            supplied.encode(), ("Bearer " + expected).encode()
        ):
            return error(401, "A valid bearer token is required", "AUTHENTICATION_ERROR")
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        categories = {404: "OBJECT_NOT_FOUND", 409: "CONFLICT", 405: "METHOD_NOT_ALLOWED"}
        return error(
            exc.status_code, str(exc.detail), categories.get(exc.status_code, "VALIDATION_ERROR")
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error(
            400,
            "; ".join(f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in exc.errors()),
            "VALIDATION_ERROR",
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return error(409, "Write conflicts with an existing record or relationship", "CONFLICT")

    @app.exception_handler(OperationalError)
    async def database_error(request, exc):
        logger.exception("Database operation failed")
        return error(503, "Database temporarily unavailable; retry the request", "TEMPORARY_ERROR")

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.exception("Unhandled API error")
        return error(500, "Internal server error", "INTERNAL_ERROR")

    @app.get("/health")
    def health(session: DB):
        session.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "version": "2026-09",
            "ui": __import__("app.ui", fromlist=["UI"]).UI,
        }

    from app.catalog import lists, pipelines, properties

    for prefix in ("/crm/v3/pipelines", "/crm/pipelines/2026-09"):
        app.include_router(pipelines, prefix=prefix)
    for prefix in ("/crm/v3/properties", "/crm/properties/2026-09"):
        app.include_router(properties, prefix=prefix)
    for prefix in ("/crm/v3/lists", "/crm/lists/2026-09"):
        app.include_router(lists, prefix=prefix)

    @app.post("/__reset", status_code=204)
    def reset_crm(session: DB):
        from app.migration import reset

        reset(session)
        return Response(status_code=204)

    @app.post("/__migrate", status_code=204)
    def migrate_crm(body: dict, request: Request, session: DB):
        from app.migration import Source, migrate

        url = body.get("export_url")
        if not isinstance(url, str):
            raise HTTPException(400, "export_url is required")
        try:
            with request.app.state.export_downloader(url) as downloaded:
                source = Source(downloaded)
                try:
                    migrate(session, source)
                finally:
                    source.close()
        except HTTPException:
            raise
        except (ValueError, KeyError, zipfile.BadZipFile, UnicodeError) as exc:
            raise HTTPException(400, "Invalid export: " + str(exc)) from exc
        except OSError as exc:
            raise HTTPException(502, "Export download or read failed") from exc
        return Response(status_code=204)

    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    from app.ui import router as ui_router

    app.include_router(ui_router)
    app.mount(
        "/ui-static", StaticFiles(directory=Path(__file__).parent / "static"), name="ui-static"
    )

    app.include_router(router, prefix="/crm/v3/objects")
    app.include_router(router, prefix="/crm/objects/2026-09")

    @app.get("/crm/v3/associations/{from_type}/{to_type}/types")
    def association_types(from_type: str, to_type: str):
        source, target = canonical(from_type), canonical(to_type)
        return {
            "results": [
                {"id": str(tid), "name": association_name(tid)}
                for tid, definition in ASSOCIATION_TYPES.items()
                if definition[:2] == (source, target)
            ]
        }

    @app.get("/crm/v4/associations/{from_type}/{to_type}/labels")
    @app.get("/crm/associations/2026-09/{from_type}/{to_type}/labels")
    def labels(from_type: str, to_type: str):
        source, target = canonical(from_type), canonical(to_type)
        return {
            "results": [
                {"category": "HUBSPOT_DEFINED", "typeId": tid, "label": definition[3]}
                for tid, definition in ASSOCIATION_TYPES.items()
                if definition[:2] == (source, target)
            ]
        }

    from app.associations import modern_objects
    from app.associations import router as association_router

    app.include_router(association_router, prefix="/crm/v3/associations")
    app.include_router(modern_objects, prefix="/crm/objects/2026-09")
    return app


app = create_app()
