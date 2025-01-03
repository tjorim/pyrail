from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession
import pytest

from pyrail.irail import iRail

"""
Unit tests for the iRail API wrapper.
"""

@pytest.mark.asyncio
@patch('pyrail.irail.ClientSession.get')
async def test_successful_request(mock_get):
    """Test a successful API request by mocking the iRail response."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={'data': 'some_data'})
    mock_get.return_value.__aenter__.return_value = mock_response

    async with iRail() as api:
        response = await api.do_request('stations')
        mock_get.assert_called_once_with('https://api.irail.be/stations/', params={'format': 'json', 'lang': 'en'}, headers={"User-Agent": "pyRail (https://github.com/tjorim/pyrail; tielemans.jorim@gmail.com)"})
        assert response == {'data': 'some_data'}

@pytest.mark.asyncio
async def test_irail_context_manager():
    """Ensure that the async context manager sets up and tears down the session properly."""
    async with iRail() as irail:
        assert irail.session is not None
        assert isinstance(irail.session, ClientSession)

@pytest.mark.asyncio
async def test_get_stations():
    async with iRail() as api:
        stations = await api.get_stations()

        # Ensure the response is not None
        assert stations is not None, "The response should not be None"

        # Validate that the response is a dictionary
        assert isinstance(stations, dict), "Expected response to be a dictionary"

        # Validate the presence of key fields
        assert 'station' in stations, "Expected the response to contain a 'station' key"

        # Validate the structure of station data
        station_list = stations.get('station', [])
        assert isinstance(station_list, list), "Expected 'station' to be a list"
        assert len(station_list) > 0, "Expected at least one station in the response"

@pytest.mark.asyncio
async def test_get_connections():
    async with iRail() as api:
        connections = await api.get_connections('Antwerpen-Centraal', 'Brussel-Centraal')

        # Ensure the response is not None
        assert connections is not None, "The response should not be None"

        # Validate that the response is a dictionary
        assert isinstance(connections, dict), "Expected response to be a dictionary"

        # Validate the presence of key fields
        assert 'connection' in connections, "Expected the response to contain a 'connection' key"

        # Validate the structure of connection data
        connection_list = connections.get('connection', [])
        assert isinstance(connection_list, list), "Expected 'connection' to be a list"
        assert len(connection_list) > 0, "Expected at least one connection in the response"
