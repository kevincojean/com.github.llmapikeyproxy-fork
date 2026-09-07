# OpenCode Go provider

Canonical feature ID: `opencode-go`
Stack subject: `feat(opencode_go): add Opencode Go provider with 3-window quota tracking and scraped balance`
Manifest: `.fork/stack.yml`

This file is the shared, repo-tracked history for the OpenCode Go feature.
Local workspace state may contain run logs and scratch notes, but this
file is canonical across contributors and developer workspaces.

OpenCode Go is the managed-inference API at `https://opencode.ai/zen/go/v1`,
OpenAI-shaped, with three percent-based usage windows (5hr rolling, weekly,
monthly) scraped from the workspace dashboard rather than exposed as a real
quota endpoint.

## Note on the feature id vs. topic prefix mismatch

The manifest id is `opencode-go` (hyphen) but the topic prefix is
`feat(opencode_go)` (underscore). `.fork/check-stack.py` derives the feature key
from the literal text inside the prefix parentheses, so it cannot match the
canonical subject back to this feature id. The practical consequence: a second
commit under this prefix is **not** auto-permitted, and **both** subjects must
be listed under `allowed_duplicate_features:` keyed by `opencode_go`. This is the
same class of exception already documented for `models:` in the manifest.

## 2026-09-07 - Send the required `x-opencode-session` header

Branch: `fix/provider-opencodego-required-header`
Stack subject: `fix(opencode_go): send required x-opencode-session header on Go requests`

Files:
- `src/rotator_library/providers/opencode_go_provider.py`
- `src/rotator_library/core/constants.py`
- `src/rotator_library/providers/provider_interface.py`
- `src/rotator_library/client/executor.py`
- `tests/test_opencode_go_session_header.py`
- `.fork/stack.yml`
- `.fork/features/opencode-go.md` (this file)
- `.fork/features/core.md`

### Problem

OpenCode filed the same request against several clients on 2026-09-03:

- https://github.com/zai-org/feedback/issues/492 (open)
- https://github.com/Kilo-Org/kilocode/issues/13723 (closed by #13752)

> Starting 09/05, requests without an `x-opencode-session` header will error on
> our side - we need a stable per-conversation ID for routing/optimization.
> Any stable UUID per conversation works; it just needs to be consistent across
> requests in the same session.

Two constraints, not one: the header must always be present, **and** its value
must not change between requests in the same conversation. A fresh `uuid4()` per
request satisfies the first and fails the second.

The provider sent `HTTP-Referer`, `X-Title`, `User-Agent` and an optional
`Cookie`, and nothing else. Every `opencode_go` request was failing from 09/05.

### Design

The proxy already computes exactly the value OpenCode is asking for.
`SessionTracker.infer_session()` (`src/rotator_library/session_tracking.py`)
mints `str(uuid.uuid4())` per inferred conversation, keeps it stable across
turns via compounding evidence anchors, and it already runs on every request.
`RequestContext.session_id` carries it for sticky credential routing.

The only gap was that it never reached the provider: `_prepare_request_kwargs()`
builds the kwargs dict both plugin call sites use, and `session_id` was not in it.

Reusing that id was preferred over having the provider derive its own (for
example `uuid5(namespace, first_user_message)`). Deriving separately would
duplicate logic the repo already owns, break differently on compaction, and
drift from the id used for credential stickiness. Reusing it means the header
value and the sticky-routing scope are the same thing.

Plumbing is **opt-in** rather than unconditional. Other custom providers only
pop `transaction_context`; an unconditional new kwarg would be forwarded to
LiteLLM by all of them and break unrelated providers. So:

- `UPSTREAM_SESSION_ID_KWARG = "upstream_session_id"` in
  `core/constants.py` - one name shared by the executor and the provider that
  pops it, instead of two literals that can drift.
- `ProviderInterface.requires_upstream_session_id: bool = False` - the opt-in
  flag, alongside the existing `skip_cost_calculation` capability flag.
- `RequestExecutor._inject_upstream_session_id()` - static, so it is testable
  without standing up a request pipeline. Injects only for opted-in plugins.
  Falls back to a fresh UUID when `context.session_id` is `None` (the tracker
  returns `None` only for anchorless requests): not stable across turns, but the
  header ships rather than being absent.
- `OpencodeProvider.requires_upstream_session_id = True`, plus
  `_pop_session_id()` and a `session_id` argument on `_get_headers()`.
  Both `acompletion()` and `aembedding()` pop and forward it. Popping matters:
  the value is transport metadata and must not reach the request body.
  (`SUPPORTED_PARAMS` would have dropped it silently - popping makes it explicit.)

