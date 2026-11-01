import csv
import io
import zipfile

from app.migration import HEADERS


def archive(data):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, columns in HEADERS.items():
            buffer = io.StringIO(newline="")
            fields = sorted(columns)
            writer = csv.DictWriter(buffer, fieldnames=fields, delimiter=";")
            writer.writeheader()
            for row in data.get(name, []):
                writer.writerow({k: row.get(k, "") for k in fields})
            z.writestr("sinergia-export/" + name + ".csv", buffer.getvalue().encode("cp1252"))
    return out.getvalue()


def fixture_data():
    return {
        "aziende": [
            {
                "id_azienda": "old",
                "ragione_sociale": "Old",
                "sito_web": "https://www.a.it/path",
                "note": "P.IVA IT12345678901",
                "citta": "Roma",
                "ultima_modifica": "2020-01-01",
            },
            {
                "id_azienda": "new",
                "ragione_sociale": " New ",
                "sito_web": "b.it",
                "note": "piva 12345678901",
                "ultima_modifica": "2024-01-01",
            },
            {
                "id_azienda": "gone",
                "ragione_sociale": "Deleted",
                "sito_web": "a.it",
                "cancellato": "Sì",
                "ultima_modifica": "2026-01-01",
            },
        ],
        "contatti": [
            {
                "id_contatto": "c1",
                "nome": "Anna",
                "email": "Anna @a.it",
                "telefono": "+39 123",
                "id_azienda": "old",
                "tipo": "Lead",
                "ultima_modifica": "2020-01-01",
            },
            {
                "id_contatto": "c2",
                "nome": "Anna New",
                "email": "anna@a.it",
                "id_azienda": "gone",
                "tipo": "Cliente",
                "ultima_modifica": "2024-01-01",
            },
            {
                "id_contatto": "c3",
                "nome": "Bob",
                "email": "123456",
                "telefono": "bob@b.it",
                "ultima_modifica": "2024-01-01",
            },
        ],
        "utenti": [
            {
                "id_utente": "u1",
                "nome": "Anna",
                "cognome": "Rossi",
                "email": "old@example.it",
                "attivo": "N",
            },
            {
                "id_utente": "u2",
                "nome": "Anna",
                "cognome": "Rossi",
                "email": "new@example.it",
                "attivo": "S",
            },
        ],
        "opportunita": [
            {
                "id_opportunita": "d1",
                "titolo": "Quote",
                "id_azienda": "old",
                "contatti": "c1;c2,c3",
                "importo": "999",
                "fase": "06 - Vinta",
                "id_commerciale": "u1",
                "ultima_modifica": "2025-01-01",
            },
            {
                "id_opportunita": "d2",
                "titolo": "NC",
                "id_azienda": "new",
                "importo": "(10,00)",
                "valuta": "USD",
                "fase": "Vinta",
                "data_chiusura": "01/02/2025",
                "ultima_modifica": "2025-02-01",
            },
            {
                "id_opportunita": "d3",
                "titolo": "Renewal",
                "id_azienda": "new",
                "importo": "100/mese",
                "pipeline": "Rinnovi",
                "fase": "R3",
                "data_chiusura": "2025-03-01",
                "ultima_modifica": "2025-03-01",
            },
            {"id_opportunita": "deleted", "cancellato": "S"},
        ],
        "storico_fasi": [
            {"id_opportunita": "d1", "fase_nuova": "Vinta", "data_cambio": "2025-01-01"}
        ],
        "listino": [
            {
                "codice_articolo": "BF00123",
                "descrizione": " Product ",
                "prezzo_listino": "1,01",
                "ultima_modifica": "2020-01-01",
            }
        ],
        "righe_offerta": [
            {
                "id_riga": "l1",
                "id_opportunita": "d1",
                "codice_articolo": "123",
                "quantita": "1",
                "sconto": "0,50",
            },
            {
                "id_riga": "l2",
                "id_opportunita": "d1",
                "codice_articolo": "123",
                "quantita": "1",
                "sconto": "50%",
            },
            {
                "id_riga": "l3",
                "id_opportunita": "deleted",
                "codice_articolo": "123",
                "quantita": "1",
            },
        ],
        "ticket": [
            {
                "id_ticket": "t1",
                "oggetto": "Help",
                "descrizione": "Line1\nLine2",
                "stato": "Risolto",
                "priorita": "URGENTE!!",
                "id_contatto": "c1",
                "id_azienda": "old",
                "aperto_il": "01/02/2025 10:00",
                "chiuso_il": "01/02/2025 11:00",
                "id_utente": "Rossi A.",
                "ultima_modifica": "2025-02-01",
            }
        ],
        "attivita": [
            {
                "id_attivita": "a1",
                "tipo": "Email",
                "data": "2024-01-01 10:00:00",
                "testo": "History",
                "id_contatto": "c1",
                "id_utente": "u1",
            },
            {
                "id_attivita": "a2",
                "tipo": "Nota",
                "data": "2025-01-01",
                "testo": "Orphan",
                "id_contatto": "missing",
            },
        ],
    }


