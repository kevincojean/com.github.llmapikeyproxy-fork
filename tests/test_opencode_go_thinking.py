# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Kevin Cojean

import json

import httpx
import pytest

from rotator_library import RotatingClient
from rotator_library.model_definitions import ModelDefinitions

CHAT_COMPLETION = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "created": 0,
    "model": "openai/test",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "ok"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


@pytest.fixture
def models_env(monkeypatch):
    def _set(config: dict):
        monkeypatch.setenv("OPENCODE_GO_MODELS", json.dumps(config))
        ModelDefinitions().reload_definitions()

    yield _set
    monkeypatch.delenv("OPENCODE_GO_MODELS", raising=False)
    ModelDefinitions().reload_definitions()


async def _upstream_body(alias, messages, tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=CHAT_COMPLETION)

    client = RotatingClient(
        api_keys={"opencode_go": ["sk-opencode-test"]},
        data_dir=tmp_path,
        configure_logging=False,
    )
    transport_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await client.http_client.aclose()
        client.http_client = transport_client
        client._executor._http_client = transport_client
        await client.acompletion(model=f"opencode_go/{alias}", messages=messages)
    finally:
        await transport_client.aclose()
        await client.close()
    return captured["body"]


async def test_model_option_from_alias_reaches_upstream_body(models_env, tmp_path):
    models_env(
        {
            "trash": {
                "id": "mimo-v2.6-flash",
                "options": {"extra_body": {"thinking": {"type": "disabled"}}},
            }
        }
    )

    body = await _upstream_body("trash", [{"role": "user", "content": "hi"}], tmp_path)

    assert body["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in body


async def test_effort_family_drops_thinking(models_env, tmp_path):
    models_env(
        {
            "trash-fallback": {
                "id": "hy3",
                "options": {"extra_body": {"thinking": {"type": "disabled"}}},
            }
        }
    )

    body = await _upstream_body(
        "trash-fallback", [{"role": "user", "content": "hi"}], tmp_path
    )

    assert body["reasoning_effort"] == "none"
    assert "thinking" not in body


async def test_toggle_and_effort_family_emits_both(models_env, tmp_path):
    models_env(
        {
            "high": {
                "id": "deepseek-v4.1-flash",
                "options": {"thinking": "enabled", "reasoning_effort": "high"},
            }
        }
    )

    body = await _upstream_body("high", [{"role": "user", "content": "hi"}], tmp_path)

    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "high"


async def test_tool_call_guard_is_not_reversed(models_env, tmp_path):
    models_env({"guard": {"id": "deepseek-v4.1-flash", "options": {"thinking": "enabled"}}})
    messages = [
        {"role": "user", "content": "list files"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "ls", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "[]"},
    ]

    body = await _upstream_body("guard", messages, tmp_path)

    assert body["thinking"] == {"type": "disabled"}
    assert body["messages"][1]["reasoning_content"] == ""


async def test_always_on_family_is_not_re_enabled(models_env, tmp_path):
    models_env({"kimi": {"id": "kimi-k2.6", "options": {"thinking": "disabled"}}})

    body = await _upstream_body("kimi", [{"role": "user", "content": "hi"}], tmp_path)

    assert "thinking" not in body


async def test_effort_family_can_turn_thinking_off(models_env, tmp_path):
    models_env(
        {
            "glm-off": {
                "id": "glm-5.2",
                "options": {"extra_body": {"thinking": {"type": "disabled"}}},
            }
        }
    )

    body = await _upstream_body("glm-off", [{"role": "user", "content": "hi"}], tmp_path)

    assert body["reasoning_effort"] == "none"


async def test_effort_family_clamps_low_to_high(models_env, tmp_path):
    models_env({"glm": {"id": "glm-5.2", "options": {"reasoning_effort": "low"}}})

    body = await _upstream_body("glm", [{"role": "user", "content": "hi"}], tmp_path)

    assert body["reasoning_effort"] == "high"


def test_every_family_emits_only_legal_values():
    from rotator_library.providers.utilities.opencode_go_thinking import (
        FAMILIES,
        OFF_ALIASES,
        ReasoningLevel,
        normalize_thinking,
        resolve_intent_and_level,
        serialize_level,
    )

    for capability in FAMILIES.values():
        for request in (
            {"reasoning_effort": "none"},
            {"reasoning_effort": "off"},
            {"reasoning_effort": "low"},
            {"reasoning_effort": "high"},
            {"reasoning_effort": "max"},
            {"thinking": {"type": "disabled"}},
            {"thinking": {"type": "enabled"}},
            {},
        ):
            intent, level = resolve_intent_and_level(request, capability, "probe")
            value = serialize_level(level, capability)
            assert value is None or value in capability.legal_wire_values
            body = normalize_thinking(request, "probe", capability)
            emitted = body.get("extra_body", {}).get("reasoning_effort")
            if emitted is not None:
                assert emitted in capability.legal_wire_values
                assert emitted not in OFF_ALIASES or emitted == "none"
            assert level is not ReasoningLevel.OFF or capability.off_value is not None

