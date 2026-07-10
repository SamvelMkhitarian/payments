from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Outbox, Payment, PaymentStatus
from app.schemas.payment import CreatePaymentRequest


async def create_payment(
    session: AsyncSession,
    idempotency_key: str,
    data: CreatePaymentRequest,
) -> Payment:
    try:
        async with session.begin():
            existing_payment = await _get_payment_by_idempotency_key(session, idempotency_key)
            if existing_payment is not None:
                return existing_payment

            payment = Payment(
                amount=data.amount,
                currency=data.currency,
                description=data.description,
                metadata_=data.metadata,
                status=PaymentStatus.PENDING,
                idempotency_key=idempotency_key,
                webhook_url=str(data.webhook_url),
            )
            session.add(payment)
            await session.flush()

            session.add(
                Outbox(
                    event_type="payment.created",
                    payload={
                        "payment_id": str(payment.id),
                        "amount": str(payment.amount),
                        "currency": payment.currency.value,
                        "description": payment.description,
                        "metadata": payment.metadata_,
                        "webhook_url": payment.webhook_url,
                    },
                )
            )

            return payment
    except IntegrityError:
        await session.rollback()
        existing_payment = await _get_payment_by_idempotency_key(session, idempotency_key)
        if existing_payment is None:
            raise
        return existing_payment


async def get_payment(session: AsyncSession, payment_id: UUID) -> Payment:
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    return payment


async def _get_payment_by_idempotency_key(
    session: AsyncSession,
    idempotency_key: str,
) -> Payment | None:
    result = await session.execute(
        select(Payment).where(Payment.idempotency_key == idempotency_key)
    )
    return result.scalar_one_or_none()
