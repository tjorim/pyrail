"""Unit tests for the LiveApi helper that wraps the client in the live smoke tests.

They live outside tests/live so they run with the offline suite and never touch the network.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyrail.exceptions import ApiUnavailableError, InvalidRequestError, InvalidResponseError, NotFoundError
from tests.live.live_api import ATTEMPTS, INCOMPATIBLE, REJECTED, UNAVAILABLE, LiveApi


@pytest.mark.parametrize("error", [NotFoundError("no such station"), InvalidRequestError("bad parameter")])
@patch("tests.live.live_api.asyncio.sleep", new_callable=AsyncMock)
async def test_rejected_request_fails_fast(mock_sleep, error):
    """Test that a 400 or 404 fails immediately as rejected instead of retrying as unavailable."""
    request = AsyncMock(side_effect=error)
    with pytest.raises(pytest.fail.Exception) as exc_info:
        await LiveApi(MagicMock()).fetch("liveboard", request)
    assert REJECTED in str(exc_info.value)
    assert str(error) in str(exc_info.value)
    assert request.call_count == 1
    mock_sleep.assert_not_called()


@patch("tests.live.live_api.asyncio.sleep", new_callable=AsyncMock)
async def test_unavailable_api_is_retried_then_fails(mock_sleep):
    """Test that an ApiUnavailableError is retried with a pause and then reported as unavailable."""
    request = AsyncMock(side_effect=ApiUnavailableError("down"))
    with pytest.raises(pytest.fail.Exception) as exc_info:
        await LiveApi(MagicMock()).fetch("stations", request)
    assert UNAVAILABLE in str(exc_info.value)
    assert request.call_count == ATTEMPTS
    assert mock_sleep.call_count == ATTEMPTS - 1


@pytest.mark.parametrize(
    "error",
    [
        InvalidResponseError("Response body from stations is empty", status=200),
        InvalidResponseError("Response from stations does not match the expected model: MissingField: version"),
    ],
)
async def test_unusable_response_fails_as_incompatible(error):
    """Test that an unusable response is reported as incompatible without retrying."""
    request = AsyncMock(side_effect=error)
    with pytest.raises(pytest.fail.Exception) as exc_info:
        await LiveApi(MagicMock()).fetch("stations", request)
    assert INCOMPATIBLE in str(exc_info.value)
    assert request.call_count == 1


async def test_successful_result_is_returned():
    """Test that a usable response is returned as is."""
    assert await LiveApi(MagicMock()).fetch("stations", AsyncMock(return_value="ok")) == "ok"


async def test_non_pyrail_error_propagates():
    """Test that an error that is not a PyRailError fails the test as an ordinary error."""
    request = AsyncMock(side_effect=KeyError("missing"))
    with pytest.raises(KeyError, match="missing"):
        await LiveApi(MagicMock()).fetch("stations", request)
