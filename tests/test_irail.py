"""Unit tests for the iRail API wrapper."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession
import pytest

from pyrail.irail import iRail
from pyrail.models import (
    Alert,
    ApiResponse,
    CompositionApiResponse,
    ConnectionDetails,
    ConnectionsApiResponse,
    Disturbance,
    DisturbancesApiResponse,
    DisturbanceType,
    LiveboardApiResponse,
    LiveboardDeparture,
    Occupancy,
    PlatformInfo,
    StationDetails,
    StationsApiResponse,
    VehicleApiResponse,
    VehicleInfo,
    _str_to_bool,
    _timestamp_to_datetime,
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
        departure_list = liveboard.departures
        assert isinstance(departure_list, list), "Expected 'departure' to be a list"
        assert len(departure_list) > 0, "Expected at least one departure in the response"
        assert isinstance(departure_list[0], LiveboardDeparture), (
            "Expected the first departure to be a LiveboardDeparture object"
        )
        # Test VehicleInfo dataclass
        assert isinstance(departure_list[0].vehicle_info, VehicleInfo), (
            "Expected vehicle_info to be a VehicleInfo object"
        )


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
        assert isinstance(connection_list[0], ConnectionDetails), (
            "Expected the first connection to be a ConnectionDetails object"
        )


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
        assert isinstance(vehicle.stops, list), "Expected 'stop' to be a list"
        assert len(vehicle.stops) > 0, "Expected at least one stop"
        if len(vehicle.stops) > 0:
            stop = vehicle.stops[0]
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
        assert isinstance(composition, CompositionApiResponse), (
            "Expected response to be a CompositionApiResponse object"
        )

        # Test segments structure
        segments = composition.composition
        assert isinstance(segments, list), "Expected 'segments' to be a list"
        assert len(segments) > 0, "Expected 'number' to be a non-negative integer"

        if len(segments) > 0:
            segment = segments[0]
            assert isinstance(segment.origin, StationDetails), "Expected origin to be a StationDetails object"
            assert isinstance(segment.destination, StationDetails), "Expected destination to be a StationDetails object"

            # Test units in composition
            units = segment.composition.units
            assert len(units) > 0, "Expected 'number' to be a non-negative integer"

            if len(units) > 0:
                unit = units[0]
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
        assert isinstance(disturbances, DisturbancesApiResponse), (
            "Expected response to be a DisturbancesApiResponse object"
        )
        assert isinstance(disturbances.disturbances, list), "Expected 'disturbances' to be a list"

        # Test disturbance attributes
        if len(disturbances.disturbances) > 0:
            disturbance = disturbances.disturbances[0]
            assert isinstance(disturbance.title, str), "Expected 'title' to be a string"
            assert isinstance(disturbance.description, str), "Expected 'description' to be a string"
            assert disturbance.type in DisturbanceType, "Expected 'type' to be 'disturbance' or 'planned'"


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


@pytest.mark.asyncio
async def test_timestamp_to_datetime():
    """Test the timestamp_to_datetime function."""
    # Test valid timestamps
    assert _timestamp_to_datetime("1705593600") == datetime(
        2024, 1, 18, 16, 0, tzinfo=timezone.utc
    )  # 2024-01-18 16:00:00
    assert _timestamp_to_datetime("0") == datetime(1970, 1, 1, 0, 0, tzinfo=timezone.utc)  # Unix epoch


@pytest.mark.asyncio
async def test_timestamp_field_deserialization():
    """Test timestamp field deserialization in various models."""
    # Test ApiResponse timestamp
    api_response = ApiResponse.from_dict({"version": "1.0", "timestamp": "1705593600"})
    assert api_response.timestamp == datetime(2024, 1, 18, 16, 0, tzinfo=timezone.utc)

    # Test LiveboardDeparture time
    departure = LiveboardDeparture.from_dict(
        {
            "id": "0",
            "station": "Brussels-South/Brussels-Midi",
            "stationinfo": {
                "@id": "http://irail.be/stations/NMBS/008814001",
                "id": "BE.NMBS.008814001",
                "name": "Brussels-South/Brussels-Midi",
                "locationX": "4.336531",
                "locationY": "50.835707",
                "standardname": "Brussel-Zuid/Bruxelles-Midi",
            },
            "time": "1705593600",
            "delay": "0",
            "canceled": "0",
            "left": "0",
            "isExtra": "0",
            "vehicle": "BE.NMBS.EC9272",
            "vehicleinfo": {
                "name": "BE.NMBS.EC9272",
                "shortname": "EC 9272",
                "number": "9272",
                "type": "EC",
                "locationX": "0",
                "locationY": "0",
                "@id": "http://irail.be/vehicle/EC9272",
            },
            "platform": "23",
            "platforminfo": {"name": "23", "normal": "1"},
            "occupancy": {"@id": "http://api.irail.be/terms/low", "name": "low"},
            "departureConnection": "http://irail.be/connections/8821006/20250106/EC9272",
        }
    )
    assert departure.time == datetime(2024, 1, 18, 16, 0, tzinfo=timezone.utc)

    # Test Alert start_time and end_time
    alert = Alert.from_dict(
        {
            "id": "0",
            "header": "Anvers-Central / Antwerpen-Centraal - Anvers-Berchem / Antwerpen-Berchem",
            "description": "During the weekends, from 4 to 19/01 Infrabel is working on the track. The departure times of this train change. The travel planner takes these changes into account.",
            "lead": "During the weekends, from 4 to 19/01 Infrabel is working on the track",
            "startTime": "1705593600",
            "endTime": "1705597200",
        }
    )
    assert alert.start_time == datetime(2024, 1, 18, 16, 0, tzinfo=timezone.utc)
    assert alert.end_time == datetime(2024, 1, 18, 17, 0, tzinfo=timezone.utc)

    # Test Disturbance timestamp
    disturbance = Disturbance.from_dict(
        {
            "id": "1",
            "title": "Mouscron / Moeskroen - Lille Flandres (FR)",
            "description": "On weekdays from 6 to 17/01 works will take place on the French rail network.An SNCB bus replaces some IC trains Courtrai / Kortrijk - Mouscron / Moeskroen - Lille Flandres (FR) between Mouscron / Moeskroen and Lille Flandres (FR).The travel planner takes these changes into account.Meer info over de NMBS-bussen (FAQ)En savoir plus sur les bus SNCB (FAQ)Où prendre mon bus ?Waar is mijn bushalte?",
            "type": "planned",
            "link": "https://www.belgiantrain.be/nl/support/faq/faq-routes-schedules/faq-bus",
            "timestamp": "1705593600",
            "richtext": "On weekdays from 6 to 17/01 works will take place on the French rail network.An SNCB bus replaces some IC trains Courtrai / Kortrijk - Mouscron / Moeskroen - Lille Flandres (FR) between Mouscron / Moeskroen and Lille Flandres (FR).The travel planner takes these changes into account.<br><a href='https://www.belgiantrain.be/nl/support/faq/faq-routes-schedules/faq-bus'>Meer info over de NMBS-bussen (FAQ)</a><br><a href='https://www.belgiantrain.be/fr/support/faq/faq-routes-schedules/faq-bus'>En savoir plus sur les bus SNCB (FAQ)</a><br><a href='https://www.belgianrail.be/jp/download/brail_him/1736172333792_FR_2501250_S.pdf'>Où prendre mon bus ?</a><br><a href='https://www.belgianrail.be/jp/download/brail_him/1736172333804_NL_2501250_S.pdf'>Waar is mijn bushalte?</a>",
            "descriptionLinks": {
                "number": "4",
                "descriptionLink": [
                    {
                        "id": "0",
                        "link": "https://www.belgiantrain.be/nl/support/faq/faq-routes-schedules/faq-bus",
                        "text": "Meer info over de NMBS-bussen (FAQ)",
                    },
                    {
                        "id": "1",
                        "link": "https://www.belgiantrain.be/fr/support/faq/faq-routes-schedules/faq-bus",
                        "text": "En savoir plus sur les bus SNCB (FAQ)",
                    },
                    {
                        "id": "2",
                        "link": "https://www.belgianrail.be/jp/download/brail_him/1736172333792_FR_2501250_S.pdf",
                        "text": "Où prendre mon bus ?",
                    },
                    {
                        "id": "3",
                        "link": "https://www.belgianrail.be/jp/download/brail_him/1736172333804_NL_2501250_S.pdf",
                        "text": "Waar is mijn bushalte?",
                    },
                ],
            },
        }
    )
    assert disturbance.timestamp == datetime(2024, 1, 18, 16, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_str_to_bool():
    """Test the str_to_bool function that converts string values to boolean."""
    # Test valid inputs
    assert _str_to_bool("1") is True, "String '1' should convert to True"
    assert _str_to_bool("0") is False, "String '0' should convert to False"


@pytest.mark.asyncio
async def test_boolean_field_deserialization():
    """Test the deserialization of boolean fields in models."""
    # Test PlatformInfo boolean field
    platform = PlatformInfo.from_dict({"name": "1", "normal": "1"})
    assert platform.normal is True, "Platform normal field should be True when '1'"

    platform = PlatformInfo.from_dict({"name": "1", "normal": "0"})
    assert platform.normal is False, "Platform normal field should be False when '0'"

    # Test LiveboardDeparture multiple boolean fields
    departure = LiveboardDeparture.from_dict(
        {
            "id": "1",
            "station": "Brussels",
            "stationinfo": {
                "@id": "1",
                "id": "1",
                "name": "Brussels",
                "locationX": 4.3517,
                "locationY": 50.8503,
                "standardname": "Brussels-Central",
            },
            "time": "1705593600",  # Example timestamp
            "delay": 0,
            "canceled": "1",
            "left": "0",
            "isExtra": "1",
            "vehicle": "BE.NMBS.IC1234",
            "vehicleinfo": {
                "name": "IC1234",
                "shortname": "IC1234",
                "number": "1234",
                "type": "IC",
                "locationX": 4.3517,
                "locationY": 50.8503,
                "@id": "1",
            },
            "platform": "1",
            "platforminfo": {"name": "1", "normal": "1"},
            "occupancy": {"@id": "http://api.irail.be/terms/low", "name": "low"},
            "departureConnection": "1",
        }
    )

    # Verify boolean fields are correctly deserialized
    assert departure.canceled is True, "Departure canceled field should be True when '1'"
    assert departure.left is False, "Departure left field should be False when '0'"
    assert departure.is_extra is True, "Departure is_extra field should be True when '1'"
    assert departure.platform_info.normal is True, "Platform normal field should be True when '1'"


# Empty Departures Handling Tests
@pytest.mark.asyncio
async def test_liveboard_empty_departures_night_hours():
    """Test LiveboardApiResponse utility methods for empty departures during night hours."""
    from pyrail.models import LiveboardApiResponse, StationDetails
    
    # Create a response representing night hours with empty departures
    night_timestamp = datetime(2025, 6, 29, 23, 30, 0, tzinfo=timezone.utc)  # 23:30 UTC
    
    liveboard = LiveboardApiResponse(
        version="1.3",
        timestamp=night_timestamp,
        station="Ostend",
        station_info=StationDetails(
            at_id="http://irail.be/stations/NMBS/008891702",
            id="BE.NMBS.008891702",
            name="Ostend",
            longitude=2.925809,
            latitude=51.228212,
            standard_name="Oostende"
        ),
        departures=[],  # Empty list - this is what triggers the HA error
        arrivals=None
    )
    
    # Test utility methods
    assert not liveboard.has_departures(), "Should report no departures"
    assert not liveboard.has_arrivals(), "Should report no arrivals"
    assert liveboard.is_empty_but_valid(), "Should be recognized as valid empty response"
    assert liveboard.is_night_hours(), "Should recognize night hours"
    assert liveboard.get_departure_count() == 0, "Departure count should be 0"
    assert liveboard.get_arrival_count() == 0, "Arrival count should be 0"
    
    # Test status summary
    summary = liveboard.get_status_summary()
    assert summary["departure_count"] == 0
    assert summary["arrival_count"] == 0
    assert not summary["has_data"]
    assert summary["is_empty_but_valid"]
    assert summary["is_night_hours"]
    assert "night hours (normal)" in summary["status"]


@pytest.mark.asyncio
async def test_liveboard_empty_departures_day_hours():
    """Test LiveboardApiResponse for empty departures during day hours."""
    from pyrail.models import LiveboardApiResponse, StationDetails
    
    # Create a response representing day hours with empty departures
    day_timestamp = datetime(2025, 6, 29, 14, 30, 0, tzinfo=timezone.utc)  # 14:30 UTC
    
    liveboard = LiveboardApiResponse(
        version="1.3",
        timestamp=day_timestamp,
        station="Small-Station",
        station_info=StationDetails(
            at_id="http://irail.be/stations/NMBS/123456789",
            id="BE.NMBS.123456789",
            name="Small-Station",
            longitude=4.0,
            latitude=51.0,
            standard_name="Small-Station"
        ),
        departures=[],
        arrivals=None
    )
    
    assert liveboard.is_empty_but_valid(), "Should be valid empty response"
    assert not liveboard.is_night_hours(), "Should not be night hours"
    
    summary = liveboard.get_status_summary()
    assert summary["is_empty_but_valid"]
    assert not summary["is_night_hours"]
    assert "limited schedule" in summary["status"]


@pytest.mark.asyncio
async def test_liveboard_with_departures():
    """Test LiveboardApiResponse with actual departures."""
    from pyrail.models import LiveboardApiResponse, StationDetails, LiveboardDeparture
    
    # Create a mock departure
    departure = LiveboardDeparture(
        id="123",
        delay=0,
        station="Brussels-Central",
        station_info=StationDetails(
            at_id="http://irail.be/stations/NMBS/008813003",
            id="BE.NMBS.008813003", 
            name="Brussels-Central",
            longitude=4.357056,
            latitude=50.845966,
            standard_name="Brussel-Centraal"
        ),
        time=datetime.now(timezone.utc),
        vehicle="BE.NMBS.IC123",
        vehicle_info=None,
        platform="1",
        platform_info=None,
        canceled=False,
        left=False,
        is_extra=False,
        alerts=None,
        occupancy=None,
        walking_time=None,
        departure_connection=""
    )
    
    liveboard = LiveboardApiResponse(
        version="1.3",
        timestamp=datetime.now(timezone.utc),
        station="Brussels-Central",
        station_info=departure.station_info,
        departures=[departure],
        arrivals=None
    )
    
    assert liveboard.has_departures(), "Should have departures"
    assert not liveboard.is_empty_but_valid(), "Should not be empty"
    assert liveboard.get_departure_count() == 1
    
    summary = liveboard.get_status_summary()
    assert summary["has_data"]
    assert summary["departure_count"] == 1
    assert "Active service" in summary["status"]


@pytest.mark.asyncio
@patch("pyrail.irail.ClientSession.get")
async def test_get_liveboard_with_validation_empty_night(mock_get):
    """Test get_liveboard_with_validation with empty night response."""
    # Mock empty liveboard response during night hours
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {}
    mock_response.json = AsyncMock(return_value={
        "version": "1.3",
        "timestamp": "1719706238",  # Night time timestamp
        "station": "Ostend",
        "stationinfo": {
            "@id": "http://irail.be/stations/NMBS/008891702",
            "id": "BE.NMBS.008891702",
            "name": "Ostend",
            "longitude": "2.925809", 
            "latitude": "51.228212",
            "standardname": "Oostende"
        },
        "departures": {"departure": []},  # Empty departures
        "arrivals": None
    })
    
    mock_get.return_value.__aenter__.return_value = mock_response
    
    async with iRail() as api:
        liveboard, summary = await api.get_liveboard_with_validation(station="Ostend")
        
        assert liveboard is not None
        assert summary["is_valid_response"]
        assert not summary["has_data"]
        assert summary["is_empty_but_valid"]
        assert summary["departure_count"] == 0
        assert "not an error" in summary["guidance"]


@pytest.mark.asyncio
@patch("pyrail.irail.ClientSession.get")
async def test_get_liveboard_with_validation_failed_request(mock_get):
    """Test get_liveboard_with_validation with failed request."""
    # Mock failed request
    mock_response = AsyncMock()
    mock_response.status = 404
    mock_response.text = AsyncMock(return_value="Station not found")
    
    mock_get.return_value.__aenter__.return_value = mock_response
    
    async with iRail() as api:
        liveboard, summary = await api.get_liveboard_with_validation(station="InvalidStation")
        
        assert liveboard is None
        assert not summary["is_valid_response"]
        assert not summary["has_data"]
        assert not summary["is_empty_but_valid"]
        assert summary["status"] == "Request failed or returned None"
        assert "network connectivity" in summary["guidance"]


@pytest.mark.asyncio
async def test_is_likely_night_service_gap():
    """Test the static method for detecting night service gaps."""
    # Test deep night hours (should always return True)
    deep_night = datetime(2025, 6, 29, 23, 30, 0, tzinfo=timezone.utc)
    assert iRail.is_likely_night_service_gap(deep_night, "Any Station")
    
    very_early = datetime(2025, 6, 29, 4, 30, 0, tzinfo=timezone.utc)
    assert iRail.is_likely_night_service_gap(very_early, "Any Station")
    
    # Test night hours for small stations (should return True)
    night_small_station = datetime(2025, 6, 29, 2, 0, 0, tzinfo=timezone.utc)
    assert iRail.is_likely_night_service_gap(night_small_station, "Small-Town")
    
    # Test night hours for major stations (should return False)
    night_major_station = datetime(2025, 6, 29, 2, 0, 0, tzinfo=timezone.utc)
    assert not iRail.is_likely_night_service_gap(night_major_station, "Brussels-South")
    assert not iRail.is_likely_night_service_gap(night_major_station, "Antwerp-Central")
    
    # Test day hours (should return False)
    day_time = datetime(2025, 6, 29, 14, 0, 0, tzinfo=timezone.utc)
    assert not iRail.is_likely_night_service_gap(day_time, "Any Station")


@pytest.mark.asyncio
async def test_liveboard_response_none_vs_empty_departures():
    """Test distinction between None departures and empty list departures."""
    from pyrail.models import LiveboardApiResponse, StationDetails
    
    station_info = StationDetails(
        at_id="http://irail.be/stations/NMBS/123",
        id="BE.NMBS.123",
        name="Test Station", 
        longitude=4.0,
        latitude=51.0,
        standard_name="Test"
    )
    
    # Test with None departures (API didn't provide departures data)
    liveboard_none = LiveboardApiResponse(
        version="1.3",
        timestamp=datetime.now(timezone.utc),
        station="Test Station",
        station_info=station_info,
        departures=None,  # None means no departures data provided
        arrivals=None
    )
    
    # Test with empty list departures (API provided empty departures data)
    liveboard_empty = LiveboardApiResponse(
        version="1.3", 
        timestamp=datetime.now(timezone.utc),
        station="Test Station",
        station_info=station_info,
        departures=[],  # Empty list means no departures available
        arrivals=None
    )
    
    # None departures should not be considered "empty but valid"
    assert not liveboard_none.is_empty_but_valid()
    assert liveboard_none.get_departure_count() == 0
    
    # Empty list departures should be considered "empty but valid"
    assert liveboard_empty.is_empty_but_valid()
    assert liveboard_empty.get_departure_count() == 0
    
    # Both should report no departures
    assert not liveboard_none.has_departures()
    assert not liveboard_empty.has_departures()