def migrate(client, data):
    payload = archive(data)
    urls = []

    def fake(url):
        urls.append(url)
        return io.BytesIO(payload)

    client.app.state.export_downloader = fake
    response = client.post(
        "/__migrate", json={"export_url": "https://export.example/download?signature=abc"}
    )
    assert urls == ["https://export.example/download?signature=abc"]
    return response


def records(client, kind):
    return client.get("/crm/v3/objects/" + kind + "?limit=100").json()["results"]


def test_authentication_fail_closed(client, monkeypatch):
    for path in ["/crm/v3/objects/contacts", "/docs", "/__reset"]:
        call = client.post if path == "/__reset" else client.get
        assert call(path, headers={"Authorization": ""}).status_code == 401
        assert call(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/health", headers={"Authorization": ""}).json() == {
        "status": "ok",
        "version": "2026-09",
        "ui": client.get("/health").json()["ui"],
    }
    monkeypatch.delenv("CRM_TOKEN")
    assert client.get("/crm/v3/objects/contacts").status_code == 401


def test_migration_semantics(client):
    response = migrate(client, fixture_data())
    assert response.status_code == 204, response.text
    company = records(client, "companies")[0]
    p = company["properties"]
    assert p["id_legacy"] == "new"
    assert p["city"] == "Roma"
    assert p["domain"] == "b.it" and p["hs_additional_domains"] == "a.it"
    assert p["fatturato_2025"] == "1191.82"  # 0.51+0.51 - 10*.92 + 1200
    assert p["classe_cliente"] == "C"
    contacts = {r["properties"]["id_legacy"]: r for r in records(client, "contacts")}
    assert set(contacts) == {"c2", "c3"}
    assert contacts["c2"]["properties"]["phone"] == "+39 123"
    assert contacts["c3"]["properties"]["email"] == "bob@b.it"
    assert contacts["c3"]["properties"]["phone"] == "123456"
    for contact in contacts.values():
        links = client.get(
            "/crm/v3/objects/contacts/" + contact["id"] + "/associations/companies"
        ).json()["results"]
        assert links[0]["id"] == company["id"]
    deals = {r["properties"]["id_legacy"]: r for r in records(client, "deals")}
    assert deals["d1"]["properties"]["amount"] == "1.02"
    assert deals["d1"]["properties"]["commerciale"] == "new@example.it"
    assert deals["d1"]["properties"]["closedate"].startswith("2025-01-01")
    assert (
        len(
            client.get(
                "/crm/v3/objects/deals/" + deals["d1"]["id"] + "/associations/contacts"
            ).json()["results"]
        )
        == 2
    )
    assert len(records(client, "line_items")) == 2
    ticket = records(client, "tickets")[0]
    assert ticket["properties"]["createdate"].startswith("2025-02-01T10:00")
    assert ticket["properties"]["assegnatario"] == "new@example.it"
    assert ticket["properties"]["content"] == "Line1\nLine2"
    assert records(client, "emails")[0]["properties"]["autore"] == "old@example.it"
    assert len(records(client, "notes")) == 1
    lists = client.post("/crm/lists/2026-09/search", json={"query": "Clienti dormienti"}).json()[
        "lists"
    ]
    assert lists[0]["additionalProperties"]["hs_list_size"] == "1"
    assert client.get("/crm/v3/lists/1/memberships").json()["results"] == [
        {"recordId": company["id"]}
    ]
    assert client.get("/crm/v3/properties/companies/partita_iva").json()["hasUniqueValue"] is True
    assert len(client.get("/crm/pipelines/2026-09/deals").json()["results"]) == 2
    assert client.get("/crm/objects/2026-09/0-49").json()["results"]
    assert (
        client.post("/crm/v3/objects/emails/search", json={"query": "History"}).json()["total"] == 1
    )
    assert len(records(client, "tickets")) == 1 and not records(
        client, "tasks"
    )  # import never fires R10/R11
    assert migrate(client, fixture_data()).status_code == 409


