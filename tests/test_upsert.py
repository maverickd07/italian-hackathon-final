from concurrent.futures import ThreadPoolExecutor


def upsert(client, prefix, email, props):
    return client.post(
        prefix + "/contacts/batch/upsert",
        json={"inputs": [{"id": email, "idProperty": "email", "properties": props}]},
    )


def test_concurrent_email_upsert_preserves_every_field(client, prefix):
    def write(i):
        return upsert(
            client,
            prefix,
            "Person@Example.test" if i % 2 else "person@example.test",
            {f"field_{i}": str(i)},
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(pool.map(write, range(24)))
    assert all(r.status_code == 200 for r in responses), [
        (r.status_code, r.text) for r in responses
    ]
    results = [r.json()["results"][0] for r in responses]
    assert len({r["id"] for r in results}) == 1
    assert sum(r["new"] for r in results) == 1
    obj = client.get(prefix + "/contacts/person@example.test?idProperty=email").json()
    assert all(obj["properties"][f"field_{i}"] == str(i) for i in range(24))
    assert client.post(prefix + "/contacts/search", json={}).json()["total"] == 1


def test_create_racing_upsert_and_duplicate_patch(client, prefix):
    def write(i):
        if i % 2:
            return client.post(
                prefix + "/contacts",
                json={"properties": {"email": "RACE@example.test", f"f{i}": str(i)}},
            )
        return upsert(client, prefix, "race@example.test", {f"f{i}": str(i)})

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(write, range(16)))
    assert all(r.status_code in (200, 201, 409) for r in responses)
    assert all(responses[i].status_code == 200 for i in range(0, 16, 2))
    obj = client.get(prefix + "/contacts/race@example.test?idProperty=email").json()
    assert all(obj["properties"][f"f{i}"] == str(i) for i in range(0, 16, 2))
    assert client.post(prefix + "/contacts/search", json={}).json()["total"] == 1
    other = client.post(
        prefix + "/contacts", json={"properties": {"email": "other@example.test"}}
    ).json()
    assert (
        client.patch(
            prefix + "/contacts/" + other["id"], json={"properties": {"email": "race@example.test"}}
        ).status_code
        == 409
    )
    assert (
        client.get(prefix + "/contacts/" + other["id"]).json()["properties"]["email"]
        == "other@example.test"
    )


def test_existing_contact_and_batch_atomicity(client, prefix):
    obj = client.post(
        prefix + "/contacts",
        json={"properties": {"email": "old@example.test", "firstname": "Keep"}},
    ).json()
    r = upsert(client, prefix, "old@example.test", {"lastname": "New"})
    assert r.status_code == 200 and r.json()["results"][0]["id"] == obj["id"]
    assert r.json()["results"][0]["new"] is False
    assert r.json()["results"][0]["properties"]["firstname"] == "Keep"
    r = client.post(
        prefix + "/contacts/batch/upsert",
        json={
            "inputs": [
                {"id": "new@example.test", "idProperty": "email", "properties": {}},
                {"id": "bad", "idProperty": "firstname", "properties": {}},
            ]
        },
    )
    assert r.status_code == 400
    assert client.get(prefix + "/contacts/new@example.test?idProperty=email").status_code == 404
    assert (
        upsert(client, prefix, "old@example.test", {"email": "different@example.test"}).status_code
        == 400
    )


def test_auth_ui_and_api_require_token(client):
    for path in [
        "/",
        "/companies",
        "/contacts",
        "/deals",
        "/tickets",
        "/dormant-customers",
        "/assistant",
    ]:
        for authorization in ["", "Bearer wrong"]:
            assert (
                client.get(
                    path, headers={"Authorization": authorization}, follow_redirects=False
                ).status_code
                == 303
            ), path
    for path in ["/openapi.json", "/does-not-exist", "/crm/v3/objects/contacts"]:
        for authorization in ["", "Bearer wrong"]:
            assert client.get(path, headers={"Authorization": authorization}).status_code == 401
    assert client.post("/__agente", json={}, headers={"Authorization": ""}).status_code == 401
    assert (
        client.post(
            "/crm/v3/objects/contacts/batch/upsert",
            json={"inputs": []},
            headers={"Authorization": ""},
        ).status_code
        == 401
    )
    assert client.get("/health", headers={"Authorization": ""}).status_code == 200
    assert client.get("/ui-static/relay.js", headers={"Authorization": ""}).status_code == 200
