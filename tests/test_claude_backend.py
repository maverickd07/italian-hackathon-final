import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.assistant.client import Disabled
from devtools.claude_backend import ClaudeClient, agent_message, claude_payload, create_test_app


def test_native_claude_tool_roundtrip():
    message = agent_message(
        {
            "stop_reason": "tool_use",
            "content": [
                {"type": "text", "text": "Controllo."},
                {
                    "type": "tool_use",
                    "id": "one",
                    "name": "search",
                    "input": {"args": {"kind": "companies"}},
                },
                {"type": "tool_use", "id": "two", "name": "users", "input": {"args": {}}},
            ],
        }
    )
    payload = claude_payload(
        [
            {"role": "system", "content": "Static prompt"},
            {"role": "user", "content": "Cerca"},
            message,
            {"role": "tool", "tool_call_id": "one", "content": "{}"},
            {"role": "tool", "tool_call_id": "two", "content": "{}"},
        ],
        [
            {
                "function": {
                    "name": "search",
                    "description": "Search CRM",
                    "parameters": {"type": "object"},
                }
            }
        ],
        "fake-claude",
    )
    assert payload["model"] == "fake-claude"
    assert payload["system"] == [{"type": "text", "text": "Static prompt"}]
    assert len(payload["messages"]) == 3
    assert [x["tool_use_id"] for x in payload["messages"][-1]["content"]] == ["one", "two"]
    assert payload["tools"][0]["input_schema"] == {"type": "object"}
    assert payload["tool_choice"]["disable_parallel_tool_use"] is True
    with pytest.raises(ValueError, match="Truncated"):
        agent_message({"stop_reason": "max_tokens", "content": []})


def test_real_transport_disabled_even_with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-never-used")
    monkeypatch.setenv("CLAUDE_TEST_ENABLED", "true")
    with pytest.raises(Disabled):
        asyncio.run(ClaudeClient().complete([], [], 1))


def test_retired_claude_cannot_be_reenabled_outside_pytest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-never-used")
    monkeypatch.setenv("CLAUDE_TEST_ENABLED", "true")
    monkeypatch.setenv("CLAUDE_MODEL", "fake-model")

    def forbidden_network(*args, **kwargs):
        pytest.fail("Retired Claude transport attempted a network request")

    monkeypatch.setattr("urllib.request.urlopen", forbidden_network)
    with pytest.raises(Disabled):
        asyncio.run(ClaudeClient().complete([], [], 1))


@pytest.mark.parametrize("module", ["run_claude", "run_claude_ui"])
def test_retired_launchers_exit(module):
    from importlib import import_module

    with pytest.raises(SystemExit, match="retired"):
        import_module("devtools." + module).main()


def test_retired_direct_uvicorn_factory(monkeypatch):
    with pytest.raises(RuntimeError, match="retired"):
        create_test_app()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with pytest.raises(RuntimeError, match="retired"):
        create_test_app(model_client=object())


def test_local_backend_fake_agent_and_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_TEST_TOKEN", "local-test-only")

    class FakeClaude:
        async def complete(self, messages, tools, timeout):
            if messages[-1]["role"] == "tool":
                data = json.loads(messages[-1]["content"])
                assert data["results"][0]["properties"]["fatturato_2025"] == "12345.67"
                return agent_message(
                    {"content": [{"type": "text", "text": "Fatturato: 12.345,67 euro."}]}
                )
            return agent_message(
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "test-call",
                            "name": "search",
                            "input": {"args": {"kind": "companies", "query": "Demo Supply"}},
                        }
                    ]
                }
            )

    app = create_test_app("sqlite:///" + str(tmp_path / "sandbox.db"), FakeClaude())
    with TestClient(app) as c:
        assert c.get("/docs").status_code == 200
        assert c.get("/health").json()["sandbox"] is True
        schema = c.get("/openapi.json").json()
        body = schema["paths"]["/__agente"]["post"]["requestBody"]["content"]["application/json"][
            "example"
        ]
        assert c.post("/__agente", json=body).status_code == 401
        r = c.post("/__agente", json=body, headers={"Authorization": "Bearer local-test-only"})
        assert r.json() == {"reply": "Fatturato: 12.345,67 euro."}


def test_local_database_and_railway_guards(monkeypatch):
    with pytest.raises(ValueError, match="SQLite"):
        create_test_app("postgresql://production")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "fake-railway")
    with pytest.raises(RuntimeError, match="Railway"):
        create_test_app()
