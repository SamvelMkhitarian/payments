import uuid
from pathlib import Path
import sys

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.db import Base
from app.models import Outbox, PaymentStatus
from app.schemas.payment import CreatePaymentRequest
from app.services.payment_service import create_payment, get_payment

TEST_SCHEMA = "test_payment_service"


@pytest_asyncio.fixture
async def session_factory():
    admin_engine = create_async_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE'))
        await connection.execute(text(f'CREATE SCHEMA "{TEST_SCHEMA}"'))
    await admin_engine.dispose()

    engine = create_async_engine(
        settings.database_url,
        connect_args={"server_settings": {"search_path": TEST_SCHEMA}},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        cleanup_engine = create_async_engine(settings.database_url, isolation_level="AUTOCOMMIT")
        async with cleanup_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE'))
        await cleanup_engine.dispose()


@pytest.mark.asyncio
async def test_create_payment_is_idempotent_and_creates_outbox_record(session_factory):
    request = CreatePaymentRequest(
        amount="100.50",
        currency="RUB",
        description="test payment",
        metadata={"order_id": "order-1"},
        webhook_url="https://example.com/hook",
    )

    async with session_factory() as session:
        first_payment = await create_payment(session, "idem-1", request)
        first_payment_id = first_payment.id

    async with session_factory() as session:
        repeated_payment = await create_payment(session, "idem-1", request)

        assert repeated_payment.id == first_payment_id
        assert repeated_payment.status == PaymentStatus.PENDING

        outbox_count = await session.scalar(select(func.count()).select_from(Outbox))
        assert outbox_count == 1

        outbox_record = await session.scalar(select(Outbox))
        assert outbox_record is not None
        assert outbox_record.event_type == "payment.created"
        assert outbox_record.payload["payment_id"] == str(first_payment_id)


@pytest.mark.asyncio
async def test_get_payment_returns_payment_or_raises_404(session_factory):
    request = CreatePaymentRequest(
        amount="10.00",
        currency="USD",
        description="lookup payment",
        webhook_url="https://example.com/hook",
    )

    async with session_factory() as session:
        payment = await create_payment(session, "lookup-1", request)
        found_payment = await get_payment(session, payment.id)

        assert found_payment.id == payment.id

        with pytest.raises(HTTPException) as exc_info:
            await get_payment(session, uuid.uuid4())

        assert exc_info.value.status_code == 404
