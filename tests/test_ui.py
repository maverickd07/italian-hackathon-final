"""Migrated database UI smoke tests; no external or model calls."""

from time import perf_counter

import pytest
from test_migration import fixture_data, migrate, records

from app.db import Object, transaction


@pytest.fixture(autouse=True)
def browser_session(client, ui_login):
    ui_login(client)


def test_every_ui_page_is_authenticated_and_fast_on_migrated_db(client):
    assert migrate(client, fixture_data()).status_code == 204
    companies = records(client, "companies")
    contacts = records(client, "contacts")
    paths = list(client.get("/health").json()["ui"].values())
    paths += [
        "/deals?pipeline=rinnovi",
        "/companies?q=New",
        "/contacts?q=Anna",
        "/tickets?stage=assistenza_open&priority=HIGH&assegnatario=u2",
    ]
    for kind, rows in [("companies", companies), ("contacts", contacts)]:
        for row in rows:
            for tab in (
                ["contacts", "deals", "tickets", "activity"]
                if kind == "companies"
                else ["companies", "deals", "tickets", "activity"]
            ):
                paths.append(f"/{kind}/{row['id']}?tab={tab}")
    for path in paths:
        start = perf_counter()
        response = client.get(path, headers={"Authorization": "Bearer test-token"})
        elapsed = perf_counter() - start
        assert response.status_code == 200, (path, response.text)
        assert elapsed < 1, (path, elapsed)
        assert "Relay CRM" in response.text
        assert "hubspot" not in response.text.lower()
    assert (
        client.get(
            "/ui-static/relay.js", headers={"Authorization": "Bearer test-token"}
        ).status_code
        == 200
    )
    assert client.get("/crm/v3/objects/companies", headers={"Authorization": ""}).status_code == 401
    assert client.post("/__agente", json={}, headers={"Authorization": ""}).status_code == 401
    company = companies[0]
    page = client.get("/companies/" + company["id"]).text
    assert "Migrated from Sinergia" in page
    assert "old" in page and "a.it" in page


def test_public_board_cannot_write_without_token(client):
    assert migrate(client, fixture_data()).status_code == 204
    deal = records(client, "deals")[0]
    path = "/crm/v3/objects/deals/" + deal["id"]
    assert (
        client.patch(
            path, json={"properties": {"dealstage": "closedlost"}}, headers={"Authorization": ""}
        ).status_code
        == 401
    )
    assert client.get(path).json()["properties"] == deal["properties"]
    assert 'class="move-deal" disabled' in client.get("/deals").text


def test_directory_pagination_and_activity_order(client):
    assert migrate(client, fixture_data()).status_code == 204
    with transaction(client.app.state.engine, write=True) as session:
        for i in range(55):
            session.add(
                Object(
                    id=str(10000 + i), object_type="companies", properties={"name": f"Paging {i}"}
                )
            )
    first = client.get("/companies?q=Paging", headers={"Authorization": "Bearer test-token"})
    # Counting record links avoids depending on page headings or duplicated text.
    assert first.text.count('class="record-link"') == 50
    # Extract escaped next URL using the standard library, no parser dependency.
    import html
    import re

    next_url = html.unescape(re.search(r'href="([^"]+)"[^>]*>Next page', first.text).group(1))
    second = client.get(next_url, headers={"Authorization": "Bearer test-token"})
    assert second.status_code == 200
    assert second.text.count('class="record-link"') == 5


def test_timeline_uses_activity_timestamp_and_paginates(client):
    import html
    import re

    from app.db import Association

    assert migrate(client, fixture_data()).status_code == 204
    contact = records(client, "contacts")[0]
    with transaction(client.app.state.engine, write=True) as session:
        for i in range(55):
            identifier = str(50000 + i)
            session.add(
                Object(
                    id=identifier,
                    object_type="notes",
                    properties={
                        "hs_timestamp": f"2025-02-{(i // 24) + 1:02d}T{i % 24:02d}:00:00Z",
                        "hs_note_body": f"Timeline test {i:02d}",
                    },
                )
            )
        session.flush()
        for i in range(55):
            session.add(
                Association(
                    from_type="contacts",
                    from_id=contact["id"],
                    to_type="notes",
                    to_id=str(50000 + i),
                    type_id=201,
                )
            )
    page = client.get(
        f"/contacts/{contact['id']}?tab=activity", headers={"Authorization": "Bearer test-token"}
    )
    assert page.status_code == 200
    assert page.text.index("Timeline test 54") < page.text.index("Timeline test 53")
    assert page.text.count("Timeline test ") == 50
    url = html.unescape(re.search(r'href="([^"]+)"[^>]*>Next page', page.text).group(1))
    next_page = client.get(url, headers={"Authorization": "Bearer test-token"})
    assert next_page.status_code == 200
    assert next_page.text.count("Timeline test ") == 5
