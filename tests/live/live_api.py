"""Retrying, failure-classifying client wrapper for the live smoke tests.

pyRail reports unavailable endpoints by raising a ``PyRailError`` (HTTP 400, 404 and
429, or ``ApiUnavailableError`` for network errors, timeouts and HTTP 5xx) or by logging
an error and returning None (unparseable bodies, unexpected statuses), while a
successful response that no longer matches the models raises during deserialization. ``LiveApi`` uses that difference to fail with one
of two clearly distinct messages.
"""

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import override

from aiohttp import ClientTimeout
import pytest

from pyrail.exceptions import InvalidRequestError, NotFoundError, PyRailError
from pyrail.irail import iRail

# Bounded retry policy: 3 attempts with a growing pause. The client is created with
# max_retries=0 (see conftest.py), so this is the only retry layer; the client still
# applies its own rate limiting.
ATTEMPTS = 3
BACKOFF_SECONDS = (5, 15)
REQUEST_TIMEOUT = ClientTimeout(total=30)

UNAVAILABLE = "API UNAVAILABLE"
REJECTED = "API REJECTED REQUEST"
INCOMPATIBLE = "API INCOMPATIBLE"


class _ErrorLogCollector(logging.Handler):
    """Collect the error messages pyRail logs while a request fails."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    @override
    def emit(self, record: logging.LogRecord) -> None:
        # iRail error bodies can include a long server stack trace, keep the head only
        self.messages.append(record.getMessage()[:300])


class LiveApi:
    """An iRail client that retries transient failures and classifies the outcome."""

    def __init__(self, client: iRail) -> None:
        """Wrap the given client."""
        self.client = client

    async def fetch[T](self, endpoint: str, request: Callable[[iRail], Awaitable[T | None]]) -> T:
        """Call an endpoint, retrying when no usable response arrives.

        Fails with ``API UNAVAILABLE`` when every attempt gets no response, with
        ``API REJECTED REQUEST`` when the API answers HTTP 400 or 404, and with
        ``API INCOMPATIBLE`` when a response arrives but cannot be deserialized.
        Rejections and deserialization failures are not retried, as they are deterministic.
        """
        logger = logging.getLogger("pyrail.irail")
        reason = "no response"
        for attempt in range(1, ATTEMPTS + 1):
            self.client.clear_etag_cache()  # a 304 would come back as None
            collector = _ErrorLogCollector()
            logger.addHandler(collector)
            try:
                result = await request(self.client)
            except (InvalidRequestError, NotFoundError) as err:
                pytest.fail(f"{REJECTED}: '{endpoint}' answered {type(err).__name__}: {str(err)[:300]}", pytrace=False)
            except PyRailError as err:
                reason = f"{type(err).__name__}: {str(err)[:300]}"
            except Exception as err:
                pytest.fail(
                    f"{INCOMPATIBLE}: '{endpoint}' answered successfully but the response failed to "
                    f"deserialize: {type(err).__name__}: {err}",
                    pytrace=False,
                )
            else:
                if result is not None:
                    return result
                reason = "; ".join(collector.messages) or "no response"
            finally:
                logger.removeHandler(collector)
            if attempt < ATTEMPTS:
                await asyncio.sleep(BACKOFF_SECONDS[attempt - 1])
        pytest.fail(
            f"{UNAVAILABLE}: '{endpoint}' gave no usable response after {ATTEMPTS} attempts: {reason}", pytrace=False
        )
