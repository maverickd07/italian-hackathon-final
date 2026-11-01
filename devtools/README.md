# Retired Claude test tools

Claude live testing was retired at the user's request on 2026-10-09.
Both former launchers exit immediately. ClaudeClient.complete always raises
Disabled, even if old Anthropic environment variables are still present.
Pure protocol helpers and injected fake-client tests remain for regression coverage.

Use the standard app.main:app entrypoint for the CRM. Its official assistant
transport uses OpenRouter with openai/gpt-6-luna. OPENROUTER_API_KEY supplies
the organizer credential; ASSISTANT_LIVE_ENABLED=false keeps all live calls off.
Changing that switch requires explicit user spending authorization.

The old local test database is retained; no CRM data was deleted. Retiring these
tools does not revoke the Anthropic credential at its provider or erase historical
chat records. The production Docker image excludes this directory.
