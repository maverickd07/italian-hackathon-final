from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Object, make_engine, transaction
from app.main import create_app


def create(client, base, properties, associations=None):
    body = {"properties": properties}
    if associations is not None:
        body["associations"] = associations
    response = client.post(base, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def assert_record(record, kind):
    assert set(record) >= {"id", "properties", "createdAt", "updatedAt", "archived"}
    assert isinstance(record["id"], str)
    assert isinstance(record["archived"], bool)
    props = record["properties"]
    assert props["hs_object_id"] == record["id"]
    assert props["createdate"] == record["createdAt"]
    modified = "lastmodifieddate" if kind == "contacts" else "hs_lastmodifieddate"
    assert props[modified] == record["updatedAt"]
    datetime.fromisoformat(record["createdAt"])
    datetime.fromisoformat(record["updatedAt"])


@pytest.mark.parametrize(
    "kind,singular,numeric",
    [
        ("contacts", "contact", "0-1"),
        ("companies", "company", "0-2"),
        ("deals", "deal", "0-3"),
        ("tickets", "ticket", "0-5"),
        ("notes", "note", "0-46"),
    ],
)
def test_crud_and_aliases(client, prefix, kind, singular, numeric):
    base = f"{prefix}/{kind}"
    original = {
        "name": "Caffè 東京",
        "external_id": "external-1",
        "metadata": {"a": [1, False]},
        "empty": "",
    }
    record = create(client, f"{prefix}/{numeric}", original)
    assert_record(record, kind)
    for alias in (kind, singular, numeric):
        assert client.get(f"{prefix}/{alias}/{record['id']}").json() == record
    lookup = f"{prefix}/{singular}/external-1?idProperty=external_id"
    assert client.get(lookup).json() == record
    projected = client.get(lookup + "&properties=name,missing").json()
    assert "metadata" not in projected["properties"]
    assert "missing" not in projected["properties"]
    assert_record(projected, kind)
    patched = client.patch(lookup, json={"properties": {"name": "Changed", "empty": ""}})
    assert patched.status_code == 200
    assert patched.json()["properties"]["metadata"] == original["metadata"]
    assert patched.json()["createdAt"] == record["createdAt"]
    assert patched.json()["updatedAt"] >= record["updatedAt"]
    assert (
        client.patch(f"{base}/{record['id']}", json={"properties": {"next": "ok"}}).status_code
        == 200
    )
    assert client.delete(f"{base}/{record['id']}").status_code == 204
    assert client.delete(f"{base}/{record['id']}").content == b""
    assert client.get(f"{base}/{record['id']}").status_code == 404
    archived = client.get(f"{base}/{record['id']}?archived=true").json()
    assert archived["archived"] is True
    assert client.get(base).json()["results"] == []
    assert len(client.get(base + "?archived=true").json()["results"]) == 1
    assert client.post(base + "/search", json={}).json() == {"total": 0, "results": []}


def test_list_pagination_limits_and_projection(client, prefix):
    base = prefix + "/contacts"
    ids = {
        create(client, base, {"firstname": str(i), "email": f"{i}@example.com"})["id"]
        for i in range(13)
    }
    first = client.get(base).json()
    assert len(first["results"]) == 10
    second = client.get(
        base, params={"after": first["paging"]["next"]["after"], "properties": "email"}
    ).json()
    assert len(second["results"]) == 3
    assert "paging" not in second
    assert ids == {r["id"] for r in first["results"] + second["results"]}
    assert "firstname" not in second["results"][0]["properties"]
    assert len(client.get(base + "?limit=100").json()["results"]) == 13
    for limit in (0, -1, 101):
        assert client.get(base, params={"limit": limit}).status_code == 400
    assert client.get(base + "?after=garbage").status_code == 400
    # Removing an already-returned record must not skip the next page.
    client.delete(base + "/" + first["results"][0]["id"])
    assert (
        len(client.get(base, params={"after": first["paging"]["next"]["after"]}).json()["results"])
        == 3
    )


def test_batch_endpoints(client, prefix):
    base = prefix + "/companies"
    response = client.post(
        base + "/batch/create",
        json={
            "inputs": [
                {"properties": {"name": "A", "external": "a"}},
                {"properties": {"name": "B", "external": "b"}},
            ]
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "COMPLETE"
    assert "startedAt" in body and "completedAt" in body
    inputs = [{"id": r["id"]} for r in body["results"]]
    read = client.post(base + "/batch/read", json={"inputs": inputs, "properties": ["name"]})
    assert read.status_code == 200
    assert len(read.json()["results"]) == 2
    assert "external" not in read.json()["results"][0]["properties"]
    read_external = client.post(
        base + "/batch/read", json={"inputs": [{"id": "a"}], "idProperty": "external"}
    )
    assert read_external.json()["results"][0]["id"] == inputs[0]["id"]
    update = client.post(
        base + "/batch/update",
        json={
            "inputs": [
                {**inputs[0], "properties": {"phone": "123"}},
                {"id": "b", "idProperty": "external", "properties": {"phone": "456"}},
            ]
        },
    )
    assert update.status_code == 200
    assert [r["properties"]["phone"] for r in update.json()["results"]] == ["123", "456"]
    assert client.post(base + "/batch/archive", json={"inputs": inputs}).status_code == 204
    archived = client.post(base + "/batch/read?archived=true", json={"inputs": inputs}).json()
    assert all(record["archived"] for record in archived["results"])
    assert client.get(base).json()["results"] == []


@pytest.mark.parametrize(
    "operator,operands,expected",
    [
        ("EQ", {"value": "10"}, {"A"}),
        ("NEQ", {"value": "10"}, {"B", "C"}),
        ("LT", {"value": "20"}, {"A"}),
        ("LTE", {"value": "20"}, {"A", "B"}),
        ("GT", {"value": "20"}, {"C"}),
        ("GTE", {"value": "20"}, {"B", "C"}),
        ("BETWEEN", {"value": "10", "highValue": "20"}, {"A", "B"}),
        ("IN", {"values": ["10", "100"]}, {"A", "C"}),
        ("NOT_IN", {"values": ["10", "100"]}, {"B"}),
        ("HAS_PROPERTY", {}, {"A", "B", "C"}),
        ("NOT_HAS_PROPERTY", {}, {"D", "E", "F"}),
        ("CONTAINS_TOKEN", {"value": "red"}, {"A", "C"}),
        ("NOT_CONTAINS_TOKEN", {"value": "red"}, {"B"}),
    ],
)
def test_every_search_operator(client, prefix, operator, operands, expected):
    base = prefix + "/deals"
    for props in [
        {"dealname": "A", "amount": "10", "description": "red apple"},
        {"dealname": "B", "amount": "20", "description": "hundred berries"},
        {"dealname": "C", "amount": "100", "description": "RED banana"},
        {"dealname": "D"},
        {"dealname": "E", "amount": ""},
        {"dealname": "F", "amount": None},
    ]:
        create(client, base, props)
    prop = "description" if "CONTAINS_TOKEN" in operator else "amount"
    response = client.post(
        base + "/search",
        json={
            "filterGroups": [
                {
                    "filters": [
                        {"propertyName": prop, "operator": operator, **operands},
                    ]
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert {r["properties"]["dealname"] for r in response.json()["results"]} == expected
    assert response.json()["total"] == len(expected)


def test_search_groups_sort_query_cursor(client, prefix):
    base = prefix + "/contacts"
    for props in [
        {"firstname": "Ada", "email": "ada@example.com", "score": "100", "team": "x"},
        {"firstname": "Bob", "email": "bob@example.com", "score": "20", "team": "x"},
        {"firstname": "Cara", "email": "cara@elsewhere.org", "score": "10", "team": "y"},
    ]:
        create(client, base, props)
    body = {
        "filterGroups": [
            {
                "filters": [
                    {"propertyName": "team", "operator": "EQ", "value": "X"},
                    {"propertyName": "score", "operator": "GT", "value": "50"},
                ]
            },
            {"filters": [{"propertyName": "firstname", "operator": "EQ", "value": "cara"}]},
        ],
        "sorts": [{"propertyName": "score", "direction": "DESCENDING"}],
        "limit": 1,
        "properties": ["firstname"],
    }
    first = client.post(base + "/search", json=body).json()
    assert first["total"] == 2
    assert first["results"][0]["properties"]["firstname"] == "Ada"
    assert "score" not in first["results"][0]["properties"]
    body["after"] = first["paging"]["next"]["after"]
    second = client.post(base + "/search", json=body).json()
    assert second["results"][0]["properties"]["firstname"] == "Cara"
    assert "paging" not in second
    results = client.post(base + "/search", json={"query": "EXAMPLE", "sorts": ["score"]}).json()
    assert [r["properties"]["firstname"] for r in results["results"]] == ["Bob", "Ada"]
    wildcard = client.post(
        base + "/search",
        json={
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "email",
                            "operator": "CONTAINS_TOKEN",
                            "value": "*@example.com",
                        },
                    ]
                }
            ]
        },
    ).json()
    assert wildcard["total"] == 2
    literal = client.post(base + "/search", json={"query": "%"}).json()
    assert literal["total"] == 0


def test_search_limits_dates_and_empty_input(client, prefix):
    base = prefix + "/contacts"
    assert client.post(base + "/search", json={}).json() == {"total": 0, "results": []}
    for i in range(12):
        create(client, base, {"firstname": str(i)})
    assert len(client.post(base + "/search", json={}).json()["results"]) == 10
    assert len(client.post(base + "/search", json={"limit": 200}).json()["results"]) == 12
    for body in [
        {"limit": 201},
        {"limit": 0},
        {"after": "bad"},
        {"after": -1},
        {"sorts": [{"propertyName": "x", "direction": "wrong"}]},
        {"filterGroups": [{"filters": [{"propertyName": "a", "operator": "EQ"}]}]},
        {"filterGroups": [{"filters": [{"propertyName": "a", "operator": "UNKNOWN"}]}]},
    ]:
        assert client.post(base + "/search", json=body).status_code == 400
    date_filter = {
        "filterGroups": [
            {
                "filters": [
                    {
                        "propertyName": "createdate",
                        "operator": "BETWEEN",
                        "value": "0",
                        "highValue": "4102444800000",
                    }
                ]
            }
        ]
    }
    assert client.post(base + "/search", json=date_filter).json()["total"] == 12


def test_associations_create_list_delete_and_reverse(client, prefix):
    company = create(client, prefix + "/companies", {"name": "Acme"})
    contact = create(
        client,
        prefix + "/contacts",
        {"firstname": "Ada"},
        [
            {
                "to": {"id": company["id"]},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 279}],
            }
        ],
    )
    path = f"{prefix}/contacts/{contact['id']}/associations/company"
    result = client.get(path).json()["results"]
    if "2026-09" in prefix:
        assert str(result[0]["toObjectId"]) == company["id"]
        assert result[0]["associationTypes"][0]["typeId"] == 279
    else:
        assert result == [{"id": company["id"], "type": "contact_to_company_unlabeled"}]
    reverse = client.get(f"{prefix}/companies/{company['id']}?associations=contacts").json()
    assert reverse["associations"]["contacts"]["results"][0]["id"] == contact["id"]
    typed = path + f"/{company['id']}/279"
    assert client.put(typed).status_code == 200
    assert client.put(typed).status_code == 200
    assert len(client.get(path).json()["results"]) == 1
    assert client.delete(typed).status_code == 204
    assert client.get(path).json() == {"results": []}
    assert (
        "contacts"
        not in client.get(f"{prefix}/companies/{company['id']}?associations=contacts").json()[
            "associations"
        ]
    )
    types = client.get("/crm/v3/associations/contact/company/types").json()
    assert {"id": "279", "name": "contact_to_company_unlabeled"} in types["results"]
    labels = client.get("/crm/associations/2026-09/0-1/0-2/labels").json()
    assert {"category": "HUBSPOT_DEFINED", "typeId": 279, "label": None} in labels["results"]
    assert client.get("/crm/v4/associations/contacts/companies/labels").json() == labels


def test_atomic_failures_and_errors(client, prefix):
    base = prefix + "/contacts"
    bad = {
        "properties": {"firstname": "Rollback"},
        "associations": [
            {
                "to": {"id": "missing"},
                "types": [{"associationTypeId": 279}],
            }
        ],
    }
    assert client.post(base, json=bad).status_code == 404
    assert client.get(base).json()["results"] == []
    assert (
        client.post(
            base + "/batch/create", json={"inputs": [{"properties": {"firstname": "A"}}, bad]}
        ).status_code
        == 404
    )
    assert client.get(base).json()["results"] == []
    record = create(client, base, {"firstname": "Original"})
    response = client.post(
        base + "/batch/update",
        json={
            "inputs": [
                {"id": record["id"], "properties": {"firstname": "Changed"}},
                {"id": "missing", "properties": {"firstname": "Bad"}},
            ]
        },
    )
    assert response.status_code == 404
    assert client.get(base + "/" + record["id"]).json()["properties"]["firstname"] == "Original"
    for response in [
        client.get(base + "/missing"),
        client.get(prefix + "/unknown"),
        client.post(base, json={}),
        client.get(base + "?limit=200"),
        client.post(base + "/batch/create", json={"inputs": [{"properties": {}}] * 101}),
        client.get("/not-found"),
    ]:
        assert response.status_code in {400, 404}
        error = response.json()
        assert set(error) == {"status", "message", "correlationId", "category"}
        assert error["status"] == "error"
        UUID(error["correlationId"])


def test_persistence_and_concurrent_updates(tmp_path):
    url = f"sqlite:///{tmp_path}/persistent.db"
    with TestClient(create_app(url), headers={"Authorization": "Bearer test-token"}) as client:
        record = create(client, "/crm/v3/objects/contact", {"firstname": "Persist"})
        path = "/crm/v3/objects/contacts/" + record["id"]

        def update(i):
            return client.patch(path, json={"properties": {f"field_{i}": str(i)}}).status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            assert list(pool.map(update, range(20))) == [200] * 20
    with TestClient(create_app(url), headers={"Authorization": "Bearer test-token"}) as restarted:
        props = restarted.get(path).json()["properties"]
        assert props["firstname"] == "Persist"
        assert all(props[f"field_{i}"] == str(i) for i in range(20))
        assert restarted.get("/health").json() == {"status": "ok", "version": "2026-09", "ui": restarted.get("/health").json()["ui"]}
        restarted.delete(path)
    engine = make_engine(url)
    with transaction(engine) as session:
        stored = session.scalar(select(Object).where(Object.id == record["id"]))
        assert stored.archived is True
        assert stored.properties["firstname"] == "Persist"
    engine.dispose()


def test_no_real_llm_and_no_brand_in_ui(client):
    with pytest.raises(AssertionError, match="fake client"):
        httpx.get("https://api.openai.com/v1/models")
    assert "hubspot" not in client.get("/docs").text.lower()
    assert client.get("/openapi.json").json()["info"]["title"] == "Relay CRM API"


def test_railway_refuses_ephemeral_sqlite(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "test-production")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        make_engine("sqlite:///unsafe.db")


def test_association_batches_and_modern_write(client):
    base = "/crm/v3/objects"
    contact = create(client, base + "/contacts", {"firstname": "Batch"})
    company = create(client, base + "/companies", {"name": "Company"})
    assoc = "/crm/v3/associations/contacts/companies/batch"
    item = {
        "from": {"id": contact["id"]},
        "to": {"id": company["id"]},
        "type": "contact_to_company",
    }
    made = client.post(assoc + "/create", json={"inputs": [item]})
    assert made.status_code == 201
    assert made.json()["status"] == "COMPLETE"
    read = client.post(assoc + "/read", json={"inputs": [{"id": contact["id"]}]})
    assert read.json()["results"][0]["to"] == [{"id": company["id"], "type": "contact_to_company"}]
    assert client.post(assoc + "/archive", json={"inputs": [item]}).status_code == 204
    assert (
        client.post(assoc + "/read", json={"inputs": [{"id": contact["id"]}]}).json()["results"][0][
            "to"
        ]
        == []
    )
    path = f"/crm/objects/2026-09/contacts/{contact['id']}/associations/companies/{company['id']}"
    assert client.put(path, json=[{"associationTypeId": 279}]).status_code == 200
    assert client.delete(path).status_code == 204
    assert client.get(path.rsplit("/", 1)[0]).json()["results"] == []


def test_association_paging_and_search(client, prefix):
    contact = create(client, prefix + "/contacts", {"firstname": "Associate"})
    companies = [create(client, prefix + "/companies", {"name": f"Company {i}"}) for i in range(3)]
    path = f"{prefix}/contacts/{contact['id']}/associations/companies"
    for company in companies:
        assert client.put(f"{path}/{company['id']}/279").status_code == 200
    first = client.get(path + "?limit=2").json()
    assert len(first["results"]) == 2
    last = client.get(path, params={"limit": 2, "after": first["paging"]["next"]["after"]}).json()
    assert len(last["results"]) == 1
    assert "paging" not in last
    result = client.post(
        prefix + "/contacts/search",
        json={
            "filters": [
                {
                    "propertyName": "associations.company",
                    "operator": "EQ",
                    "value": companies[0]["id"],
                },
            ]
        },
    ).json()
    assert result["total"] == 1
    assert result["results"][0]["id"] == contact["id"]
    assert client.put(f"{path}/{companies[0]['id']}/3").status_code == 400


def test_readonly_metadata_and_ambiguous_identifier(client, prefix):
    base = prefix + "/contacts"
    assert client.post(base, json={"properties": {"hs_object_id": "forced"}}).status_code == 400
    record = create(client, base, {"email": "ADA@EXAMPLE.COM", "external": "duplicate"})
    assert client.get(base + "/ada@example.com?idProperty=email").json()["id"] == record["id"]
    create(client, base, {"external": "duplicate"})
    assert client.get(base + "/duplicate?idProperty=external").status_code == 409
    assert (
        client.patch(
            base + "/duplicate?idProperty=external", json={"properties": {"firstname": "Wrong"}}
        ).status_code
        == 409
    )


def test_concurrent_updates_on_configured_database(client):
    record = create(client, "/crm/v3/objects/contacts", {"firstname": "Concurrent"})
    path = "/crm/v3/objects/contacts/" + record["id"]

    def update(i):
        return client.patch(path, json={"properties": {f"concurrent_{i}": str(i)}}).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(update, range(24))) == [200] * 24
    props = client.get(path).json()["properties"]
    assert all(props[f"concurrent_{i}"] == str(i) for i in range(24))


def test_second_app_instance_preserves_records_and_associations(client):
    base = "/crm/v3/objects"
    company = create(client, base + "/companies", {"name": "Durable Company"})
    contact = create(
        client,
        base + "/contacts",
        {"firstname": "Durable"},
        [
            {
                "to": {"id": company["id"]},
                "types": [{"associationTypeId": 279}],
            }
        ],
    )
    url = client.app.state.engine.url.render_as_string(hide_password=False)
    with TestClient(create_app(url), headers={"Authorization": "Bearer test-token"}) as second:
        record = second.get(f"{base}/contacts/{contact['id']}?associations=companies").json()
        assert record["properties"]["firstname"] == "Durable"
        assert record["associations"]["companies"]["results"][0]["id"] == company["id"]
        assert (
            second.patch(
                f"{base}/contacts/{contact['id']}", json={"properties": {"phone": "123"}}
            ).status_code
            == 200
        )
    assert client.get(f"{base}/contacts/{contact['id']}").json()["properties"]["phone"] == "123"
