"""Module defining data models for the pyrail application."""

from dataclasses import dataclass, field
from typing import List

from mashumaro import field_options
from mashumaro.mixins.orjson import DataClassORJSONMixin


@dataclass
class ApiResponse(DataClassORJSONMixin):
    """Base class for API responses, including schema version and timestamp."""

    version: str  # Version of the response schema
    timestamp: int  # Timestamp of the response


@dataclass
class Station(DataClassORJSONMixin):
    """Represents a single railway station with location and naming attributes."""

    id: str  # The (iRail) ID of the station
    at_id: str = field(metadata=field_options(alias="@id"))  # Corresponds to "@id" in the schema
    location_x: float = field(metadata=field_options(alias="locationX"))  # Longitude of the station
    location_y: float = field(metadata=field_options(alias="locationY"))  # Latitude of the station
    standard_name: str = field(metadata=field_options(alias="standardname"))  # Consistent name of the station
    name: str  # Default name of the station


@dataclass
class StationsApiResponse(ApiResponse):
    """Holds a list of station objects returned by the 'stations' endpoint."""

    stations: List[Station] = field(metadata=field_options(alias="station"))  # List of stations information


@dataclass
class Departures(DataClassORJSONMixin):
    number: int  # Number of departures
    departure: List[dict] = field(default_factory=list)  # List of departure details


@dataclass
class LiveboardResponse(ApiResponse):
    station: str  # Name of the station
    station_info: Station | None = field(
        metadata=field_options(alias="stationinfo")
    )  # Reusing the `Station` class for detailed station information
    departures: Departures  # Departures information


@dataclass
class VehicleInfo(DataClassORJSONMixin):
    name: str  # Name of the vehicle
    location_x: float = field(metadata=field_options(alias="locationX"))  # Longitude of the vehicle
    location_y: float = field(metadata=field_options(alias="locationY"))  # Latitude of the vehicle
    short_name: str = field(metadata=field_options(alias="shortname"))  # Shortened name of the vehicle
    at_id: str = field(metadata=field_options(alias="@id"))  # ID of the vehicle


@dataclass
class Stops(DataClassORJSONMixin):
    number: int  # Number of stops
    stop: List[dict] = field(default_factory=list)  # List of stop details


@dataclass
class VehicleResponse(ApiResponse):
    vehicle: str  # Vehicle identifier
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))  # Vehicle information
    stops: Stops  # Stops information


@dataclass
class SegmentComposition(DataClassORJSONMixin):
    source: str  # Source of the composition
    units: List[dict] = field(metadata=field_options(alias="unit"))  # List of units in the composition


@dataclass
class Segment(DataClassORJSONMixin):
    id: str  # ID of the segment
    origin: Station  # Origin station information
    destination: Station  # Destination station information
    composition: SegmentComposition  # Composition details of the segment


@dataclass
class CompositionSegments(DataClassORJSONMixin):
    number: int  # Number of segments
    segment: List[Segment] = field(metadata=field_options(alias="segment"))  # List of segments


@dataclass
class CompositionResponse(ApiResponse):
    composition: CompositionSegments  # Composition details


@dataclass
class Connection(DataClassORJSONMixin):
    departure: Station  # Departure station information
    arrival: Station  # Arrival station information
    departure_time: str = field(metadata=field_options(alias="departureTime"))  # Departure time in ISO format
    arrival_time: str = field(metadata=field_options(alias="arrivalTime"))  # Arrival time in ISO format
    duration: str  # Duration of the connection
    vehicles: List[str] = field(default_factory=list)  # List of vehicle identifiers
    departure_delay: int | None = field(
        metadata=field_options(alias="departureDelay"), default=None
    )  # Delay at departure in seconds
    arrival_delay: int | None = field(
        metadata=field_options(alias="arrivalDelay"), default=None
    )  # Delay at arrival in seconds


@dataclass
class ConnectionsResponse(ApiResponse):
    connection: List[Connection] = field(default_factory=list)  # List of connections


@dataclass
class Disturbance(DataClassORJSONMixin):
    id: str  # ID of the disturbance
    title: str  # Title of the disturbance
    description: str  # Description of the disturbance
    link: str  # Link to more information
    type: str  # Type of disturbance (e.g., "disturbance", "planned")
    timestamp: int  # Timestamp of the disturbance
    attachment: str | None = None  # Optional attachment URL


@dataclass
class DisturbancesResponse(ApiResponse):
    disturbance: List[Disturbance]  # List of disturbances
