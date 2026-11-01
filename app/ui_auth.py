"""Database-backed browser sessions; official APIs never accept these cookies."""

import hashlib
import hmac
import os
import secrets
from asyncio import to_thread
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Boolean, DateTime, Text, delete
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, now, transaction
from app.dependencies import DB
from app.schemas import Update

COOKIE = "relay_session"
SESSION_SECONDS = 8 * 60 * 60
router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


class BrowserSession(Base):
    __tablename__ = "ui_sessions"
    id_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    csrf: Mapped[str] = mapped_column(Text, nullable=False)
    credential_tag: Mapped[str] = mapped_column(Text, nullable=False)
    authenticated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


def credential_tag(identifier):
    return hmac.new(os.getenv("CRM_TOKEN", "").encode(), identifier.encode(), "sha256").hexdigest()


def local_preview(request):
    """Explicit local-only preview; never enable on Railway or remote requests."""
    return (
        os.getenv("UI_LOCAL_PREVIEW") == "true"
        and not any(
            os.getenv(key)
            for key in (
                "RAILWAY_ENVIRONMENT_ID",
                "RAILWAY_PROJECT_ID",
                "RAILWAY_SERVICE_ID",
                "RAILWAY_DEPLOYMENT_ID",
            )
        )
        and request.url.hostname in {"localhost", "127.0.0.1", "::1"}
        and request.client is not None
        and request.client.host in {"127.0.0.1", "::1"}
        and same_origin(request)
    )


def preview_redirect(request, destination):
    identifier, _, seconds = new_session(request, authenticated=True)
    response = RedirectResponse(destination, 303)
    set_cookie(response, request, identifier, seconds)
    response.headers["Cache-Control"] = "no-store"
    return response


def session_hash(identifier):
    return hashlib.sha256(identifier.encode()).hexdigest()


def read_session(request):
    identifier = request.cookies.get(COOKIE, "")
    if not identifier or len(identifier) > 128 or not os.getenv("CRM_TOKEN"):
        return None
    with transaction(request.app.state.engine) as session:
        row = session.get(BrowserSession, session_hash(identifier))
        if row is None or row.expires_at.replace(tzinfo=UTC) <= now():
            return None
        if not secrets.compare_digest(row.credential_tag, credential_tag(identifier)):
            return None
        return row


def secure_cookie(request):
    return (
        request.url.scheme == "https"
        or bool(os.getenv("RAILWAY_ENVIRONMENT_ID"))
        or os.getenv("UI_COOKIE_SECURE") == "true"
    )


def set_cookie(response, request, identifier, seconds):
    response.set_cookie(
        COOKIE,
        identifier,
        max_age=seconds,
        expires=now() + timedelta(seconds=seconds),
        httponly=True,
        samesite="lax",
        secure=secure_cookie(request),
        path="/",
    )


def clear_cookie(response, request):
    response.delete_cookie(COOKIE, httponly=True, samesite="lax", secure=secure_cookie(request))


def new_session(request, authenticated=False):
    identifier = secrets.token_urlsafe(32)
    seconds = SESSION_SECONDS if authenticated else 600
    row = BrowserSession(
        id_hash=session_hash(identifier),
        csrf=secrets.token_urlsafe(32),
        credential_tag=credential_tag(identifier),
        authenticated=authenticated,
        expires_at=now() + timedelta(seconds=seconds),
    )
    with transaction(request.app.state.engine, write=True) as session:
        session.execute(delete(BrowserSession).where(BrowserSession.expires_at <= now()))
        old = request.cookies.get(COOKIE)
        if old:
            session.execute(
                delete(BrowserSession).where(BrowserSession.id_hash == session_hash(old))
            )
        session.add(row)
    return identifier, row, seconds


def safe_next(value):
    from app.ui import public_path

    value = value or "/"
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "/"
    if parsed.scheme or parsed.netloc or "\\" in value or any(ord(c) < 32 for c in value):
        return "/"
    if not public_path(parsed.path) or parsed.path.startswith("/ui-static/"):
        return "/"
    return parsed.path + ("?" + parsed.query if parsed.query else "")


