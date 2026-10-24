# core — Infrastructure Improvements

## 2026-06-22 — Extend reasoning tag handling for `<think>`/`</think>`

Target: `feat(core): infrastructure improvements - latest aliases, error standardization, and utilities`
Files:
- `src/rotator_library/client/streaming.py`
- `src/rotator_library/client/executor.py`

Working commits before autosquash:
- `24876cfb fixup! feat(core): infrastructure improvements - latest aliases, error standardization, and utilities`

Final stack commit after autosquash:
- `039836ab feat(core): infrastructure improvements - latest aliases, error standardization, and utilities`

Verification:
- `uv run python3 -m py_compile src/rotator_library/client/streaming.py` — passed
- `uv run python3 -m py_compile src/rotator_library/client/executor.py` — passed
- `uv run ruff check src/rotator_library/client/streaming.py --select F401,F811,F821,E9` — passed
- `uv run ruff check src/rotator_library/client/executor.py --select F401,F811,F821,E9` — passed
- Live streaming test (umans/kimi-k2.6, max_tokens=300): reasoning properly captured, content clean
- Live streaming test (umans/kimi-k2.6, max_tokens=4096): full reasoning separated, haiku content only
- Live non-streaming test: reasoning extracted via regex, content clean
- Non-kimi model (mistral): unaffected, no false reasoning detection

Notes:
- Kimi K2 via umans streams reasoning as plain content with only a bare `</think>`
  (no opening `<think>`) to mark the transition to real content.
- Extended `_split_thought_tags` to handle both `<thought>...</thought>` (Gemma-4)
  and `<think>...</think>` tag pairs, plus the bare-close-tag pattern.
- Extended `_extract_thought_tags_from_response` (non-streaming) with matching
  regex patterns and bare-close detection.

## 2026-06-22 — Fix: remove _model_has_implicit_thinking (double-handling bug)

Target: `feat(core): infrastructure improvements - latest aliases, error standardization, and utilities`
Files:
- `src/rotator_library/client/streaming.py`

Working commits before autosquash:
- `9811c72c fixup! feat(core): ...`

Verification:
- `uv run python3 -m py_compile src/rotator_library/client/streaming.py` — passed
- `uv run ruff check src/rotator_library/client/streaming.py --select F401,F811,F821,E9` — passed
- Live streaming test (umans/kimi-k2.6): content no longer misclassified as reasoning

Notes:
- Removed `_IMPLICIT_THINKING_MODELS` tuple and `_model_has_implicit_thinking()`.
- LiteLLM already handles `<think>` tag separation during streaming for providers
  that emit them. Starting `in_thought_block=True` caused double-handling where
  post-thinking content was suppressed as reasoning_content.
- The tag-based detection in `_split_thought_tags` remains for providers that emit
  tags but where LiteLLM does not strip them (e.g. `<thought>` from Gemma-4).

## 2026-06-22 — Multi-segment display keys for PROVIDER_MODELS

Target: `feat(core): infrastructure improvements - latest aliases, error standardization, and utilities`
Files:
- `src/rotator_library/client/models.py`
- `src/rotator_library/model_definitions.py`
- `src/rotator_library/providers/openai_compatible_provider.py`
- `.fork/stack.yml` (added file ownership for model_definitions.py, openai_compatible_provider.py)

Verification:
- `uv run python3 -m py_compile` — passed (all 3 files)
- `uv run ruff check --select F401,F811,F821,E9` — passed (all 3 files)
- Hot-patched llm-proxy-dev: models listed as `umans/moonshot/kimi-k2.6` etc.
- Pricing fuzzy-matched correctly for kimi-k2.6, glm-5.1, glm-5.2
- Routing test: `umans/moonshot/kimi-k2` resolved to `umans-kimi-k2.6` upstream, response received

Notes:
- Enables aggregation providers (like umans) to present canonical `provider/org/model`
  display names via `PROVIDER_MODELS` dict keys containing slashes, while routing
  the `"id"` value to the upstream API.
- `ModelResolver.resolve_model_id`: changed `split("/")[-1]` to `split("/", 1)[1]`
  so multi-segment keys like `moonshot/kimi-k2.6` are preserved during lookup.
- `ModelDefinitions.get_model_definition`: added last-segment fallback so existing
  single-segment configs still work when the resolver passes multi-segment names.
