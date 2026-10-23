# opencode-go - Opencode Go provider

Canonical feature ID: `opencode-go`
Manifest: `.fork/stack.yml`

Stack subjects:
- `feat(opencode_go): add Opencode Go provider with 3-window quota tracking and scraped balance`
- `fix(opencode_go): send required x-opencode-session header on Go requests`
- `fix(opencode_go): honor model options and normalize thinking requests`

This file is the shared, repo-tracked history for opencode-go feature changes.
Local workspace state may contain run logs and scratch notes, but this file is
canonical across contributors and developer workspaces.

## 2026-10-23 — Honor model options and normalize thinking requests

Target commit subject:
`fix(opencode_go): honor model options and normalize thinking requests`

Files changed:
- `src/rotator_library/providers/utilities/opencode_go_thinking.py` (new)
- `src/rotator_library/client/transforms.py`
- `src/rotator_library/client/executor.py`
- `src/rotator_library/client/request_builder.py`
- `src/rotator_library/core/types.py`
- `src/rotator_library/request_sanitizer.py`
- `src/rotator_library/providers/opencode_go_provider.py`
- `tests/test_opencode_go_thinking.py` (new)
- `tests/test_provider_transforms.py`
- `.gitignore`

What changed:
- Options lookup: `RequestContext.model_alias` now captures the requested alias
  before `resolve_model_id` overwrites `kwargs["model"]`; `ProviderTransforms._get_model_options`
  looks up by alias first, then resolved name, and only consults the provider plugin hook,
  deep-copying the returned dict. `OpencodeProvider` now owns `get_model_options` and delegates
  to `ModelDefinitions` for `opencode_go`, so providers without the hook (gemini, nvidia,
  mistral, anthropic) keep their previous behavior of not applying `*_MODELS.options`.
- New pure module `opencode_go_thinking.py`: `ThinkingControl` / `ThinkingIntent` /
  `ReasoningLevel` StrEnums, validated `ThinkingCapability` dataclass, 13-entry `FAMILIES`
  prefix table, `capability_for`, `normalize_thinking` (returns a new dict, never mutates),
  `serialize_level`.
- Normalizer runs inside `transforms.apply` AFTER option application and BEFORE the
  sanitizer, writing native fields under `extra_body` and popping the top-level copies.
- Sanitizer gained an opt-in keyword `accepts_thinking: bool | None = None`; `None`
  preserves the legacy allowlist behavior byte-for-byte.
- `executor._accepts_thinking` maps no capability hook and `ThinkingControl.UNKNOWN` to
  `None` (legacy allowlist), and otherwise `control in TOGGLE_CONTROLS`. Unmapped opencode
  models therefore keep their previous wire behavior and never newly forward client-supplied
  `thinking`.
- `_guard_thinking_tool_calls` now skips injection for UNKNOWN or non-toggle capabilities,
  so the guard is no longer silently inverted; its message string had its em dash
  replaced with a plain hyphen.
- `OpencodeProvider` gained `get_thinking_capability`; `SUPPORTED_PARAMS` gained
  `reasoning_effort`; `_ensure_deepseek_v4_reasoning` / `_ensure_moonshot_reasoning` were
  deleted (they treated "absent" as "enable"); their `reasoning_content` padding was
  retained as `_pad_deepseek_v4_reasoning_content` and `_pad_moonshot_reasoning_content`
  (padding values `""` and `" "` unchanged).

Note: `transforms.py`, `executor.py`, `request_builder.py`, `core/types.py`, and
`request_sanitizer.py` are shared `core` files; this entry is the cross-feature
documentation required by AGENTS.md for touching files owned by another feature key.

Verification:
- `uv run pytest tests/test_opencode_go_thinking.py -q` - 6 passed
- `uv run pytest -q` - 540 passed, 2 failed
- `uv run pytest tests/test_opencode_go_thinking.py tests/test_provider_transforms.py tests/test_request_sanitizer.py -q` - 35 passed
- `uv run ruff check <changed files> --select F401,F811,F821,E9` - all checks passed
- `uv run python3 -m py_compile` on the changed modules - passed

Pre-existing failures (unrelated to this change, recorded so a future reader does not
blame this work):
- `tests/test_umans_quota_tracker.py::test_store_baselines_to_usage_manager`
  (expects `quota_max_requests == 200`, actual 400)
- `tests/test_x_ai_quota_tracker.py::test_period_end_ts_iso_z`
  (hardcoded `2026-07-01` timestamp is now in the past)

Notes:
- The global `ModelDefinitions()` fallback in `_get_model_options` was removed because it
  newly enabled `*_MODELS.options` for providers whose request behavior must not change
  (gemini, nvidia, mistral, anthropic). Option lookup is now per-provider through the plugin
  hook. Regression coverage:
  `tests/test_provider_transforms.py::test_options_not_applied_for_provider_without_hook`.
- Unknown/undiscovered opencode models pass through unchanged (`ThinkingControl.UNKNOWN`),
  so new vendor models are never mis-normalized, and they keep legacy sanitizer behavior
  rather than newly forwarding client-supplied `thinking`.
- `tests/test_opencode_go_thinking.py` covers both config shapes: the flat
  `options.thinking` shape the design doc describes and the nested
  `options.extra_body.thinking` shape real configs use, e.g.
  `{"trash": {"id": "mimo-v2.6-flash", "options": {"extra_body": {"thinking": {"type": "disabled"}}}}}`.
  Both normalize to the same upstream body. `test_model_option_from_alias_reaches_upstream_body`
  (renamed from `test_option_from_alias_reaches_wire_body`) and `test_effort_family_drops_thinking`
  exercise the nested shape; the remaining four tests keep the flat shape.
- `ProviderTransforms.apply_sync` remains unused dead code and was intentionally not extended.