def same_origin(request):
    expected = str(request.base_url).rstrip("/")
    # Railway terminates HTTPS before forwarding HTTP to the container. Use only
    # its configured public domain, never a caller-supplied forwarded host/proto.
    public_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
    if (
        os.getenv("RAILWAY_ENVIRONMENT_ID")
        and public_domain
        and request.url.hostname == public_domain
    ):
        expected = "https://" + public_domain
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site":
        return False
    if origin:
        return origin == expected
    referer = request.headers.get("referer")
    if referer:
        parsed = urlsplit(referer)
        return f"{parsed.scheme}://{parsed.netloc}" == expected
    return True  # The unpredictable synchronizer token is still mandatory.


def valid_csrf(request, supplied):
    row = getattr(request.state, "ui_session", None)
    return bool(
        row
        and supplied
        and same_origin(request)
        and secrets.compare_digest(supplied.encode(), row.csrf.encode())
    )


def login_redirect(request, expired=False):
    destination = safe_next(
        request.url.path + ("?" + request.url.query if request.url.query else "")
    )
    response = RedirectResponse(
        "/login?" + urlencode({"next": destination, "expired": int(expired)}), 303
    )
    clear_cookie(response, request)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    destination = safe_next(request.query_params.get("next", "/"))
    if local_preview(request):
        return preview_redirect(request, destination)
    row = read_session(request)
    if row and row.authenticated:
        return RedirectResponse(destination, 303)
    identifier, row, seconds = new_session(request)
    response = templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "csrf": row.csrf,
            "next": destination,
            "error": "",
            "expired": request.query_params.get("expired") == "1",
        },
    )
    set_cookie(response, request, identifier, seconds)
    return response


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request):
    # Parse a bounded form ourselves: never include a supplied credential in validation errors.
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        return HTMLResponse("Invalid login form. Please reload the sign-in page.", 400)
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > 8192:
            return HTMLResponse("Invalid login form. Please reload the sign-in page.", 400)
        content.extend(chunk)
    try:
        fields = parse_qs(content.decode("utf-8", errors="replace"), max_num_fields=8)
    except ValueError:
        return HTMLResponse("Invalid login form. Please reload the sign-in page.", 400)
    field = lambda key: fields.get(key, [""])[0]
    row = await to_thread(read_session, request)
    request.state.ui_session = row
    if not valid_csrf(request, field("csrf")):
        return HTMLResponse("Sign-in session expired. Please reload the sign-in page.", 403)
    expected = os.getenv("CRM_TOKEN", "")
    if not expected or not secrets.compare_digest(field("token").encode(), expected.encode()):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            status_code=401,
            context={
                "csrf": row.csrf,
                "next": safe_next(field("next")),
                "expired": False,
                "error": "The CRM token is incorrect. Please try again.",
            },
        )
    identifier, _, seconds = await to_thread(new_session, request, authenticated=True)
    response = RedirectResponse(safe_next(field("next")), 303)
    set_cookie(response, request, identifier, seconds)
    return response


@router.post("/ui-api/logout")
def logout(request: Request):
    with transaction(request.app.state.engine, write=True) as session:
        session.execute(
            delete(BrowserSession).where(BrowserSession.id_hash == request.state.ui_session.id_hash)
        )
    response = JSONResponse({"logged_out": True})
    clear_cookie(response, request)
    return response


@router.get("/ui-api/session")
def session_status(request: Request):
    return {"expires_at": request.state.ui_session.expires_at.isoformat()}


@router.patch("/ui-api/deals/{object_id}")
def update_deal(object_id: str, body: Update, session: DB):
    from app.main import patch_object

    return patch_object("deals", object_id, body, session)


@router.post("/ui-api/assistant")
async def ui_assistant(request: Request):
    from app.assistant.router import assistant

    return await assistant(request)