- `OpenAICompatibleProvider.get_models`: dedup now checks both display-key suffixes
  and explicit `"id"` values from static definitions, preventing dynamic discovery
  from re-adding models that have a static display mapping.
- `OpenAICompatibleProvider.get_model_options`: strips provider prefix correctly
  instead of taking only the last segment.

## 2026-07-10 — OAuth error handling and credential lifecycle fixes

Branch: `fix/oauth-error-handling`
Target: `fix(core): stop invalidated OAuth credentials from rotating forever`

Files (11 modified):
- `src/rotator_library/usage/manager.py` — auth error cooldown in `_record_failure`, persist `clear_cooldown_if_exists`
- `src/rotator_library/usage/tracking/engine.py` — `_apply_cooldown` uses `max()` to prevent truncation race
- `src/rotator_library/error_handler.py` — `credential_reauth_needed` in ABNORMAL_ERROR_TYPES + priority, streamed dict 401/403/429 classification
- `src/rotator_library/core/errors.py` — `credential_reauth_needed` → HTTP 401 in status map
- `src/rotator_library/providers/openai_oauth_base.py` — propagate CredentialNeedsReauthError from get_auth_header, NO AUTO-REAUTH on headless, fix reauth queue (keep unavailable on failure), fix _queue_refresh membership gate, idle-exit clears _queued_credentials, timeout 15→45s
- `src/rotator_library/providers/anthropic_oauth_base.py` — same as OpenAI base
- `src/rotator_library/providers/google_oauth_base.py` — calendar.timegm for UTC expiry, pop stale token_expiry after refresh, ms/s normalization, idle-exit fix, timeout 15→45s, propagate CredentialNeedsReauthError
- `src/rotator_library/client/executor.py` — mid-stream non-rotatable errors wrapped in TerminalRequestError
- `src/rotator_library/client/streaming.py` — fix ClassifiedError constructor (message→original_exception)
- `src/rotator_library/providers/codex_provider.py` — parse_quota_error uses x-codex-*-reset-at headers
- `src/rotator_library/providers/utilities/codex_quota_tracker.py` — background refresh applies exhaustion cooldowns

Root causes fixed:
- RC1: API 401s now apply escalating global cooldown (15m→4h) removing dead credentials from rotation
- RC2: is_credential_available() still dead code, but _unavailable_credentials now preserved on failed reauth
- RC3: CredentialNeedsReauthError propagates from get_auth_header instead of serving dead cached tokens
- RC4: Headless servers log [NO AUTO-REAUTH] and keep cred unavailable (ported from Google base)
- RC5: Sequential sticky selection broken by RC1 fix (dead creds get global cooldown → filtered by candidate selection)

Verification:
- `uv run python3 -m py_compile` — passed (all 11 files)
- `uv run ruff check --select F401,F811,F821,E9` — passed (0 new errors; 5 pre-existing)

## 2026-06-22 — Sub-provider alias resolution and upstream context overrides

Target: `feat(core): infrastructure improvements - latest aliases, error standardization, and utilities`
Files:
- `src/rotator_library/model_info_service.py`
- `src/proxy_app/main.py`

Working commits before autosquash:
- `b9966964 fixup! feat(core): infrastructure improvements - latest aliases, error standardization, and utilities`

Changes:
- `model_info_service._get_alias_candidates()`: for multi-segment model IDs
  (e.g. `umans/moonshot/kimi-k2.6`), generate alias candidates for the
  sub-provider segment using `PROVIDER_ALIASES` (moonshot→moonshotai,
  z-ai→zai/zhipuai, qwen→alibaba).
- `model_info_service._resolve_model()` Step 3: fuzzy index search now includes
  alias candidates alongside the raw model ID for better matching.
- `PROVIDER_ALIASES` expanded with `moonshot`, `z-ai`, `qwen` entries.
- `main.py /v1/models`: generic loop applies upstream-authoritative context
  window overrides from providers (like Umans) that fetch context data during
  model discovery, overriding models.dev enrichment values.

Verification:
- `uv run python3 -m py_compile` — passed (both files)
- `uv run ruff check --select F401,F811,F821,E9` — passed (both files)
- Hot-patched llm-proxy-dev: pricing resolved correctly for all umans models
- `/v1/models` context_window values match upstream API (e.g. glm-5.2: 405504)

