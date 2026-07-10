from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.webhook_service import (
    MAX_WEBHOOK_ATTEMPTS,
    WEBHOOK_RETRY_DELAYS_SECONDS,
    _should_retry_response,
    send_webhook,
)


def test_should_retry_response_for_server_errors_and_429():
    assert _should_retry_response(httpx.Response(500, request=MagicMock())) is True
    assert _should_retry_response(httpx.Response(429, request=MagicMock())) is True
    assert _should_retry_response(httpx.Response(400, request=MagicMock())) is False


@pytest.mark.asyncio
async def test_send_webhook_returns_true_on_success():
    response = MagicMock(is_success=True, status_code=200)
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhook_service.httpx.AsyncClient", return_value=client):
        delivered = await send_webhook("https://example.com/hook", {"payment_id": "1"})

    assert delivered is True
    client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_webhook_retries_on_500_and_succeeds():
    failed_response = MagicMock(is_success=False, status_code=500)
    success_response = MagicMock(is_success=True, status_code=200)
    client = AsyncMock()
    client.post = AsyncMock(side_effect=[failed_response, success_response])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.webhook_service.httpx.AsyncClient", return_value=client),
        patch("app.services.webhook_service.asyncio.sleep", new=AsyncMock()) as sleep_mock,
    ):
        delivered = await send_webhook("https://example.com/hook", {"payment_id": "1"})

    assert delivered is True
    assert client.post.await_count == 2
    sleep_mock.assert_awaited_once_with(WEBHOOK_RETRY_DELAYS_SECONDS[0])


@pytest.mark.asyncio
async def test_send_webhook_stops_on_non_retriable_400():
    response = MagicMock(is_success=False, status_code=400)
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhook_service.httpx.AsyncClient", return_value=client):
        delivered = await send_webhook("https://example.com/hook", {"payment_id": "1"})

    assert delivered is False
    client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_webhook_returns_false_after_max_attempts():
    response = MagicMock(is_success=False, status_code=503)
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.webhook_service.httpx.AsyncClient", return_value=client),
        patch("app.services.webhook_service.asyncio.sleep", new=AsyncMock()),
    ):
        delivered = await send_webhook("https://example.com/hook", {"payment_id": "1"})

    assert delivered is False
    assert client.post.await_count == MAX_WEBHOOK_ATTEMPTS
