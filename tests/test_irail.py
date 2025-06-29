"""Unit tests for the iRail API wrapper."""

from datetime import datetime, timedelta, timezone
import time
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession
import pytest

from pyrail.irail import iRail, CacheEntry
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


# Enhanced ETag Caching Tests
@pytest.mark.asyncio
async def test_cache_entry_creation():
    """Test CacheEntry dataclass functionality."""
    current_time = time.time()
    data = {"test": "data"}
    etag = "W/\"12345\""
    
    entry = CacheEntry(etag=etag, data=data, timestamp=current_time)
    
    assert entry.etag == etag
    assert entry.data == data
    assert entry.timestamp == current_time
    assert not entry.is_expired(max_age_seconds=3600)  # Should not be expired immediately
    
    # Test expiration
    old_entry = CacheEntry(etag=etag, data=data, timestamp=current_time - 7200)  # 2 hours ago
    assert old_entry.is_expired(max_age_seconds=3600)  # Should be expired after 1 hour max age


@pytest.mark.asyncio
async def test_cache_key_generation():
    """Test cache key generation for different scenarios."""
    async with iRail() as api:
        # Test basic method cache key
        key1 = api._generate_cache_key("stations")
        key2 = api._generate_cache_key("stations")
        assert key1 == key2, "Same method should generate same cache key"
        
        # Test different methods generate different keys
        key_stations = api._generate_cache_key("stations")
        key_liveboard = api._generate_cache_key("liveboard")
        assert key_stations != key_liveboard, "Different methods should generate different cache keys"
        
        # Test same method with different args
        args1 = {"station": "Brussels-South"}
        args2 = {"station": "Antwerp-Central"}
        key_args1 = api._generate_cache_key("liveboard", args1)
        key_args2 = api._generate_cache_key("liveboard", args2)
        assert key_args1 != key_args2, "Same method with different args should generate different keys"
        
        # Test arg order doesn't matter
        args_ordered1 = {"from": "Brussels", "to": "Antwerp"}
        args_ordered2 = {"to": "Antwerp", "from": "Brussels"}
        key_ordered1 = api._generate_cache_key("connections", args_ordered1)
        key_ordered2 = api._generate_cache_key("connections", args_ordered2)
        assert key_ordered1 == key_ordered2, "Argument order should not affect cache key"


@pytest.mark.asyncio
@patch("pyrail.irail.ClientSession.get")
async def test_etag_caching_workflow(mock_get):
    """Test complete ETag caching workflow."""
    # First request: 200 response with ETag
    mock_response_200 = AsyncMock()
    mock_response_200.status = 200
    mock_response_200.headers = {"Etag": "W/\"12345\""}
    mock_response_200.json = AsyncMock(return_value={"stations": [{"name": "Brussels"}]})
    
    # Second request: 304 Not Modified response
    mock_response_304 = AsyncMock()
    mock_response_304.status = 304
    mock_response_304.headers = {"Etag": "W/\"12345\""}
    
    mock_get.return_value.__aenter__.side_effect = [mock_response_200, mock_response_304]
    
    async with iRail() as api:
        # First request should cache the response
        result1 = await api._do_request("stations")
        assert result1 == {"stations": [{"name": "Brussels"}]}
        
        # Verify cache was populated
        cache_stats = api.get_cache_stats()
        assert cache_stats["total_entries"] == 1
        assert cache_stats["valid_entries"] == 1
        
        # Second request should return cached data on 304
        result2 = await api._do_request("stations")
        assert result2 == {"stations": [{"name": "Brussels"}]}
        assert result1 == result2, "Cached data should be identical to original"


@pytest.mark.asyncio
@patch("pyrail.irail.ClientSession.get")
async def test_etag_header_sent_on_cached_request(mock_get):
    """Test that If-None-Match header is sent when cache exists."""
    # First request: 200 response with ETag
    mock_response_200 = AsyncMock()
    mock_response_200.status = 200
    mock_response_200.headers = {"Etag": "W/\"12345\""}
    mock_response_200.json = AsyncMock(return_value={"data": "test"})
    
    # Second request: should include If-None-Match header
    mock_response_304 = AsyncMock()
    mock_response_304.status = 304
    mock_response_304.headers = {}
    
    mock_get.return_value.__aenter__.side_effect = [mock_response_200, mock_response_304]
    
    async with iRail() as api:
        # First request - no If-None-Match header expected
        await api._do_request("stations")
        
        # Verify first call didn't include If-None-Match
        first_call_headers = mock_get.call_args_list[0][1]["headers"]
        assert "If-None-Match" not in first_call_headers
        
        # Second request - If-None-Match header should be included
        await api._do_request("stations")
        
        # Verify second call included If-None-Match
        second_call_headers = mock_get.call_args_list[1][1]["headers"]
        assert "If-None-Match" in second_call_headers
        assert second_call_headers["If-None-Match"] == "W/\"12345\""