Notes:
- The sub-provider aliasing is generic and will benefit any future aggregation
  provider that uses multi-segment display keys.
- Context window override loop is guarded with try/except and only runs for
  providers known to supply `get_model_context_overrides()`.

---

### fix/quota-auth-reauth-detection — Detect expired credentials from billing/quota API failures

Branch: `fix/quota-auth-reauth-detection`

Files changed:
- `src/rotator_library/providers/utilities/x_ai_quota_tracker.py` — trigger reauth on billing 401/403
- `src/rotator_library/providers/utilities/codex_quota_tracker.py` — trigger reauth on quota 401/403
- `src/proxy_app/api/config.py` — recognize QuotaAuthFailed/BillingAuthFailed for needs_reauth badge
- `src/proxy_app/main.py` — overlay ErrorTracker auth errors onto quota-stats and health endpoints
- `webui/src/pages/Quota.tsx` — show error_count badge on provider row

Problem:
- Billing (xAI) and quota (Codex) fetch endpoints returning HTTP 401/403 were
  silently logged without marking credentials for re-authentication, leaving
  dead OAuth tokens in rotation indefinitely.
- Dashboard showed all credentials as "active", Quota page showed green bars,
  and Credentials page showed green "active" badges — even for dead credentials.
- Root cause: UsageManager only tracks cooldown/exhaustion, not auth health.
  The only signal path was ErrorTracker, but quota trackers didn't record errors
  and the credentials API only checked two error types.

Fix:
- xAI/Codex quota trackers now call `_queue_refresh(needs_reauth=True)` and
  `_record_refresh_error()` on 401/403 from billing/quota APIs.
- Credentials API (`/v1/admin/credentials`) now matches QuotaAuthFailed and
  BillingAuthFailed error types for the needs_reauth override.
- New `_overlay_auth_errors_on_quota_stats()` in main.py cross-references the
  ErrorTracker and flips credential status from "active" to "needs_reauth" in
  quota-stats responses. Applied to both `GET /v1/quota-stats` and the health
  endpoint so Dashboard counts and Quota page both reflect broken credentials.
- Quota page provider table shows `N err` badge when `error_count > 0`.

Verification:
- `uv run python3 -m py_compile` — passed (all 4 Python files)
- `uv run ruff check --select F401,F811,F821,E9` — passed (all 4 Python files)
- Hot-patched llm-proxy-dev: codex_oauth_1.json correctly shows needs_reauth
  on Credentials page, "1 err" badge on Quota page, "3 active / 1 error" on
  Dashboard, with QuotaAuthFailed in Error Summary and Recent Errors.

---

## 2026-07-09 — Responses API compatibility: root /responses route, model normalization, reasoning lifecycle

Branch: `fix/core-responses-compat`
Files:
- `src/proxy_app/main.py`
- `src/proxy_app/responses_compat.py`
- `tests/test_responses_compat.py`
- `tests/test_proxy_endpoints.py`

Changes:
- Added root `/responses` route as a compatibility alias for clients that
  already append `/responses` to their configured base URL or cannot safely
  use a `/v1` base path. Both `/responses` and `/v1/responses` route to the
  same `responses_api` handler.
- Added `_normalize_model_id()` helper at the API handler layer that rewrites
  compatibility model IDs (e.g. `openai/gpt-5.5` → `codex/gpt-5.5`) before
  the request reaches `RotatingClient.acompletion()`. The rewrite only fires
  when an alias exists and the target provider has credentials. This avoids
  modifying routing logic in `acompletion()`.
- Fixed reasoning stream lifecycle in `ResponsesStreamConverter`: reasoning
  now emits `response.output_item.added` + `response.reasoning_summary_part.added`
  before the first delta, and `response.reasoning_summary_text.done` +
  `response.reasoning_summary_part.done` + `response.output_item.done` during
  finalization. Previously reasoning only emitted bare delta events with a
  fresh `build_item_id("rs")` per chunk and `output_index: 0`.
- Replaced ad-hoc `output_index` allocation with a centralized
  `_allocate_output_index()` counter. Reasoning, message, and tool call items
  each get unique sequential indices. The `_finalize` method now builds
  `output_items` sorted by allocation index.

