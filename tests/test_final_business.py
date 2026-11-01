"""Final client-rule checks with literal expected answers, not importer helpers."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from test_migration import fixture_data, migrate, records

from app.db import Metadata, transaction

BASE = "/crm/objects/2026-09"


def by_legacy(client, kind):
    return {r["properties"]["id_legacy"]: r for r in records(client, kind)}


def linked(client, kind, identifier, target):
    response = client.get(f"{BASE}/{kind}/{identifier}/associations/{target}")
    assert response.status_code == 200
    return {str(r["toObjectId"]) for r in response.json()["results"]}


@pytest.mark.parametrize("raw_amount", ["garbage", "999999", ""])
def test_valid_quote_is_authoritative_even_when_original_amount_is_bad(client, raw_amount):
    data = fixture_data()
    data["opportunita"] = [dict(data["opportunita"][0], importo=raw_amount, valuta="USD")]
    assert migrate(client, data).status_code == 204
    deal = by_legacy(client, "deals")["d1"]["properties"]
    # Two EUR lines: each 1.01 at 50% rounds to 0.51, independently of header amount.
    assert Decimal(deal["amount"]) == Decimal("1.02")
    assert deal["deal_currency_code"] == "EUR"
    company = records(client, "companies")[0]["properties"]
    assert company.get("fatturato_2025") == "1.02"
    assert company["classe_cliente"] == "C"


def test_invalid_new_lifecycle_does_not_hide_older_valid_value(client):
    data = fixture_data()
    data["contatti"][1]["tipo"] = "unknown lifecycle"
    assert migrate(client, data).status_code == 204
    person = by_legacy(client, "contacts")["c2"]
    assert person["properties"]["lifecyclestage"] == "lead"
    assert person["properties"]["firstname"] == "Anna New"
    assert linked(client, "contacts", person["id"], "companies") == {
        records(client, "companies")[0]["id"]
    }


def test_source_user_role_and_reporting_line_survive_import(client):
    data = fixture_data()
    data["utenti"][1].update(ruolo="Commerciale", responsabile="manager-7")
    assert migrate(client, data).status_code == 204
    with transaction(client.app.state.engine) as session:
        user = session.get(Metadata, ("users", "u2")).value
        assert user["ruolo"] == "Commerciale"
        assert user["responsabile"] == "manager-7"


def test_transitive_company_identity_keeps_all_domains_and_repoints_every_reference(client):
    data = fixture_data()
    data["aziende"].append(
        {
            "id_azienda": "latest",
            "ragione_sociale": " Latest ",
            "sito_web": "https://b.it/new",
            "provincia": " MI ",
            "ultima_modifica": "2026-01-01",
        }
    )
    assert migrate(client, data).status_code == 204
    companies = records(client, "companies")
    assert len(companies) == 1
    company = companies[0]
    for field, expected in {
        "id_legacy": "latest",
        "name": "Latest",
        "domain": "b.it",
        "city": "Roma",
        "state": "MI",
        "partita_iva": "12345678901",
        "hs_additional_domains": "a.it",
    }.items():
        assert company["properties"][field] == expected
    for kind in ["contacts", "deals", "tickets"]:
        for record in records(client, kind):
            assert linked(client, kind, record["id"], "companies") == {company["id"]}
    deal = by_legacy(client, "deals")["d1"]
    assert linked(client, "deals", deal["id"], "contacts") == {
        r["id"] for r in records(client, "contacts")
    }


def test_revenue_uses_year_boundaries_fx_credit_and_final_sum_rounding(client):
    data = fixture_data()
    values = [
        ("usd1", "0.01", "USD", "2025-01-01", "Vinta", ""),
        ("usd2", "0.01", "USD", "2025-12-31", "Vinta", ""),
        ("gbp", "100", "GBP", "2025-06-01", "Vinta", ""),
        ("credit", "(10)", "EUR", "2025-06-02", "Vinta", ""),
        ("annual", "2/mese", "EUR", "2025-07-01", "R3", "Rinnovi"),
        ("old", "900000", "EUR", "2024-12-31", "Vinta", ""),
        ("future", "900000", "EUR", "2026-01-01", "Vinta", ""),
        ("lost", "900000", "EUR", "2025-02-01", "Persa", ""),
    ]
    data["opportunita"] = [
        {
            "id_opportunita": i,
            "id_azienda": "old",
            "titolo": i,
            "importo": amount,
            "valuta": currency,
            "data_chiusura": closed,
            "fase": stage,
            "pipeline": pipeline,
        }
        for i, amount, currency, closed, stage, pipeline in values
    ]
    data["righe_offerta"] = []
    assert migrate(client, data).status_code == 204
    # 0.01*.92 + 0.01*.92 + 100*1.17 - 10 + 2*12 = 131.0184 => 131.02.
    company = records(client, "companies")[0]["properties"]
    assert company["fatturato_2025"] == "131.02"
    assert company["classe_cliente"] == "C"
    assert records(client, "tasks") == []
    assert len(records(client, "tickets")) == 1  # imported history never triggers automations


@pytest.mark.parametrize(
    "activity_date,expected_dormant",
    [
        ("2024-12-31 23:59:59", True),
        ("2025-01-01", False),
        ("2025-12-31 23:59:59", False),
        ("2026-01-01", True),
    ],
)
def test_dormancy_counts_indirect_contact_activity_at_year_edges(
    client, activity_date, expected_dormant
):
    data = fixture_data()
    data["attivita"] = [
        {
            "id_attivita": "edge",
            "tipo": "Chiamata",
            "data": activity_date,
            "testo": "Touch",
            "id_contatto": "c1",
        }
    ]
    assert migrate(client, data).status_code == 204
    response = client.get("/crm/v3/lists/1/memberships")
    assert response.status_code == 200
    assert bool(response.json()["results"]) is expected_dormant


def test_reset_clears_automation_claims_and_uniqueness_then_allows_new_migration(client):
    data = fixture_data()
    for _ in range(2):
        assert migrate(client, data).status_code == 204
        company = records(client, "companies")[0]
        assert (
            client.post(
                BASE + "/companies",
                json={"properties": {"partita_iva": company["properties"]["partita_iva"]}},
            ).status_code
            == 409
        )
        assert (
            client.post(
                BASE + "/deals",
                json={"properties": {"dealname": "Cycle", "dealstage": "closedwon"}},
            ).status_code
            == 201
        )
        assert len(records(client, "tickets")) == 2
        assert client.post("/__reset").status_code == 204
        assert records(client, "companies") == []
        with transaction(client.app.state.engine) as session:
            assert (
                session.scalar(select(Metadata).where(Metadata.namespace == "automation")) is None
            )
