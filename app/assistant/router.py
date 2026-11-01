"""HTTP boundary: authenticate in the existing middleware, errors remain Italian 200s."""

import asyncio
import json
import logging
import threading
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from .client import Disabled, OpenRouterClient
from .prompt import SYSTEM, TOOLS
from .tools import CRMTools, Refusal

router = APIRouter()
log = logging.getLogger(__name__)
DEADLINE_SECONDS = 45
MAX_TOOL_STEPS = 8


def tool_arguments(name, raw):
    """Accept the declared envelope and the provider's observed flat arguments."""
    args = json.loads(raw)
    if not isinstance(args, dict):
        raise Refusal("Argomenti dello strumento non validi. Nessuna modifica eseguita.")
    if "args" in args:
        if set(args) != {"args"}:
            raise Refusal("Argomenti ambigui dello strumento. Nessuna modifica eseguita.")
        args = args["args"]
    schema = next(t for t in TOOLS if t["function"]["name"] == name)["function"]["parameters"][
        "properties"
    ]["args"]
    if (
        not isinstance(args, dict)
        or set(args) - set(schema["properties"])
        or set(schema.get("required", [])) - set(args)
    ):
        raise Refusal("Argomenti dello strumento non validi. Nessuna modifica eseguita.")
    return args


def prepare(body):
    context = body["context"]
    now = datetime.fromisoformat(context["now"])
    if now.tzinfo is None or not isinstance(context["user"], str):
        raise ValueError()
    context = {"now": now, "user": context["user"].strip().lower()}
    attachments, history = [], []
    for message in body["messages"]:
        if message["role"] not in {"user", "assistant"} or not isinstance(message["content"], str):
            raise ValueError()
        item = {"role": message["role"], "content": message["content"]}
        for attachment in message.get("attachments", []):
            if message["role"] != "user" or not isinstance(attachment["content"], str):
                raise ValueError()
            index = len(attachments)
            attachments.append(attachment)
            item["content"] += "\nAllegato disponibile tramite attachment: " + json.dumps(
                {"index": index, "name": str(attachment.get("name", "CSV"))[:200]},
                ensure_ascii=False,
            )
        history.append(item)
    if not history or history[-1]["role"] != "user" or len(json.dumps(history).encode()) > 40000:
        raise ValueError()
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "system",
            "content": "Contesto della richiesta: "
            + json.dumps({"now": now.isoformat(), "user": context["user"]}),
        },
        *history,
    ]
    return context, attachments, messages


def tool_error(exc):
    if isinstance(exc, Refusal):
        return str(exc)
    if isinstance(exc, HTTPException):
        if exc.status_code == 404:
            return "Il record richiesto non esiste. Nessuna modifica eseguita."
        if exc.status_code == 409:
            return "Il valore non è univoco o è già presente. Nessuna modifica eseguita."
    return "Dati o operazione non validi. Nessuna modifica eseguita."


@router.post("/__agente")
async def assistant(request: Request):
    cancelled = threading.Event()
    toolkit = None
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            context, attachments, messages = prepare(await request.json())
            toolkit = CRMTools(request.app.state.engine, context, attachments, deadline, cancelled)
            await asyncio.to_thread(toolkit.identity)
            model = getattr(request.app.state, "assistant_client", None) or OpenRouterClient()
            steps = 0
            # At most 8 tool executions + one answer-only completion.
            for _ in range(MAX_TOOL_STEPS + 1):
                toolkit.check()
                if len(json.dumps(messages, ensure_ascii=False).encode()) > 56000:
                    raise Refusal(
                        "La conversazione è troppo lunga. Restringi la richiesta; nessuna modifica eseguita."
                    )
                response = await model.complete(
                    messages,
                    TOOLS if steps < MAX_TOOL_STEPS else [],
                    timeout=max(0.1, deadline - time.monotonic()),
                )
                calls = response.get("tool_calls") or []
                if not calls:
                    answer = response.get("content")
                    return {
                        "reply": answer.strip()
                        if isinstance(answer, str) and answer.strip()
                        else "Non ho abbastanza informazioni per rispondere. Nessuna modifica eseguita."
                    }
                if len(calls) > MAX_TOOL_STEPS - steps:
                    raise Refusal(
                        "Limite di operazioni raggiunto. Nessuna modifica eseguita; restringi la richiesta."
                    )
                # A write must be the only tool in its completion: no partial multi-tool batches.
                if len(calls) > 1 and any(
                    c["function"]["name"] in {"apply", "apply_csv"} for c in calls
                ):
                    raise Refusal("Riunire tutte le modifiche in una singola operazione atomica.")
                messages.append(
                    {"role": "assistant", "content": response.get("content"), "tool_calls": calls}
                )
                for call in calls:
                    steps += 1
                    name = call["function"]["name"]
                    if name not in {t["function"]["name"] for t in TOOLS}:
                        raise Refusal("Strumento non supportato. Nessuna modifica eseguita.")
                    args = tool_arguments(name, call["function"]["arguments"])
                    try:
                        result = await asyncio.to_thread(toolkit.execute, name, args)
                    except (Refusal, HTTPException, ValueError, KeyError, TypeError) as exc:
                        # Invalid writes stop immediately; never let the model "repair" by
                        # changing another target, clearing a VAT, or selecting another owner.
                        if name in {"apply", "apply_csv"}:
                            return {"reply": tool_error(exc)}
                        result = {"error": tool_error(exc)}
                    if toolkit.receipt:
                        return {"reply": toolkit.receipt}
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
            raise Refusal("Limite di operazioni raggiunto. Nessuna modifica eseguita.")
    except Disabled:
        return {"reply": "L’assistente AI non è ancora abilitato. Nessuna modifica eseguita."}
    except TimeoutError:
        cancelled.set()
        return {
            "reply": toolkit.receipt
            if toolkit and toolkit.receipt
            else "Tempo disponibile esaurito. Non posso confermare il completamento; verifica lo stato nel CRM prima di riprovare."
        }
    except Refusal as exc:
        return {"reply": str(exc)}
    except Exception as exc:  # noqa: BLE001 -- contract requires an Italian 200 on assistant errors
        # Do not log messages, attachments, key, user email, or provider exception text.
        log.warning("assistant_failed type=%s", type(exc).__name__)
        return {
            "reply": toolkit.receipt
            if toolkit and toolkit.receipt
            else "Non riesco a completare la richiesta: dati non validi o servizio temporaneamente non disponibile. Nessuna modifica confermata."
        }
    finally:
        cancelled.set()
