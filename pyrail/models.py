"""Module defining data models for the pyrail application."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from mashumaro import field_options
from mashumaro.mixins.orjson import DataClassORJSONMixin


def _timestamp_to_datetime(timestamp: str) -> datetime:
    """Convert an epoch timestamp to a datetime object."""
    return datetime.fromtimestamp(int(timestamp))


def _str_to_bool(strbool: str) -> bool:
    """Convert a string ("0" or "1") to a boolean."""
    return strbool == "1"


class DisturbanceType(Enum):
    """Enum for the type of disturbance, either 'disturbance' or 'planned'."""

    DISTURBANCE = "disturbance"
    PLANNED = "planned"


class OccupancyName(Enum):
    """Enum for the occupancy, either 'low', 'medium', 'high', or 'unknown'."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class Orientation(Enum):
    """Enum for the orientation of the material type of a train unit, either 'LEFT' or 'RIGHT'."""

    LEFT = "LEFT"
    RIGHT = "RIGHT"


@dataclass
class ApiResponse(DataClassORJSONMixin):
    """Base class for API responses, including schema version and timestamp."""

    version: str  # Version of the response schema
    timestamp: datetime = field(metadata=field_options(deserialize=_timestamp_to_datetime))  # Timestamp of the response


@dataclass
class StationDetails(DataClassORJSONMixin):
    """Represents a single railway station with location and naming attributes."""

    at_id: str = field(metadata=field_options(alias="@id"))  # Corresponds to "@id" in the schema
    id: str  # The (iRail) ID of the station
    name: str  # Default name of the station
    longitude: float = field(metadata=field_options(alias="locationX"))  # Longitude of the station
    latitude: float = field(metadata=field_options(alias="locationY"))  # Latitude of the station
    standard_name: str = field(metadata=field_options(alias="standardname"))  # Consistent name of the station


@dataclass
class StationsApiResponse(ApiResponse):
    """Holds a list of station objects returned by the 'stations' endpoint."""

    stations: list[StationDetails] = field(
        metadata=field_options(alias="station"), default_factory=list
    )  # List of stations information


@dataclass
class VehicleInfo(DataClassORJSONMixin):
    """Represents information about a specific vehicle, including name and location."""

    name: str  # Name of the vehicle
    short_name: str = field(metadata=field_options(alias="shortname"))  # Shortened name of the vehicle
    number: str  # Number of the vehicle
    type: str  # Type of vehicle (e.g., IC, EC)
    longitude: float = field(metadata=field_options(alias="locationX"))  # Longitude of the vehicle
    latitude: float = field(metadata=field_options(alias="locationY"))  # Latitude of the vehicle
    at_id: str = field(metadata=field_options(alias="@id"))  # ID of the vehicle


@dataclass
class PlatformInfo(DataClassORJSONMixin):
    """Details about the platform, such as name and whether it is the normal one."""

    name: str  # Platform name
    normal: bool = field(metadata=field_options(deserialize=_str_to_bool))  # Whether it is the normal platform


@dataclass
class Occupancy(DataClassORJSONMixin):
    """Represents occupancy details for a specific departure."""

    at_id: str = field(metadata=field_options(alias="@id"))  # Identifier for the occupancy level
    name: OccupancyName  # Occupancy level (e.g., low, high)


@dataclass
class LiveboardDeparture(DataClassORJSONMixin):
    """Details of a single departure in the liveboard response."""

    id: str  # ID of the departure
    station: str  # Station name
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))  # Detailed station info
    time: datetime = field(metadata=field_options(deserialize=_timestamp_to_datetime))  # Departure time (timestamp)
    delay: int  # Delay in seconds
    canceled: bool = field(metadata=field_options(deserialize=_str_to_bool))  # Whether the departure is canceled
    left: bool = field(metadata=field_options(deserialize=_str_to_bool))  # Whether the train has left
    is_extra: bool = field(
        metadata=field_options(alias="isExtra", deserialize=_str_to_bool)
    )  # Whether the train is extra
    vehicle: str  # Vehicle identifier
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))  # Vehicle details
    platform: str  # Platform name
    platform_info: PlatformInfo = field(metadata=field_options(alias="platforminfo"))  # Detailed platform info
    occupancy: Occupancy  # Occupancy level
    departure_connection: str = field(metadata=field_options(alias="departureConnection"))  # Departure connection link


