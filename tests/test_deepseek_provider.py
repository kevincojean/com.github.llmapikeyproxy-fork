# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Mirrowel
from __future__ import annotations

import json
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from rotator_library.providers.deepseek_provider import DeepseekProvider


class MockStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self) -> AsyncGenerator[str, None]:
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockAsyncClient:
    def __init__(self, response: MockStreamResponse):
        self._response = response

    def stream(self, method: str, url: str, **kwargs) -> MockStreamResponse:
        return self._response


@pytest.mark.asyncio
async def test_stream_completion_normal_termination_logs_done():
    provider = DeepseekProvider()
    client = MagicMock(spec=httpx.AsyncClient)

    chunk = {
        "id": "test-123",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": "Hello"},
                "finish_reason": None,
            }
        ],
    }
    final_chunk = {
        "id": "test-123",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    lines = [
        f"data: {json.dumps(chunk)}",
        f"data: {json.dumps(final_chunk)}",
        "data: [DONE]",
    ]
    response = MockStreamResponse(lines)
    client.stream = MagicMock(return_value=response)

    file_logger = AsyncMock()
    stream = provider._stream_completion(
        client=client,
        url="https://api.deepseek.com/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        payload={"model": "deepseek-chat", "messages": [{"role": "user", "content": "Hi"}], "stream": True},
        model="deepseek/deepseek-chat",
        file_logger=file_logger,
    )

    chunks = []
    async for chunk in stream:
        chunks.append(chunk)

    assert len(chunks) == 2
    assert chunks[0].choices[0].delta.content == "Hello"
    assert chunks[1].choices[0].finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_completion_incomplete_stream_raises_error():
    provider = DeepseekProvider()
    client = MagicMock(spec=httpx.AsyncClient)

    chunk = {
        "id": "test-123",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "reasoning_content": "Thinking..."},
                "finish_reason": None,
            }
        ],
    }

    lines = [
        f"data: {json.dumps(chunk)}",
    ]
    response = MockStreamResponse(lines)
    client.stream = MagicMock(return_value=response)

    file_logger = AsyncMock()
    stream = provider._stream_completion(
        client=client,
        url="https://api.deepseek.com/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        payload={"model": "deepseek-chat", "messages": [{"role": "user", "content": "Hi"}], "stream": True},
        model="deepseek/deepseek-chat",
        file_logger=file_logger,
    )

    chunks = []
    with pytest.raises(RuntimeError, match="incomplete|truncated|premature"):
        async for chunk in stream:
            chunks.append(chunk)


@pytest.mark.asyncio
async def test_stream_completion_with_finish_reason_no_done_is_ok():
    provider = DeepseekProvider()
    client = MagicMock(spec=httpx.AsyncClient)

    chunk = {
        "id": "test-123",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": "Hello"},
                "finish_reason": None,
            }
        ],
    }
    final_chunk = {
        "id": "test-123",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }

    lines = [
        f"data: {json.dumps(chunk)}",
        f"data: {json.dumps(final_chunk)}",
    ]
    response = MockStreamResponse(lines)
    client.stream = MagicMock(return_value=response)

    file_logger = AsyncMock()
    stream = provider._stream_completion(
        client=client,
        url="https://api.deepseek.com/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        payload={"model": "deepseek-chat", "messages": [{"role": "user", "content": "Hi"}], "stream": True},
        model="deepseek/deepseek-chat",
        file_logger=file_logger,
    )

    chunks = []
    async for chunk in stream:
        chunks.append(chunk)

    assert len(chunks) == 2
    assert chunks[1].choices[0].finish_reason == "stop"
