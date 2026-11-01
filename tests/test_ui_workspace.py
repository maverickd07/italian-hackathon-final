"""Personal UI tests against migrated data; no model calls or backend changes."""

import html
import json
import re
from datetime import UTC, datetime
from time import perf_counter

import pytest
from test_migration import fixture_data, migrate, records

from app.db import Association, ListMember, Metadata, Object, transaction


@pytest.fixture(autouse=True)
def browser_session(client, ui_login):
    ui_login(client)


def context(response):
    return json.loads(re.search(r'id="relay-ui-context">(.*?)</script>', response.text).group(1))


def kpi(response, key):
    return re.search(rf'data-kpi="{key}">(.*?)<', response.text).group(1)


def test_identity_and_direct_report_scope(client):
    assert migrate(client, fixture_data()).status_code == 204
    company = records(client, "companies")[0]["id"]
    year = datetime.now(UTC).year
    with transaction(client.app.state.engine, write=True) as session:
        user = session.get(Metadata, ("users", "u2"))
        user.value = {**user.value, "ruolo": "Commerciale", "responsabile": "manager"}
        for identifier, email, role, manager in [
            ("manager", "manager@example.it", "Responsabile di zona", "director"),
            ("director", "director@example.it", "Direttore commerciale", ""),
            ("inactive", "inactive@example.it", "Commerciale", "manager"),
        ]:
            session.add(
                Metadata(
                    namespace="users",
                    key=identifier,
                    value={
                        "id_utente": identifier,
                        "nome": identifier.title(),
                        "cognome": "Test",
                        "email": email,
                        "ruolo": role,
                        "responsabile": manager,
                        "attivo": "N" if identifier == "inactive" else "S",
                    },
                )
            )
        for identifier, owner, value, stage in [
            ("90001", "new@example.it", "100", "qualifiedtobuy"),
            ("90002", "manager@example.it", "50", "contractsent"),
            ("90003", "director@example.it", "200", "appointmentscheduled"),
            ("90004", "inactive@example.it", "900", "qualifiedtobuy"),
            ("90005", "new@example.it", "70", "closedwon"),
        ]:
            session.add(
                Object(
                    id=identifier,
                    object_type="deals",
                    properties={
                        "dealname": "Scope " + identifier,
                        "commerciale": owner,
                        "amount": value,
                        "pipeline": "default",
                        "dealstage": stage,
                        "closedate": f"{year}-01-02T10:00:00Z",
                    },
                )
            )
        session.add(
            Object(
                id="90101",
                object_type="tasks",
                properties={
                    "hs_task_subject": "Richiamare: Scope 90001",
                    "hs_task_status": "NOT_STARTED",
                    "hs_timestamp": "2020-01-01T10:00:00Z",
                },
            )
        )
        session.add(
            Object(
                id="90102",
                object_type="tasks",
                properties={
                    "hs_task_subject": "Richiamare: Future",
                    "hs_task_status": "NOT_STARTED",
                    "hs_timestamp": "2099-01-01T10:00:00Z",
                },
            )
        )
        session.add(
            Object(
                id="90201",
                object_type="tickets",
                properties={
                    "subject": "Avvio fornitura - Scope 90001",
                    "assegnatario": "new@example.it",
                    "hs_pipeline": "assistenza",
                    "hs_pipeline_stage": "assistenza_open",
                },
            )
        )
        session.flush()
        for source, target, kind in [
            ("90001", "90101", "tasks"),
            ("90001", "90102", "tasks"),
            ("90001", company, "companies"),
            ("90005", company, "companies"),
        ]:
            session.add(
                Association(
                    from_type="deals",
                    from_id=source,
                    to_type=kind,
                    to_id=target,
                    type_id=5 if kind == "companies" else 215,
                )
            )
        if not session.get(ListMember, ("1", company)):
            session.add(ListMember(list_id="1", record_id=company))
    public = {"Authorization": "Bearer test-token"}
    default = client.get("/", headers=public)
    assert context(default)["user"] == "new@example.it"
    assert "inactive@example.it" not in default.text
    assert kpi(default, "open-deals-count") == "1"
    assert "€ 100,00" in kpi(default, "open-deals-value")
    assert kpi(default, "won-value") == "€ 70,00"
    assert kpi(default, "dormant-count") == "1"
    assert "overdue-badge" in default.text
    assert "Richiamare: Scope 90001" in default.text
    assert "Richiamare: Future" not in default.text
    assert "Avvio fornitura - Scope 90001" in default.text
    assert "My team" not in default.text
    manager = client.get("/?user=manager@example.it&team=1", headers=public)
    assert kpi(manager, "open-deals-count") == "2"
    assert "€ 150,00" in kpi(manager, "open-deals-value")
    assert "My team" in manager.text
    director = client.get("/?user=director@example.it&team=1", headers=public)
    assert kpi(director, "open-deals-count") == "2"
    assert "€ 250,00" in kpi(director, "open-deals-value")
    # The director includes the regional manager, not their grandchildren.
    assert "Scope 90001" not in director.text
    inactive = client.get("/?user=inactive@example.it", headers=public)
    assert context(inactive)["user"] == "new@example.it"
    board = client.get("/deals?view=my&user=manager@example.it", headers=public)
    assert "Scope 90002" in board.text and "Scope 90001" not in board.text


