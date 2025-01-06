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
    longitude: float = field(metadata=field_options(alias="locationX"))  # Longitude of the station
    latitude: float = field(metadata=field_options(alias="locationY"))  # Latitude of the station
    standard_name: str = field(metadata=field_options(alias="standardname"))  # Consistent name of the station
    name: str  # Default name of the station


@dataclass
class StationsApiResponse(ApiResponse):
    """Holds a list of station objects returned by the 'stations' endpoint."""

    stations: List[Station] = field(metadata=field_options(alias="station"))  # List of stations information


@dataclass
class VehicleInfo(DataClassORJSONMixin):
    """Represents information about a specific vehicle, including name and location."""

    name: str  # Name of the vehicle
    longitude: float = field(metadata=field_options(alias="locationX"))  # Longitude of the vehicle
    latitude: float = field(metadata=field_options(alias="locationY"))  # Latitude of the vehicle
    short_name: str = field(metadata=field_options(alias="shortname"))  # Shortened name of the vehicle
    at_id: str = field(metadata=field_options(alias="@id"))  # ID of the vehicle
    number: str  # Number of the vehicle
    type: str  # Type of vehicle (e.g., IC, EC)


@dataclass
class PlatformInfo(DataClassORJSONMixin):
    """Details about the platform, such as name and whether it is the normal one."""

    name: str  # Platform name
    normal: bool  # Whether it is the normal platform


@dataclass
class Occupancy(DataClassORJSONMixin):
    """Represents occupancy details for a specific departure."""

    at_id: str = field(metadata=field_options(alias="@id"))  # Identifier for the occupancy level
    name: str  # Occupancy level (e.g., low, high)


@dataclass
class Departure(DataClassORJSONMixin):
    """Details of a single departure, including timing, delay, and vehicle information."""

    id: str  # ID of the departure
    station: str  # Station name
    station_info: Station = field(metadata=field_options(alias="stationinfo"))  # Detailed station info
    time: int  # Departure time (timestamp)
    delay: int  # Delay in seconds
    canceled: bool  # Whether the departure is canceled
    left: bool  # Whether the train has left
    is_extra: bool = field(metadata=field_options(alias="isExtra"))  # Whether the train is extra
    vehicle: str  # Vehicle identifier
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))  # Vehicle details
    platform: str  # Platform name
    platform_info: PlatformInfo = field(metadata=field_options(alias="platforminfo"))  # Detailed platform info
    occupancy: Occupancy  # Occupancy level
    departure_connection: str = field(metadata=field_options(alias="departureConnection"))  # Departure connection link


@dataclass
class Departures(DataClassORJSONMixin):
    """Represents departures data for a railway station."""

    number: int  # Number of departures
    departure: List[Departure] = field(default_factory=list)  # List of departure details


@dataclass
class LiveboardApiResponse(ApiResponse):
    """Represents a liveboard response containing station details and departures."""

    station: str  # Name of the station
    station_info: Station = field(
        metadata=field_options(alias="stationinfo")
    )  # Reusing the `Station` class for detailed station information
    departures: Departures  # Departures information


@dataclass
class Stops(DataClassORJSONMixin):
    """Holds the number of stops and a list of detailed stop information."""

    number: int  # Number of stops
    stop: List[dict] = field(default_factory=list)  # List of stop details


@dataclass
class VehicleApiResponse(ApiResponse):
    """Provides detailed data about a particular vehicle, including its stops."""

    vehicle: str  # Vehicle identifier
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))  # Vehicle information
    stops: Stops  # Stops information


@dataclass
class SegmentComposition(DataClassORJSONMixin):
    """Describes a collection of train units and related metadata."""

    source: str  # Source of the composition
    units: List[dict] = field(metadata=field_options(alias="unit"))  # List of units in the composition


@dataclass
class Segment(DataClassORJSONMixin):
    """Defines a single segment within a journey, including composition details."""

    id: str  # ID of the segment
    origin: Station  # Origin station information
    destination: Station  # Destination station information
    composition: SegmentComposition  # Composition details of the segment


@dataclass
class CompositionSegments(DataClassORJSONMixin):
    """Represents multiple journey segments, each having its own composition details."""

    number: int  # Number of segments
    segment: List[Segment] = field(metadata=field_options(alias="segment"))  # List of segments


@dataclass
class CompositionApiResponse(ApiResponse):
    """Encapsulates the response containing composition details for a specific journey."""

    composition: CompositionSegments  # Composition details


@dataclass
class Connection(DataClassORJSONMixin):
    """Represents a single train connection, including scheduling and delay details."""

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
class ConnectionsApiResponse(ApiResponse):
    """Holds a list of train connections returned by the connections endpoint."""

    connection: List[Connection] = field(default_factory=list)  # List of connections


@dataclass
class Disturbance(DataClassORJSONMixin):
    """Represents a railway system disturbance, including description and metadata."""

    id: str  # ID of the disturbance
    title: str  # Title of the disturbance
    description: str  # Description of the disturbance
    link: str  # Link to more information
    type: str  # Type of disturbance (e.g., "disturbance", "planned")
    timestamp: int  # Timestamp of the disturbance
    attachment: str | None = None  # Optional attachment URL


@dataclass
class DisturbancesApiResponse(ApiResponse):
    """Encapsulates multiple disturbances returned by the disturbances endpoint."""

    disturbance: List[Disturbance]  # List of disturbances
