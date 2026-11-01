"""Local-only Claude adapter and minimal API playground for the existing CRM agent."""

import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.assistant.client import Disabled
from app.assistant.router import router
from app.catalog import save, seed
from app.db import Object, init_db, make_engine, transaction
from app.schemas import Create
from app.store import create_record

log = logging.getLogger(__name__)


def claude_payload(messages, tools, model):
    """Translate our agent protocol into native Anthropic Messages tool blocks."""
    system, history = [], []
    for message in messages:
        role = message["role"]
        if role == "system":
            system.append({"type": "text", "text": message["content"]})
            continue
        blocks = []
        if role == "tool":
            role = "user"
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message["tool_call_id"],
                    "content": message["content"],
                }
            )
        else:
            if message.get("content"):
                blocks.append({"type": "text", "text": message["content"]})
            for call in message.get("tool_calls", []):
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["function"]["name"],
                        "input": json.loads(call["function"]["arguments"]),
                    }
                )
        if not blocks:
            continue
        if history and history[-1]["role"] == role:
            history[-1]["content"].extend(blocks)
        else:
            history.append({"role": role, "content": blocks})
    payload = {"model": model, "system": system, "messages": history, "max_tokens": 1800}
    if tools:
        payload["tools"] = [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "input_schema": t["function"]["parameters"],
            }
            for t in tools
        ]
        payload["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
    return payload


def agent_message(result):
    text, calls = [], []
    for block in result["content"]:
        if block["type"] == "text":
            text.append(block["text"])
        elif block["type"] == "tool_use":
            calls.append(
                {
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block["input"], ensure_ascii=False),
                    },
                }
            )
    if result.get("stop_reason") == "max_tokens":
        raise ValueError("Truncated Claude response")
    return {"role": "assistant", "content": "\n".join(text) or None, "tool_calls": calls}


class ClaudeClient:
    async def complete(self, messages, tools, timeout):
        # Retired: retain the fake-protocol fixtures, never contact Anthropic.
        raise Disabled("Claude testing has been retired; use the official OpenRouter client.")


def create_test_app(database_url=None, model_client=None):
    if os.getenv("RAILWAY_ENVIRONMENT_ID"):
        raise RuntimeError("Claude sandbox must not run in Railway")
    url = database_url or "sqlite:///" + str(Path(__file__).resolve().parents[1] / "claude-test.db")
    if not url.startswith("sqlite:///"):
        raise ValueError("Claude sandbox requires its own local SQLite database")
    if model_client is None or not os.getenv("PYTEST_CURRENT_TEST"):
        raise RuntimeError("Claude sandbox retired; only injected fake clients in tests are allowed")

    @asynccontextmanager
    async def lifespan(app):
        engine = make_engine(url)
        init_db(engine)
        app.state.engine = engine
        app.state.assistant_client = model_client or ClaudeClient()
        with transaction(engine, write=True) as s:
            if s.scalar(select(Object.id).limit(1)) is None:
                seed(s, migrated=True)
                save(
                    s,
                    "users",
                    "sandbox",
                    {
                        "nome": "Test",
                        "cognome": "User",
                        "email": "tester@relay.local",
                        "attivo": "S",
                    },
                )
                company = create_record(
                    s,
                    "companies",
                    Create(
                        properties={
                            "name": "Demo Supply",
                            "domain": "demo.example",
                            "fatturato_2025": "12345.67",
                            "classe_cliente": "C",
                        }
                    ),
                )
                create_record(
                    s,
                    "deals",
                    Create(
                        properties={
                            "dealname": "Demo Order",
                            "pipeline": "default",
                            "dealstage": "qualifiedtobuy",
                            "commerciale": "tester@relay.local",
                            "amount": "1500",
                            "deal_currency_code": "EUR",
                        },
                        associations=[
                            {"to": {"id": company.id}, "types": [{"associationTypeId": 5}]}
                        ],
                    ),
                )
                save(s, "migration", "last", {"sandbox": True})
        try:
            yield
        finally:
            engine.dispose()

    security = HTTPBearer(auto_error=False)

    def authenticate(
        credentials: HTTPAuthorizationCredentials | None = Depends(security),  # noqa: B008
    ):
        token = os.getenv("CLAUDE_TEST_TOKEN", "")
        if (
            not token
            or not credentials
            or not secrets.compare_digest(credentials.credentials.encode(), token.encode())
        ):
            raise HTTPException(401, "Valid sandbox bearer token required")

    app = FastAPI(
        title="Relay Agent — Local Claude Sandbox",
        lifespan=lifespan,
        description="Local test database. Use Authorize with CLAUDE_TEST_TOKEN, then Try it out. Replies are in Italian.",
    )
    app.include_router(router, dependencies=[Depends(authenticate)])

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "sandbox": True,
            "model_configured": False,
            "key_configured": False,
            "enabled": False,
        }

    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()
        schema["paths"]["/__agente"]["post"]["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object"},
                    "example": {
                        "context": {
                            "now": "2026-12-02T10:00:00+01:00",
                            "user": "tester@relay.local",
                        },
                        "messages": [
                            {
                                "role": "user",
                                "content": "Quanto abbiamo fatturato con Demo Supply nel 2025?",
                            }
                        ],
                    },
                }
            },
        }
        return schema

    app.openapi = openapi
    return app
