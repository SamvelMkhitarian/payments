import asyncio
import logging

from app.outbox.relay import install_signal_handlers, run_relay


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)
    await run_relay(stop_event)


if __name__ == "__main__":
    asyncio.run(main())
