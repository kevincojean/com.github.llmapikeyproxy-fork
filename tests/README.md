# SPDX-License-Identifier: MIT
# Copyright (c) 2026 b3nw
#
# LLM-API-Key-Proxy Test Suite

## Design Philosophy

Tests are **fully runnable locally without any real API keys or provider connections**. We achieve this through:

1. **Mocked HTTP layer** - `httpx.AsyncClient` is mocked so no real outbound requests are made
2. **Synthetic credentials** - In-memory credential files and env vars, never touching real keys
3. **FastAPI TestClient** - Full proxy app is tested end-to-end using `httpx.AsyncClient` against the ASGI app
4. **Deterministic fixtures** - All test data is self-contained in `conftest.py`

### Cost-Safe Guarantees

Everything except tests marked `e2e`:

- **Zero cost** - No queries are sent to real LLM providers
- **No API keys needed** - Tests use fake/synthetic credentials
- **No OAuth flows** - OAuth token refresh is mocked; no browser interaction needed
- **No network access** - All HTTP calls are intercepted at the `httpx`/`litellm` level
- **Runs in <30s** - Fast enough to run before every commit

### The `e2e` marker

Tests marked `e2e` are the one exception. They call a real vendor API with real
credentials and **cost real money**.

- They read credentials from a `.env` file: `$PROXY_ENV_FILE`, else
  `~/.config/com.github.mirrowel-llmapikeyproxy/.env`.
- They `pytest.skip` when no credentials are configured, but plain `pytest`
  still runs them whenever credentials are present. Use `pytest -m "not e2e"`
  for a guaranteed-free run.
- Run only the e2e tests with `pytest -m e2e`.

## Test Modules

| Test Module | What It Covers | Why It Matters |
|---|---|---|
| `test_anthropic_translator.py` | Anthropic/OpenAI format translation | Breakage here silently corrupts all Claude Code requests |
| `test_anthropic_streaming.py` | SSE format conversion (OpenAI to Anthropic events) | Streaming breakage is hard to detect in production |
| `test_anthropic_models_dev.py` | Dynamic model discovery via models.dev | Stale model lists hide new models |
| `test_anthropic_oauth_headers.py` | OAuth request headers | Wrong headers make the provider reject the request |
| `test_anthropic_compat_e2e.py` | Full Anthropic Messages API round-trip | Each branch modifies translator/streaming differently |
| `test_error_handler.py` | Error classification, duration parsing | Misclassified errors cause wrong retry/rotation behavior |
| `test_error_tracker.py` | Per-key error tracking and lockouts | Bad tracking keeps failed keys disabled |
| `test_request_sanitizer.py` | Parameter stripping (dimensions, thinking) | Invalid params cause 400s from providers |
| `test_provider_transforms.py` | Per-provider request mutations | Transform regressions silently break specific providers |
| `test_provider_config.py` | Provider configuration parsing | Config bugs stop providers from initializing |
| `test_provider_plugins.py` | All provider plugin registration and init | Branch-specific providers can fail to register |
| `test_model_filters.py` | Whitelist/blacklist model filtering | Wrong filter means missing or extra models exposed |
| `test_model_alias.py` | MODEL_ALIAS env parsing, alias resolution | Alias breakage breaks cross-provider routing |
| `test_model_fallback.py` | Fallback chains between models | Broken fallback gives hard failures instead of retries |
| `test_usage_tracking.py` | Window tracking, quota groups, custom caps | Usage bugs cause over/under-use of credentials |
| `test_usage_window_modes.py` | per_model vs credential vs daily reset modes | Different branches alter usage tracking config |
| `test_usage_reconciliation.py` | Reconciling local counts with upstream quota | Drift causes premature or late exhaustion |
| `test_classifier_scoped_routing.py` | Isolated per-user credential pools | Leaking user keys into global rotation is a data bug |
| `test_selection_engine.py` | Credential selection ordering | Wrong order ignores priority tiers |
| `test_fair_cycle.py` | Fair-cycle rotation across credentials | Some credentials starve otherwise |
| `test_credential_manager.py` | Discovery, dedup, env-based creds | Credential loading bugs leave zero providers available |
| `test_session_tracking.py` | Evidence-based session inference and affinity | Wrong affinity breaks provider-side caching |
| `test_proxy_endpoints.py` | FastAPI endpoint routing and auth | Endpoint breakage means 404/401 for all clients |
| `test_access_log_middleware.py` | Request logging middleware | Logging bugs leak or drop request data |
| `test_headless_detection.py` | TTY/headless detection | Wrong detection blocks non-interactive deploys |
| `test_openai_oauth_callback.py` | OAuth callback handling | Callback bugs break first-time setup |
| `test_xai_oauth_flow.py` | xAI device-code OAuth flow | Provider auth unavailable without it |
| `test_responses_compat.py` | OpenAI Responses API translation | codex-cli and the OpenAI SDK depend on it |
| `test_suppress_litellm_warnings.py` | litellm log noise suppression | Noise hides real warnings |
| `test_timeout_config.py` | HTTP timeout configuration | Timeout bugs hang or kill long requests |
| `test_failure_logger.py` | Failure log writing and masking | Unmasked credentials in logs are a leak |
| `test_cline_pass_quota_tracker.py` | ClinePass 3-window quota tracking | Wrong windows cause bans or waste |
| `test_umans_quota_tracker.py` | Umans request-based quota tracking | Same |
| `test_x_ai_quota_tracker.py` | xAI billing quota parsing | Same |
| `test_gemini_cli_models.py` | Gemini CLI model definitions | Missing models or wrong quota groups |
| `test_opencode_go_thinking.py` | opencode_go thinking/reasoning normalization | Wrong normalization changes billing and output |
| `test_opencode_go_session_header.py` | Required `x-opencode-session` header | Missing header means rejected requests |
| `test_opencode_go_live.py` | **`e2e`** - real opencode_go models answer | Catches vendor-side breakage that mocks cannot |
| `rotator_library/test_litellm_providers.py` | LiteLLM provider integration | Upstream library contract drift |
| `rotator_library/test_vertex_provider.py` | Vertex AI Express Mode provider | Provider-specific quirks |
| `utils/test_paths.py` | Root/log/data path resolution | Wrong paths write data to unexpected places |
| `test_resilient_io.py` | JSON writes with retry buffering | Lost auth tokens when disk writes fail |

## Running

```bash
# All tests. Includes e2e when credentials are configured (may cost money).
pytest

# Everything except e2e: always free, no network
pytest -m "not e2e"

# Only the real-vendor tests: costs money, needs a .env file
pytest -m e2e

# Specific module
pytest tests/test_anthropic_translator.py -v

# Verbose
pytest -v
```
