"""Final browser-to-assistant-to-store acceptance, with an injected fake model."""

import pytest
from sqlalchemy import select
from test_assistant import BASE, NOW, USER, Fake, call, create, props
from test_assistant import crm as _crm

from app.db import Object, transaction


@pytest.fixture
def crm(client):
    return _crm.__wrapped__(client)


def test_browser_agent_write_and_readback_matches_rest_page_database(crm, ui_login):
    csrf = ui_login(crm)
    identifier = create(
        crm,
        "deals",
        {
            "dealname": "Final integration fixture",
            "pipeline": "default",
            "dealstage": "qualifiedtobuy",
            "commerciale": USER,
        },
    )
    fake = Fake(
        call("get", kind="deals", id=identifier),
        call(
            "apply",
            operations=[
                {
                    "op": "update",
                    "kind": "deals",
                    "id": identifier,
                    "properties": {"dealstage": "closedwon"},
                }
            ],
        ),
    )
    crm.app.state.assistant_client = fake
    result = crm.post(
        "/ui-api/assistant",
        headers={"Authorization": "", "X-CSRF-Token": csrf},
        json={
            "context": {"now": NOW, "user": USER},
            "messages": [{"role": "user", "content": "Segna come vinta Final integration fixture"}],
        },
    )
    assert result.status_code == 200
    assert "Vinta" in result.json()["reply"]
    assert props(crm, "deals", identifier)["dealstage"] == "closedwon"
    query = crm.post(
        BASE + "/deals/search",
        json={
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "dealname",
                            "operator": "EQ",
                            "value": "Final integration fixture",
                        }
                    ]
                }
            ]
        },
    ).json()
    assert query["total"] == 1 and query["results"][0]["id"] == identifier
    page = crm.get("/deals/" + identifier, headers={"Authorization": ""})
    assert page.status_code == 200 and "Final integration fixture" in page.text
    assert "Won" in page.text
    with transaction(crm.app.state.engine) as session:
        assert session.get(Object, identifier).properties["dealstage"] == "closedwon"
        tickets = session.scalars(select(Object).where(Object.object_type == "tickets")).all()
        assert len(tickets) == 1
        assert tickets[0].properties["subject"] == "Avvio fornitura - Final integration fixture"
    # A repeated browser write follows the same once-per-deal rule.
    assert (
        crm.patch(
            "/ui-api/deals/" + identifier,
            headers={"Authorization": "", "X-CSRF-Token": csrf},
            json={"properties": {"dealstage": "closedwon"}},
        ).status_code
        == 200
    )
    assert crm.post(BASE + "/tickets/search", json={}).json()["total"] == 1
