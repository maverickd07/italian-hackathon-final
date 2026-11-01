"""Bounded release stress: isolated fixtures, fake model, never production data."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from test_assistant import NOW, USER, call, create, props
from test_assistant import crm as _crm

from app.db import Object, transaction


@pytest.fixture
def crm(client):
    return _crm.__wrapped__(client)


def path(i, kind):
    return ("/crm/v3/objects/" if i % 2 else "/crm/objects/2026-09/") + kind


def test_sixty_mixed_version_transitions_preserve_fields_and_once_only_effects(crm):
    identifier = create(
        crm,
        "deals",
        {"dealname": "Stress deal", "pipeline": "default", "dealstage": "qualifiedtobuy"},
    )

    def write(i):
        return crm.patch(
            path(i, "deals/") + identifier,
            json={
                "properties": {
                    "dealstage": ["closedwon", "closedlost", "qualifiedtobuy"][i % 3],
                    f"stress_{i}": str(i),
                }
            },
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(pool.map(write, range(60)))
    assert all(r.status_code == 200 for r in responses)
    actual = props(crm, "deals", identifier)
    assert all(actual[f"stress_{i}"] == str(i) for i in range(60))
    with transaction(crm.app.state.engine) as session:
        effects = session.scalars(
            select(Object).where(Object.object_type.in_(["tickets", "tasks"]))
        ).all()
        assert sorted(r.object_type for r in effects) == ["tasks", "tickets"]


def test_eighty_email_upserts_both_versions_create_one_record(crm):
    def write(i):
        return crm.post(
            path(i, "contacts/batch/upsert"),
            json={
                "inputs": [
                    {
                        "id": "Stress@Example.test" if i % 2 else "stress@example.test",
                        "idProperty": "email",
                        "properties": {f"stress_{i}": str(i)},
                    }
                ]
            },
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(pool.map(write, range(80)))
    assert all(r.status_code == 200 for r in responses)
    rows = [r.json()["results"][0] for r in responses]
    assert len({r["id"] for r in rows}) == 1
    assert sum(r["new"] for r in rows) == 1
    actual = props(crm, "contacts", rows[0]["id"])
    assert all(actual[f"stress_{i}"] == str(i) for i in range(80))


def test_forty_failed_batches_leave_no_automation_or_field_writes(crm):
    identifier = create(
        crm,
        "deals",
        {"dealname": "Rollback stress", "pipeline": "default", "dealstage": "qualifiedtobuy"},
    )
    before = props(crm, "deals", identifier)

    def fail(i):
        return crm.post(
            path(i, "deals/batch/update"),
            json={
                "inputs": [
                    {"id": identifier, "properties": {"dealstage": "closedwon", f"bad_{i}": "bad"}},
                    {"id": "0", "properties": {"dealstage": "closedwon"}},
                ]
            },
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(pool.map(fail, range(40)))
    assert all(r.status_code == 404 for r in responses)
    assert props(crm, "deals", identifier) == before
    assert crm.post(path(0, "tickets/search"), json={}).json()["total"] == 0
    # A real transition must still work: rolled-back claims cannot suppress it.
    assert (
        crm.patch(
            path(0, "deals/") + identifier, json={"properties": {"dealstage": "closedwon"}}
        ).status_code
        == 200
    )
    assert crm.post(path(0, "tickets/search"), json={}).json()["total"] == 1


def test_eighty_fake_conversations_eight_concurrent_do_not_cross_write(crm):
    identifiers = [
        create(crm, "companies", {"name": f"Stress {i}", "city": "Old", "state": "MI"})
        for i in range(80)
    ]
    untouched = create(crm, "companies", {"name": "Untouched", "city": "Keep", "state": "TO"})
    before = props(crm, "companies", untouched)

    class Fake:
        async def complete(self, messages, tools, timeout):
            identifier = next(m["content"] for m in messages if m["role"] == "user")
            if messages[-1]["role"] == "tool":
                return call(
                    "apply",
                    operations=[
                        {
                            "op": "update",
                            "kind": "companies",
                            "id": identifier,
                            "properties": {"city": "Verified " + identifier},
                        }
                    ],
                )
            return call("get", kind="companies", id=identifier)

    crm.app.state.assistant_client = Fake()

    def send(identifier):
        return crm.post(
            "/__agente",
            json={
                "context": {"now": NOW, "user": USER},
                "messages": [{"role": "user", "content": identifier}],
            },
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(send, identifiers))
    assert all(r.status_code == 200 and "verificata" in r.json()["reply"] for r in responses)
    assert props(crm, "companies", untouched) == before
    for identifier in identifiers:
        actual = props(crm, "companies", identifier)
        assert actual["city"] == "Verified " + identifier and actual["state"] == "MI"
