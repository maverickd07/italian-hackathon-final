"""Browser authentication isolation, shared sessions and fake-only UI operations."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from fastapi.testclient import TestClient
from test_assistant import Fake, answer
from test_migration import fixture_data, migrate, records

from app.db import now, transaction
from app.main import create_app
from app.ui_auth import COOKIE, BrowserSession, session_hash


def csrf_from_login(client):
    page = client.get("/login", headers={"Authorization": ""})
    assert page.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def test_local_preview_preserves_api_and_production_auth(client, monkeypatch):
    monkeypatch.setenv("UI_LOCAL_PREVIEW", "true")
    for key in list(__import__("os").environ):
        if key.startswith("RAILWAY_"):
            monkeypatch.delenv(key)
    preview = TestClient(client.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    assert preview.get("/companies").status_code == 200
    assert preview.get("/login").url.path == "/"
    assert preview.get("/crm/v3/objects/companies").status_code == 401
    assert preview.post("/__agente", json={}).status_code == 401
    assert preview.patch("/ui-api/deals/1", json={}).status_code == 403
    preview.cookies.clear()
    assert (
        preview.get(
            "/companies", headers={"Origin": "https://other.example"}, follow_redirects=False
        )
        .headers["location"]
        .startswith("/login")
    )
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "fake-production")
    assert (
        preview.get("/companies", follow_redirects=False).headers["location"].startswith("/login")
    )
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID")
    remote = TestClient(client.app, base_url="http://127.0.0.1", client=("192.0.2.1", 50000))
    assert remote.get("/companies", follow_redirects=False).headers["location"].startswith("/login")


def test_login_failure_success_cookie_and_no_credential_leaks(client, ui_login):
    csrf = csrf_from_login(client)
    anonymous_id = client.cookies.get(COOKIE)
    failed = client.post("/login", data={"token": "incorrect-fake-secret", "csrf": csrf})
    assert failed.status_code == 401
    assert "incorrect-fake-secret" not in failed.text
    assert "incorrect" in failed.text
    assert client.get("/companies", follow_redirects=False).status_code == 303
    ui_login(client)
    authenticated_id = client.cookies.get(COOKIE)
    assert authenticated_id != anonymous_id and "test-token" not in authenticated_id
    assert client.get("/companies", headers={"Authorization": ""}).status_code == 200
    html = client.get("/").text
    assert "test-token" not in html and "Connect CRM token" not in html
    assert "not employee authentication" in html
    with transaction(client.app.state.engine) as session:
        row = session.get(BrowserSession, session_hash(authenticated_id))
        assert row.authenticated
        assert "test-token" not in repr(vars(row))
        assert authenticated_id not in repr(vars(row))


def test_unauthenticated_pages_and_writes_blocked_and_public_assets_safe(client):
    for path in ["/", "/companies", "/contacts/1", "/deals/1", "/tickets/1", "/assistant"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login?")
        assert "Relay CRM" not in response.text
    for method, path in [
        ("patch", "/ui-api/deals/1"),
        ("post", "/ui-api/assistant"),
        ("post", "/ui-api/logout"),
    ]:
        assert getattr(client, method)(path, json={}).status_code == 401
    assert client.get("/health", headers={"Authorization": ""}).status_code == 200
    for path in ["/login", "/ui-static/relay.css", "/ui-static/login.js"]:
        assert client.get(path, headers={"Authorization": ""}).status_code == 200
    assert client.get("/login").headers["cache-control"] == "no-store"


def test_login_csrf_and_redirect_safety(client):
    csrf = csrf_from_login(client)
    for headers, supplied in [({}, ""), ({}, "wrong"), ({"Origin": "https://other.example"}, csrf)]:
        response = client.post(
            "/login", data={"token": "test-token", "csrf": supplied}, headers=headers
        )
        assert response.status_code == 403
    response = client.post(
        "/login",
        data={"token": "test-token", "csrf": csrf, "next": "//other.example"},
        follow_redirects=False,
    )
    assert response.status_code == 303 and response.headers["location"] == "/"


def test_cookie_flags_expiration_logout_and_token_rotation(client, ui_login, monkeypatch):
    challenge = client.get("/login")
    cookie = challenge.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Secure" not in cookie
    csrf = ui_login(client)
    assert client.get("/ui-api/session").status_code == 200
    assert client.post("/ui-api/logout").status_code == 403
    assert client.post("/ui-api/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert not client.cookies.get(COOKIE)
    assert client.get("/", follow_redirects=False).status_code == 303
    csrf = ui_login(client)
    identifier = client.cookies.get(COOKIE)
    with transaction(client.app.state.engine, write=True) as session:
        row = session.get(BrowserSession, session_hash(identifier))
        row.expires_at = now() - timedelta(seconds=1)
    assert client.get("/ui-api/session").status_code == 401
    assert (
        client.patch("/ui-api/deals/1", json={}, headers={"X-CSRF-Token": csrf}).status_code == 401
    )
    ui_login(client)
    monkeypatch.setenv("CRM_TOKEN", "rotated-fake-token")
    assert client.get("/ui-api/session").status_code == 401


def test_https_cookie_secure(tmp_path):
    with TestClient(
        create_app(f"sqlite:///{tmp_path}/secure.db"), base_url="https://testserver"
    ) as client:
        response = client.get("/login")
        assert "Secure" in response.headers["set-cookie"]


def test_two_workers_can_start_against_fresh_database(tmp_path):
    url = f"sqlite:///{tmp_path}/concurrent-start.db"
    barrier = Barrier(2)

    def start_worker(_):
        barrier.wait(timeout=5)
        with TestClient(create_app(url)) as worker:
            return worker.get("/login").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(start_worker, range(2))) == [200, 200]


def test_session_shared_by_two_workers_and_official_api_stays_bearer_only(tmp_path, ui_login):
    url = f"sqlite:///{tmp_path}/shared.db"
    with TestClient(create_app(url)) as first, TestClient(create_app(url)) as second:
        csrf = ui_login(first)
        second.cookies.update(first.cookies)
        assert second.get("/companies").status_code == 200
        assert second.get("/ui-api/session").status_code == 200
        for client in [first, second]:
            for path in [
                "/crm/v3/objects/companies",
                "/crm/objects/2026-09/companies",
                "/openapi.json",
            ]:
                for header in ["", "Bearer invalid"]:
                    assert client.get(path, headers={"Authorization": header}).status_code == 401
                assert (
                    client.get(path, headers={"Authorization": "Bearer test-token"}).status_code
                    == 200
                )
            assert (
                client.post("/__agente", json={}, headers={"Authorization": ""}).status_code == 401
            )
        assert second.post("/ui-api/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert first.get("/ui-api/session").status_code == 401


def test_ui_deal_update_reuses_automations_and_requires_csrf(client, ui_login):
    assert migrate(client, fixture_data()).status_code == 204
    csrf = ui_login(client)
    deal = client.post(
        "/crm/v3/objects/deals",
        json={
            "properties": {
                "dealname": "Session deal",
                "pipeline": "default",
                "dealstage": "qualifiedtobuy",
                "commerciale": "new@example.it",
            }
        },
    ).json()
    path = "/ui-api/deals/" + deal["id"]
    body = {"properties": {"dealstage": "closedwon"}}
    for header in [
        {},
        {"X-CSRF-Token": "wrong"},
        {"X-CSRF-Token": csrf, "Origin": "https://other.example"},
    ]:
        assert client.patch(path, json=body, headers=header).status_code == 403
    assert (
        client.get("/crm/v3/objects/deals/" + deal["id"]).json()["properties"] == deal["properties"]
    )
    response = client.patch(path, json=body, headers={"Authorization": "", "X-CSRF-Token": csrf})
    assert response.status_code == 200 and response.json()["properties"]["dealstage"] == "closedwon"
    tickets = records(client, "tickets")
    assert any(
        r["properties"].get("subject") == "Avvio fornitura - " + deal["properties"]["dealname"]
        for r in tickets
    )
    assert (
        client.patch(
            path, json={"properties": {"dealstage": "closedlost"}}, headers={"X-CSRF-Token": csrf}
        ).status_code
        == 200
    )
    assert any(
        r["properties"].get("hs_task_subject") == "Richiamare: Session deal"
        for r in records(client, "tasks")
    )
    assert (
        client.patch(
            "/crm/v3/objects/deals/" + deal["id"], json=body, headers={"Authorization": ""}
        ).status_code
        == 401
    )


def test_ui_assistant_full_history_context_csv_and_fake_model(client, ui_login):
    assert migrate(client, fixture_data()).status_code == 204
    csrf = ui_login(client)
    body = {
        "context": {"now": "2026-12-02T10:00:00+01:00", "user": "new@example.it"},
        "messages": [
            {
                "role": "user",
                "content": "Leggi questo CSV",
                "attachments": [
                    {
                        "name": "test.csv",
                        "content_type": "text/csv",
                        "content": "codice;nome\nX1;Test",
                    }
                ],
            },
            {"role": "assistant", "content": "Vuoi procedere?"},
            {"role": "user", "content": "No"},
        ],
    }
    fake = Fake(answer("Va bene, nessuna modifica eseguita."))
    client.app.state.assistant_client = fake
    assert client.post("/ui-api/assistant", json=body).status_code == 403
    assert not fake.calls
    response = client.post(
        "/ui-api/assistant", json=body, headers={"Authorization": "", "X-CSRF-Token": csrf}
    )
    assert response.status_code == 200 and response.json()["reply"].startswith("Va bene")
    context = json.loads(fake.calls[0][1]["content"].split(": ", 1)[1])
    assert context == body["context"]
    assert [m["role"] for m in fake.calls[0][-3:]] == ["user", "assistant", "user"]
    assert "test.csv" in fake.calls[0][-3]["content"]
    assert fake.calls[0][-1]["content"] == "No"
    assert client.post("/__agente", json=body, headers={"Authorization": ""}).status_code == 401


def test_railway_https_origin_behind_http_proxy(client, monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "test-environment")
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "testserver")
    # The ASGI request is HTTP although the browser used HTTPS to Railway.
    from starlette.requests import Request

    from app.ui_auth import same_origin

    def request(headers):
        return Request(
            {
                "type": "http",
                "scheme": "http",
                "server": ("testserver", 80),
                "path": "/login",
                "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            }
        )

    assert same_origin(request({"origin": "https://testserver"}))
    assert same_origin(request({"referer": "https://testserver/login"}))
    assert not same_origin(
        request({"origin": "https://evil.example", "x-forwarded-host": "evil.example"})
    )
    assert not same_origin(request({"origin": "http://testserver"}))
    assert not same_origin(
        request({"origin": "https://testserver", "sec-fetch-site": "cross-site"})
    )
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID")
    assert not same_origin(request({"origin": "https://testserver"}))


def test_login_and_static_do_not_contain_business_records_or_frontend_bearer(client):
    assert migrate(client, fixture_data()).status_code == 204
    name = records(client, "companies")[0]["properties"]["name"]
    assert name not in client.get("/login").text
    for path in [
        "/ui-static/relay.js",
        "/ui-static/assistant-client.js",
        "/ui-static/assistant.js",
    ]:
        text = client.get(path).text
        assert "Bearer " not in text and "getToken" not in text
        assert name not in text