Verification:
- `uv run python3 -m py_compile` — passed (all source files)
- `uv run ruff check --select F401,F811,F821,E9` — passed (all source files)
- `uv run --with pytest python3 -m pytest tests/test_responses_compat.py tests/test_proxy_endpoints.py -v` — passed

Notes:
- `CodexProvider.get_models()` still returns `codex/<model>` (unchanged)
- `RotatingClient.acompletion()` routing logic unchanged
- `list_models()` and `get_model()` unchanged
- Ref: b3nw/LLM-API-Key-Proxy#110

## 2026-10-23 — Add `--env-file` / `PROXY_ENV_FILE` and drop the duplicate dotenv load

Target: `fix(core): add --env-file flag and remove duplicate dotenv load`
Files:
- `src/proxy_app/main.py`
- `README.md`

Branch: `fix/opencode-modeloptions`

Behavior:
- New `--env-file PATH` CLI flag, plus `PROXY_ENV_FILE` as the env-var equivalent.
  Precedence is `--env-file` > `$PROXY_ENV_FILE` > `./.env`.
- An explicit path loads with `override=True` (the file wins over the process
  environment) and fails fast via `parser.error` when the path is missing,
  instead of silently falling back to `./.env`.
- The default path keeps the old behaviour: `load_dotenv(ENV_FILE)` without
  override, then any additional `*.env` files in the working directory with
  `override=False`.
- `needs_onboarding()` now reads the module-level `ENV_FILE` instead of
  recomputing `get_data_file(".env")`, so the flag and the onboarding check
  agree on which file is authoritative.
- Non-interactive startup with a missing `.env` now prints an actionable error
  and exits 1 instead of entering the interactive credential tool.
- Removed the second `load_dotenv(ENV_FILE)` call that ran later in module
  initialisation. The first call already loaded the same file and nothing
  cleared or mutated the environment in between.

Verification:
- `uv run python3 -m py_compile src/proxy_app/main.py` — passed
- `uv run ruff check src/proxy_app/main.py --select F401,F811,F821,E9` — passed
- `uv run python src/proxy_app/main.py --env-file /tmp/definitely-missing.env`
  → `error: --env-file not found: /tmp/definitely-missing.env` (fails fast)
- `uv run python src/proxy_app/main.py --env-file <real .env> --port 18124`
  → `📁 Loaded .env file: ...`, server ready, 27 providers discovered

Notes:
- Documented the full CLI flag table in `README.md` under Deployment →
  Command-Line Arguments, including the `--env-file` precedence rules, because
  `compliance-check.yml` requires new CLI arguments to be documented there.
- The default-path branch still prints a count that includes the main `.env`
  while the load loop skips it. Known cosmetic mismatch, left unchanged
  deliberately (out of scope for this change).

## 2026-10-24 — Report upstream content policy violations clearly

Target: `fix(core): report upstream content policy violations clearly`
Files:
- `src/rotator_library/error_handler.py`
- `src/rotator_library/core/errors.py`
- `src/rotator_library/providers/provider_interface.py`
- `src/rotator_library/client/executor.py`
- `src/rotator_library/client/rotating_client.py`
- `src/rotator_library/client/cross_provider_executor.py`
- `src/rotator_library/anthropic_compat/streaming.py`
- `src/proxy_app/main.py`
- `tests/test_content_policy_violation.py`

Branch: `fix/badrequesterror`

Behavior:
- New `ProviderErrorType(StrEnum)` member `content_policy_violation`. There is no
  `moderation` vocabulary in the codebase.
- New `ProviderInterface.parse_content_policy_violation(error, error_body)` hook,
  returning `None` by default. There is no shared marker table; detection is
  provider specific. The base implementation enforces its own return type, so a
  bad override raises `TypeError` at its first call.
- `opencode_go` is the only override: it matches the two identifiers
  `data_inspection_failed` and `DataInspectionFailed` and returns
  `ContentPolicyViolation(reason=ContentPolicyReason.DATA_INSPECTION, marker=...)`.
- `classify_error` asks the provider plugin before the generic 400 fallback and
  returns `CONTENT_POLICY_VIOLATION` with HTTP 400. `should_rotate_on_error`
  already returned `False` for `invalid_request`, so the error stays terminal and
  no cross-provider fallback is attempted.
- `TerminalRequestError` now carries the `ClassifiedError`, so `executor.py` no
  longer classifies the same exception a second time.
