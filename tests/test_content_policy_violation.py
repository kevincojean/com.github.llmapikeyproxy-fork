# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Kevin Cojean

import json
import logging

import httpx
import pytest

from rotator_library import RotatingClient

UPSTREAM_MARKERS = (
    "litellm",
    "Upstream request failed",
    "data_inspection_failed",
    "InternalError.Algo",
)

DATA_INSPECTION_BODY = (
    "Upstream request failed: [data_inspection_failed] <400> "
    "InternalError.Algo.DataInspectionFailed: "
    "Input text data may contain inappropriate content."
)

VALIDATION_BODY = (
    "Upstream request failed: [400] reasoning_effort: Invalid option: "
    'expected one of "max"|"xhigh"|"high"|"medium"|"low"|"minimal"|"none"'
)


def _openai_error_response(body: str) -> httpx.Response:
    return httpx.Response(
        400,
        json={
            "error": {
                "message": body,
                "type": "invalid_request_error",
                "code": "invalid_request",
            }
        },
    )


@pytest.fixture
def client_with_upstream(tmp_path):
    created = []

    def _make(upstream: httpx.Response) -> RotatingClient:
        def handler(request: httpx.Request) -> httpx.Response:
            return upstream

        client = RotatingClient(
            api_keys={"opencode_go": ["sk-opencode-policy-test"]},
            data_dir=tmp_path,
            configure_logging=False,
        )
        transport = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        created.append((client, transport))
        return client, transport

    yield _make

    import asyncio

    async def _close_all():
        for client, transport in created:
            await transport.aclose()
            await client.close()

    asyncio.run(_close_all())


async def _capture_stream(stream) -> str:
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return "".join(chunks)


async def test_non_streaming_content_policy_violation_is_sanitized(
    client_with_upstream, tmp_path
):
    client, transport = client_with_upstream(_openai_error_response(DATA_INSPECTION_BODY))
    await client.http_client.aclose()
    client.http_client = transport
    client._executor._http_client = transport

    with pytest.raises(Exception) as exc_info:
        await client.acompletion(
            model="opencode_go/deep-fallback",
            messages=[{"role": "user", "content": "hello"}],
        )

    payload = json.dumps(getattr(exc_info.value, "error_response", None) or str(exc_info.value))
    for marker in UPSTREAM_MARKERS:
        assert marker not in payload

    error_response = getattr(exc_info.value, "error_response", None)
    if error_response is not None:
        assert error_response["error"]["code"] == "content_policy_violation"
        assert error_response["error"]["type"] == "invalid_request"


async def test_streaming_content_policy_violation_is_sanitized(client_with_upstream):
    client, transport = client_with_upstream(_openai_error_response(DATA_INSPECTION_BODY))
    await client.http_client.aclose()
    client.http_client = transport
    client._executor._http_client = transport

    stream = await client.acompletion(
        model="opencode_go/deep-fallback",
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )
    payload = await _capture_stream(stream)

    for marker in UPSTREAM_MARKERS:
        assert marker not in payload

    error_chunks = [
        json.loads(line[len("data: "):])
        for line in payload.splitlines()
        if line.startswith("data: ") and line.strip() != "data: [DONE]"
    ]
    codes = [c.get("error", {}).get("code") for c in error_chunks]
    assert "content_policy_violation" in codes


async def test_validation_error_does_not_leak_upstream_text(client_with_upstream):
    client, transport = client_with_upstream(_openai_error_response(VALIDATION_BODY))
    await client.http_client.aclose()
    client.http_client = transport
    client._executor._http_client = transport

    with pytest.raises(Exception) as exc_info:
        await client.acompletion(
            model="opencode_go/hy3",
            messages=[{"role": "user", "content": "hello"}],
        )

    payload = json.dumps(getattr(exc_info.value, "error_response", None) or str(exc_info.value))
    assert "reasoning_effort: Invalid option" not in payload
    assert "litellm" not in payload


async def test_content_policy_violation_logs_one_warning(client_with_upstream, caplog):
    client, transport = client_with_upstream(_openai_error_response(DATA_INSPECTION_BODY))
    await client.http_client.aclose()
    client.http_client = transport
    client._executor._http_client = transport

    with caplog.at_level(logging.WARNING, logger="rotator_library"):
        with pytest.raises(Exception):
            await client.acompletion(
                model="opencode_go/deep-fallback",
                messages=[{"role": "user", "content": "hello"}],
            )

    lines = [
        record
        for record in caplog.records
        if record.name == "rotator_library"
        and record.levelno == logging.WARNING
        and "content policy violation" in record.getMessage()
    ]
    assert len(lines) == 1
    assert "opencode_go" in lines[0].getMessage()


async def test_validation_error_logs_no_content_policy_warning(
    client_with_upstream, caplog
):
    client, transport = client_with_upstream(_openai_error_response(VALIDATION_BODY))
    await client.http_client.aclose()
    client.http_client = transport
    client._executor._http_client = transport

    with caplog.at_level(logging.WARNING, logger="rotator_library"):
        with pytest.raises(Exception):
            await client.acompletion(
                model="opencode_go/hy3",
                messages=[{"role": "user", "content": "hello"}],
            )

    assert not [
        record
        for record in caplog.records
        if "content policy violation" in record.getMessage()
    ]


async def test_configured_fallback_does_not_replace_content_policy_error(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "MODEL_FALLBACK_POLICY_FALLBACK", "nanogpt:some-model"
    )
    attempted = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempted.append(str(request.url))
        return _openai_error_response(DATA_INSPECTION_BODY)

    client = RotatingClient(
        api_keys={
            "opencode_go": ["sk-opencode-policy-test"],
            "nanogpt": ["sk-nanogpt-policy-test"],
        },
        data_dir=tmp_path,
        configure_logging=False,
    )
    transport = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await client.http_client.aclose()
        client.http_client = transport
        client._executor._http_client = transport

        with pytest.raises(Exception) as exc_info:
            await client.acompletion(
                model="opencode_go/policy-fallback",
                messages=[{"role": "user", "content": "hello"}],
            )

        error_response = getattr(exc_info.value, "error_response", None)
        assert error_response is not None
        assert error_response["error"]["code"] == "content_policy_violation"
        assert getattr(exc_info.value, "http_status", None) == 400
        assert len(attempted) == 1
    finally:
        await transport.aclose()
        await client.close()
