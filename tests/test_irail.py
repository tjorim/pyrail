"""Unit tests for the iRail API wrapper."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from aiohttp import ClientError, ClientSession
from multidict import CIMultiDict
import pytest

from pyrail.exceptions import (
    ApiUnavailableError,
    InvalidRequestError,
    InvalidResponseError,
    NotFoundError,
    PyRailError,
    RateLimitError,
)
from pyrail.irail import _parse_retry_after, iRail
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
    LiveboardArrival,
    LiveboardDeparture,
    Occupancy,
    PlatformInfo,
    StationDetails,
    StationsApiResponse,
    Unit,
    VehicleApiResponse,
    VehicleInfo,
    _str_to_bool,
    _timestamp_to_datetime,
)

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _load_example(name: str) -> dict[str, Any]:
    """Load a recorded API response from the examples directory."""
    return json.loads((EXAMPLES_DIR / name).read_text())


def _mock_response(
    status: int = 200, data: dict[str, Any] | None = None, headers: dict[str, str] | None = None
) -> AsyncMock:
    """Build a mocked ClientResponse returning the given status, JSON body and headers.

    Each json() call returns a fresh copy of data, so deserialization hooks
    that mutate the payload cannot leak into the next call.
    """
    response = AsyncMock()
    response.status = status
    response.headers = CIMultiDict(headers or {})
    response.json = AsyncMock(side_effect=lambda: deepcopy(data))
    response.text = AsyncMock(return_value="")
    return response


@patch("pyrail.irail.ClientSession.get")
async def test_successful_request(mock_get):
    """Test a successful API request by mocking the iRail response."""
    mock_response = _mock_response(data={"data": "some_data"})
    mock_get.return_value.__aenter__.return_value = mock_response

    async with iRail() as api:
        assert api.session is not None
        response = await api._do_request("stations")
        mock_get.assert_called_once_with(
            "https://api.irail.be/v1/stations/",
            params={"format": "json", "lang": "en"},
            headers={"User-Agent": "pyRail (https://github.com/tjorim/pyrail; tielemans.jorim@gmail.com)"},
        )
        assert response == {"data": "some_data"}
        assert mock_response.status == 200


async def test_irail_context_manager():
    """Ensure that the async context manager sets up and tears down the session properly."""
    async with iRail() as irail:
        assert irail.session is not None
        assert isinstance(irail.session, ClientSession)


@patch("pyrail.irail.ClientSession.get")
async def test_client_without_context_manager(mock_get):
    """A client used without the context manager creates a session lazily and close() closes it."""
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("stations.json"))

    api = iRail()
    stations = await api.get_stations()
    await api.close()

    assert stations is not None
    assert api.session is not None
    assert api.session.closed


@patch("pyrail.irail.ClientSession.get")
async def test_close_leaves_external_session_open(mock_get):
    """close() never closes a session provided by the caller."""
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("stations.json"))

    async with ClientSession() as session:
        api = iRail(session=session)
        assert await api.get_stations() is not None
        await api.close()
        assert not session.closed


@patch("pyrail.irail.ClientSession.get")
async def test_get_stations(mock_get):
    """Test the get_stations endpoint.

    Verifies that:
    - The response is not None
    - The response is a StationsApiResponse object
    - The response contains a 'station' key
    - The station list is non-empty
    """
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("stations.json"))

    async with iRail() as api:
        stations = await api.get_stations()

        assert stations is not None, "The response should not be None"

        assert isinstance(stations, StationsApiResponse), "Expected the response to be a StationsApiResponse object"

        station_list = stations.stations
        assert isinstance(station_list, list), "Expected 'station' to be a list"
        assert len(station_list) > 0, "Expected at least one station in the response"
        assert isinstance(station_list[0], StationDetails), "Expected the first station to be a StationDetails object"


@patch("pyrail.irail.ClientSession.get")
async def test_get_liveboard(mock_get):
    """Test the get_liveboard endpoint.

    Verifies that:
    - The response is not None
    - The response is a LiveboardApiResponse object
    - The response contains a 'departures' key
    - The departure list is non-empty
    """
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("liveboard.json"))

    async with iRail() as api:
        liveboard = await api.get_liveboard("Brussels-Central")

        assert liveboard is not None, "The response should not be None"

        assert isinstance(liveboard, LiveboardApiResponse), "Expected response to be a LiveboardApiResponse object"

        departure_list = liveboard.departures
        assert isinstance(departure_list, list), "Expected 'departure' to be a list"
        assert len(departure_list) > 0, "Expected at least one departure in the response"
        assert isinstance(departure_list[0], LiveboardDeparture), (
            "Expected the first departure to be a LiveboardDeparture object"
        )
        assert isinstance(departure_list[0].vehicle_info, VehicleInfo), (
            "Expected vehicle_info to be a VehicleInfo object"
        )


@patch("pyrail.irail.ClientSession.get")
async def test_get_liveboard_arrivals(mock_get):
    """An arrival board has arrivals but no departures, and its arrivals carry no occupancy."""
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("liveboard_arrivals.json"))

    async with iRail() as api:
        liveboard = await api.get_liveboard("Brussels-Central", arrdep="arrival")

    assert liveboard is not None
    assert liveboard.departures is None
    assert liveboard.arrivals is not None and len(liveboard.arrivals) > 0
    assert all(isinstance(arrival, LiveboardArrival) for arrival in liveboard.arrivals)
    assert not hasattr(liveboard.arrivals[0], "occupancy")
    assert mock_get.call_args.kwargs["params"]["arrdep"] == "arrival"


@patch("pyrail.irail.ClientSession.get")
@pytest.mark.parametrize("departures", [{"number": "0"}, {"number": "0", "departure": []}])
async def test_get_liveboard_without_departures(mock_get, departures, caplog):
    """A liveboard with no departures is a valid answer: an empty list, and no warning is logged."""
    data = {**_load_example("liveboard.json"), "departures": departures}
    mock_get.return_value.__aenter__.return_value = _mock_response(data=data)

    async with iRail() as api:
        with caplog.at_level("WARNING", logger="pyrail.irail"):
            liveboard = await api.get_liveboard("Brussels-South")

    assert liveboard is not None
    assert liveboard.departures == []
    assert not caplog.records


@patch("pyrail.irail.ClientSession.get")
async def test_get_liveboard_by_id(mock_get):
    """A liveboard can be requested by station id instead of name, but not both."""
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("liveboard.json"))

    async with iRail() as api:
        liveboard = await api.get_liveboard(id="BE.NMBS.008813003")
        params = mock_get.call_args.kwargs["params"]
        assert liveboard is not None
        assert params["id"] == "BE.NMBS.008813003"
        assert "station" not in params

        with pytest.raises(ValueError, match="Exactly one of the XOR parameters"):
            await api.get_liveboard(station="Brussels-Central", id="BE.NMBS.008813003")
        with pytest.raises(ValueError, match="Exactly one of the XOR parameters"):
            await api.get_liveboard()


@patch("pyrail.irail.ClientSession.get")
async def test_get_liveboard_alerts_parameter(mock_get):
    """The alerts flag is sent as 'true' or 'false' and does not change how the response is read."""
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("liveboard.json"))

    async with iRail() as api:
        default = await api.get_liveboard("Brussels-Central")
        assert mock_get.call_args.kwargs["params"]["alerts"] == "false"
        with_alerts = await api.get_liveboard("Brussels-Central", alerts=True)
        assert mock_get.call_args.kwargs["params"]["alerts"] == "true"

    assert default == with_alerts


@patch("pyrail.irail.ClientSession.get")
async def test_get_connections(mock_get):
    """Test the get_connections endpoint.

    Verifies that:
    - The response is not None
    - The response is a ConnectionsApiResponse object
    - The response contains a 'connections' key
    - The connection list is non-empty
    """
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("connections.json"))

    async with iRail() as api:
        connections = await api.get_connections("Antwerpen-Centraal", "Brussel-Centraal")

        assert connections is not None, "The response should not be None"

        assert isinstance(connections, ConnectionsApiResponse), (
            "Expected response to be a ConnectionsApiResponse object"
        )

        connection_list = connections.connections
        assert isinstance(connection_list, list), "Expected 'connection' to be a list"
        assert len(connection_list) > 0, "Expected at least one connection in the response"
        assert isinstance(connection_list[0], ConnectionDetails), (
            "Expected the first connection to be a ConnectionDetails object"
        )


@patch("pyrail.irail.ClientSession.get")
async def test_get_connections_timesel_and_type_of_transport(mock_get):
    """The time selection and transport filter are sent to the API as given."""
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("connections.json"))

    async with iRail() as api:
        assert await api.get_connections("Antwerpen-Centraal", "Brussel-Centraal", timesel="arrival")
        params = mock_get.call_args.kwargs["params"]
        assert params["timesel"] == "arrival"
        assert params["typeOfTransport"] == "automatic"

        for type_of_transport in ["automatic", "trains", "no_international_trains", "all"]:
            await api.get_connections("Brussel-Zuid", "Paris-Nord", type_of_transport=type_of_transport)
            assert mock_get.call_args.kwargs["params"]["typeOfTransport"] == type_of_transport


@patch("pyrail.irail.ClientSession.get")
async def test_fixed_value_parameters_reject_unknown_values(mock_get):
    """Values the API would silently replace by a default are rejected before any request is sent."""
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("connections.json"))

    async with iRail() as api:
        with pytest.raises(ValueError, match="Invalid typeOfTransport"):
            await api._do_request("connections", {"from": "A", "to": "B", "typeOfTransport": "nointernationaltrains"})
        with pytest.raises(ValueError, match="Invalid typeOfTransport"):
            await api._do_request("connections", {"from": "A", "to": "B", "typeOfTransport": "Trains"})
        with pytest.raises(ValueError, match="Invalid timesel"):
            await api._do_request("connections", {"from": "A", "to": "B", "timesel": "arrivals"})
        with pytest.raises(ValueError, match="Invalid arrdep"):
            await api._do_request("liveboard", {"station": "Brussels-Central", "arrdep": "arrivals"})

    mock_get.assert_not_called()


@patch("pyrail.irail.ClientSession.get")
async def test_get_vehicle(mock_get):
    """Test the get_vehicle endpoint.

    Verifies that:
    - The response is not None
    - The response is a VehicleApiResponse object
    - The response contains a 'vehicle' key
    - The vehicle list is non-empty
    """
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("vehicle.json"))

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


@patch("pyrail.irail.ClientSession.get")
async def test_get_composition(mock_get):
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
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("composition.json"))

    async with iRail() as api:
        composition = await api.get_composition("S102092")

        assert composition is not None, "The response should not be None"
        assert isinstance(composition, CompositionApiResponse), (
            "Expected response to be a CompositionApiResponse object"
        )

        segments = composition.composition
        assert isinstance(segments, list), "Expected 'segments' to be a list"
        assert len(segments) > 0, "Expected at least one segment"

        segment = segments[0]
        assert isinstance(segment.origin, StationDetails), "Expected origin to be a StationDetails object"
        assert isinstance(segment.destination, StationDetails), "Expected destination to be a StationDetails object"

        units = segment.composition.units
        assert len(units) > 0, "Expected at least one unit"

        unit = units[0]
        assert isinstance(unit.has_toilets, bool), "Expected 'has_toilets' to be a boolean"
        assert isinstance(unit.seats_first_class, int), "Expected 'seats_first_class' to be an integer"
        assert isinstance(unit.length_in_meter, int), "Expected 'length_in_meter' to be an integer"
        assert isinstance(unit.material_number, str | None), "Expected 'material_number' to be a string or None"
        assert isinstance(unit.material_sub_type_name, str | None), (
            "Expected 'material_sub_type_name' to be a string or None"
        )
        assert isinstance(unit.has_tables, bool | None), "Expected 'has_tables' to be a boolean or None"
        assert isinstance(unit.has_luggage_section, bool | None), (
            "Expected 'has_luggage_section' to be a boolean or None"
        )


@patch("pyrail.irail.ClientSession.get")
async def test_get_disturbances(mock_get):
    """Test the get_disturbances endpoint.

    Verifies that:
    - The response is not None
    - The response is a DisturbancesApiResponse object
    - The response contains a 'disturbances' key
    - The disturbances list is non-empty
    - The disturbance has valid attributes
    """
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("disturbances.json"))

    async with iRail() as api:
        disturbances = await api.get_disturbances()

        assert disturbances is not None, "The response should not be None"
        assert isinstance(disturbances, DisturbancesApiResponse), (
            "Expected response to be a DisturbancesApiResponse object"
        )
        assert isinstance(disturbances.disturbances, list), "Expected 'disturbances' to be a list"

        if len(disturbances.disturbances) > 0:
            disturbance = disturbances.disturbances[0]
            assert isinstance(disturbance.title, str), "Expected 'title' to be a string"
            assert isinstance(disturbance.description, str), "Expected 'description' to be a string"
            assert disturbance.type in DisturbanceType, "Expected 'type' to be 'disturbance' or 'planned'"


async def test_date_time_validation():
    """Test that accepted dates and times pass validation and invalid ones raise ValueError."""
    async with iRail() as api:
        api._validate_date("150923")
        api._validate_date("010124")
        api._validate_date(None)
        api._validate_date("290224")

        for date in ["320923", "151323", "abcdef", "15092023", "0", "290223", ""]:
            with pytest.raises(ValueError, match="Invalid date format"):
                api._validate_date(date)

        api._validate_time("1430")
        api._validate_time("0000")
        api._validate_time("2359")
        api._validate_time(None)
        api._validate_time("0001")

        for time in ["2460", "2361", "abcd", "143000", "1", ""]:
            with pytest.raises(ValueError, match="Invalid time format"):
                api._validate_time(time)


@patch("pyrail.irail.ClientSession.get")
async def test_liveboard_with_date_time(mock_get):
    """Test liveboard request with date and time parameters."""
    mock_get.return_value.__aenter__.return_value = _mock_response(data=_load_example("liveboard.json"))
    async with iRail() as api:
        result = await api.get_liveboard(
            station="Brussels-Central",
            date=datetime.now().strftime("%d%m%y"),
            time="1430",
        )
        assert result is not None

        result = await api.get_liveboard(
            station="Brussels-Central",
            date=(datetime.now() + timedelta(days=1)).strftime("%d%m%y"),
        )
        assert result is not None

        with pytest.raises(ValueError, match="Invalid date format"):
            await api.get_liveboard(
                station="Brussels-Central",
                date="320923",
            )

        with pytest.raises(ValueError, match="Invalid time format"):
            await api.get_liveboard(
                station="Brussels-Central",
                time="2460",
            )

    assert mock_get.call_count == 2


@patch("pyrail.irail.ClientSession.get")
async def test_error_handling(mock_get):
    """Test error handling for various API endpoints.

    Verifies that:
    - A NotFoundError is raised for each tested endpoint when the API returns a 404
    """
    mock_get.return_value.__aenter__.return_value = _mock_response(status=404)

    async with iRail() as api:
        with pytest.raises(NotFoundError):
            await api.get_vehicle("INVALID_ID")

        with pytest.raises(NotFoundError):
            await api.get_liveboard("INVALID_STATION")

        with pytest.raises(NotFoundError):
            await api.get_composition("INVALID_TRAIN")

        with pytest.raises(NotFoundError):
            await api.get_connections("InvalidStation1", "InvalidStation2")


def test_timestamp_to_datetime():
    """Test the timestamp_to_datetime function."""
    assert _timestamp_to_datetime("1705593600") == datetime(2024, 1, 18, 16, 0, tzinfo=UTC)
    assert _timestamp_to_datetime("0") == datetime(1970, 1, 1, 0, 0, tzinfo=UTC)


def test_timestamp_field_deserialization():
    """Test timestamp field deserialization in various models."""
    api_response = ApiResponse.from_dict({"version": "1.0", "timestamp": "1705593600"})
    assert api_response.timestamp == datetime(2024, 1, 18, 16, 0, tzinfo=UTC)

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
    assert departure.time == datetime(2024, 1, 18, 16, 0, tzinfo=UTC)

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
    assert alert.start_time == datetime(2024, 1, 18, 16, 0, tzinfo=UTC)
    assert alert.end_time == datetime(2024, 1, 18, 17, 0, tzinfo=UTC)

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
    assert disturbance.timestamp == datetime(2024, 1, 18, 16, 0, tzinfo=UTC)


def test_str_to_bool():
    """Test the str_to_bool function that converts string values to boolean."""
    assert _str_to_bool("1") is True, "String '1' should convert to True"
    assert _str_to_bool("0") is False, "String '0' should convert to False"


def test_unit_optional_field_deserialization():
    """Test deserialization of the optional composition unit fields against the recorded example."""
    example = _load_example("composition.json")
    segment = example["composition"]["segments"]["segment"][0]
    unit_data = deepcopy(segment["composition"]["units"]["unit"][0])

    assert "materialNumber" in unit_data, "Expected the recorded unit to carry materialNumber"
    assert "materialSubTypeName" in unit_data, "Expected the recorded unit to carry materialSubTypeName"

    unit = Unit.from_dict(unit_data)
    assert unit.material_number == unit_data["materialNumber"], (
        "Expected 'material_number' to read the materialNumber key"
    )
    assert unit.material_sub_type_name == unit_data["materialSubTypeName"], (
        "Expected 'material_sub_type_name' to read the materialSubTypeName key"
    )
    assert unit.has_tables is None, "Expected 'has_tables' to default to None when absent"
    assert unit.has_luggage_section is None, "Expected 'has_luggage_section' to default to None when absent"

    unit_data["hasTables"] = "1"
    unit_data["hasLuggageSection"] = "0"
    unit = Unit.from_dict(unit_data)
    assert unit.has_tables is True, "Expected 'has_tables' to be True when '1'"
    assert unit.has_luggage_section is False, "Expected 'has_luggage_section' to be False when '0'"


def test_boolean_field_deserialization():
    """Test the deserialization of boolean fields in models."""
    platform = PlatformInfo.from_dict({"name": "1", "normal": "1"})
    assert platform.normal is True, "Platform normal field should be True when '1'"

    platform = PlatformInfo.from_dict({"name": "1", "normal": "0"})
    assert platform.normal is False, "Platform normal field should be False when '0'"

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
            "time": "1705593600",
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

    assert departure.canceled is True, "Departure canceled field should be True when '1'"
    assert departure.left is False, "Departure left field should be False when '0'"
    assert departure.is_extra is True, "Departure is_extra field should be True when '1'"
    assert departure.platform_info.normal is True, "Platform normal field should be True when '1'"


def test_liveboard_arrival_boolean_deserialization():
    """Test that LiveboardArrival boolean fields convert '0' and '1' strings."""
    arrival_data = {
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
        "time": "1705593600",
        "delay": 0,
        "canceled": "0",
        "arrived": "0",
        "isExtra": "0",
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
        "departureConnection": "1",
    }
    arrival = LiveboardArrival.from_dict(arrival_data)
    assert arrival.canceled is False
    assert arrival.arrived is False
    assert arrival.is_extra is False
    arrival_data["canceled"] = "1"
    arrival_data["arrived"] = "1"
    arrival_data["isExtra"] = "1"
    arrival = LiveboardArrival.from_dict(arrival_data)
    assert arrival.canceled is True
    assert arrival.arrived is True
    assert arrival.is_extra is True


async def test_handle_success_response_empty():
    """Test that empty response bodies raise InvalidResponseError."""
    api = iRail()
    response = AsyncMock()
    response.headers = {}
    response.json = AsyncMock(return_value=None)
    with pytest.raises(InvalidResponseError, match="empty") as exc_info:
        await api._handle_success_response(response, "stations")
    assert exc_info.value.status == 200
    response.json = AsyncMock(return_value={})
    with pytest.raises(InvalidResponseError, match="empty"):
        await api._handle_success_response(response, "stations")


@patch("pyrail.irail.ClientSession.get")
async def test_handle_response_bad_request(mock_get):
    """Test that a 400 response raises an InvalidRequestError."""
    mock_get.return_value.__aenter__.return_value = _mock_response(status=400)
    async with iRail() as api:
        with pytest.raises(InvalidRequestError):
            await api._do_request("stations")


@patch("pyrail.irail.ClientSession.get")
async def test_bad_request_uses_error_field_from_json_body(mock_get):
    """Test that the InvalidRequestError message is the 'error' field of a JSON error body."""
    mock_get.return_value.__aenter__.return_value = _mock_response(
        status=400, data={"error": "Missing required parameter: station"}
    )
    async with iRail() as api:
        with pytest.raises(InvalidRequestError, match="Missing required parameter: station"):
            await api._do_request("stations")


@patch("pyrail.irail.ClientSession.get")
async def test_bad_request_falls_back_to_response_text(mock_get):
    """Test that the InvalidRequestError message falls back to the raw text when the body is not JSON."""
    response = _mock_response(status=400)
    response.text.return_value = "Bad Request"
    response.json.side_effect = ValueError("not json")
    mock_get.return_value.__aenter__.return_value = response
    async with iRail() as api:
        with pytest.raises(InvalidRequestError, match="Bad Request"):
            await api._do_request("stations")


@patch("pyrail.irail.ClientSession.get")
async def test_not_found_uses_response_text_as_message(mock_get):
    """Test that the NotFoundError message is the response text."""
    response = _mock_response(status=404)
    response.text.return_value = "Station not found"
    mock_get.return_value.__aenter__.return_value = response
    async with iRail() as api:
        with pytest.raises(NotFoundError, match="Station not found"):
            await api._do_request("stations")


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_handle_response_rate_limited(mock_get, mock_sleep):
    """Test that a 429 response raises a RateLimitError immediately, carrying Retry-After."""
    mock_get.return_value.__aenter__.return_value = _mock_response(status=429, headers={"Retry-After": "7"})
    async with iRail() as api:
        with pytest.raises(RateLimitError) as exc_info:
            await api._do_request("stations")
    assert exc_info.value.retry_after == 7
    mock_sleep.assert_not_called()
    assert mock_get.call_count == 1


@patch("pyrail.irail.ClientSession.get")
async def test_handle_response_rate_limited_without_retry_after(mock_get):
    """Test that a 429 without a usable Retry-After header leaves retry_after unset."""
    mock_get.return_value.__aenter__.return_value = _mock_response(status=429, headers={"Retry-After": "soon"})
    async with iRail() as api:
        with pytest.raises(RateLimitError) as exc_info:
            await api._do_request("stations")
    assert exc_info.value.retry_after is None


def test_parse_retry_after():
    """Test parsing Retry-After given as seconds, as an HTTP date, and as invalid input."""
    in_30s = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    in_the_past = format_datetime(datetime.now(UTC) - timedelta(seconds=30), usegmt=True)
    assert _parse_retry_after("5") == 5
    assert _parse_retry_after("-3") == 0
    assert _parse_retry_after(in_30s) in range(28, 31)
    assert _parse_retry_after(in_the_past) == 0
    assert _parse_retry_after("soon") is None
    assert _parse_retry_after(None) is None


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_handle_response_server_error(mock_get, mock_sleep):
    """Test that a persistent 5xx response is retried and then raises ApiUnavailableError."""
    mock_get.return_value.__aenter__.return_value = _mock_response(status=500)
    async with iRail() as api:
        with pytest.raises(ApiUnavailableError):
            await api._do_request("stations")
    assert mock_get.call_count == 3


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_handle_response_unexpected_status(mock_get, mock_sleep):
    """Test that an unexpected non-5xx status code raises InvalidResponseError without retrying."""
    mock_get.return_value.__aenter__.return_value = _mock_response(status=403)
    async with iRail() as api:
        with pytest.raises(InvalidResponseError, match="unexpected status 403") as exc_info:
            await api._do_request("stations")
    assert exc_info.value.status == 403
    assert mock_get.call_count == 1
    mock_sleep.assert_not_called()


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_request_client_error(mock_get, mock_sleep):
    """Test that a persistent client error is retried and then raises ApiUnavailableError."""
    mock_get.side_effect = ClientError("connection failed")
    async with iRail() as api:
        with pytest.raises(ApiUnavailableError):
            await api._do_request("stations")
    assert mock_get.call_count == 3


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_retry_on_network_error(mock_get, mock_sleep):
    """Test that network errors are retried until the request succeeds."""
    mock_get.side_effect = [
        ClientError("Connection failed"),
        ClientError("Timeout"),
        AsyncMock(__aenter__=AsyncMock(return_value=_mock_response(data={"data": "success_after_retry"}))),
    ]
    async with iRail() as api:
        assert await api._do_request("stations") == {"data": "success_after_retry"}
    assert mock_get.call_count == 3
    assert mock_sleep.call_count == 2


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_retry_on_server_error(mock_get, mock_sleep):
    """Test that a 5xx response is retried until the request succeeds."""
    mock_get.return_value.__aenter__.side_effect = [
        _mock_response(status=500),
        _mock_response(data={"data": "success_after_server_error"}),
    ]
    async with iRail() as api:
        assert await api._do_request("stations") == {"data": "success_after_server_error"}
    assert mock_get.call_count == 2


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_retry_logs_each_failed_attempt(mock_get, mock_sleep, caplog):
    """Test that every failed attempt is logged and the final failure is reported."""
    mock_get.side_effect = ClientError("Persistent network error")
    async with iRail() as api:
        with caplog.at_level(logging.WARNING), pytest.raises(ApiUnavailableError):
            await api._do_request("stations")
    assert mock_get.call_count == 3
    assert caplog.text.count("retrying in") == 2
    assert "failed after 3 attempt(s)" in caplog.text


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_api_unavailable_error_is_chained(mock_get, mock_sleep):
    """Test that ApiUnavailableError is a PyRailError chained to the underlying failure."""
    mock_get.side_effect = TimeoutError("too slow")
    async with iRail() as api:
        with pytest.raises(PyRailError) as exc_info:
            await api._do_request("stations")
    assert isinstance(exc_info.value, ApiUnavailableError)
    assert isinstance(exc_info.value.__cause__, TimeoutError)
    assert "stations" in str(exc_info.value)
    assert "TimeoutError: too slow" in str(exc_info.value)


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_retry_backoff_delays(mock_get, mock_sleep):
    """Test that the delay doubles between attempts and is capped."""
    mock_get.side_effect = ClientError("down")
    async with iRail(max_retries=6) as api:
        api.tokens = api.burst_tokens = 99
        with pytest.raises(ApiUnavailableError):
            await api._do_request("stations")
    assert [call.args[0] for call in mock_sleep.call_args_list] == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_retry_on_timeout(mock_get, mock_sleep):
    """Test that a request timeout is retried like a network error."""
    mock_get.side_effect = [
        TimeoutError(),
        AsyncMock(__aenter__=AsyncMock(return_value=_mock_response(data={"data": "after_timeout"}))),
    ]
    async with iRail() as api:
        assert await api._do_request("stations") == {"data": "after_timeout"}
    assert mock_get.call_count == 2


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_max_retries_zero_disables_retrying(mock_get, mock_sleep):
    """Test that max_retries=0 makes a single attempt."""
    mock_get.side_effect = ClientError("down")
    async with iRail(max_retries=0) as api:
        with pytest.raises(ApiUnavailableError):
            await api._do_request("stations")
    assert mock_get.call_count == 1
    mock_sleep.assert_not_called()


def test_negative_max_retries_rejected():
    """Test that a negative max_retries is rejected."""
    with pytest.raises(ValueError):
        iRail(max_retries=-1)


def test_invalid_language_rejected():
    """Test that an unsupported language raises ValueError instead of falling back to English."""
    with pytest.raises(ValueError, match="Invalid language"):
        iRail(lang="xx")
    api = iRail(lang="nl")
    with pytest.raises(ValueError, match="Invalid language"):
        api.lang = "xx"
    assert api.lang == "nl"


def test_validate_params_rejects_bad_requests():
    """Test that unknown endpoints, missing required parameters and unexpected parameters raise ValueError."""
    api = iRail()
    with pytest.raises(ValueError, match="Unknown API endpoint"):
        api._validate_params("unknown", {})
    with pytest.raises(ValueError, match="Missing required parameter"):
        api._validate_params("connections", {"from": "A"})
    with pytest.raises(ValueError, match="Unexpected parameter"):
        api._validate_params("disturbances", {"unexpected": True})


def test_non_positive_request_timeout_rejected():
    """Test that a request_timeout of zero or less is rejected."""
    with pytest.raises(ValueError, match="request_timeout"):
        iRail(request_timeout=0)
    with pytest.raises(ValueError, match="request_timeout"):
        iRail(request_timeout=-1)


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_request_timeout_is_retried_then_raises(mock_get, mock_sleep):
    """Test that an attempt exceeding request_timeout is retried and then raises ApiUnavailableError."""
    hang = asyncio.Event()
    response = _mock_response()
    response.json = AsyncMock(side_effect=hang.wait)
    mock_get.return_value.__aenter__.return_value = response
    async with iRail(request_timeout=0.01) as api:
        with pytest.raises(ApiUnavailableError) as exc_info:
            await api._do_request("stations")
    assert mock_get.call_count == 3
    assert isinstance(exc_info.value.__cause__, TimeoutError)


@patch("pyrail.irail.ClientSession.get")
async def test_deserialization_failure_raises_invalid_response(mock_get):
    """Test that a body that does not match the models raises InvalidResponseError."""
    mock_get.return_value.__aenter__.return_value = _mock_response(data={"unexpected": True})
    async with iRail() as api:
        with pytest.raises(InvalidResponseError, match="does not match the expected model"):
            await api.get_stations()


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_every_retry_attempt_uses_a_rate_limit_token(mock_get, mock_sleep):
    """Test that retries pass through the rate limiter instead of bypassing it."""
    mock_get.side_effect = ClientError("down")
    async with iRail() as api:
        with (
            patch.object(api, "_handle_rate_limit", new_callable=AsyncMock) as mock_rate_limit,
            pytest.raises(ApiUnavailableError),
        ):
            await api._do_request("stations")
    assert mock_rate_limit.call_count == 3


@patch("pyrail.irail.asyncio.sleep", new_callable=AsyncMock)
@patch("pyrail.irail.ClientSession.get")
async def test_no_retry_on_client_error_status(mock_get, mock_sleep):
    """Test that 4xx responses are raised immediately without retrying."""
    mock_get.return_value.__aenter__.return_value = _mock_response(status=404)
    async with iRail() as api:
        with pytest.raises(NotFoundError):
            await api._do_request("stations")
    assert mock_get.call_count == 1


@patch("pyrail.irail.ClientSession.get")
async def test_etag_caching(mock_get):
    """Test that an ETag from a 200 response is cached and sent as If-None-Match, and a 304 returns None."""
    etag = '"abc123"'
    mock_get.return_value.__aenter__.side_effect = [
        _mock_response(data={"data": "some_data"}, headers={"Etag": etag}),
        _mock_response(status=304),
    ]
    async with iRail() as api:
        assert await api._do_request("stations") == {"data": "some_data"}
        assert api.etag_cache == {"stations": etag}
        assert await api._do_request("stations") is None
    assert mock_get.call_count == 2
    assert "If-None-Match" not in mock_get.call_args_list[0].kwargs["headers"]
    assert mock_get.call_args_list[1].kwargs["headers"]["If-None-Match"] == etag


@patch("pyrail.irail.ClientSession.get")
async def test_handle_success_response_invalid_json(mock_get):
    """Test that a body that fails to parse as JSON raises InvalidResponseError."""
    response = _mock_response()
    response.json.side_effect = ValueError("invalid json")
    mock_get.return_value.__aenter__.return_value = response
    async with iRail() as api:
        with pytest.raises(InvalidResponseError, match="not valid JSON"):
            await api._do_request("stations")


def test_package_exposes_version() -> None:
    """The package exposes its installed version as a string."""
    import pyrail

    assert isinstance(pyrail.__version__, str)
    assert pyrail.__version__
