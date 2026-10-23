# Fork tests

Canonical feature ID: `tests`
Stack subject: `feat(tests): add local test suite (153 tests, zero-cost, no network)`
Manifest: `.fork/stack.yml`

This file is the shared, repo-tracked history for the test suite.
Note: the stack subject above is the literal commit subject on `dev` and
predates the current count of 543 tests. `check-stack.py` validates manifest
subjects against real commits, so the subject string cannot be reworded here
without rewording that commit.

## 2026-10-23 — Remove test-suite fiction, declare pytest, add the `e2e` marker

Target: `fix(tests): make the test suite reproducible and document the e2e marker`
Files:
- `pyproject.toml`
- `requirements.txt`
- `uv.lock`
- `tests/conftest.py`
- `tests/README.md`
- `tests/test_opencode_go_live.py`
- `tests/test_resilient_io.py`
- `tests/test_access_log_middleware.py`
- `tests/test_anthropic_compat_e2e.py`
- `tests/test_anthropic_streaming.py`
- `tests/test_usage_reconciliation.py`
- `tests/rotator_library/test_vertex_provider.py`
- removed: `tests/utils/test_resilient_io.py`, `tests/utils/__init__.py`

Branch: `fix/opencode-modeloptions`

What was wrong and what changed:
- **pytest was undeclared.** `[dependency-groups] dev` had only `ruff`, and
  `uv.lock` had zero pytest entries, so `uv sync` deleted the test runner.
  Added `pytest==9.1.1`, `pytest-asyncio==1.4.0`, `pytest-mock==3.17.0` to the
  dev group and pinned the same versions in `requirements.txt`.
- **`unit` / `integration` markers were fiction.** Declared in
  `[tool.pytest.ini_options]` but used by zero tests, so `-m unit` and
  `-m integration` selected nothing. Removed both. Replaced with a single real
  marker, `e2e`, carried by `test_opencode_go_live.py`.
- **README documented commands that did not work.** It suggested `-m unit`,
  `-m integration`, and `pytest tests/ test_anthropic_translator.py` (the latter
  errored on a wrong path). Rewritten with working commands, including
  `pytest -m "not e2e"` for the always-free subset.
- **README cited 6 modules that do not exist** (`test_background_refresher.py`,
  `test_credential_filter.py`, `test_cross_provider.py`,
  `test_model_latest_registry.py`, `test_provider_singleton.py`,
  `test_rotating_client.py`). Replaced the three invented category tables with
  one table listing every module that actually exists: 42 `test_*.py` files
  (43 `.py` files if `conftest.py` is counted).
- **README claimed "No network access" unconditionally**, which is false for the
  live test. The guarantees now say "everything except `e2e`", and a dedicated
  section explains what `e2e` does, where it reads credentials from
  (`$PROXY_ENV_FILE`, else `~/.config/com.github.llmapikeyproxy/.env`), and that
  it skips when unconfigured.
- **25 dead `@pytest.mark.asyncio` decorators** removed from 5 files.
  `asyncio_mode = "auto"` makes them no-ops. Removed the now-unused `pytest`
  imports that this exposed in `test_anthropic_compat_e2e.py` and
  `test_anthropic_streaming.py`.
- **Deprecated session-scoped `event_loop` fixture** removed from
  `tests/conftest.py`. It is the pytest-asyncio 0.x pattern; installed version is
  1.4.0 where it is ignored.
- **Duplicate test module merged.** `tests/utils/test_resilient_io.py` had 2
  tests covering tempfile-creation failure buffering, which
  `tests/test_resilient_io.py` did not cover. Merged them into
  `tests/test_resilient_io.py` as the parametrized
  `test_safe_write_json_buffers_on_tempfile_creation_failure[oserror|permissionerror]`,
  then deleted the duplicate module and `tests/utils/__init__.py` (which existed
  only to allow the duplicate basename).
- Cleaned the unused imports across `tests/` that the decorator removal exposed
  and ruff F401 flagged: 29 findings across 26 import lines.

Verification:
- `uv lock` → resolved 81 packages; `uv sync --dry-run` no longer uninstalls pytest
- `uv run pytest --collect-only -q` → 543 tests collected
- `uv run pytest -m e2e --collect-only -q` → exactly 1 test
- `uv run pytest -q -m "not e2e"` → 540 passed, 2 pre-existing failures
- `uv run pytest -q` → 540 passed, 3 failed (2 pre-existing + the live GLM-5.2 case)
- `uv run pytest tests/test_resilient_io.py` → merged tests collect and pass
- `uv run ruff check tests/ --select F401,F811,F821,E9` → all checks passed

Notes:
- CI still does not run pytest. That is a known gap, intentionally out of scope
  for this change.
- `.fork/stack.yml` still says `feat(tests): add local test suite (153 tests,
  zero-cost, no network)`. That string is the literal commit subject on `dev`
  and `check-stack.py` validates manifest subjects against real commits, so
  rewording it here would fail validation. The current count (543) is recorded
  in this ledger instead. Fixing the subject requires rewording the commit.

## 2026-10-23 — Repair the two long-standing test failures

Target: `fix(tests): repair stale umans assertion and xai time-bomb test`
Files:
- `tests/test_umans_quota_tracker.py`
- `tests/test_x_ai_quota_tracker.py`

Branch: `fix/opencode-modeloptions`

Root causes:
- `test_store_baselines_to_usage_manager` asserted `quota_max_requests == 200`.
  Commit `dd26793` (`fix(umans): normalize API base and show quota without proxy
  requests`) changed the stored limit to `requests_hard_cap or requests_limit`,
  i.e. 400, because the 200 soft limit is not enforced upstream. The test was
  written before that change in `3de6733` and never updated. Production was
  correct; the assertion was stale.
- `test_parse_period_end_ts_iso_z` asserted `_parse_period_end_ts("2026-07-01...")
  > time.time()`. The hardcoded date expired in July 2026, so the assertion could
  never pass again. It also tested nothing about the function: "a literal is in
  the future" is not a property of ISO-8601 parsing.

Fixes:
- Umans: assert against `snapshot.requests_hard_cap` instead of a literal, plus a
  guard that the fixture hard cap is 400. The assertion now tracks the source of
  truth, so a future change to the effective limit cannot silently drift again.
- xAI: replaced the wall-clock comparison with exact epoch equality
  (`== 1782864000.0`), covering the `Z` and bare-naive forms plus the two `None`
  paths (unparseable input, missing input). Stable forever, and it actually tests
  the conversion.

Verification:
- `uv run pytest -q tests/test_umans_quota_tracker.py tests/test_x_ai_quota_tracker.py` → 46 passed
- `uv run pytest -q -m "not e2e"` → 542 passed, 0 failed
- `uv run pytest -q` → 542 passed, 1 failed (the live `e2e` GLM-5.2 config case only)
- `uv run ruff check` on both files → passed

Notes:
- No production code changed. Both failures were test defects.
- No test clock dependency added. The remaining `time.time()` assertions in
  `test_usage_window_modes.py` and `test_usage_tracking.py` compute
  `time.time() + 3600` at run time, so they cannot expire.
