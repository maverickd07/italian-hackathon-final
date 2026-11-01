"""Adversarial fixtures and metamorphic checks, independent of production normalization."""

import copy
import random

import pytest
from test_migration import fixture_data, migrate, records

BASE = "/crm/v3/objects"


def snapshot(client):
    kinds = [
        "companies",
        "contacts",
        "deals",
        "products",
        "line_items",
        "tickets",
        "notes",
        "calls",
        "emails",
        "meetings",
    ]
    rows = {kind: records(client, kind) for kind in kinds}
    identity = {
        r["id"]: (kind, r["properties"].get("id_legacy") or r["properties"].get("hs_sku"))
        for kind, items in rows.items()
        for r in items
    }
    result = {}
    for kind, items in rows.items():
        for r in items:
            props = {
                k: v
                for k, v in r["properties"].items()
                if k
                not in {"hs_object_id", "createdate", "lastmodifieddate", "hs_lastmodifieddate"}
            }
            if props.get("hs_product_id"):
                props["hs_product_id"] = identity[props["hs_product_id"]]
            links = []
            for target in ["companies", "contacts", "deals", "line_items"]:
                for a in client.get(f"{BASE}/{kind}/{r['id']}/associations/{target}").json()[
                    "results"
                ]:
                    links.append((identity[a["id"]], a["type"]))
            result[identity[r["id"]]] = (props, sorted(links))
    return result


def test_row_order_cannot_change_merged_fields_or_associations(client):
    data = fixture_data()
    assert migrate(client, data).status_code == 204
    expected = snapshot(client)
    for seed in [17, 81, 2026]:
        assert client.post("/__reset").status_code == 204
        shuffled = copy.deepcopy(data)
        for rows in shuffled.values():
            random.Random(seed).shuffle(rows)
        assert migrate(client, shuffled).status_code == 204
        assert snapshot(client) == expected


@pytest.mark.parametrize(
    "amount,expected",
    [
        ("-0.01", ""),
        ("0", ""),
        ("0.01", "C"),
        ("19999.99", "C"),
        ("20000", "B"),
        ("99999.99", "B"),
        ("100000", "A"),
        ("100000.01", "A"),
    ],
)
def test_revenue_class_boundaries(client, amount, expected):
    data = fixture_data()
    data["opportunita"] = [
        {
            "id_opportunita": "edge",
            "id_azienda": "old",
            "fase": "Vinta",
            "titolo": "Boundary",
            "importo": amount,
            "data_chiusura": "2025-06-01",
            "ultima_modifica": "2025-06-01",
        }
    ]
    data["righe_offerta"] = []
    assert migrate(client, data).status_code == 204
    props = records(client, "companies")[0]["properties"]
    assert props.get("classe_cliente", "") == expected


def test_identical_company_names_not_identity_keys(client):
    data = fixture_data()
    data["aziende"].append(
        {
            "id_azienda": "distinct",
            "ragione_sociale": "New",
            "sito_web": "distinct.it",
            "ultima_modifica": "2024-01-01",
        }
    )
    assert migrate(client, data).status_code == 204
    assert len(records(client, "companies")) == 2


@pytest.mark.parametrize(
    "provider", ["gmail.com", "libero.it", "yahoo.com", "hotmail.com", "outlook.com", "tiscali.it"]
)
def test_freemail_never_links_to_provider_company(client, provider):
    data = fixture_data()
    data["aziende"].append(
        {
            "id_azienda": "provider",
            "ragione_sociale": "Provider",
            "sito_web": provider,
            "ultima_modifica": "2024-01-01",
        }
    )
    data["contatti"].append(
        {
            "id_contatto": "personal",
            "nome": "Personal",
            "email": "someone@" + provider,
            "ultima_modifica": "2024-01-01",
        }
    )
    assert migrate(client, data).status_code == 204
    person = next(
        r for r in records(client, "contacts") if r["properties"]["id_legacy"] == "personal"
    )
    assert (
        client.get(f"{BASE}/contacts/{person['id']}/associations/companies").json()["results"] == []
    )
    live = client.post(
        BASE + "/contacts", json={"properties": {"email": "another@" + provider}}
    ).json()
    assert (
        client.get(f"{BASE}/contacts/{live['id']}/associations/companies").json()["results"] == []
    )


def test_deleted_product_does_not_delete_valid_line_or_revive_product(client):
    data = fixture_data()
    data["listino"][0]["cancellato"] = "S"
    for row in data["righe_offerta"]:
        row["prezzo_unitario"] = "1.01"
        row["descrizione"] = "Historical item"
    assert migrate(client, data).status_code == 204
    assert records(client, "products") == []
    lines = records(client, "line_items")
    assert len(lines) == 2
    assert all(not r["properties"].get("hs_product_id") for r in lines)