@dataclass
class LiveboardArrival(DataClassORJSONMixin):
    """Details of a single arrival in the liveboard response."""

    id: str  # ID of the arrival
    station: str  # Station name
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))  # Detailed station info
    time: datetime = field(metadata=field_options(deserialize=_timestamp_to_datetime))  # Arrival time (timestamp)
    delay: int  # Delay in seconds
    canceled: bool  # Whether the arrival is canceled
    arrived: bool  # Whether the train has arrived
    is_extra: bool = field(metadata=field_options(alias="isExtra"))  # Whether the train is extra
    vehicle: str  # Vehicle identifier
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))  # Vehicle details
    platform: str  # Platform name
    platform_info: PlatformInfo = field(metadata=field_options(alias="platforminfo"))  # Detailed platform info
    departure_connection: str = field(metadata=field_options(alias="departureConnection"))  # Departure connection link


@dataclass
class LiveboardApiResponse(ApiResponse):
    """Represents a liveboard response containing station details and departure/arrival information."""

    station: str  # Name of the station
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))  # Detailed station info
    departures: list[LiveboardDeparture] | None = field(default=None)  # Departures information
    arrivals: list[LiveboardArrival] | None = field(default=None)  # Arrivals information

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre-deserialization hook to safely flatten departures and arrivals."""
        # Safely flatten departures
        if "departures" in d and d["departures"] is not None:
            d["departures"] = d["departures"].get("departure", [])
        else:
            d["departures"] = None  # Set to None if missing or null

        # Safely flatten arrivals
        if "arrivals" in d and d["arrivals"] is not None:
            d["arrivals"] = d["arrivals"].get("arrival", [])
        else:
            d["arrivals"] = None  # Set to None if missing or null

        return d


@dataclass
class ConnectionStop(DataClassORJSONMixin):
    """Represents a single stop in a journey for connections."""

    id: str  # Stop ID
    station: str  # Station name
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))  # Detailed station info
    scheduled_arrival_time: datetime = field(
        metadata=field_options(alias="scheduledArrivalTime", deserialize=_timestamp_to_datetime)
    )  # Scheduled arrival time
    arrival_canceled: bool = field(
        metadata=field_options(alias="arrivalCanceled", deserialize=_str_to_bool)
    )  # Arrival cancellation status
    arrived: bool = field(metadata=field_options(deserialize=_str_to_bool))  # Arrival status
    scheduled_departure_time: datetime = field(
        metadata=field_options(alias="scheduledDepartureTime", deserialize=_timestamp_to_datetime)
    )  # Scheduled departure time
    arrival_delay: int = field(metadata=field_options(alias="arrivalDelay"))  # Arrival delay
    departure_delay: int = field(metadata=field_options(alias="departureDelay"))  # Departure delay
    departure_canceled: bool = field(
        metadata=field_options(alias="departureCanceled", deserialize=_str_to_bool)
    )  # Departure cancellation status
    left: bool = field(metadata=field_options(deserialize=_str_to_bool))  # Departure status
    is_extra_stop: bool = field(
        metadata=field_options(alias="isExtraStop", deserialize=_str_to_bool)
    )  # Whether the stop is an extra one
    platform: str  # Platform name
    platform_info: PlatformInfo = field(metadata=field_options(alias="platforminfo"))  # Detailed platform info


@dataclass
class Direction(DataClassORJSONMixin):
    """Represents the direction of a train connection."""

    name: str  # Direction name


@dataclass
class ConnectionDeparture(DataClassORJSONMixin):
    """Details of a single departure in the connections response."""

    delay: int  # Delay in seconds
    station: str  # Station name
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))  # Detailed station info
    time: datetime = field(metadata=field_options(deserialize=_timestamp_to_datetime))  # Departure time (timestamp)
    vehicle: str  # Vehicle identifier
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))  # Vehicle details
    platform: str  # Platform name
    platform_info: PlatformInfo = field(metadata=field_options(alias="platforminfo"))  # Detailed platform info
    canceled: bool = field(metadata=field_options(deserialize=_str_to_bool))  # Whether the departure is canceled
    departure_connection: str = field(metadata=field_options(alias="departureConnection"))  # Departure connection link
    direction: Direction  # Direction of the connection
    left: bool = field(metadata=field_options(deserialize=_str_to_bool))  # Whether the train has left
    walking: bool = field(
        metadata=field_options(deserialize=_str_to_bool)
    )  # Indicates if the connection requires walking
    occupancy: Occupancy  # Occupancy level
    stops: list[ConnectionStop] = field(default_factory=list)  # List of stop along the journey

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Extract 'stop' list from 'stops' before deserialization."""
        d["stops"] = d["stops"]["stop"]
        return d


