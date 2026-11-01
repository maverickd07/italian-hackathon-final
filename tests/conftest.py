import os
import re
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.db import make_engine
from app.main import create_app


@pytest.fixture
def ui_login():
    """Browser login uses an independent fake credential; never a local .env file."""

    def sign_in(client):
        page = client.get("/login")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        response = client.post(
            "/login",
            data={"token": "test-token", "csrf": csrf, "next": "/"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        # Read the rendered synchronizer token, just as the browser does.
        page = client.get("/")
        import json

        return json.loads(re.search(r'id="relay-ui-context">(.*?)</script>', page.text).group(1))[
            "csrf"
        ]

    return sign_in


@pytest.fixture(autouse=True)
def no_paid_network(monkeypatch):
    """Real outbound HTTP (including LLM SDK clients) is forbidden during tests."""

    def forbidden(*args, **kwargs):
        raise AssertionError("Automated tests must use a fake client; outbound HTTP is forbidden")

    monkeypatch.setenv("CRM_TOKEN", "test-token")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr("app.migration.urlopen", forbidden)


@pytest.fixture
def client(tmp_path):
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        with TestClient(
            create_app(f"sqlite:///{tmp_path}/test.db"),
            headers={"Authorization": "Bearer test-token"},
        ) as client:
            yield client
        return
    # Only touch a fresh random schema; never clear an existing database's tables.
    schema = "test_" + uuid4().hex
    engine = make_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(database_url).update_query_dict({"options": f"-csearch_path={schema}"})
    try:
        with TestClient(
            create_app(url.render_as_string(hide_password=False)),
            headers={"Authorization": "Bearer test-token"},
        ) as client:
            yield client
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.fixture(params=["/crm/v3/objects", "/crm/objects/2026-09"])
def prefix(request):
    return request.param
