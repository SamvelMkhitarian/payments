from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app.consumer.webhook_processor import deliver_webhook
from app.models import Currency, Payment, PaymentStatus
from app.services.webhook_service import (
    NonRetriableWebhookError,
    WebhookDeliveryError,
    _should_retry_response,
    send_webhook_once,
)


async def _create_payment(session_factory, *, webhook_delivered_at=None):
    payment = Payment(
        id=uuid4(),
        amount=Decimal("100.00"),
        currency=Currency.RUB,
        description="webhook test",
        metadata_={},
        status=PaymentStatus.SUCCEEDED,
        idempotency_key=f"webhook-{uuid4()}",
        webhook_url="https://example.com/hook",
        created_at=datetime.now(UTC),
        processed_at=datetime.now(UTC),
        webhook_delivered_at=webhook_delivered_at,
    )
    async with session_factory() as session:
        async with session.begin():
            session.add(payment)
    return payment


@pytest.mark.asyncio
async def test_deliver_webhook_marks_payment_as_delivered(patched_session_factory):
    payment = await _create_payment(patched_session_factory)
    payload = {
        "payment_id": str(payment.id),
        "webhook_url": payment.webhook_url,
        "status": "succeeded",
        "amount": "100.00",
        "currency": "RUB",
        "processed_at": payment.processed_at.isoformat(),
    }

    with patch(
        "app.consumer.webhook_processor.send_webhook_once",
        new=AsyncMock(),
    ):
        await deliver_webhook(payload)

    async with patched_session_factory() as session:
        updated = await session.get(Payment, payment.id)
        assert updated is not None
        assert updated.webhook_delivered_at is not None


@pytest.mark.asyncio
async def test_deliver_webhook_skips_already_delivered_payment(patched_session_factory):
    payment = await _create_payment(
        patched_session_factory,
        webhook_delivered_at=datetime.now(UTC),
    )
    send = AsyncMock()

    with patch("app.consumer.webhook_processor.send_webhook_once", send):
        await deliver_webhook(
            {
                "payment_id": str(payment.id),
                "webhook_url": payment.webhook_url,
                "status": "succeeded",
                "amount": "100.00",
                "currency": "RUB",
                "processed_at": payment.processed_at.isoformat(),
            }
        )

    send.assert_not_awaited()


def test_should_retry_response_for_server_errors_and_429():
    assert _should_retry_response(httpx.Response(500, request=MagicMock())) is True
    assert _should_retry_response(httpx.Response(429, request=MagicMock())) is True
    assert _should_retry_response(httpx.Response(400, request=MagicMock())) is False


@pytest.mark.asyncio
async def test_send_webhook_once_succeeds_without_retry():
    response = AsyncMock(is_success=True, status_code=200)
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhook_service.httpx.AsyncClient", return_value=client):
        await send_webhook_once("https://example.com/hook", {"payment_id": "1"})

    client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_webhook_once_raises_on_500():
    response = AsyncMock(is_success=False, status_code=500)
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.webhook_service.httpx.AsyncClient", return_value=client),
        pytest.raises(WebhookDeliveryError),
    ):
        await send_webhook_once("https://example.com/hook", {"payment_id": "1"})


@pytest.mark.asyncio
async def test_send_webhook_once_raises_non_retriable_on_400():
    response = AsyncMock(is_success=False, status_code=400)
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.webhook_service.httpx.AsyncClient", return_value=client),
        pytest.raises(NonRetriableWebhookError),
    ):
        await send_webhook_once("https://example.com/hook", {"payment_id": "1"})