@dataclass
class ConnectionArrival(DataClassORJSONMixin):
    """Details of a single arrival, including timing, delay, and vehicle information."""

    delay: int  # Delay in seconds
    station: str  # Station name
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))  # Detailed station info
    time: datetime = field(metadata=field_options(deserialize=_timestamp_to_datetime))  # Arrival time (timestamp)
    vehicle: str  # Vehicle identifier
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))  # Vehicle details
    platform: str  # Platform name
    platform_info: PlatformInfo = field(metadata=field_options(alias="platforminfo"))  # Detailed platform info
    canceled: bool = field(metadata=field_options(deserialize=_str_to_bool))  # Whether the arrival is canceled
    direction: Direction  # Direction of the connection
    arrived: bool = field(metadata=field_options(deserialize=_str_to_bool))  # Whether the train has arrived
    walking: bool = field(
        metadata=field_options(deserialize=_str_to_bool)
    )  # Indicates if the connection requires walking
    departure_connection: str = field(metadata=field_options(alias="departureConnection"))  # Departure connection link


@dataclass
class Via(DataClassORJSONMixin):
    """Represents a single via station in a train connection."""

    id: str  # Via ID
    arrival: ConnectionArrival
    departure: ConnectionDeparture
    timebetween: int  # Time between arrival and departure (assuming in seconds)
    station: str  # Station name
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))  # Detailed station info
    vehicle: str  # Vehicle identifier
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))  # Vehicle details


@dataclass
class Remark(DataClassORJSONMixin):
    """Represents a single remark for a train connection, including type and content."""

    id: str  # Remark ID
    # Unsure about the content of a remark, so using a generic type for now
    content: str  # Remark content


@dataclass
class Alert(DataClassORJSONMixin):
    """Represents a single alert for a train connection, including type and content."""

    id: str  # Alert ID
    header: str  # Alert header
    description: str  # Alert description
    lead: str  # Alert lead
    start_time: datetime = field(
        metadata=field_options(alias="startTime", deserialize=_timestamp_to_datetime)
    )  # Start time of the alert
    end_time: datetime = field(
        metadata=field_options(alias="endTime", deserialize=_timestamp_to_datetime)
    )  # End time of the alert
    link: str | None = field(default=None)  # Link to more information


@dataclass
class ConnectionDetails(DataClassORJSONMixin):
    """Details of a single connection, including departure and arrival information."""

    id: str  # Connection ID
    departure: ConnectionDeparture  # Departure details
    arrival: ConnectionArrival  # Arrival details
    duration: int  # Duration of the connection in minutes
    remarks: list[Remark] = field(default_factory=list)  # List of remarks for the connection
    alerts: list[Alert] = field(default_factory=list)  # List of alerts for the connection
    vias: list[Via] | None = field(default=None)  # List of via details

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        # Extract 'remark' and 'alert' list from 'remarks' and 'alerts' before deserialization.
        d["remarks"] = d["remarks"]["remark"]
        d["alerts"] = d["alerts"]["alert"]

        # Safely flatten vias
        if "vias" in d and d["vias"] is not None:
            d["vias"] = d["vias"].get("via", [])
        else:
            d["vias"] = None  # Set to None if missing or null

        return d


