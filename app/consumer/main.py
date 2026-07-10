from faststream import FastStream

from app.consumer.processor import handle_payment_created
from app.db import engine
from app.messaging.broker import (
    broker,
    declare_topology,
    payments_exchange,
    payments_new_queue,
)


async def shutdown() -> None:
    await engine.dispose()


@broker.subscriber(payments_new_queue, payments_exchange)
async def process_payment_created(payload: dict) -> None:
    await handle_payment_created(payload)


app = FastStream(
    broker,
    after_startup=[declare_topology],
    on_shutdown=[shutdown],
)


async def run() -> None:
    await app.run()
