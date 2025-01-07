"""Unit tests for the iRail API wrapper."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession
import pytest

from pyrail.irail import iRail
from pyrail.models import (
    CompositionApiResponse,
    ConnectionDetails,
    ConnectionsApiResponse,
    DisturbancesApiResponse,
    LiveboardApiResponse,
    LiveboardDeparture,
    Occupancy,
    PlatformInfo,
    StationDetails,
    StationsApiResponse,
    VehicleApiResponse,
    VehicleInfo,
)


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
        response = await api._do_request("stations")
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

        # Validate that the response is a StationsApiResponse object
        assert isinstance(stations, StationsApiResponse), "Expected the response to be a StationsApiResponse object"

        # Validate the structure of station data
        station_list = stations.stations
        assert isinstance(station_list, list), "Expected 'station' to be a list"
        assert len(station_list) > 0, "Expected at least one station in the response"
        assert isinstance(station_list[0], StationDetails), "Expected the first station to be a StationDetails object"


@pytest.mark.asyncio
async def test_get_liveboard():
    """Test the get_liveboard endpoint.

    Verifies that:
    - The response is not None
    - The response is a LiveboardApiResponse object
    - The response contains a 'departures' key
    - The departure list is non-empty
    """
    async with iRail() as api:
        liveboard = await api.get_liveboard("Brussels-Central")

        # Ensure the response is not None
        assert liveboard is not None, "The response should not be None"

        # Validate that the response is a LiveboardApiResponse object
        assert isinstance(liveboard, LiveboardApiResponse), "Expected response to be a dictionary"

        # Validate the structure of departure data
        departure_list = liveboard.departures.departure
        assert isinstance(departure_list, list), "Expected 'departure' to be a list"
        assert len(departure_list) > 0, "Expected at least one departure in the response"
        assert isinstance(
            departure_list[0], LiveboardDeparture
        ), "Expected the first departure to be a LiveboardDeparture object"
        # Test VehicleInfo dataclass
        assert isinstance(
            departure_list[0].vehicle_info, VehicleInfo
        ), "Expected vehicle_info to be a VehicleInfo object"


@pytest.mark.asyncio
async def test_get_connections():
    """Test the get_connections endpoint.

    Verifies that:
    - The response is not None
    - The response is a ConnectionsApiResponse object
    - The response contains a 'connections' key
    - The connection list is non-empty
    """
    async with iRail() as api:
        connections = await api.get_connections("Antwerpen-Centraal", "Brussel-Centraal")

        # Ensure the response is not None
        assert connections is not None, "The response should not be None"

        # Validate that the response is a ConnectionsApiResponse object
        assert isinstance(connections, ConnectionsApiResponse), "Expected response to be a dictionary"

        # Validate the structure of connection data
        connection_list = connections.connections
        assert isinstance(connection_list, list), "Expected 'connection' to be a list"
        assert len(connection_list) > 0, "Expected at least one connection in the response"
        assert isinstance(
            connection_list[0], ConnectionDetails
        ), "Expected the first connection to be a ConnectionDetails object"


@pytest.mark.asyncio
async def test_get_vehicle():
    """Test the get_vehicle endpoint.

    Verifies that:
    - The response is not None
    - The response is a dictionary
    - The response contains a 'vehicle' key
    - The vehicle list is non-empty
    """
    async with iRail() as api:
        vehicle = await api.get_vehicle("IC538")

        assert vehicle is not None, "The response should not be None"
        assert isinstance(vehicle, VehicleApiResponse), "Expected response to be a VehicleApiResponse object"
        assert isinstance(vehicle.vehicle_info, VehicleInfo), "Expected vehicle_info to be a VehicleInfo object"
        assert isinstance(vehicle.stops.stop, list), "Expected 'stop' to be a list"
        assert vehicle.stops.number >= 0, "Expected 'number' to be a non-negative integer"
        stop = vehicle.stops.stop[0]
        assert isinstance(stop.platform_info, PlatformInfo), "Expected platform_info to be a PlatformInfo object"
        assert isinstance(stop.occupancy, Occupancy), "Expected occupancy to be an Occupancy object"


@pytest.mark.asyncio
async def test_get_composition():
    """Test the get_composition endpoint.

    Verifies that:
    - The response is not None
    - The response is a CompositionApiResponse object
    - The response contains a 'composition' key
    - The composition segments list is non-empty
    - The segment has valid attributes
    - The composition units list is non-empty
    - The unit has valid attributes
    """
    async with iRail() as api:
        composition = await api.get_composition("IC538")

        assert composition is not None, "The response should not be None"
        assert isinstance(
            composition, CompositionApiResponse
        ), "Expected response to be a CompositionApiResponse object"

        # Test segments structure
        segments = composition.composition.segments
        assert isinstance(segments.segment, list), "Expected 'segment' to be a list"
        assert segments.number >= 0, "Expected 'number' to be a non-negative integer"

        if segments.number > 0:
            segment = segments.segment[0]
            assert isinstance(segment.origin, StationDetails), "Expected origin to be a StationDetails object"
            assert isinstance(segment.destination, StationDetails), "Expected destination to be a StationDetails object"

            # Test units in composition
            units = segment.composition.units
            assert units.number >= 0, "Expected 'number' to be a non-negative integer"

            if units.number > 0:
                unit = units.unit[0]
                assert isinstance(unit.has_toilets, bool), "Expected 'has_toilets' to be a boolean"
                assert isinstance(unit.seats_first_class, int), "Expected 'seats_first_class' to be an integer"
                assert isinstance(unit.length_in_meter, int), "Expected 'length_in_meter' to be an integer"


@pytest.mark.asyncio
async def test_get_disturbances():
    """Test the get_disturbances endpoint.

    Verifies that:
    - The response is not None
    - The response is a DisturbancesApiResponse object
    - The response contains a 'disturbances' key
    - The disturbances list is non-empty
    - The disturbance has valid attributes
    """
    async with iRail() as api:
        disturbances = await api.get_disturbances()

        assert disturbances is not None, "The response should not be None"
        assert isinstance(
            disturbances, DisturbancesApiResponse
        ), "Expected response to be a DisturbancesApiResponse object"
        assert isinstance(disturbances.disturbances, list), "Expected 'disturbances' to be a list"

        # Test disturbance attributes
        if len(disturbances.disturbances) > 0:
            disturbance = disturbances.disturbances[0]
            assert isinstance(disturbance.title, str), "Expected 'title' to be a string"
            assert isinstance(disturbance.description, str), "Expected 'description' to be a string"
            assert disturbance.type in ["disturbance", "planned"], "Expected 'type' to be 'disturbance' or 'planned'"


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


@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling for various API endpoints with invalid data.

    Verifies that:
    - The response is None for invalid data
    """
    async with iRail() as api:
        # Test with invalid vehicle ID
        vehicle = await api.get_vehicle("INVALID_ID")
        assert vehicle is None, "Expected None for invalid vehicle ID"

        # Test with invalid station for liveboard
        liveboard = await api.get_liveboard("INVALID_STATION")
        assert liveboard is None, "Expected None for invalid station"

        # Test with invalid train ID for composition
        composition = await api.get_composition("INVALID_TRAIN")
        assert composition is None, "Expected None for invalid train ID"

        # Test with invalid station for connections
        connections = await api.get_connections("InvalidStation1", "InvalidStation2")
        assert connections is None, "Expected None for invalid stations"