def test_bad_value_after_buffer_flush_preserves_everything(client):
    data = fixture_data()
    data["attivita"] = [
        {
            "id_attivita": str(i),
            "tipo": "Nota",
            "data": "2024-01-01",
            "testo": "Buffered",
            "id_contatto": "c1",
        }
        for i in range(2100)
    ] + [{"id_attivita": "bad", "tipo": "unknown activity", "data": "2024-01-01"}]
    # The invalid final row arrives after COPY/batch buffers have flushed to the transaction.
    result = migrate(client, data)
    assert result.status_code == 204, result.text
    assert client.post("/crm/v3/objects/notes/search", json={}).json()["total"] == 2101
    assert client.post("/__reset").status_code == 204
    assert not records(client, "companies")
    assert not records(client, "emails")
    assert client.get("/crm/v3/lists/1").status_code == 404
    assert client.get("/crm/v3/properties/companies/partita_iva").status_code == 404
    assert len(client.get("/crm/v3/pipelines/deals").json()["results"]) == 1
    assert migrate(client, fixture_data()).status_code == 204


def test_missing_files_rejected(client):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.writestr("aziende.csv", "id_azienda\n")
    client.app.state.export_downloader = lambda url: io.BytesIO(output.getvalue())
    assert (
        client.post("/__migrate", json={"export_url": "https://example.test/a"}).status_code == 400
    )
    assert client.post("/__migrate", json={}).status_code == 400


def test_vat_conflict_atomic_and_r12(client):
    assert migrate(client, fixture_data()).status_code == 204
    company = records(client, "companies")[0]
    assert (
        client.post(
            "/crm/v3/objects/companies",
            json={"properties": {"name": "Duplicate", "partita_iva": "12345678901"}},
        ).status_code
        == 409
    )
    other = client.post(
        "/crm/v3/objects/companies",
        json={"properties": {"name": "Other", "partita_iva": "99999999999"}},
    ).json()
    response = client.patch(
        "/crm/v3/objects/companies/" + other["id"],
        json={"properties": {"name": "Bad", "partita_iva": "12345678901"}},
    )
    assert response.status_code == 409
    assert (
        client.get("/crm/v3/objects/companies/" + other["id"]).json()["properties"]["name"]
        == "Other"
    )
    contact = client.post(
        "/crm/v3/objects/contacts", json={"properties": {"email": "auto@a.it"}}
    ).json()
    assert (
        client.get("/crm/v3/objects/contacts/" + contact["id"] + "/associations/companies").json()[
            "results"
        ][0]["id"]
        == company["id"]
    )


def test_normalization_edge_cases():
    from decimal import Decimal

    from app.normalize import date, number, text

    assert number("1,2mln") == Decimal(1200000)
    assert number("8mila") == Decimal(8000)
    assert number("£ 1,234.56") == Decimal("1234.56")
    assert number("8146,18-") == Decimal("-8146.18")
    assert number("50 al mese", annual=True) == Decimal(600)
    assert text(" ForlÃ¬ ") == "Forlì"
    assert date("43669").isoformat() == "2019-07-23T00:00:00"


def test_concurrent_vat_creates(client):
    from concurrent.futures import ThreadPoolExecutor

    def create(_):
        return client.post(
            "/crm/v3/objects/companies", json={"properties": {"partita_iva": "77777777777"}}
        ).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(create, range(8)))
    assert statuses.count(201) == 1
    assert statuses.count(409) == 7


def test_r9_indirect_activity_and_credit_stage(client):
    data = fixture_data()
    data["attivita"][0]["data"] = "2025-12-01"
    assert migrate(client, data).status_code == 204
    assert not client.get("/crm/v3/lists/1/memberships").json()["results"]
    assert client.post("/__reset").status_code == 204
    data = fixture_data()
    data["opportunita"] = [data["opportunita"][1]]  # only a negative closed-won credit
    assert migrate(client, data).status_code == 204
    company = records(client, "companies")[0]
    assert company["properties"]["fatturato_2025"] == "-9.20"
    assert not company["properties"].get("classe_cliente")
    assert client.get("/crm/v3/lists/1/memberships").json()["results"] == [
        {"recordId": company["id"]}
    ]


