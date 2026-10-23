# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Kevin Cojean

import json
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

from rotator_library import RotatingClient

ENV_FILE = Path(
    os.getenv(
        "PROXY_ENV_FILE",
        Path.home() / ".config/com.github.mirrowel-llmapikeyproxy/.env",
    )
).expanduser()

REAL_MODELS = (
    "mimo-v2.6-flash",
    "hy3",
    "deepseek-v4.1-flash",
    "qwen3.7-plus",
    "GLM-5.2",
    "mimo-v2.6-pro",
)


def _load_env_file(path):
    if not path.is_file():
        return
    for key, value in dotenv_values(path).items():
        if value is not None:
            os.environ.setdefault(key, value)


def _credentials():
    keys = [
        value
        for key, value in sorted(os.environ.items())
        if key.startswith("OPENCODE_GO_API_KEY") and value.strip()
    ]
    return {"opencode_go": keys} if keys else {}


@pytest.fixture(scope="module")
def live_api_keys():
    _load_env_file(ENV_FILE)
    keys = _credentials()
    if not keys:
        pytest.skip("no OPENCODE_GO_API_KEY configured")
    configured = json.loads(os.getenv("OPENCODE_GO_MODELS", "{}"))
    known = {entry.get("id") for entry in configured.values()}
    missing = [model for model in REAL_MODELS if model not in known]
    if missing:
        pytest.skip(f"models not in OPENCODE_GO_MODELS: {missing}")
    return keys


@pytest.mark.e2e
async def test_configured_models_answer_opencode_go(live_api_keys, tmp_path):
    client = RotatingClient(
        api_keys=live_api_keys,
        data_dir=tmp_path,
        configure_logging=False,
        max_retries=0,
    )
    failures = {}
    try:
        for model in REAL_MODELS:
            try:
                response = await client.acompletion(
                    model=f"opencode_go/{model}",
                    messages=[{"role": "user", "content": "Reply with: ok"}],
                    max_tokens=32,
                )
                message = response.choices[0].message
                if not (message.content or message.reasoning_content):
                    failures[model] = "empty response"
            except Exception as exc:
                failures[model] = f"{type(exc).__name__}: {exc}"
    finally:
        await client.close()

    assert not failures, failures
