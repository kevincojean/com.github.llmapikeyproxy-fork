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

## 2026-10-24 — Send legal `reasoning_effort` values

Target commit subject:
`fix(opencode_go): send legal reasoning_effort values`

Files changed:
- `src/rotator_library/providers/utilities/opencode_go_thinking.py`
- `tests/test_opencode_go_thinking.py`

Branch: `fix/badrequesterror`

Problem:
- `hy3` / `hy4` declared `off_value = "no_think"`. The upstream accepts only
  `max|xhigh|high|medium|low|minimal|none`, so every "thinking off" request was a
  guaranteed 400.
- Three distinct inputs collapsed to that value: config `thinking: {type: disabled}`,
  config `reasoning_effort: "none"` (`none` is in `OFF_ALIASES`), and the Anthropic
  compat layer emitting `reasoning_effort="disable"`. No config could avoid it.
- `glm-5.2` / `glm-5.3` declared `(HIGH, MAX)` with no `off_value`, so an explicit
  "off" request was silently dropped by the "no off switch" branch instead of
  turning thinking off.

Behavior:
- `hy3`, `hy4`: `off_value = "none"`. Levels unchanged `(LOW, HIGH)`.
- `glm-5.2`, `glm-5.3`: `off_value = "none"`. Levels stay `(HIGH, MAX)`; `low`
  still clamps up to `high`, and `off` now turns thinking off.
- `ThinkingCapability.__post_init__` no longer requires `OFF` to be present in
  `levels` for an effort family to carry an `off_value`. Every other validation
  is unchanged.
- `serialize_level` now enforces a runtime postcondition: the emitted value must be
  a member of `ThinkingCapability.legal_wire_values`. Anything else is dropped and
  logged at warning, so the next model added cannot repeat this defect.
- `NO_THINK` removed (no family needs it). `NO_NEED = "none"` still serves the
  `gpt-*` families that list `OFF` explicitly.

Verification:
- `uv run pytest tests/test_opencode_go_thinking.py -q` — 8 passed
- `uv run pytest -m "not e2e" -q` — 546 passed, 1 deselected
- `uv run ruff check <changed files> --select F401,F811,F821,E9` — passed
- `uv run python3 -m py_compile` on the changed modules — passed

Notes:
- `test_effort_family_drops_thinking` now expects `"none"`; it used to lock the bug in.
- Added `test_every_family_serializes_only_legal_values`, a single invariant test
  over all `FAMILIES` entries instead of a per-model matrix.
- Live verification of whether `none` actually disables thinking (rather than
  merely being the lowest effort) was not performed; the failure mode addressed
  here is the 400, which `none` removes either way.

### 2026-10-24 — Review follow-up (`fixup!` into the commit above)

- `normalize_thinking` now calls `check_legal_wire_value` before serialisation. If
  `resolve_intent_and_level` ever produces a level whose wire value is outside the
  family's `legal_wire_values`, the request raises instead of silently dropping
  `reasoning_effort`. The `serialize_level` drop-and-warn remains for the
  defensive path.
- The previous invariant test only restated `legal_wire_values`. It now drives
  `resolve_intent_and_level` + `normalize_thinking` across eight request shapes
  (`none`, `off`, `low`, `high`, `max`, `thinking: disabled`, `thinking: enabled`,
  empty) for every `FAMILIES` entry, and asserts the emitted body value is legal,
  that `no_think` is never emitted, and that `OFF` is never produced for a family
  without an `off_value`.
- Known, deliberately not changed: `deepseek-v4` declares `OFF` in its levels but
  has no `off_value`, so `read_level("none")` (which maps to `OFF` via
  `OFF_ALIASES`) resolves to `UNSET` and emits no `reasoning_effort`. It does not
  send an illegal value, so it is outside this fix; turning thinking off for that
  family would need `TOGGLE_AND_EFFORT` off-semantics work.

Verification:
- `uv run pytest tests/test_opencode_go_thinking.py -q` — 8 passed
- `uv run pytest -m "not e2e" -q` — 550 passed, 1 deselected
