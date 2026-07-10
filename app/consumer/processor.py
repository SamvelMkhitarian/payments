import asyncio
import logging
import random
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory
from app.messaging.broker import (
    PAYMENT_FAILED_ROUTING_KEY,
    PAYMENT_RETRY_ROUTING_KEYS,
    broker,
    payments_dlx_exchange,
    payments_retry_exchange,
)
from app.models import Payment, PaymentStatus
from app.services.webhook_service import send_webhook

logger = logging.getLogger(__name__)

GATEWAY_DELAY_SECONDS = (2.0, 5.0)
GATEWAY_SUCCESS_RATE = 0.9
MAX_RETRY_ATTEMPTS = 3
RETRY_ATTEMPT_FIELD = "retry_attempt"


async def handle_payment_created(payload: dict[str, Any]) -> None:
    try:
        await process_payment(payload)
    except Exception as exc:
        await publish_retry_or_dlq(payload, exc)


async def process_payment(payload: Mapping[str, Any]) -> PaymentStatus:
    payment_id = UUID(str(payload["payment_id"]))

    async with async_session_factory() as session:
        async with session.begin():
            payment = await _get_payment_for_update(session, payment_id)
            if payment is None:
                raise ValueError(f"Payment {payment_id} not found")
            if payment.webhook_delivered_at is not None:
                return payment.status
            requires_gateway = payment.status == PaymentStatus.PENDING

    if requires_gateway:
        await asyncio.sleep(random.uniform(*GATEWAY_DELAY_SECONDS))
        gateway_status = (
            PaymentStatus.SUCCEEDED
            if random.random() < GATEWAY_SUCCESS_RATE
            else PaymentStatus.FAILED
        )
        async with async_session_factory() as session:
            async with session.begin():
                payment = await _get_payment_for_update(session, payment_id)
                if payment is None:
                    raise ValueError(f"Payment {payment_id} not found")
                if payment.webhook_delivered_at is not None:
                    return payment.status
                if payment.status == PaymentStatus.PENDING:
                    payment.status = gateway_status
                    payment.processed_at = datetime.now(UTC)

    async with async_session_factory() as session:
        async with session.begin():
            payment = await _get_payment_for_update(session, payment_id)
            if payment is None:
                raise ValueError(f"Payment {payment_id} not found")
            if payment.webhook_delivered_at is not None:
                return payment.status
            webhook_url = payment.webhook_url
            webhook_payload = _build_webhook_payload(payment)
            result_status = payment.status

    if await send_webhook(webhook_url, webhook_payload):
        await _mark_webhook_delivered(payment_id)

    return result_status


async def publish_retry_or_dlq(payload: dict[str, Any], exc: Exception) -> None:
    attempt = int(payload.get(RETRY_ATTEMPT_FIELD, 0))
    if attempt < MAX_RETRY_ATTEMPTS:
        next_attempt = attempt + 1
        retry_payload = {**payload, RETRY_ATTEMPT_FIELD: next_attempt}
        await broker.publish(
            retry_payload,
            exchange=payments_retry_exchange,
            routing_key=PAYMENT_RETRY_ROUTING_KEYS[next_attempt - 1],
            persist=True,
        )
        logger.exception(
            "Payment processing failed; scheduled retry %s/%s",
            next_attempt,
            MAX_RETRY_ATTEMPTS,
            exc_info=exc,
        )
        return

    await broker.publish(
        payload,
        exchange=payments_dlx_exchange,
        routing_key=PAYMENT_FAILED_ROUTING_KEY,
        persist=True,
    )
    logger.exception("Payment processing failed; sent to DLQ", exc_info=exc)


async def _mark_webhook_delivered(payment_id: UUID) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            payment = await _get_payment_for_update(session, payment_id)
            if payment is not None and payment.webhook_delivered_at is None:
                payment.webhook_delivered_at = datetime.now(UTC)


async def _get_payment_for_update(
    session: AsyncSession,
    payment_id: UUID,
) -> Payment | None:
    return await session.get(Payment, payment_id, with_for_update=True)


def _build_webhook_payload(payment: Payment) -> dict[str, Any]:
    return {
        "payment_id": str(payment.id),
        "status": payment.status.value,
        "amount": str(payment.amount),
        "currency": payment.currency.value,
        "processed_at": (
            payment.processed_at.isoformat()
            if payment.processed_at is not None
            else None
        ),
    }
