"""Unit tests for the iRail API wrapper."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession
import pytest

from pyrail.irail import iRail


@pytest.mark.asyncio
@patch("pyrail.irail.ClientSession.get")
async def test_successful_request(mock_get):
    """Test a successful API request by mocking the iRail response."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"data": "some_data"})
    mock_get.return_value.__aenter__.return_value = mock_response

    async with iRail() as api:
        assert api.session is not None
        response = await api.do_request("stations")
        mock_get.assert_called_once_with(
            "https://api.irail.be/stations/",
            params={"format": "json", "lang": "en"},
            headers={"User-Agent": "pyRail (https://github.com/tjorim/pyrail; tielemans.jorim@gmail.com)"},
        )
        assert response == {"data": "some_data"}
        assert mock_response.status == 200


@pytest.mark.asyncio
async def test_irail_context_manager():
    """Ensure that the async context manager sets up and tears down the session properly."""
    async with iRail() as irail:
        assert irail.session is not None
        assert isinstance(irail.session, ClientSession)


@pytest.mark.asyncio
async def test_get_stations():
    """Test the get_stations endpoint.

    Verifies that:
    - The response is not None
    - The response is a dictionary
    - The response contains a 'station' key
    - The station list is non-empty
    """
    async with iRail() as api:
        stations = await api.get_stations()

        # Ensure the response is not None
        assert stations is not None, "The response should not be None"

        # Validate that the response is a dictionary
        assert isinstance(stations, dict), "Expected response to be a dictionary"

        # Validate the presence of key fields
        assert "station" in stations, "Expected the response to contain a 'station' key"

        # Validate the structure of station data
        station_list = stations.get("station", [])
        assert isinstance(station_list, list), "Expected 'station' to be a list"
        assert len(station_list) > 0, "Expected at least one station in the response"


@pytest.mark.asyncio
async def test_get_connections():
    """Test the get_connections endpoint.

    Verifies that:
    - The response is not None
    - The response is a dictionary
    - The response contains a 'connection' key
    - The connection list is non-empty
    """
    async with iRail() as api:
        connections = await api.get_connections("Antwerpen-Centraal", "Brussel-Centraal")

        # Ensure the response is not None
        assert connections is not None, "The response should not be None"

        # Validate that the response is a dictionary
        assert isinstance(connections, dict), "Expected response to be a dictionary"

        # Validate the presence of key fields
        assert "connection" in connections, "Expected the response to contain a 'connection' key"

        # Validate the structure of connection data
        connection_list = connections.get("connection", [])
        assert isinstance(connection_list, list), "Expected 'connection' to be a list"
        assert len(connection_list) > 0, "Expected at least one connection in the response"


@pytest.mark.asyncio
async def test_get_connections_invalid_stations():
    """Test get_connections with invalid station names."""
    async with iRail() as api:
        result = await api.get_connections("InvalidStation1", "InvalidStation2")
        assert result is None, "Expected None for invalid stations"


@pytest.mark.asyncio
async def test_date_time_validation():
    """Test date and time format validation."""
    async with iRail() as api:
        # Valid date examples
        assert api._validate_date("150923")  # September 15, 2023
        assert api._validate_date("010124")  # January 1, 2024
        assert api._validate_date(None)  # None is valid (uses current date)
        assert api._validate_date("290224")  # Leap year 2024

        # Invalid date examples
        assert not api._validate_date("320923")  # Invalid day
        assert not api._validate_date("151323")  # Invalid month
        assert not api._validate_date("abcdef")  # Not numeric
        assert not api._validate_date("15092023")  # Too long
        assert not api._validate_date("")  # Empty string
        assert not api._validate_date("0")  # Too short
        assert not api._validate_date("290223")  # Invalid leap year 2023

        # Valid time examples
        assert api._validate_time("1430")  # 2:30 PM
        assert api._validate_time("0000")  # Midnight
        assert api._validate_time("2359")  # 11:59 PM
        assert api._validate_time(None)  # None is valid (uses current time)
        assert api._validate_time("0001")  # 12:01 AM

        # Invalid time examples
        assert not api._validate_time("2460")  # Invalid hour
        assert not api._validate_time("2361")  # Invalid minute
        assert not api._validate_time("abcd")  # Not numeric
        assert not api._validate_time("143000")  # Too long
        assert not api._validate_time("")  # Empty string
        assert not api._validate_time("1")  # Too short


@pytest.mark.asyncio
async def test_liveboard_with_date_time():
    """Test liveboard request with date and time parameters."""
    async with iRail() as api:
        # Valid date/time
        result = await api.get_liveboard(
            station="Brussels-Central",
            date=datetime.now().strftime("%d%m%y"),
            time="1430",  # 2:30 PM
        )
        assert result is not None

        # Test with future date
        result = await api.get_liveboard(
            station="Brussels-Central",
            date=(datetime.now() + timedelta(days=1)).strftime("%d%m%y"),
        )
        assert result is not None

        # Invalid date
        result = await api.get_liveboard(
            station="Brussels-Central",
            date="320923",  # Invalid day 32
        )
        assert result is None

        # Invalid time
        result = await api.get_liveboard(
            station="Brussels-Central",
            time="2460",  # Invalid hour 24
        )
        assert result is None
