from unittest.mock import MagicMock

from faststream.rabbit import RabbitMessage

from app.messaging.utils import delivery_count


def test_delivery_count_returns_zero_without_x_death_header():
    message = MagicMock(spec=RabbitMessage)
    message.headers = {}

    assert delivery_count(message) == 0


def test_delivery_count_sums_x_death_entries():
    message = MagicMock(spec=RabbitMessage)
    message.headers = {
        "x-death": [
            {"count": 1},
            {"count": 2},
        ]
    }

    assert delivery_count(message) == 3
