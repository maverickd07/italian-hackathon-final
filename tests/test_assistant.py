"""Scripted fake model integration tests; outbound network is forbidden by conftest."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.catalog import save, seed
from app.db import Association, Object, transaction

BASE = "/crm/v3/objects"
NOW = "2026-12-02T10:00:00+01:00"
USER = "elena.silvestri@brambillaforniture.it"


def call(name, **args):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_" + name,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps({"args": args})},
            }
        ],
    }


def answer(content):
    return {"role": "assistant", "content": content}


class Fake:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = []

    async def complete(self, messages, tools, timeout):
        self.calls.append(messages.copy())
        assert timeout > 0
        assert self.steps, "Unexpected model call"
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(messages) if callable(step) else step


def last(messages):
    return json.loads(messages[-1]["content"])


@pytest.fixture
def crm(client):
    with transaction(client.app.state.engine, write=True) as s:
        seed(s, migrated=True)
        save(s, "migration", "last", {"counts": {}})
        for i, email, active in [
            ("1", USER, "S"),
            ("2", "mattia.vigano@brambillaforniture.it", "S"),
            ("3", "left@example.it", "N"),
        ]:
            save(
                s,
                "users",
                i,
                {"nome": email.split("@")[0], "cognome": "", "email": email, "attivo": active},
            )
    return client


def create(client, kind, props, associations=None):
    r = client.post(
        BASE + "/" + kind, json={"properties": props, "associations": associations or []}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def assoc(identifier, tid):
    return {"to": {"id": identifier}, "types": [{"associationTypeId": tid}]}


def props(client, kind, identifier):
    return client.get(BASE + "/" + kind + "/" + identifier).json()["properties"]


def rows(client, kind):
    return client.post(BASE + "/" + kind + "/search", json={"limit": 100}).json()["results"]


def ask(client, fake, message, attachments=None, user=USER, messages=None):
    client.app.state.assistant_client = fake
    r = client.post(
        "/__agente",
        json={
            "context": {"now": NOW, "user": user},
            "messages": messages
            or [{"role": "user", "content": message, "attachments": attachments or []}],
        },
    )
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"reply"} and isinstance(r.json()["reply"], str)
    return r.json()["reply"]


def snapshot(client):
    with transaction(client.app.state.engine) as s:
        return (
            {
                r.id: (r.object_type, dict(r.properties), r.updated_at, r.archived)
                for r in s.scalars(select(Object))
            },
            {(a.from_id, a.to_id, a.type_id) for a in s.scalars(select(Association))},
        )


def test_example_win_and_r10(crm):
    c = create(crm, "companies", {"name": "Nuova Serramenti Mazza"})
    d = create(
        crm,
        "deals",
        {
            "dealname": "Ordine Mazza",
            "pipeline": "default",
            "dealstage": "qualifiedtobuy",
            "commerciale": USER,
        },
        [assoc(c, 5)],
    )
    fake = Fake(
        call("search", kind="companies", query="Nuova Serramenti Mazza"),
        call("get", kind="companies", id=c, associations=["deals"]),
        call(
            "apply",
            operations=[
                {"op": "update", "kind": "deals", "id": d, "properties": {"dealstage": "closedwon"}}
            ],
        ),
    )
    reply = ask(
        crm,
        fake,
        "Segna come vinta la trattativa di Nuova Serramenti Mazza, è arrivato l’ordine firmato.",
    )
    assert "Qualifica → Vinta" in reply
    assert "dealstage" not in reply
    assert d not in reply
    assert props(crm, "deals", d)["dealstage"] == "closedwon"
    tickets = rows(crm, "tickets")
    assert len(tickets) == 1
    t = tickets[0]
    assert t["properties"]["subject"] == "Avvio fornitura - Ordine Mazza"
    assert t["properties"]["assegnatario"] == USER
    assert {
        a["id"]
        for a in crm.get(BASE + "/tickets/" + t["id"] + "/associations/companies").json()["results"]
    } == {c}


def test_example_revenue_grounded(crm):
    create(crm, "companies", {"name": "Nuova Tessile Spinelli", "fatturato_2025": "12345.67"})

    def grounded(messages):
        assert last(messages)["results"][0]["properties"]["fatturato_2025"] == "12345.67"
        return answer("Nel 2025 abbiamo fatturato 12.345,67 euro con Nuova Tessile Spinelli.")

    before = snapshot(crm)
    reply = ask(
        crm,
        Fake(call("search", kind="companies", query="Nuova Tessile Spinelli"), grounded),
        "Quanto abbiamo fatturato con Nuova Tessile Spinelli nel 2025?",
        user="mattia.vigano@brambillaforniture.it",
    )
    assert "12.345,67" in reply
    assert snapshot(crm) == before


def test_ambiguous_name_clarifies_no_write(crm):
    create(crm, "companies", {"name": "Rossi", "city": "Milano"})
    create(crm, "companies", {"name": "Rossi", "city": "Roma"})

    def clarify(messages):
        assert last(messages)["total"] == 2
        return answer("Quale Rossi: Milano o Roma?")

    before = snapshot(crm)
    assert "Quale" in ask(
        crm, Fake(call("search", kind="companies", query="Rossi"), clarify), "Aggiorna Rossi."
    )
    assert snapshot(crm) == before


def test_nonexistent_company(crm):
    def absent(messages):
        assert last(messages)["total"] == 0
        return answer("L’azienda non esiste. Nessuna modifica.")

    before = snapshot(crm)
    ask(crm, Fake(call("search", kind="companies", query="Missing"), absent), "Aggiorna Missing.")
    assert snapshot(crm) == before


def test_nonexistent_deal_cannot_write(crm):
    before = snapshot(crm)
    reply = ask(
        crm,
        Fake(
            call("get", kind="deals", id="missing"),
            call(
                "apply",
                operations=[
                    {
                        "op": "update",
                        "kind": "deals",
                        "id": "missing",
                        "properties": {"dealstage": "closedwon"},
                    }
                ],
            ),
        ),
        "Segna vinta la trattativa missing.",
    )
    assert "prima" in reply
    assert snapshot(crm) == before


def test_duplicate_vat_rolls_back(crm):
    create(crm, "companies", {"name": "Existing", "partita_iva": "12345678901"})
    before = snapshot(crm)
    reply = ask(
        crm,
        Fake(
            call(
                "apply",
                operations=[
                    {
                        "op": "create",
                        "kind": "companies",
                        "properties": {"name": "Duplicate", "partita_iva": "IT 12345678901"},
                    }
                ],
            )
        ),
        "Crea Duplicate con partita IVA IT 12345678901.",
    )
    assert "partita IVA" in reply and "Nessuna modifica" in reply
    assert snapshot(crm) == before


def test_inactive_owner_rejected(crm):
    d = create(crm, "deals", {"dealname": "Test", "commerciale": USER})
    before = snapshot(crm)
    reply = ask(
        crm,
        Fake(
            call("get", kind="deals", id=d),
            call(
                "apply",
                operations=[
                    {
                        "op": "update",
                        "kind": "deals",
                        "id": d,
                        "properties": {"commerciale": "left@example.it"},
                    }
                ],
            ),
        ),
        "Assegna Test a left@example.it.",
    )
    assert "non è un utente attivo" in reply
    assert snapshot(crm) == before


def test_my_customers_union_distinct(crm):
    a = create(crm, "companies", {"name": "Both"})
    b = create(crm, "companies", {"name": "Ticket only"})
    other = create(crm, "companies", {"name": "Other"})
    create(crm, "deals", {"commerciale": USER}, [assoc(a, 5)])
    create(crm, "tickets", {"assegnatario": USER}, [assoc(a, 26), assoc(b, 26)])
    create(crm, "deals", {"commerciale": "mattia.vigano@brambillaforniture.it"}, [assoc(other, 5)])

    def verify(messages):
        result = last(messages)
        assert result["total"] == 2
        assert {x["id"] for x in result["results"]} == {a, b}
        return answer("I tuoi clienti sono Both e Ticket only.")

    ask(crm, Fake(call("customers"), verify), "Chi sono i miei clienti?")


def test_relative_calendar_date_and_stateless_history(crm):
    def write(messages):
        assert last(messages)["date"] == "2027-06-02T09:00:00.000Z"
        assert any(m["content"] == "Confermi il promemoria tra sei mesi?" for m in messages)
        return call(
            "apply",
            operations=[
                {
                    "op": "create",
                    "kind": "tasks",
                    "properties": {
                        "hs_task_subject": "Promemoria",
                        "hs_timestamp": last(messages)["date"],
                        "hs_task_status": "NOT_STARTED",
                    },
                }
            ],
        )

    ask(
        crm,
        Fake(call("relative_date", months=6), write),
        "",
        messages=[
            {"role": "user", "content": "Crea un promemoria tra sei mesi."},
            {"role": "assistant", "content": "Confermi il promemoria tra sei mesi?"},
            {"role": "user", "content": "sì"},
        ],
    )
    assert rows(crm, "tasks")[0]["properties"]["hs_timestamp"] == "2027-06-02T09:00:00.000Z"


def test_lost_180_days_context_clock(crm):
    d = create(
        crm, "deals", {"dealname": "Lost", "pipeline": "default", "dealstage": "qualifiedtobuy"}
    )
    ask(
        crm,
        Fake(
            call("get", kind="deals", id=d),
            call(
                "apply",
                operations=[
                    {
                        "op": "update",
                        "kind": "deals",
                        "id": d,
                        "properties": {"dealstage": "closedlost"},
                    }
                ],
            ),
        ),
        "Segna persa Lost.",
    )
    task = rows(crm, "tasks")[0]
    assert datetime.fromisoformat(task["properties"]["hs_timestamp"]) == datetime.fromisoformat(
        NOW
    ) + timedelta(days=180)
    assert task["properties"]["hs_task_status"] == "NOT_STARTED"


def test_contact_domain_r12(crm):
    c = create(crm, "companies", {"name": "Client", "domain": "client.it"})
    ask(
        crm,
        Fake(
            call(
                "apply",
                operations=[
                    {
                        "op": "create",
                        "kind": "contacts",
                        "properties": {"firstname": "Anna", "email": "anna@client.it"},
                    }
                ],
            )
        ),
        "Crea Anna, anna@client.it.",
    )
    contact = rows(crm, "contacts")[0]
    assert {
        x["id"]
        for x in crm.get(BASE + "/contacts/" + contact["id"] + "/associations/companies").json()[
            "results"
        ]
    } == {c}


def test_csv_attachment_normalized_and_only_requested_products(crm):
    p = create(crm, "products", {"name": "Old", "hs_sku": "BF-00123", "price": "10"})
    other = create(crm, "products", {"name": "Untouched", "hs_sku": "BF-00999", "price": "42"})
    before = props(crm, "products", other)
    content = "codice_articolo;descrizione;prezzo_listino\n123;New;1.234,56\n"

    def inspect(messages):
        assert last(messages)["results"][0]["price"] == "1234.56"
        return call("apply_csv", index=0, kind="products")

    ask(
        crm,
        Fake(call("attachment", index=0, kind="products"), inspect),
        "Aggiorna i prodotti dal listino.",
        attachments=[{"name": "listino.csv", "content_type": "text/csv", "content": content}],
    )
    assert props(crm, "products", p)["price"] == "1234.56"
    assert props(crm, "products", other) == before


def test_atomic_batch_failure_rolls_back_first_write(crm):
    d = create(crm, "deals", {"dealname": "Keep", "commerciale": USER})
    before = snapshot(crm)
    ask(
        crm,
        Fake(
            call("get", kind="deals", id=d),
            call(
                "apply",
                operations=[
                    {
                        "op": "update",
                        "kind": "deals",
                        "id": d,
                        "properties": {"dealname": "Changed"},
                    },
                    {
                        "op": "create",
                        "kind": "tickets",
                        "properties": {"subject": "Invalid", "assegnatario": "left@example.it"},
                    },
                ],
            ),
        ),
        "Rinomina Keep e crea il ticket.",
    )
    assert snapshot(crm) == before


def test_four_conversations_isolated_and_errors(crm, monkeypatch):
    ids = [create(crm, "companies", {"name": f"C{i}", "city": "Old"}) for i in range(4)]

    class ConcurrentFake:
        async def complete(self, messages, tools, timeout):
            identifier = next(m["content"] for m in messages if m["role"] == "user")
            await asyncio.sleep(0.01)
            if messages[-1]["role"] == "tool":
                return call(
                    "apply",
                    operations=[
                        {
                            "op": "update",
                            "kind": "companies",
                            "id": identifier,
                            "properties": {"city": "New"},
                        }
                    ],
                )
            return call("get", kind="companies", id=identifier)

    crm.app.state.assistant_client = ConcurrentFake()

    def send(identifier):
        return crm.post(
            "/__agente",
            json={
                "context": {"now": NOW, "user": USER},
                "messages": [{"role": "user", "content": identifier}],
            },
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(send, ids))
    assert all(r.status_code == 200 and "verificata" in r.json()["reply"] for r in results)
    assert all(props(crm, "companies", i)["city"] == "New" for i in ids)
    assert "disponibile" in ask(crm, Fake(RuntimeError("provider unavailable")), "test")

    class Slow:
        async def complete(self, *args, **kwargs):
            await asyncio.sleep(1)

    monkeypatch.setattr("app.assistant.router.DEADLINE_SECONDS", 0.05)
    assert "esaurito" in ask(crm, Slow(), "test")


def test_untouched_snapshot_only_requested_fields(crm):
    target = create(crm, "companies", {"name": "Target", "city": "Old", "state": "MI"})
    create(crm, "companies", {"name": "Leave alone", "city": "Old"})
    create(crm, "contacts", {"firstname": "Contact", "email": "someone@example.it"})
    before, links = snapshot(crm)
    ask(
        crm,
        Fake(
            call("get", kind="companies", id=target),
            call(
                "apply",
                operations=[
                    {
                        "op": "update",
                        "kind": "companies",
                        "id": target,
                        "properties": {"city": "Roma"},
                    }
                ],
            ),
        ),
        "Cambia solo la città di Target in Roma.",
    )
    after, after_links = snapshot(crm)
    assert links == after_links
    assert {k: v for k, v in before.items() if k != target} == {
        k: v for k, v in after.items() if k != target
    }
    assert after[target][1] == {**before[target][1], "city": "Roma"}


def test_auth_invalid_payload_and_live_disabled(crm, monkeypatch):
    assert (
        crm.post("/__agente", json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    )
    assert crm.post("/__agente", json={}).status_code == 200
    monkeypatch.delenv("ASSISTANT_LIVE_ENABLED", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-never-used")
    assert "non è ancora abilitato" in ask(crm, None, "Ciao")
    monkeypatch.setenv("ASSISTANT_LIVE_ENABLED", "true")
    # Automated tests cannot use the real client even when live mode is configured.
    assert "non è ancora abilitato" in ask(crm, None, "Ciao")


def test_full_aggregate_more_than_twenty_and_paging(crm):
    for i in range(25):
        create(crm, "companies", {"name": f"A{i}", "fatturato_2025": "100.10"})

    def page(messages):
        result = last(messages)
        assert result["total"] == 25 and len(result["results"]) == 20
        return call("search", kind="companies", after=int(result["paging"]["next"]["after"]))

    def aggregate(messages):
        assert len(last(messages)["results"]) == 5
        return call("aggregate", kind="companies", property="fatturato_2025")

    def total(messages):
        assert last(messages) == {
            "count": 25,
            "sum": "2.502,50",
            "missing": 0,
            "property": "fatturato_2025",
        }
        return answer("Totale: 2.502,50 euro, 25 aziende.")

    ask(
        crm,
        Fake(call("search", kind="companies"), page, aggregate, total),
        "Totale fatturato 2025?",
    )


def test_metadata_and_association_tool(crm):
    from app.db import ListMember

    c = create(crm, "companies", {"name": "Dormant"})
    person = create(crm, "contacts", {"email": "person@example.it"})
    with transaction(crm.app.state.engine, write=True) as s:
        save(
            s,
            "lists",
            "dormant",
            {
                "listId": "dormant",
                "name": "Clienti dormienti",
                "objectTypeId": "0-2",
                "processingType": "MANUAL",
            },
        )
        s.add(ListMember(list_id="dormant", record_id=c))

    def members(messages):
        assert last(messages)["results"][0]["name"] == "Clienti dormienti"
        return call("lists", id="dormant")

    def company(messages):
        assert last(messages)["results"] == [{"recordId": c}]
        return call("get", kind="companies", id=c)

    reply = ask(
        crm,
        Fake(
            call("pipelines", kind="tickets"),
            call("lists", query="dormienti"),
            members,
            company,
            call("get", kind="contacts", id=person),
            call(
                "apply",
                operations=[
                    {
                        "op": "associate",
                        "kind": "contacts",
                        "id": person,
                        "to_kind": "companies",
                        "to_id": c,
                        "type_id": 1,
                    }
                ],
            ),
        ),
        "Associa il contatto all’azienda dormiente.",
    )
    assert "associato" in reply
    assert {
        x["id"]
        for x in crm.get(BASE + "/contacts/" + person + "/associations/companies").json()["results"]
    } == {c}


def test_eight_tool_limit(crm):
    fake = Fake(*([call("users")] * 9))
    before = snapshot(crm)
    assert "Limite" in ask(crm, fake, "Continua")
    assert len(fake.calls) == 9
    assert snapshot(crm) == before


def test_stale_read_prevents_overwrite(crm):
    c = create(crm, "companies", {"name": "Target", "city": "Old"})

    def race(messages):
        assert last(messages)["properties"]["city"] == "Old"
        with transaction(crm.app.state.engine, write=True) as s:
            from app.store import get_record, update_record

            update_record(s, get_record(s, "companies", c, lock=True), {"city": "Concurrent"})
        return call(
            "apply",
            operations=[
                {"op": "update", "kind": "companies", "id": c, "properties": {"city": "Assistant"}}
            ],
        )

    assert "frattempo" in ask(crm, Fake(call("get", kind="companies", id=c), race), "Cambia città.")
    assert props(crm, "companies", c)["city"] == "Concurrent"


def test_invalid_csv_entire_operation_unchanged(crm):
    create(crm, "products", {"hs_sku": "BF-00123", "name": "Old", "price": "12"})
    before = snapshot(crm)
    attachment = {
        "name": "listino.csv",
        "content_type": "text/csv",
        "content": "codice_articolo;prezzo_listino\n123;20\n999;40\n",
    }
    reply = ask(
        crm,
        Fake(
            call("attachment", index=0, kind="products"),
            call("apply_csv", index=0, kind="products"),
        ),
        "Aggiorna listino.",
        attachments=[attachment],
    )
    assert "non esiste" in reply
    assert snapshot(crm) == before


@pytest.mark.parametrize("operation", ["create", "update"])
def test_unknown_property_names_rejected_before_any_batch_write(crm, operation):
    deal = create(
        crm, "deals", {"dealname": "Guarded", "pipeline": "default", "dealstage": "contractsent"}
    )
    company = create(crm, "companies", {"name": "Existing", "partita_iva": "12345678901"})
    before = snapshot(crm)
    reply = ask(
        crm,
        Fake(
            call("get", kind="deals", id=deal, properties=["dealstage"]),
            call(
                "apply",
                operations=[
                    {
                        "op": "update",
                        "kind": "deals",
                        "id": deal,
                        "properties": {"dealstage": "closedwon"},
                    },
                    {
                        "op": operation,
                        "kind": "companies",
                        "id": company,
                        "properties": {"name": "Wrong", "vat_number": "12345678901"},
                    },
                ],
            ),
        ),
        "Write company VAT",
    )
    assert "vat_number" in reply and "partita_iva" in reply and "Proprietà valide" in reply
    assert snapshot(crm) == before  # Includes the earlier valid write and its automatic ticket.


def test_assistant_property_catalog_is_per_object_and_extensible(crm):
    with transaction(crm.app.state.engine, write=True) as s:
        save(
            s,
            "properties:companies",
            "approved_custom",
            {"name": "approved_custom", "archived": False},
        )
        save(
            s,
            "properties:companies",
            "retired_custom",
            {"name": "retired_custom", "archived": True},
        )
    reply = ask(
        crm,
        Fake(
            call(
                "apply",
                operations=[
                    {
                        "op": "create",
                        "kind": "companies",
                        "properties": {"name": "Catalog company", "approved_custom": "kept"},
                    },
                ],
            )
        ),
        "Create with registered field",
    )
    assert "completata" in reply
    assert rows(crm, "companies")[0]["properties"]["approved_custom"] == "kept"
    for kind, field in [("contacts", "approved_custom"), ("companies", "retired_custom")]:
        before = snapshot(crm)
        reply = ask(
            crm,
            Fake(
                call(
                    "apply",
                    operations=[
                        {"op": "create", "kind": kind, "properties": {field: "invalid"}},
                    ],
                )
            ),
            "Reject invalid field",
        )
        assert "Proprietà non riconosciute" in reply
        assert snapshot(crm) == before
    # The assistant guard must not narrow the generic REST object store.
    identifier = create(crm, "companies", {"name": "REST custom", "unregistered": "preserved"})
    assert props(crm, "companies", identifier)["unregistered"] == "preserved"


def flat_call(name, **args):
    response = call(name, **args)
    response["tool_calls"][0]["function"]["arguments"] = json.dumps(args)
    return response


@pytest.mark.parametrize("missing_second_sku", [False, True])
def test_observed_flat_csv_tool_arguments(crm, missing_second_sku):
    product = create(crm, "products", {"name": "Test", "hs_sku": "BF-991455", "price": "10.00"})
    before = snapshot(crm)
    csv = "codice_articolo;prezzo_listino\nBF-991455;12,34\n"
    if missing_second_sku:
        csv += "BF-991456;99,00\n"
    reply = ask(
        crm,
        Fake(
            flat_call("attachment", index=0, kind="products"),
            flat_call("apply_csv", index=0, kind="products"),
        ),
        "Aggiorna il listino senza creare prodotti.",
        attachments=[
            {
                "name": "listino.csv",
                "content_type": "text/csv",
                "content": csv,
            }
        ],
    )
    if missing_second_sku:
        assert "non esiste" in reply
        assert snapshot(crm) == before
    else:
        assert "completata" in reply
        assert props(crm, "products", product)["price"] == "12.34"


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        {"args": []},
        {"args": {}, "index": 0},
        {"kind": "products"},
        {"index": 0, "kind": "products", "unexpected": True},
    ],
)
def test_malformed_tool_envelopes_fail_without_writes(crm, arguments):
    before = snapshot(crm)
    response = call("apply_csv", index=0, kind="products")
    response["tool_calls"][0]["function"]["arguments"] = json.dumps(arguments)
    reply = ask(crm, Fake(response), "Aggiorna listino.")
    assert "Argomenti" in reply and "Nessuna modifica" in reply
    assert snapshot(crm) == before
