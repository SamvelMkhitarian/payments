import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

MAX_WEBHOOK_ATTEMPTS = 3
WEBHOOK_RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0)


async def send_webhook(url: str, payload: Mapping[str, Any]) -> bool:
    async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
        for attempt in range(1, MAX_WEBHOOK_ATTEMPTS + 1):
            try:
                response = await client.post(url, json=payload)
            except (httpx.TimeoutException, httpx.TransportError):
                logger.exception(
                    "Webhook attempt %s/%s failed with transport error",
                    attempt,
                    MAX_WEBHOOK_ATTEMPTS,
                )
            else:
                if response.is_success:
                    logger.info("Webhook sent successfully to %s", url)
                    return True

                if not _should_retry_response(response):
                    logger.warning(
                        "Webhook rejected with non-retriable status %s",
                        response.status_code,
                    )
                    return False

                logger.warning(
                    "Webhook attempt %s/%s failed with status %s",
                    attempt,
                    MAX_WEBHOOK_ATTEMPTS,
                    response.status_code,
                )

            if attempt < MAX_WEBHOOK_ATTEMPTS:
                await asyncio.sleep(WEBHOOK_RETRY_DELAYS_SECONDS[attempt - 1])

    logger.error("Webhook delivery failed after %s attempts", MAX_WEBHOOK_ATTEMPTS)
    return False


def _should_retry_response(response: httpx.Response) -> bool:
    return response.status_code == 429 or response.status_code >= 500
