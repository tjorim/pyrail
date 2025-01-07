"""Unit tests for the iRail API wrapper."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession
import pytest

from pyrail.irail import StationDetails, iRail


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

        # Validate that the response is a list
        assert isinstance(stations, list), "Expected the response to be a list"

        # Validate the structure of a station
        assert isinstance(stations[0], StationDetails), "Expected the first item to be a Station object"
        assert len(stations) > 0, "Expected at least one station in the response"


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
"""Additional unit tests for the pyrail models and API endpoints."""

import pytest
from datetime import datetime

from pyrail.models import (
    LiveboardApiResponse,
    VehicleApiResponse,
    CompositionApiResponse,
    DisturbancesApiResponse,
    StationDetails,
    VehicleInfo,
    PlatformInfo,
    Occupancy,
)

# Sample data for testing
SAMPLE_STATION = {
    "@id": "http://irail.be/stations/NMBS/008892007",
    "id": "BE.NMBS.008892007",
    "name": "Brussels-Central",
    "locationX": 4.356802,
    "locationY": 50.845658,
    "standardname": "BRUXELLES-CENTRAL/BRUSSEL-CENTRAAL"
}

SAMPLE_VEHICLE = {
    "name": "IC 538",
    "shortname": "538",
    "number": "538",
    "type": "IC",
    "locationX": 4.356802,
    "locationY": 50.845658,
    "@id": "http://irail.be/vehicle/IC538"
}

@pytest.mark.asyncio
async def test_liveboard_response_model():
    """Test LiveboardApiResponse model serialization and deserialization."""
    sample_data = {
        "version": "1.3",
        "timestamp": int(datetime.now().timestamp()),
        "station": "Brussels-Central",
        "stationinfo": SAMPLE_STATION,
        "departures": {
            "number": 1,
            "departure": [{
                "id": "1",
                "station": "Antwerp-Central",
                "stationinfo": SAMPLE_STATION,
                "time": int(datetime.now().timestamp()),
                "delay": 0,
                "canceled": False,
                "left": False,
                "isExtra": False,
                "vehicle": "IC538",
                "vehicleinfo": SAMPLE_VEHICLE,
                "platform": "3",
                "platforminfo": {"name": "3", "normal": True},
                "occupancy": {"@id": "low", "name": "LOW"},
                "departureConnection": "http://irail.be/connections/1"
            }]
        }
    }

    response = LiveboardApiResponse.from_dict(sample_data)
    assert response.version == "1.3"
    assert isinstance(response.station_info, StationDetails)
    assert len(response.departures.departure) == 1
    assert response.departures.departure[0].platform == "3"

    # Test serialization
    serialized = response.to_dict()
    assert serialized["stationinfo"]["@id"] == SAMPLE_STATION["@id"]
    assert serialized["departures"]["departure"][0]["isExtra"] is False

@pytest.mark.asyncio
async def test_vehicle_api_response():
    """Test VehicleApiResponse model with sample data."""
    async with iRail() as api:
        vehicle = await api.get_vehicle("IC538")
        
        assert vehicle is not None
        assert isinstance(vehicle, VehicleApiResponse)
        assert isinstance(vehicle.vehicle_info, VehicleInfo)
        assert vehicle.stops.number >= 0
        
        # Test that all stops have valid platform info
        for stop in vehicle.stops.stop:
            assert isinstance(stop.platform_info, PlatformInfo)
            assert isinstance(stop.occupancy, Occupancy)

@pytest.mark.asyncio
async def test_composition_api_response():
    """Test train composition endpoint and response model."""
    async with iRail() as api:
        composition = await api.get_composition("IC538")
        
        assert composition is not None
        assert isinstance(composition, CompositionApiResponse)
        
        # Test segments structure
        segments = composition.composition.segments
        assert segments.number >= 0
        
        if segments.number > 0:
            segment = segments.segment[0]
            assert isinstance(segment.origin, StationDetails)
            assert isinstance(segment.destination, StationDetails)
            
            # Test units in composition
            units = segment.composition.units
            assert units.number >= 0
            
            if units.number > 0:
                unit = units.unit[0]
                assert isinstance(unit.has_toilets, bool)
                assert isinstance(unit.seats_first_class, int)
                assert isinstance(unit.length_in_meter, int)

@pytest.mark.asyncio
async def test_disturbances_api_response():
    """Test disturbances endpoint and response model."""
    async with iRail() as api:
        disturbances = await api.get_disturbances()
        
        assert disturbances is not None
        assert isinstance(disturbances, DisturbancesApiResponse)
        
        # Test disturbance attributes
        if len(disturbances.disturbances) > 0:
            disturbance = disturbances.disturbances[0]
            assert isinstance(disturbance.id, str)
            assert isinstance(disturbance.title, str)
            assert isinstance(disturbance.timestamp, int)
            assert disturbance.type in ["disturbance", "planned"]

@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling for various API endpoints."""
    async with iRail() as api:
        # Test with invalid vehicle ID
        vehicle = await api.get_vehicle("INVALID_ID")
        assert vehicle is None
        
        # Test with invalid station for liveboard
        liveboard = await api.get_liveboard("INVALID_STATION")
        assert liveboard is None
        
        # Test with invalid train ID for composition
        composition = await api.get_composition("INVALID_TRAIN")
        assert composition is None

@pytest.mark.asyncio
async def test_field_aliases():
    """Test that field aliases are correctly handled in serialization."""
    station = StationDetails.from_dict({
        "@id": "test_id",
        "id": "BE.TEST.1",
        "name": "Test Station",
        "locationX": 4.0,
        "locationY": 51.0,
        "standardname": "TEST"
    })
    
    assert station.at_id == "test_id"
    assert station.longitude == 4.0
    assert station.latitude == 51.0
    assert station.standard_name == "TEST"
    
    # Test serialization maintains the original field names
    serialized = station.to_dict()
    assert "@id" in serialized
    assert "locationX" in serialized
    assert "locationY" in serialized
    assert "standardname" in serialized
"""Additional unit tests for the pyrail models and API endpoints."""

# ... (same test content as before) ...
