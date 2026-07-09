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

    await asyncio.sleep(random.uniform(*GATEWAY_DELAY_SECONDS))
    status = (
        PaymentStatus.SUCCEEDED
        if random.random() < GATEWAY_SUCCESS_RATE
        else PaymentStatus.FAILED
    )

    async with async_session_factory() as session:
        async with session.begin():
            payment = await _get_payment_for_update(session, payment_id)
            if payment is None:
                raise ValueError(f"Payment {payment_id} not found")

            if payment.status != PaymentStatus.PENDING:
                return payment.status

            payment.status = status
            payment.processed_at = datetime.now(UTC)
            return status


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


async def _get_payment_for_update(
    session: AsyncSession,
    payment_id: UUID,
) -> Payment | None:
    return await session.get(Payment, payment_id, with_for_update=True)
