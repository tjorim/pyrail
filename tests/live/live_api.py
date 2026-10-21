"""Retrying, failure-classifying client wrapper for the live smoke tests.

pyRail reports failures by raising: ``InvalidRequestError``, ``NotFoundError`` and
``RateLimitError`` for HTTP 400, 404 and 429, ``ApiUnavailableError`` for network errors,
timeouts and HTTP 5xx, and ``InvalidResponseError`` for unusable bodies and for responses
that no longer match the models. ``LiveApi`` uses those types to fail with one of three
clearly distinct messages.
"""

import asyncio
from collections.abc import Awaitable, Callable

from aiohttp import ClientTimeout
import pytest

from pyrail.exceptions import InvalidRequestError, InvalidResponseError, NotFoundError, PyRailError
from pyrail.irail import IRail

# The fixture disables client retries, so this is the only retry layer; client
# rate limiting still applies to every attempt.
ATTEMPTS = 3
BACKOFF_SECONDS = (5, 15)
REQUEST_TIMEOUT = ClientTimeout(total=30)

UNAVAILABLE = "API UNAVAILABLE"
REJECTED = "API REJECTED REQUEST"
INCOMPATIBLE = "API INCOMPATIBLE"


class LiveApi:
    """An IRail client that retries transient failures and classifies the outcome."""

    def __init__(self, client: IRail) -> None:
        """Wrap the given client."""
        self.client = client

    async def fetch[T](self, endpoint: str, request: Callable[[IRail], Awaitable[T | None]]) -> T:
        """Call an endpoint, retrying when no usable response arrives.

        Fails with ``API UNAVAILABLE`` when every attempt fails with a transient ``PyRailError``,
        with ``API REJECTED REQUEST`` when the API answers HTTP 400 or 404, and with
        ``API INCOMPATIBLE`` when the response is unusable or cannot be deserialized.
        Rejections and unusable responses are not retried, as they are deterministic.
        The ETag cache is cleared before every attempt so a 304 answer cannot come back as None.
        Anything else that goes wrong fails the test as an ordinary error, since it is a bug
        in the test or the client rather than an API change.
        """
        reason = "no response"
        for attempt in range(1, ATTEMPTS + 1):
            self.client.clear_etag_cache()
            try:
                result = await request(self.client)
            except (InvalidRequestError, NotFoundError) as err:
                pytest.fail(f"{REJECTED}: '{endpoint}' answered {type(err).__name__}: {str(err)[:300]}", pytrace=False)
            except InvalidResponseError as err:
                pytest.fail(
                    f"{INCOMPATIBLE}: '{endpoint}' answered but the response cannot be used: {str(err)[:300]}",
                    pytrace=False,
                )
            except PyRailError as err:
                reason = f"{type(err).__name__}: {str(err)[:300]}"
            else:
                if result is not None:
                    return result
                reason = "no usable response"
            if attempt < ATTEMPTS:
                await asyncio.sleep(BACKOFF_SECONDS[attempt - 1])
        pytest.fail(
            f"{UNAVAILABLE}: '{endpoint}' gave no usable response after {ATTEMPTS} attempts: {reason}", pytrace=False
        )
