from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.consumer.processor import process_payment, publish_retry_or_dlq
from app.messaging.broker import (
    PAYMENT_FAILED_ROUTING_KEY,
    PAYMENT_RETRY_ROUTING_KEYS,
    payments_dlx_exchange,
    payments_retry_exchange,
)
from app.models import Currency, Payment, PaymentStatus


async def _create_payment(
    session_factory,
    *,
    status=PaymentStatus.PENDING,
    webhook_delivered_at=None,
):
    payment = Payment(
        id=uuid4(),
        amount=Decimal("100.00"),
        currency=Currency.RUB,
        description="consumer test",
        metadata_={},
        status=status,
        idempotency_key=f"consumer-{uuid4()}",
        webhook_url="https://example.com/hook",
        created_at=datetime.now(UTC),
        processed_at=datetime.now(UTC) if status != PaymentStatus.PENDING else None,
        webhook_delivered_at=webhook_delivered_at,
    )
    async with session_factory() as session:
        async with session.begin():
            session.add(payment)
    return payment


@pytest.mark.asyncio
async def test_process_payment_updates_pending_payment_and_delivers_webhook(
    patched_session_factory,
):
    payment = await _create_payment(patched_session_factory)

    with (
        patch("app.consumer.processor.asyncio.sleep", new=AsyncMock()),
        patch("app.consumer.processor.random.uniform", return_value=3.0),
        patch("app.consumer.processor.random.random", return_value=0.0),
        patch("app.consumer.processor.send_webhook", new=AsyncMock(return_value=True)) as send_webhook,
    ):
        result = await process_payment({"payment_id": str(payment.id)})

    assert result == PaymentStatus.SUCCEEDED
    send_webhook.assert_awaited_once()

    async with patched_session_factory() as session:
        updated = await session.get(Payment, payment.id)
        assert updated is not None
        assert updated.status == PaymentStatus.SUCCEEDED
        assert updated.processed_at is not None
        assert updated.webhook_delivered_at is not None


@pytest.mark.asyncio
async def test_process_payment_retries_webhook_for_already_processed_payment(
    patched_session_factory,
):
    payment = await _create_payment(
        patched_session_factory,
        status=PaymentStatus.SUCCEEDED,
    )

    with (
        patch("app.consumer.processor.asyncio.sleep", new=AsyncMock()) as sleep_mock,
        patch("app.consumer.processor.send_webhook", new=AsyncMock(return_value=True)) as send_webhook,
    ):
        result = await process_payment({"payment_id": str(payment.id)})

    assert result == PaymentStatus.SUCCEEDED
    sleep_mock.assert_not_awaited()
    send_webhook.assert_awaited_once()

    async with patched_session_factory() as session:
        updated = await session.get(Payment, payment.id)
        assert updated is not None
        assert updated.webhook_delivered_at is not None


@pytest.mark.asyncio
async def test_process_payment_skips_when_webhook_already_delivered(
    patched_session_factory,
):
    payment = await _create_payment(
        patched_session_factory,
        status=PaymentStatus.SUCCEEDED,
        webhook_delivered_at=datetime.now(UTC),
    )

    with patch("app.consumer.processor.send_webhook", new=AsyncMock(return_value=True)) as send_webhook:
        result = await process_payment({"payment_id": str(payment.id)})

    assert result == PaymentStatus.SUCCEEDED
    send_webhook.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_retry_or_dlq_schedules_retry_before_dlq():
    publish = AsyncMock()
    payload = {"payment_id": str(uuid4())}

    with patch("app.consumer.processor.broker.publish", publish):
        await publish_retry_or_dlq(payload, RuntimeError("boom"))

    publish.assert_awaited_once()
    kwargs = publish.await_args.kwargs
    assert kwargs["exchange"] == payments_retry_exchange
    assert kwargs["routing_key"] == PAYMENT_RETRY_ROUTING_KEYS[0]
    assert publish.await_args.args[0]["retry_attempt"] == 1


@pytest.mark.asyncio
async def test_publish_retry_or_dlq_sends_to_dlq_after_max_attempts():
    publish = AsyncMock()
    payload = {"payment_id": str(uuid4()), "retry_attempt": 3}

    with patch("app.consumer.processor.broker.publish", publish):
        await publish_retry_or_dlq(payload, RuntimeError("boom"))

    publish.assert_awaited_once()
    kwargs = publish.await_args.kwargs
    assert kwargs["exchange"] == payments_dlx_exchange
    assert kwargs["routing_key"] == PAYMENT_FAILED_ROUTING_KEY