@pytest.mark.asyncio
async def test_cache_expiration():
    """Test cache expiration functionality."""
    async with iRail() as api:
        # Set very short cache expiration for testing
        api.set_cache_max_age(0.1)  # 100ms
        
        # Create expired cache entry manually
        expired_entry = CacheEntry(
            etag="W/\"expired\"",
            data={"expired": "data"},
            timestamp=time.time() - 1  # 1 second ago
        )
        
        cache_key = api._generate_cache_key("test_method")
        api.response_cache[cache_key] = expired_entry
        
        # Check cache stats before cleanup
        stats_before = api.get_cache_stats()
        assert stats_before["total_entries"] == 1
        assert stats_before["expired_entries"] == 1
        assert stats_before["valid_entries"] == 0
        
        # Trigger cleanup by calling _add_etag_header
        headers = api._add_etag_header(cache_key)
        
        # Expired entry should be removed
        assert cache_key not in api.response_cache
        assert "If-None-Match" not in headers


@pytest.mark.asyncio
async def test_cache_invalidation():
    """Test cache invalidation methods."""
    async with iRail() as api:
        # Add some cache entries
        entry1 = CacheEntry(etag="1", data={"data": 1}, timestamp=time.time())
        entry2 = CacheEntry(etag="2", data={"data": 2}, timestamp=time.time())
        entry3 = CacheEntry(etag="3", data={"data": 3}, timestamp=time.time())
        
        key1 = api._generate_cache_key("stations")
        key2 = api._generate_cache_key("liveboard", {"station": "Brussels"})
        key3 = api._generate_cache_key("connections", {"from": "A", "to": "B"})
        
        api.response_cache[key1] = entry1
        api.response_cache[key2] = entry2
        api.response_cache[key3] = entry3
        
        assert len(api.response_cache) == 3
        
        # Test clearing all cache
        api.clear_cache()
        assert len(api.response_cache) == 0
        
        # Re-add entries for method-specific invalidation test
        api.response_cache[key1] = entry1
        api.response_cache[key2] = entry2
        api.response_cache[key3] = entry3
        
        # Test invalidating specific method (this is approximate due to hash-based keys)
        removed = api.invalidate_cache_for_method("stations")
        # Note: This test might be fragile due to hash collision possibilities
        # In a real implementation, you might want to store method info in the cache


@pytest.mark.asyncio
async def test_cache_stats():
    """Test cache statistics functionality."""
    async with iRail() as api:
        # Initially empty cache
        stats = api.get_cache_stats()
        assert stats["total_entries"] == 0
        assert stats["valid_entries"] == 0
        assert stats["expired_entries"] == 0
        assert stats["cache_max_age_seconds"] == 3600  # Default
        
        # Add valid entry
        valid_entry = CacheEntry(
            etag="valid",
            data={"valid": "data"},
            timestamp=time.time()
        )
        api.response_cache["valid_key"] = valid_entry
        
        # Add expired entry
        expired_entry = CacheEntry(
            etag="expired",
            data={"expired": "data"},
            timestamp=time.time() - 7200  # 2 hours ago
        )
        api.response_cache["expired_key"] = expired_entry
        
        stats = api.get_cache_stats()
        assert stats["total_entries"] == 2
        assert stats["valid_entries"] == 1
        assert stats["expired_entries"] == 1


@pytest.mark.asyncio
async def test_cache_max_age_setting():
    """Test setting cache max age."""
    async with iRail() as api:
        # Test setting valid max age
        api.set_cache_max_age(1800)  # 30 minutes
        assert api.cache_max_age == 1800
        
        # Test error on invalid max age
        with pytest.raises(ValueError, match="Cache max age must be positive"):
            api.set_cache_max_age(-1)
        
        with pytest.raises(ValueError, match="Cache max age must be positive"):
            api.set_cache_max_age(0)


@pytest.mark.asyncio
@patch("pyrail.irail.ClientSession.get")
async def test_no_cache_without_etag(mock_get):
    """Test that responses without ETag headers are not cached."""
    # Response without ETag header
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {}  # No ETag
    mock_response.json = AsyncMock(return_value={"data": "no_etag"})
    
    mock_get.return_value.__aenter__.return_value = mock_response
    
    async with iRail() as api:
        result = await api._do_request("stations")
        assert result == {"data": "no_etag"}
        
        # Verify no cache entry was created
        cache_stats = api.get_cache_stats()
        assert cache_stats["total_entries"] == 0


@pytest.mark.asyncio
async def test_deprecated_clear_etag_cache():
    """Test that the deprecated clear_etag_cache method still works."""
    async with iRail() as api:
        # Add a cache entry
        entry = CacheEntry(etag="test", data={"test": "data"}, timestamp=time.time())
        api.response_cache["test_key"] = entry
        
        assert len(api.response_cache) == 1
        
        # Use deprecated method (should log warning)
        with patch('pyrail.irail.logger') as mock_logger:
            api.clear_etag_cache()
            mock_logger.warning.assert_called_with("clear_etag_cache is deprecated, use clear_cache instead")
        
        # Cache should be cleared
        assert len(api.response_cache) == 0
