from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.payment import CreatePaymentRequest, CreatePaymentResponse
from app.services import payment_service

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "",
    response_model=CreatePaymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_payment(
    data: CreatePaymentRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CreatePaymentResponse:
    payment = await payment_service.create_payment(session, idempotency_key, data)
    return CreatePaymentResponse.model_validate(payment, from_attributes=True)