def test_concurrent_workers_seed_fresh_catalog_once(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi.testclient import TestClient
    from sqlalchemy import delete

    from app.db import Metadata, transaction
    from app.main import create_app

    engine = client.app.state.engine
    with transaction(engine, write=True) as session:
        session.execute(delete(Metadata))
    barrier = Barrier(2)
    url = engine.url.render_as_string(hide_password=False)

    def start_worker(_):
        barrier.wait(timeout=10)
        with TestClient(create_app(url), headers={"Authorization": "Bearer test-token"}) as worker:
            assert worker.get("/health").status_code == 200
            return worker.get("/crm/v3/pipelines/deals").json()["results"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start_worker, range(2)))
    assert all(len(pipelines) == 1 and pipelines[0]["id"] == "default" for pipelines in results)


def test_every_column_garbage_still_imports(client):
    data = {name: [{field: "garbage" for field in fields}] for name, fields in HEADERS.items()}
    response = migrate(client, data)
    assert response.status_code == 204, response.text
    for kind in ("companies", "contacts", "deals", "products", "line_items", "tickets", "notes"):
        assert len(records(client, kind)) == 1, kind
    for kind, fields in {
        "deals": ["amount", "dealstage", "pipeline"],
        "line_items": ["price", "quantity", "amount", "hs_discount_percentage"],
        "products": ["price", "hs_sku"],
        "notes": ["hs_timestamp"],
        "tickets": ["hs_pipeline_stage", "closed_date"],
    }.items():
        props = records(client, kind)[0]["properties"]
        for field in fields:
            assert not props.get(field), (kind, field, props)
    from app.db import Metadata, transaction

    with transaction(client.app.state.engine) as session:
        log = session.get(Metadata, ("migration", "last")).value["log"]
    assert log["total"] >= 20
    assert any(c["field"] == "quantita" for c in log["cases"])


def test_bad_line_does_not_publish_partial_deal_total(client):
    data = fixture_data()
    data["righe_offerta"][0]["prezzo_unitario"] = "garbage"
    assert migrate(client, data).status_code == 204
    deal = next(x for x in records(client, "deals") if x["properties"]["id_legacy"] == "d1")
    assert not deal["properties"].get("amount")
    assert not records(client, "companies")[0]["properties"].get("fatturato_2025")


def test_missing_duplicate_ids_and_unknown_skus_keep_records(client):
    data = {
        "aziende": [{"ragione_sociale": "One"}, {"ragione_sociale": "Two"}],
        "listino": [{"codice_articolo": "garbage"}, {"codice_articolo": "nonsense"}],
        "attivita": [{"id_attivita": "same"}, {"id_attivita": "same"}],
    }
    assert migrate(client, data).status_code == 204
    assert len(records(client, "companies")) == 2
    assert len(records(client, "products")) == 2
    assert len(records(client, "notes")) == 2


def test_unreadable_csv_rolls_back(client):
    data = archive(fixture_data())
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(output, "w") as dst:
        for name in src.namelist():
            content = src.read(name)
            if name.endswith("attivita.csv"):
                content += b'"unterminated'
            dst.writestr(name, content)
    client.app.state.export_downloader = lambda url: io.BytesIO(output.getvalue())
    response = client.post("/__migrate", json={"export_url": "https://example.test/export"})
    assert response.status_code == 400
    assert not records(client, "companies")


def test_numeric_garbage_with_digits_is_not_a_number(client):
    data = fixture_data()
    data["opportunita"][1]["importo"] = "garbage123"
    data["attivita"][0]["data"] = "9999999999999999999999"
    assert migrate(client, data).status_code == 204
    d = next(x for x in records(client, "deals") if x["properties"]["id_legacy"] == "d2")
    assert not d["properties"].get("amount")


def test_originally_empty_amount_keeps_zero_revenue(client):
    data = fixture_data()
    data["opportunita"] = [
        {
            "id_opportunita": "empty",
            "id_azienda": "old",
            "fase": "Vinta",
            "data_chiusura": "2025-01-01",
        }
    ]
    data["righe_offerta"] = []
    assert migrate(client, data).status_code == 204
    assert records(client, "companies")[0]["properties"]["fatturato_2025"] == "0.00"