@dataclass
class ConnectionsApiResponse(ApiResponse):
    """Holds a list of connections returned by the connections endpoint."""

    connections: list[ConnectionDetails] = field(
        metadata=field_options(alias="connection"), default_factory=list
    )  # List of connections


@dataclass
class VehicleStop(DataClassORJSONMixin):
    """Represents a single stop in a journey for vehicles."""

    id: str  # Stop ID
    station: str  # Station name
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))  # Detailed station info
    time: datetime = field(
        metadata=field_options(deserialize=_timestamp_to_datetime)
    )  # Scheduled stop time (timestamp)
    platform: str  # Platform name
    platform_info: PlatformInfo = field(metadata=field_options(alias="platforminfo"))  # Detailed platform info
    scheduled_departure_time: datetime = field(
        metadata=field_options(alias="scheduledDepartureTime", deserialize=_timestamp_to_datetime)
    )  # Scheduled departure time
    scheduled_arrival_time: datetime = field(
        metadata=field_options(alias="scheduledArrivalTime", deserialize=_timestamp_to_datetime)
    )  # Scheduled arrival time
    delay: int  # Delay in minutes
    canceled: bool = field(metadata=field_options(deserialize=_str_to_bool))  # Whether the stop is canceled
    departure_delay: int = field(metadata=field_options(alias="departureDelay"))  # Departure delay
    departure_canceled: bool = field(
        metadata=field_options(alias="departureCanceled", deserialize=_str_to_bool)
    )  # Departure cancellation status
    arrival_delay: int = field(metadata=field_options(alias="arrivalDelay"))  # Arrival delay
    arrival_canceled: bool = field(
        metadata=field_options(alias="arrivalCanceled", deserialize=_str_to_bool)
    )  # Arrival cancellation status
    left: bool = field(metadata=field_options(deserialize=_str_to_bool))  # Whether the train has left
    arrived: bool = field(metadata=field_options(deserialize=_str_to_bool))  # Whether the train has arrived
    is_extra_stop: bool = field(
        metadata=field_options(alias="isExtraStop", deserialize=_str_to_bool)
    )  # Whether this is an extra stop
    occupancy: Occupancy | None = field(default=None)  # Occupancy level, not present in last stop
    departure_connection: str | None = field(
        default=None, metadata=field_options(alias="departureConnection")
    )  # Departure connection link, not present in the last stop


