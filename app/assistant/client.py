"""Fixed-model OpenRouter transport; no retries, no fallback models, no key logging."""

import asyncio
import json
import logging
import os
import urllib.request

MODEL = "openai/gpt-6-luna"
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class Disabled(Exception):
    pass


class OpenRouterClient:
    async def complete(self, messages, tools, timeout):
        # Checked on every call; merely configuring the competition key never enables spending.
        if os.getenv("ASSISTANT_LIVE_ENABLED") != "true" or os.getenv("PYTEST_CURRENT_TEST"):
            raise Disabled()
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise Disabled()
        payload = {
            "model": MODEL,
            "messages": messages,
            "tools": tools,
            "max_tokens": 1800,
            "stream": False,
            "parallel_tool_calls": False,
        }
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        if len(encoded) > 64000:
            raise ValueError("Conversazione troppo lunga: restringi la richiesta.")

        def call():
            request = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=encoded,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=max(0.1, min(timeout, 35))) as response:
                return json.loads(response.read(2_000_000))

        usage = {}
        status = "error"
        try:
            result = await asyncio.wait_for(asyncio.to_thread(call), timeout=timeout)
            usage = result.get("usage") or {}
            status = "ok"
            return result["choices"][0]["message"]
        finally:
            log.info(
                "assistant_model_usage %s",
                json.dumps(
                    {
                        "model": MODEL,
                        "status": status,
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get(
                            "cached_tokens"
                        ),
                        "cost_usd": usage.get("cost"),
                    }
                ),
            )
