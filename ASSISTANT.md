# R13 assistant implementation

`POST /__agente` is registered by `app/main.py`; implementation is isolated in
`app/assistant/`. No importer, normalization module or deployment changes are required.
The existing bearer-token middleware applies: invalid/missing credentials return 401.
Authenticated assistant failures return HTTP 200 with an Italian `reply`.

## Model access and budget

Live calls are **disabled by default**. The presence of `OPENROUTER_API_KEY` alone
never enables them. Only after the user's explicit permission to spend the competition
budget may an operator set `ASSISTANT_LIVE_ENABLED=true`. Do not enable it as part of
installation or deployment. No variables were changed by this implementation.

The transport fixes the model to `openai/gpt-6-luna`, uses OpenRouter's chat completion
endpoint, has no retries or model fallback, and bounds output to 1,800 tokens per call.
The system prompt and tool definitions are static; request context is a separate message.
This preserves a common prefix for provider prompt caching; actual cache hits are not
guaranteed. UTF-8 request payloads are capped at 64 KB and accumulated conversational
messages at 56 KB. These are conservative size limits, not exact tokenizer measurements.
There are at most eight tool executions and nine model completions per turn, with a
45-second internal deadline. No database transaction spans a model call.

Every actual provider call emits an `assistant_model_usage` INFO event with model,
status, prompt/completion/cached token counts and provider-reported USD cost. Missing
usage/cost is null, not zero. Messages, user email, attachments and keys are not logged.
The provider's $10 cap remains the daily spending ceiling; these controls do not promise
that a particular number of conversations will fit in $10.

## Behavior and tools

Each request supplies the entire history, context date and active user. There is no
server conversation store. Supplied system/tool roles are rejected. Attachment contents
remain server-side and are exposed through deterministic CSV parsing tools.

Tools support search with REST filters, record reads and associations, create/update/
associate through the same `app.store` functions as REST, list memberships, pipeline
stages, active-user lookup, relative calendar dates, customer ownership, complete SQL
aggregates and CSV batches. Search uses `app.search.run_search`; aggregates use its
filter predicates. Query pages contain at most 20 rows with totals/continuations.
Aggregates do not truncate at the page size. Mixed-currency amount sums are rejected.

“My customers” is the distinct union of companies associated with the user's deals
(`commerciale`) and tickets (`assegnatario`). `context.now` drives relative dates and
is passed through `session.info['context_now']` for R11's exact 180-day automation.

The prompt instructs the model to execute explicit unambiguous requests directly,
clarify multiple matches, refuse forbidden changes and never alter unrelated data.
Existing targets and changed fields must have been read in the current turn. Updates
lock records and check the observed field values before writing. Owners and stages
are validated in deterministic code; database uniqueness enforces R7. R10/R11/R12
run through the shared store, never duplicated by assistant code.

All requested mutations are submitted in one transaction (up to 200 operations), with
rollback on any error. A write ends the tool loop, so a later model step cannot make
additional changes. Records and explicit association writes are re-read before commit;
only after successful commit does deterministic Italian text report the verified result.
A timeout near commit reports uncertainty instead of claiming a rollback or encouraging
blind retries. Repeated create requests are not automatically deduplicated: the official
contract has no request idempotency key.

CSV attachments use `;`, existing Sinergia normalizers and deterministic header mapping.
Products match by normalized `hs_sku`; other objects default to `id_legacy`. Missing or
ambiguous matches, duplicate CSV keys and malformed values abort the entire update.
Creating missing records requires the model to supply `create_missing=true` only when
explicitly requested by the user. Cancelled source rows are skipped. CSV batches are
limited to 200 rows and 200 KB; larger files must be split. Custom column mappings are
supported. No general ZIP migration is performed by the assistant.

## Verification and limits

`tests/test_assistant.py` contains 21 fake-model integration tests, including both official
examples, ambiguity, missing targets, duplicate VAT, inactive owners, customer ownership,
relative dates, R10/R11/R12, CSV import, atomic rollback, four concurrent conversations,
untouched-record snapshots, authentication, default-disabled model access, full aggregates,
pagination, catalogs/lists/associations, the tool limit, stale writes and invalid CSV batches.

Fake scripts exercise actual HTTP routes and the database; they do **not** demonstrate
real-model language understanding or official evaluation scores. Ambiguity interpretation,
user authorization scope and choosing the intended fields still depend on the model.
No real model call or deployment was made.

Run with `.venv/bin/pytest -q tests/test_assistant.py`. To check PostgreSQL, set
`TEST_DATABASE_URL` to a local test database; the existing fixture creates and drops only
random isolated test schemas. Never point tests at production.

OpenRouter transport references:
- https://openrouter.ai/docs/api_reference/overview
- https://openrouter.ai/docs/cookbook/administration/usage-accounting

## Agent correctness/stability pass — 2026-10-09

The local Claude experiment server was stopped. Production still selects only
`openai/gpt-6-luna` through OpenRouter, with live calls disabled unless explicitly
authorized. This pass made no real model requests and no deployment.

Verified mutation receipts now use Italian field/stage labels and Italian number
formatting for both old and new values. Named records no longer expose internal
object type names or numeric IDs in these receipts. The acting user's active status
is checked again inside the write transaction, after any model latency.

The 21 integration cases plus 10 fault/concurrency cases (31 total) passed on both
SQLite and local PostgreSQL using fake models. Added coverage includes malformed tool
arguments, unsupported tools, mixed parallel writes, rollback of an in-flight write
on deadline expiry, user deactivation during a turn, concurrent updates of different
fields on one record, a concurrent VAT collision, rejection of supplied system/tool
roles and Italian mutation receipts. These results establish the tested deterministic
behavior, not a measured real-model interpretation accuracy or official score.

A further fake-only pass increased Agent coverage to 36 passing cases on SQLite and
PostgreSQL. It verified 40 independent conversations with four in flight, rollback of
R10's generated ticket AND persistent once-only marker after a later batch failure,
no duplicate ticket on repeated win transitions, required fresh reads after a historical
confirmation, and January-to-February month-end handling in a leap year. No production
code change was needed for these cases. This load test excludes real-model latency and
does not establish provider throughput, model interpretation accuracy or Railway latency.