def test_company_revenue_sort_filter_and_stable_pagination(client):
    assert migrate(client, fixture_data()).status_code == 204
    with transaction(client.app.state.engine, write=True) as session:
        for i in range(55):
            session.add(
                Object(
                    id=str(91000 + i),
                    object_type="companies",
                    properties={
                        "name": f"Rank {i:02d}",
                        "id_legacy": str(i),
                        "fatturato_2025": str(i),
                        "classe_cliente": "A" if i >= 50 else "C",
                    },
                )
            )
    first = client.get("/companies?q=Rank", headers={"Authorization": "Bearer test-token"})
    assert first.status_code == 200
    assert first.text.index("Rank 54") < first.text.index("Rank 53")
    assert first.text.count('class="record-link"') == 50
    url = html.unescape(re.search(r'href="([^"]+)"[^>]*>Next page', first.text).group(1))
    second = client.get(url, headers={"Authorization": "Bearer test-token"})
    assert second.status_code == 200 and second.text.count('class="record-link"') == 5
    assert "Rank 04" in second.text and "Rank 05" not in second.text
    only_a = client.get(
        "/companies?q=Rank&customer_class=A", headers={"Authorization": "Bearer test-token"}
    )
    assert only_a.text.count('class="record-link"') == 5
    assert "class-A" in only_a.text and "Sinergia #54" in only_a.text
    assert "Unclassified" not in first.text


def test_new_pages_and_record_companions_are_fast_and_public(client):
    assert migrate(client, fixture_data()).status_code == 204
    paths = [
        "/",
        "/assistant",
        "/companies?customer_class=A",
        "/companies?customer_class=dormant",
        "/deals?view=my",
        "/tickets?view=my",
        "/dormant-customers?view=my",
    ]
    for kind in ["deals", "tickets"]:
        for row in records(client, kind):
            paths.append(f"/{kind}/{row['id']}")
    for path in paths:
        start = perf_counter()
        response = client.get(path, headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200, (path, response.text)
        assert perf_counter() - start < 1
        if path == "/assistant":
            assert 'id="companion-toggle"' not in response.text
            assert 'id="assistant-drawer"' not in response.text
            assert response.text.count("data-chat-surface=") == 1
            assert "chat-pet-arrival" in response.text
        else:
            assert "companion-toggle" in response.text
        assert "hubspot" not in response.text.lower()
    assert client.get("/health").json()["ui"]["today"] == "/"
    assert client.get("/health").json()["ui"]["assistant"] == "/assistant"
    company = records(client, "companies")[0]
    response = client.get("/companies/" + company["id"])
    assert "Ask me about " + company["properties"]["name"] in response.text
    assert context(response)["record"] == company["properties"]["name"]
    # Rendering a chat page never calls the assistant endpoint.
    assert (
        "assistant-client.js"
        in client.get("/assistant", headers={"Authorization": "Bearer test-token"}).text
    )
