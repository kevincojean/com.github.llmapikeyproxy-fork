# SPDX-License-Identifier: MIT
# Copyright (c) 2026 b3nw

"""
OpenCode Go requires an `x-opencode-session` header on every request.

Upstream announcement (same text filed against several clients):
- https://github.com/zai-org/feedback/issues/492
- https://github.com/Kilo-Org/kilocode/issues/13723

    "Starting 09/05, requests without an x-opencode-session header will error on
     our side ... Any stable UUID per conversation works; snip it just needs to be
     consistent across requests in the same session."

Two things to pin: the header is always present, and its value does not change
between turns of one conversation.

`litellm.acompletion` / `litellm.aembedding` are the only things stubbed. They
are the paid vendor boundary - a real call costs money and needs credentials.
Everything below them is the real provider.
"""

import uuid
from unittest.mock import patch

import httpx
import litellm

from rotator_library.providers.opencode_go_provider import (
    OPENCODE_SESSION_HEADER,
    OpencodeProvider,
)

# Deliberately not a deepseek/kimi/glm name: those trigger unrelated
# model-specific request rewriting that has nothing to do with headers.
TEST_MODEL = "opencode_go/test-model"
TEST_CREDENTIAL = "sk-opencode-test-key"


async def _session_ids_for(conversations):
    provider = OpencodeProvider()
    captured = []

    async def _capture(**kwargs):
        captured.append(kwargs["extra_headers"][OPENCODE_SESSION_HEADER])
        return "response"

    async with httpx.AsyncClient() as client:
        with patch.object(litellm, "acompletion", side_effect=_capture):
            for messages in conversations:
                await provider.acompletion(
                    client,
                    model=TEST_MODEL,
                    messages=messages,
                    credential_identifier=TEST_CREDENTIAL,
                )
    return captured


async def test_header_is_stable_across_turns_of_one_conversation():
    """
    Given a conversation whose history grows over two turns
    When each turn is sent to OpenCode Go
    Then both requests carry the same session id
    """
    turn_one = [{"role": "user", "content": "explain the retry policy"}]
    turn_two = turn_one + [
        {"role": "assistant", "content": "It backs off exponentially."},
        {"role": "user", "content": "and on 429?"},
    ]

    first, second = await _session_ids_for([turn_one, turn_two])

    assert first == second
    uuid.UUID(first)


async def test_header_differs_between_conversations():
    """
    Given two unrelated conversations
    When each is sent to OpenCode Go
    Then they do not collapse onto the same session id
    """
    first, second = await _session_ids_for(
        [
            [{"role": "user", "content": "explain the retry policy"}],
            [{"role": "user", "content": "write a haiku about yaks"}],
        ]
    )

    assert first != second


async def test_embedding_still_sends_the_header():
    """
    Given an embedding request, which has no conversation to anchor to
    When it is sent to OpenCode Go
    Then the mandatory session header is still present and is a UUID
    """
    provider = OpencodeProvider()
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
            )

    uuid.UUID(captured["extra_headers"][OPENCODE_SESSION_HEADER])
