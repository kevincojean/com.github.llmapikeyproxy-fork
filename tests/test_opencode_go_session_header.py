# SPDX-License-Identifier: MIT
# Copyright (c) 2026 b3nw

"""
OpenCode Go requires an `x-opencode-session` header on every inference request.

Upstream announcement (same text filed against several clients):
- https://github.com/zai-org/feedback/issues/492
- https://github.com/Kilo-Org/kilocode/issues/13723

    "Starting 09/05, requests without an x-opencode-session header will error on
     our side ... Any stable UUID per conversation works; it just needs to be
     consistent across requests in the same session."

So there are two things to pin: the header is always present, and its value does
not change between requests belonging to the same conversation.

`litellm.acompletion` / `litellm.aembedding` are the only things stubbed here.
They are the paid vendor boundary; everything below them is the real provider.
"""

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import litellm

from rotator_library.client.executor import RequestExecutor
from rotator_library.core.constants import UPSTREAM_SESSION_ID_KWARG
from rotator_library.core.types import RequestContext
from rotator_library.providers.opencode_go_provider import (
    OPENCODE_SESSION_HEADER,
    OpencodeProvider,
)

# Deliberately not a deepseek/kimi/glm name: those trigger unrelated
# model-specific request rewriting that has nothing to do with headers.
TEST_MODEL = "opencode_go/test-model"
TEST_CREDENTIAL = "sk-opencode-test-key"


def _request_kwargs(**overrides):
    kwargs = {
        "model": TEST_MODEL,
        "messages": [{"role": "user", "content": "hello"}],
        "credential_identifier": TEST_CREDENTIAL,
    }
    kwargs.update(overrides)
    return kwargs


def _make_context(session_id):
    return RequestContext(
        model=TEST_MODEL,
        provider="opencode_go",
        kwargs={},
        streaming=False,
        credentials=[TEST_CREDENTIAL],
        deadline=0.0,
        session_id=session_id,
    )


async def test_acompletion_sends_stable_session_header():
    """The header is sent, and repeat turns of one conversation reuse its value."""
    provider = OpencodeProvider()
    session_id = str(uuid.uuid4())
    captured = []

    async def _capture(**kwargs):
        captured.append(kwargs)
        return "response"

    async with httpx.AsyncClient() as client:
        with patch.object(litellm, "acompletion", side_effect=_capture):
            for turn in ("first turn", "second turn"):
                await provider.acompletion(
                    client,
                    **_request_kwargs(
                        messages=[{"role": "user", "content": turn}],
                        **{UPSTREAM_SESSION_ID_KWARG: session_id},
                    ),
                )

    assert len(captured) == 2
    sent = [call["extra_headers"][OPENCODE_SESSION_HEADER] for call in captured]
    assert sent == [session_id, session_id]


async def test_acompletion_falls_back_to_generated_uuid():
    """A request must never reach OpenCode Go without the header."""
    provider = OpencodeProvider()
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return "response"

    async with httpx.AsyncClient() as client:
        with patch.object(litellm, "acompletion", side_effect=_capture):
            await provider.acompletion(client, **_request_kwargs())

    header = captured["extra_headers"][OPENCODE_SESSION_HEADER]
    # Raises ValueError if the fallback is not a real UUID.
    uuid.UUID(header)


async def test_aembedding_sends_session_header():
    """Embeddings hit the same upstream and are a separate code path."""
    provider = OpencodeProvider()
    session_id = str(uuid.uuid4())
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return "response"

    async with httpx.AsyncClient() as client:
        with patch.object(litellm, "aembedding", side_effect=_capture):
            await provider.aembedding(
                client,
                model=TEST_MODEL,
                input=["hello"],
                credential_identifier=TEST_CREDENTIAL,
                **{UPSTREAM_SESSION_ID_KWARG: session_id},
            )

    assert captured["extra_headers"][OPENCODE_SESSION_HEADER] == session_id


def test_executor_injects_session_id_only_for_providers_that_require_it():
    """The new kwarg must not leak into providers that never asked for it."""
    context = _make_context("session-abc")

    opting_in = AsyncMock()
    opting_in.requires_upstream_session_id = True
    kwargs = {}
    RequestExecutor._inject_upstream_session_id(opting_in, kwargs, context)
    assert kwargs[UPSTREAM_SESSION_ID_KWARG] == "session-abc"

    opting_out = AsyncMock()
    opting_out.requires_upstream_session_id = False
    kwargs = {}
    RequestExecutor._inject_upstream_session_id(opting_out, kwargs, context)
    assert UPSTREAM_SESSION_ID_KWARG not in kwargs


def test_executor_falls_back_when_session_inference_returns_nothing():
    """SessionTracker yields None for anchorless requests; the header still ships."""
    plugin = AsyncMock()
    plugin.requires_upstream_session_id = True
    kwargs = {}

    RequestExecutor._inject_upstream_session_id(plugin, kwargs, _make_context(None))

    uuid.UUID(kwargs[UPSTREAM_SESSION_ID_KWARG])
