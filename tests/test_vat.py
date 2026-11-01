"""VAT source spellings and their downstream business effects; fake/no model."""

import pytest
from test_migration import fixture_data, migrate, records

from analysis.audit_sinergia import vat as audit_vat
from app.normalize import vat


@pytest.mark.parametrize(
    "label", ["partita iva", "P. IVA", "P.IVA", "p.iva", "PI", "P.I.", "P. I.", "PIVA"]
)
def test_vat_labels(label):
    for parser in (vat, audit_vat):
        assert parser(f"listino B; {label}: IT 34340 014470 - cliente storico") == ["34340014470"]


@pytest.mark.parametrize(
    "note",
    [
        "listino B; PI: 97660762986",
        "PI: 56138306362 - cliente storico",
    ],
)
def test_observed_pi_notes(note):
    expected = "97660762986" if "listino" in note else "56138306362"
    assert vat(note) == audit_vat(note) == [expected]


@pytest.mark.parametrize(
    "note",
    [
        "34340014470",
        "telefono: 34340014470",
        "SCAMPI: 34340014470",
        "PI: 3434001447",
        "PI: 343400144700",
        "PI: 34340014470 0",
        "PI: 34340014470x",
        "PI: ３４３４００１４４７０",
    ],
)
def test_do_not_extract_unlabelled_or_partial_identifiers(note):
    assert vat(note) == audit_vat(note) == []


def test_r7_does_not_require_checksum_and_deduplicates_occurrences():
    # R7 requires 11 digits; a checksum filter would invalidate synthetic IDs.
    note = "PI: 12345678901; P.IVA IT12345678901"
    assert vat(note) == audit_vat(note) == ["12345678901"]


@pytest.mark.parametrize("label", ["PI:", "P.I.", "P. I."])
def test_pi_merge_repoints_links_revenue_and_reserves_vat(client, label):
    data = fixture_data()
    data["opportunita"] = [data["opportunita"][0]]
    data["aziende"][1]["note"] = f"{label} IT12345678901"
    assert migrate(client, data).status_code == 204
    companies = records(client, "companies")
    assert len(companies) == 1
    company = companies[0]
    assert company["properties"]["id_legacy"] == "new"
    assert company["properties"]["partita_iva"] == "12345678901"
    assert company["properties"]["fatturato_2025"] == "1.02"
    assert company["properties"]["hs_additional_domains"] == "a.it"
    for kind in ("deals", "contacts", "tickets"):
        for row in records(client, kind):
            response = client.get(f"/crm/objects/2026-09/{kind}/{row['id']}/associations/companies")
            assert {str(x["toObjectId"]) for x in response.json()["results"]} == {company["id"]}
    response = client.post(
        "/crm/v3/objects/companies", json={"properties": {"partita_iva": "12345678901"}}
    )
    assert response.status_code == 409


def test_pi_merge_combines_activity_before_dormant_list(client):
    data = fixture_data()
    data["aziende"][1]["note"] = "PI: 12345678901"
    data["contatti"] = [{"id_contatto": "touch", "email": "touch@b.it", "id_azienda": "new"}]
    data["opportunita"] = [dict(data["opportunita"][0], id_azienda="old")]
    data["attivita"] = [
        {"id_attivita": "touch", "tipo": "Nota", "data": "2025-01-01", "id_contatto": "touch"}
    ]
    assert migrate(client, data).status_code == 204
    assert len(records(client, "companies")) == 1
    # Old company has a win; activity on its PI-labelled duplicate excludes it.
    assert client.get("/crm/v3/lists/1/memberships").json()["results"] == []