- New `build_terminal_error_response(error_type, model, provider)` is the single
  client-facing builder; the streaming and non-streaming terminal paths both use
  it. The client sees
  `{"error": {"message", "type": "invalid_request", "code", "details": {...}}}`
  and never the raw `litellm.BadRequestError` text.
- One `lib_logger.warning` per content policy violation, naming
  `<provider>/<model>` and the matched marker. The full raw upstream body still
  goes to the failure logger unchanged.
- Downstream layers (`proxy_app/main.py`, `anthropic_compat/streaming.py`,
  `cross_provider_executor.py`) forward the clean message instead of
  re-stringifying the exception. The Anthropic layer maps
  `CONTENT_POLICY_VIOLATION` to `invalid_request_error`, not `api_error`.
- `_attempt_fallback` no longer replaces the original `ProxyExhaustionError` with
  a generic message.

Verification:
- `uv run pytest tests/test_content_policy_violation.py tests/test_error_handler.py -q` — passed
- `uv run pytest -m "not e2e" -q` — 546 passed, 1 deselected
- `uv run ruff check <changed files> --select F401,F811,F821,E9` — passed
  (`anthropic_compat/streaming.py` keeps its pre-existing unused-`Any` warning,
  which is present on `dev` too)
- `uv run python3 -m py_compile` on every changed module — passed

Notes:
- Gemini `SAFETY -> content_filter` is a `finish_reason` on a 200 response, not an
  error type, and is deliberately out of scope.
- `responses_compat.py` silently dropping error chunks and `MODEL_FALLBACK_*`
  being keyed by alias instead of resolved model name are known but out of scope.

### 2026-10-24 — Review follow-up (`fixup!` into the commit above)

Findings from the post-implementation review, folded into the same commit:

- `RotatingClient._execute_with_fallback` now re-raises a terminal
  `ProxyExhaustionError` before attempting `MODEL_FALLBACK_*`. Previously an
  unguarded fallback call would run first and rely on `_attempt_fallback`'s own
  refusal to surface the primary error; a reachable ordering bug if the refusal
  path ever changed. Covered by
  `test_configured_fallback_does_not_replace_content_policy_error`.
- `CrossProviderExecutor` stops the alias fan-out for terminal codes in both the
  non-streaming path (raises `ProxyExhaustionError` carrying the clean response
  instead of `NoAvailableKeysError`) and the streaming path (forwards the
  terminal SSE chunk instead of trying the next alias target).
- `classify_error`'s hook guard no longer relies on a bare `except TypeError:
  raise`. A `TypeError` raised *inside* a plugin is now logged and swallowed; only
  the contract violation (wrong return type) propagates.
- `anthropic_compat/streaming.py` no longer re-emits an upstream
  `error.message` verbatim when the chunk carries no `code`. A coded chunk keeps
  the message the builder already sanitized; an uncoded chunk gets a neutral
  message, so a raw `litellm` string cannot reach an Anthropic client.
- `_sanitized_openai_error` substitutes `"the requested model"` /
  `"the upstream provider"` when `litellm` does not expose `.model` /
  `.llm_provider`, instead of rendering empty strings.
- `serialize_level` gained `check_legal_wire_value`, called from
  `normalize_thinking`. An illegal value the resolver could produce now raises
  instead of being silently dropped, so a future capability change fails loudly
  at the request instead of shipping a bad wire value.

Not changed, with reasons:
- `_wrap_streaming_with_fallback` needs no terminal-code guard: it only inspects
  chunks whose `error.type` is in `_STREAMING_EXHAUSTION_TYPES`, and terminal
  errors carry `type: invalid_request`, so the guard would be unreachable dead
  code. Verified by instrumenting `_attempt_fallback`; it is never called for a
  content policy violation.
- The hook still runs before the provider 429/5xx quota parse. A body carrying
  both a content-policy marker and a quota mark is classified as content policy;
  markers are exact upstream identifiers, so the collision is not reachable for
  `opencode_go` today.
- `ProviderInterface` does not enforce the hook's return type in the base class;
  `classify_error` does, which is the only caller.

Verification:
- `uv run pytest -m "not e2e" -q` — 550 passed, 1 deselected
- `uv run ruff check <changed files> --select F401,F811,F821,E9` — passed
- `uv run python3 -m py_compile` on every changed module — passed
