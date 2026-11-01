from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from test_migration import fixture_data, migrate, records

BASE = "/crm/v3/objects"


def ready(client):
    assert migrate(client, fixture_data()).status_code == 204
    company = records(client, "companies")[0]
    response = client.post(
        BASE + "/deals",
        json={
            "properties": {
                "dealname": "Supply",
                "pipeline": "default",
                "dealstage": "qualifiedtobuy",
                "commerciale": "new@example.it",
            },
            "associations": [
                {
                    "to": {"id": company["id"]},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 5}],
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), company


def test_win_once_with_associations_and_owner(client):
    deal, company = ready(client)
    path = BASE + "/deals/" + deal["id"]
    for stage in ["closedwon", "qualifiedtobuy", "closedwon", "closedwon"]:
        assert client.patch(path, json={"properties": {"dealstage": stage}}).status_code == 200
    tickets = [
        r
        for r in records(client, "tickets")
        if r["properties"]["subject"] == "Avvio fornitura - Supply"
    ]
    assert len(tickets) == 1
    ticket = tickets[0]
    assert ticket["properties"]["assegnatario"] == "new@example.it"
    assert ticket["properties"]["hs_pipeline"] == "assistenza"
    assert ticket["properties"]["hs_pipeline_stage"] == "assistenza_open"
    for kind, identifier in [("deals", deal["id"]), ("companies", company["id"])]:
        links = client.get(BASE + "/tickets/" + ticket["id"] + "/associations/" + kind).json()[
            "results"
        ]
        assert {r["id"] for r in links} == {identifier}


def test_lost_exactly_180_days_and_once(client):
    deal, _ = ready(client)
    path = BASE + "/deals/" + deal["id"]
    assert client.patch(path, json={"properties": {"dealstage": "closedlost"}}).status_code == 200
    task = records(client, "tasks")[0]
    assert datetime.fromisoformat(task["properties"]["hs_timestamp"]) - datetime.fromisoformat(
        task["createdAt"]
    ) == timedelta(days=180)
    assert task["properties"]["hs_task_subject"] == "Richiamare: Supply"
    assert task["properties"]["hs_task_status"] == "NOT_STARTED"
    for stage in ["qualifiedtobuy", "closedlost"]:
        assert client.patch(path, json={"properties": {"dealstage": stage}}).status_code == 200
    assert len(records(client, "tasks")) == 1


def test_direct_create_and_batch_and_renewal_exclusion(client):
    ready(client)
    response = client.post(
        BASE + "/deals/batch/create",
        json={
            "inputs": [
                {"properties": {"dealname": "Direct", "dealstage": "closedwon"}},
                {
                    "properties": {
                        "dealname": "Lost",
                        "pipeline": "default",
                        "dealstage": "closedlost",
                    }
                },
                {"properties": {"dealname": "Renewal", "pipeline": "rinnovi", "dealstage": "R3"}},
            ]
        },
    )
    assert response.status_code == 201, response.text
    assert len(records(client, "tickets")) == 2  # one imported plus one direct-created
    assert len(records(client, "tasks")) == 1


def test_concurrent_win_idempotent(client):
    deal, _ = ready(client)

    def win(_):
        return client.patch(
            BASE + "/deals/" + deal["id"], json={"properties": {"dealstage": "closedwon"}}
        ).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(win, range(8))) == [200] * 8
    assert len(records(client, "tickets")) == 2


def test_imported_terminal_edit_no_trigger_and_batch_rollback(client):
    ready(client)
    imported = next(r for r in records(client, "deals") if r["properties"].get("id_legacy") == "d1")
    assert (
        client.patch(
            BASE + "/deals/" + imported["id"], json={"properties": {"dealname": "Rename"}}
        ).status_code
        == 200
    )
    assert len(records(client, "tickets")) == 1
    response = client.post(
        BASE + "/deals/batch/create",
        json={
            "inputs": [
                {"properties": {"dealname": "Should roll back", "dealstage": "closedwon"}},
                {
                    "properties": {"dealstage": "closedwon"},
                    "associations": [
                        {
                            "to": {"id": "missing"},
                            "types": [
                                {"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 5}
                            ],
                        }
                    ],
                },
            ]
        },
    )
    assert response.status_code == 404
    assert len(records(client, "tickets")) == 1


def test_marker_survives_new_app_and_generated_record_archive(client):
    from fastapi.testclient import TestClient

    from app.main import create_app

    deal, _ = ready(client)
    path = BASE + "/deals/" + deal["id"]
    assert (
        client.post(
            BASE + "/deals/batch/update",
            json={"inputs": [{"id": deal["id"], "properties": {"dealstage": "closedwon"}}]},
        ).status_code
        == 200
    )
    generated = next(
        r
        for r in records(client, "tickets")
        if r["properties"]["subject"] == "Avvio fornitura - Supply"
    )
    assert client.delete(BASE + "/tickets/" + generated["id"]).status_code == 204
    url = client.app.state.engine.url.render_as_string(hide_password=False)
    with TestClient(create_app(url), headers={"Authorization": "Bearer test-token"}) as restarted:
        for stage in ["qualifiedtobuy", "closedwon"]:
            assert (
                restarted.patch(path, json={"properties": {"dealstage": stage}}).status_code == 200
            )
        assert len(records(restarted, "tickets")) == 1  # only the historical imported ticket


def test_r12_never_overwrites_explicit_company(client):
    ready(client)
    other = client.post(
        BASE + "/companies", json={"properties": {"name": "Other", "domain": "other.it"}}
    ).json()
    person = client.post(
        BASE + "/contacts",
        json={
            "properties": {"email": "person@b.it"},
            "associations": [
                {
                    "to": {"id": other["id"]},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 1}],
                }
            ],
        },
    ).json()
    path = BASE + "/contacts/" + person["id"]
    assert client.patch(path, json={"properties": {"email": "changed@a.it"}}).status_code == 200
    linked = client.get(path + "/associations/companies").json()["results"]
    assert {r["id"] for r in linked} == {other["id"]}