@dataclass
class VehicleApiResponse(ApiResponse):
    """Provides detailed data about a particular vehicle, including a list of its stops."""

    vehicle: str  # Vehicle identifier
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))  # Vehicle information
    stops: list[VehicleStop] = field(default_factory=list)  # List of stop details

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Extract 'stop' list from 'stops' before deserialization."""
        d["stops"] = d["stops"]["stop"]
        return d


@dataclass
class MaterialType(DataClassORJSONMixin):
    """Represents the material type of a train unit."""

    parent_type: str  # Parent material type
    sub_type: str  # Sub material type
    orientation: Orientation  # Orientation of the material type


@dataclass
class Unit(DataClassORJSONMixin):
    """Represents a single train unit, including its type and location."""

    id: str  # Unit ID
    material_type: MaterialType = field(metadata=field_options(alias="materialType"))  # Material type of the unit
    has_toilets: bool = field(
        metadata=field_options(alias="hasToilets", deserialize=_str_to_bool)
    )  # Whether the unit has toilets
    has_second_class_outlets: bool = field(
        metadata=field_options(alias="hasSecondClassOutlets", deserialize=_str_to_bool)
    )  # Whether the unit has power outlets in second class
    has_first_class_outlets: bool = field(
        metadata=field_options(alias="hasFirstClassOutlets", deserialize=_str_to_bool)
    )  # Whether the unit has power outlets in first class
    has_heating: bool = field(
        metadata=field_options(alias="hasHeating", deserialize=_str_to_bool)
    )  # Whether the unit has heating
    has_airco: bool = field(
        metadata=field_options(alias="hasAirco", deserialize=_str_to_bool)
    )  # Whether the unit has air conditioning
    traction_type: str = field(metadata=field_options(alias="tractionType"))  # Traction type of the unit
    can_pass_to_next_unit: bool = field(
        metadata=field_options(alias="canPassToNextUnit", deserialize=_str_to_bool)
    )  # Whether the unit can pass to the next
    seats_first_class: int = field(metadata=field_options(alias="seatsFirstClass"))  # Number of seats in first class
    seats_coupe_first_class: int = field(
        metadata=field_options(alias="seatsCoupeFirstClass")
    )  # Number of seats in coupe in first class
    standing_places_first_class: int = field(
        metadata=field_options(alias="standingPlacesFirstClass")
    )  # Number of standing places in first class
    seats_second_class: int = field(metadata=field_options(alias="seatsSecondClass"))  # Number of seats in second class
    seats_coupe_second_class: int = field(
        metadata=field_options(alias="seatsCoupeSecondClass")
    )  # Number of seats in coupe in second class
    standing_places_second_class: int = field(
        metadata=field_options(alias="standingPlacesSecondClass")
    )  # Number of standing places in second class
    length_in_meter: int = field(metadata=field_options(alias="lengthInMeter"))  # Length of the unit in meters
    has_semi_automatic_interior_doors: bool = field(
        metadata=field_options(alias="hasSemiAutomaticInteriorDoors", deserialize=_str_to_bool)
    )  # Whether the unit has semi-automatic interior doors
    traction_position: int = field(metadata=field_options(alias="tractionPosition"))  # Traction position of the unit
    has_prm_section: bool = field(
        metadata=field_options(alias="hasPrmSection", deserialize=_str_to_bool)
    )  # Whether the unit has a PRM section
    has_priority_places: bool = field(
        metadata=field_options(alias="hasPriorityPlaces", deserialize=_str_to_bool)
    )  # Whether the unit has priority places
    has_bike_section: bool = field(
        metadata=field_options(alias="hasBikeSection", deserialize=_str_to_bool)
    )  # Whether the unit has a bike section


@dataclass
class SegmentComposition(DataClassORJSONMixin):
    """Describes a collection of train units and related metadata."""

    source: str  # Source of the composition
    units: list[Unit] = field(default_factory=list)  # List of units

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Extract 'unit' list from 'units' before deserialization."""
        d["units"] = d["units"]["unit"]
        return d


@dataclass
class Segment(DataClassORJSONMixin):
    """Defines a single segment within a journey, including composition details."""

    id: str  # ID of the segment
    origin: StationDetails  # Origin station information
    destination: StationDetails  # Destination station information
    composition: SegmentComposition  # Composition details of the segment


@dataclass
class CompositionApiResponse(ApiResponse):
    """Encapsulates the response containing composition details of a specific train."""

    composition: list[Segment] = field(default_factory=list)  # Composition details of the train

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre-deserialization hook to safely flatten composition segments."""
        d["composition"] = d["composition"]["segments"]["segment"]
        return d


@dataclass
class DescriptionLink(DataClassORJSONMixin):
    """Represents a single link within a disturbance description."""

    id: str  # Link ID
    link: str  # URL of the link
    text: str  # Text displayed for the link


@dataclass
class Disturbance(DataClassORJSONMixin):
    """Represents a railway system disturbance, including description and metadata."""

    id: str  # ID of the disturbance
    title: str  # Title of the disturbance
    description: str  # Description of the disturbance
    type: DisturbanceType  # Type of disturbance (e.g., "disturbance", "planned")
    link: str  # Link to more information
    timestamp: datetime = field(
        metadata=field_options(deserialize=_timestamp_to_datetime)
    )  # Timestamp of the disturbance
    richtext: str  # Rich-text description (HTML-like)
    description_links: list[DescriptionLink] = field(
        metadata=field_options(alias="descriptionLinks"), default_factory=list
    )  # List of description links

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Extract 'descriptionLink' list from 'descriptionLinks' before deserialization."""
        d["descriptionLinks"] = d["descriptionLinks"]["descriptionLink"]
        return d


@dataclass
class DisturbancesApiResponse(ApiResponse):
    """Encapsulates multiple disturbances returned by the disturbances endpoint."""

    disturbances: list[Disturbance] = field(
        metadata=field_options(alias="disturbance"), default_factory=list
    )  # List of disturbances