`get_models()` also talks to `/zen/go/v1` and now sends the header too, using a
single `self._discovery_session_id` generated in `__init__`. The issue text says
"all outbound inference HTTP requests", so discovery is probably not gated - but
if it is, discovery would fail silently and fall back to three hardcoded model
names. Cheap insurance.

### Cross-area file ownership (deliberate exception)

`src/rotator_library/client/executor.py`, `core/constants.py` and
`providers/provider_interface.py` are mapped to the `core` feature in
`.fork/stack.yml`, but they ship in this `fix(opencode_go):` commit.

Rationale: the core hop is ~15 lines and is inert without the provider change -
`requires_upstream_session_id` defaults to `False`, so with no opted-in provider
the executor code path never fires. Splitting it into a separate `feat(core):`
PR would have meant two sequential merges on a fix that was already breaking
production as of 09/05. `.fork/check-stack.py` validates commit subjects and
feature-file contents only, not file ownership, so the split commit is not
required for CI. Mirrored in `.fork/features/core.md`.

### Out of scope: `opencode_zen`

`opencode_zen` hits `https://opencode.ai/zen/v1` - same operator, different
product - and needs the same header. It is **not** covered here: no Zen access
is available to verify against, and it is a separate feature area
(`opencode-zen`) requiring its own commit under the one-commit-per-PR rule.
Left as a known follow-up.

### Tests

`tests/test_opencode_go_session_header.py`, 5 cases. `litellm.acompletion` /
`litellm.aembedding` are the only things stubbed - they are the paid vendor
boundary; everything below them is the real provider.

- `test_acompletion_sends_stable_session_header` - two turns with one session id
  produce the same header value both times. This is the actual requirement:
  presence *and* stability.
- `test_acompletion_falls_back_to_generated_uuid` - with no id supplied the
  header is still present and parses as a UUID.
- `test_aembedding_sends_session_header` - separate code path, easy to forget.
- `test_executor_injects_session_id_only_for_providers_that_require_it` - the
  regression guard that stops the new kwarg leaking into other providers.
- `test_executor_falls_back_when_session_inference_returns_nothing` - pins the
  anchorless-request fallback.

Written and confirmed failing before the fix (RED: 3* `KeyError:
'x-opencode-session'`, 2* `AttributeError: ... has no attribute
'_inject_upstream_session_id'`), then GREEN.

### Verification

- `uv run python3 -m py_compile` - passed (all 5 changed files)
- `uv run ruff check --select F401,F811,F821,E9` - passed (all 5 changed files)
- `uv run --with pytest --with pytest-asyncio python3 -m pytest tests/test_opencode_go_session_header.py -q` - 5 passed
- `uv run --with pytest --with pytest-asyncio python3 -m pytest tests/ -q` - **2 failed, 520 passed, 15 errors**.
  Baseline on the same worktree before any change was **2 failed, 515 passed,
  15 errors** - identical pre-existing failures
  (`test_umans_quota_tracker.py::test_store_baselines_to_usage_manager`,
  `test_x_ai_quota_tracker.py::test_parse_period_end_ts_iso_z`, which is a
  hardcoded-date assertion that expired) and the same 15 pre-existing setup
  errors in `test_failure_logger.py` / `tests/utils/test_paths.py`. The +5 are
  the new tests. No regressions.
- `uv run --no-project python3 .fork/check-stack.py` - **already failing on
  `dev` before this change**, with 22 errors from a manifest that is stale
  relative to an advanced `upstream/dev`: missing manifest subjects, undeclared
  `codex` / `core` / `webui` duplicates, and `proxy.md` not mentioning its
  subject. Verified by stashing - byte-identical output with and without this
  change, so this commit adds no new violations. Not fixed here (out of scope
  for this PR), but the manifest needs a resync against `upstream/dev`.
- The new `opencode_go` exception was verified to parse by driving
  `check-stack.parse_manifest()` directly: both subjects come back under the
  `opencode_go` key, and this file contains the canonical subject verbatim as
  the feature-file content check requires.
- Live verification not possible from the dev workspace. Post-merge check:
  `opencode_go` requests stop erroring in the deployment.

### Notes

- Session identity here is *inferred*, not proven. `SessionTracker` deliberately
  starts a new session on compaction, so OpenCode receives a new routing id at
  that point. That is a routing hint on their side, not a correctness boundary.
- Concurrent conversations sharing one credential now surface distinct session
  ids upstream. Intended, but it is a visible change in what our traffic looks
  like to OpenCode.
- The issues say "any stable UUID", so no v4-specific shape is assumed. The
  tracker emits `uuid4()` anyway, so either reading is satisfied.
