"""Data models for the iRail API responses.

Every list field has a default. The fields with a deserialization hook honor it:
a wrapper key that is absent, null or not a dict produces the default instead of
an error. The top-level station, connection and disturbance wrappers have no
hook, and a null value in one of them is an error. A wrapper key the hooks do
not recognise is not detected here, so the live smoke suite detects upstream
shape changes where it asserts data is present.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, override

from mashumaro import field_options
from mashumaro.mixins.orjson import DataClassORJSONMixin


def _timestamp_to_datetime(timestamp: str) -> datetime:
    """Convert an epoch timestamp to a datetime object."""
    return datetime.fromtimestamp(int(timestamp), UTC)


def _str_to_bool(strbool: str) -> bool:
    """Convert a string ("0" or "1") to a boolean.

    Raises:
        ValueError: If the value is neither '0' nor '1'.

    """
    if strbool not in ("0", "1"):
        msg = f"Expected '0' or '1', got: {strbool}"
        raise ValueError(msg)
    return strbool == "1"


class DisturbanceType(StrEnum):
    """Enum for the type of disturbance, either 'disturbance' or 'planned'."""

    DISTURBANCE = "disturbance"
    PLANNED = "planned"


class OccupancyName(StrEnum):
    """Enum for the occupancy, either 'low', 'medium', 'high', or 'unknown'."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class Orientation(StrEnum):
    """Enum for the orientation of the material type of a train unit, either 'LEFT' or 'RIGHT'."""

    LEFT = "LEFT"
    RIGHT = "RIGHT"


@dataclass(slots=True)
class ApiResponse(DataClassORJSONMixin):
    """Base class for API responses, including schema version and timestamp."""

    version: str
    timestamp: datetime = field(metadata=field_options(deserialize=_timestamp_to_datetime))


@dataclass(slots=True)
class StationDetails(DataClassORJSONMixin):
    """Represents a single railway station with location and naming attributes."""

    at_id: str = field(metadata=field_options(alias="@id"))
    id: str
    name: str
    longitude: float = field(metadata=field_options(alias="locationX"))
    latitude: float = field(metadata=field_options(alias="locationY"))
    standard_name: str = field(metadata=field_options(alias="standardname"))


@dataclass(slots=True)
class StationsApiResponse(ApiResponse):
    """Holds a list of station objects returned by the 'stations' endpoint."""

    stations: list[StationDetails] = field(metadata=field_options(alias="station"), default_factory=list)


@dataclass(slots=True)
class VehicleInfo(DataClassORJSONMixin):
    """Represents information about a specific vehicle, including name and location."""

    name: str
    short_name: str = field(metadata=field_options(alias="shortname"))
    number: str
    type: str
    longitude: float = field(metadata=field_options(alias="locationX"))
    latitude: float = field(metadata=field_options(alias="locationY"))
    at_id: str = field(metadata=field_options(alias="@id"))


@dataclass(slots=True)
class PlatformInfo(DataClassORJSONMixin):
    """Details about the platform, such as name and whether it is the normal one."""

    name: str
    normal: bool = field(metadata=field_options(deserialize=_str_to_bool))


@dataclass(slots=True)
class Occupancy(DataClassORJSONMixin):
    """Represents occupancy details for a specific departure."""

    at_id: str = field(metadata=field_options(alias="@id"))
    name: OccupancyName


@dataclass(slots=True)
class LiveboardDeparture(DataClassORJSONMixin):
    """Details of a single departure in the liveboard response. The delay is in seconds."""

    id: str
    station: str
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))
    time: datetime = field(metadata=field_options(deserialize=_timestamp_to_datetime))
    delay: int
    canceled: bool = field(metadata=field_options(deserialize=_str_to_bool))
    left: bool = field(metadata=field_options(deserialize=_str_to_bool))
    is_extra: bool = field(metadata=field_options(alias="isExtra", deserialize=_str_to_bool))
    vehicle: str
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))
    platform: str
    platform_info: PlatformInfo = field(metadata=field_options(alias="platforminfo"))
    occupancy: Occupancy
    departure_connection: str = field(metadata=field_options(alias="departureConnection"))


@dataclass(slots=True)
class LiveboardArrival(DataClassORJSONMixin):
    """Details of a single arrival in the liveboard response. The delay is in seconds."""

    id: str
    station: str
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))
    time: datetime = field(metadata=field_options(deserialize=_timestamp_to_datetime))
    delay: int
    canceled: bool = field(metadata=field_options(deserialize=_str_to_bool))
    arrived: bool = field(metadata=field_options(deserialize=_str_to_bool))
    is_extra: bool = field(metadata=field_options(alias="isExtra", deserialize=_str_to_bool))
    vehicle: str
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))
    platform: str
    platform_info: PlatformInfo = field(metadata=field_options(alias="platforminfo"))
    departure_connection: str = field(metadata=field_options(alias="departureConnection"))


@dataclass(slots=True)
class LiveboardApiResponse(ApiResponse):
    """Represents a liveboard response containing station details and departure/arrival information."""

    station: str
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))
    departures: list[LiveboardDeparture] | None = field(default=None)
    arrivals: list[LiveboardArrival] | None = field(default=None)

    @classmethod
    @override
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Flatten departures and arrivals before deserialization, honoring the field defaults."""
        d = d.copy()
        departures = d.get("departures")
        d["departures"] = departures.get("departure", []) if isinstance(departures, dict) else None
        arrivals = d.get("arrivals")
        d["arrivals"] = arrivals.get("arrival", []) if isinstance(arrivals, dict) else None
        return d


@dataclass(slots=True)
class ConnectionStop(DataClassORJSONMixin):
    """Represents a single stop in a journey for connections."""

    id: str
    station: str
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))
    scheduled_arrival_time: datetime = field(
        metadata=field_options(alias="scheduledArrivalTime", deserialize=_timestamp_to_datetime)
    )
    arrival_canceled: bool = field(metadata=field_options(alias="arrivalCanceled", deserialize=_str_to_bool))
    arrived: bool = field(metadata=field_options(deserialize=_str_to_bool))
    scheduled_departure_time: datetime = field(
        metadata=field_options(alias="scheduledDepartureTime", deserialize=_timestamp_to_datetime)
    )
    arrival_delay: int = field(metadata=field_options(alias="arrivalDelay"))
    departure_delay: int = field(metadata=field_options(alias="departureDelay"))
    departure_canceled: bool = field(metadata=field_options(alias="departureCanceled", deserialize=_str_to_bool))
    left: bool = field(metadata=field_options(deserialize=_str_to_bool))
    is_extra_stop: bool = field(metadata=field_options(alias="isExtraStop", deserialize=_str_to_bool))
    platform: str
    platform_info: PlatformInfo = field(metadata=field_options(alias="platforminfo"))


@dataclass(slots=True)
class Direction(DataClassORJSONMixin):
    """Represents the direction of a train connection."""

    name: str


@dataclass(slots=True)
class ConnectionDeparture(DataClassORJSONMixin):
    """Details of a single departure in the connections response. The delay is in seconds."""

    delay: int
    station: str
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))
    time: datetime = field(metadata=field_options(deserialize=_timestamp_to_datetime))
    vehicle: str
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))
    platform: str
    platform_info: PlatformInfo = field(metadata=field_options(alias="platforminfo"))
    canceled: bool = field(metadata=field_options(deserialize=_str_to_bool))
    departure_connection: str = field(metadata=field_options(alias="departureConnection"))
    direction: Direction
    left: bool = field(metadata=field_options(deserialize=_str_to_bool))
    walking: bool = field(metadata=field_options(deserialize=_str_to_bool))
    occupancy: Occupancy
    stops: list[ConnectionStop] = field(default_factory=list)

    @classmethod
    @override
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Extract the 'stop' list from 'stops' before deserialization, defaulting to an empty list."""
        d = d.copy()
        stops = d.get("stops")
        d["stops"] = stops.get("stop", []) if isinstance(stops, dict) else []
        return d


@dataclass(slots=True)
class ConnectionArrival(DataClassORJSONMixin):
    """Details of a single arrival, including timing, delay, and vehicle information. The delay is in seconds."""

    delay: int
    station: str
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))
    time: datetime = field(metadata=field_options(deserialize=_timestamp_to_datetime))
    vehicle: str
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))
    platform: str
    platform_info: PlatformInfo = field(metadata=field_options(alias="platforminfo"))
    canceled: bool = field(metadata=field_options(deserialize=_str_to_bool))
    direction: Direction
    arrived: bool = field(metadata=field_options(deserialize=_str_to_bool))
    walking: bool = field(metadata=field_options(deserialize=_str_to_bool))
    departure_connection: str = field(metadata=field_options(alias="departureConnection"))


@dataclass(slots=True)
class Via(DataClassORJSONMixin):
    """Represents a single via station in a train connection. The time between the arrival and the departure is in seconds."""

    id: str
    arrival: ConnectionArrival
    departure: ConnectionDeparture
    timebetween: int
    station: str
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))
    vehicle: str
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))


@dataclass(slots=True)
class Remark(DataClassORJSONMixin):
    """Represents a single remark for a train connection.

    The API does not document what a remark contains.
    """

    id: str
    content: str


@dataclass(slots=True)
class Alert(DataClassORJSONMixin):
    """Represents a single alert for a train connection."""

    id: str
    header: str
    description: str
    lead: str
    start_time: datetime = field(metadata=field_options(alias="startTime", deserialize=_timestamp_to_datetime))
    end_time: datetime = field(metadata=field_options(alias="endTime", deserialize=_timestamp_to_datetime))
    link: str | None = field(default=None)


@dataclass(slots=True)
class ConnectionDetails(DataClassORJSONMixin):
    """Details of a single connection, including departure and arrival information. The duration is in seconds."""

    id: str
    departure: ConnectionDeparture
    arrival: ConnectionArrival
    duration: int
    remarks: list[Remark] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    vias: list[Via] | None = field(default=None)

    @classmethod
    @override
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Flatten remarks, alerts and vias before deserialization, honoring the field defaults."""
        d = d.copy()
        remarks = d.get("remarks")
        d["remarks"] = remarks.get("remark", []) if isinstance(remarks, dict) else []
        alerts = d.get("alerts")
        d["alerts"] = alerts.get("alert", []) if isinstance(alerts, dict) else []
        vias = d.get("vias")
        d["vias"] = vias.get("via", []) if isinstance(vias, dict) else None
        return d


@dataclass(slots=True)
class ConnectionsApiResponse(ApiResponse):
    """Holds a list of connections returned by the connections endpoint."""

    connections: list[ConnectionDetails] = field(metadata=field_options(alias="connection"), default_factory=list)


@dataclass(slots=True)
class VehicleStop(DataClassORJSONMixin):
    """Represents a single stop in a journey for vehicles. Delays are in seconds."""

    id: str
    station: str
    station_info: StationDetails = field(metadata=field_options(alias="stationinfo"))
    time: datetime = field(metadata=field_options(deserialize=_timestamp_to_datetime))
    platform: str
    platform_info: PlatformInfo = field(metadata=field_options(alias="platforminfo"))
    scheduled_departure_time: datetime = field(
        metadata=field_options(alias="scheduledDepartureTime", deserialize=_timestamp_to_datetime)
    )
    scheduled_arrival_time: datetime = field(
        metadata=field_options(alias="scheduledArrivalTime", deserialize=_timestamp_to_datetime)
    )
    delay: int
    canceled: bool = field(metadata=field_options(deserialize=_str_to_bool))
    departure_delay: int = field(metadata=field_options(alias="departureDelay"))
    departure_canceled: bool = field(metadata=field_options(alias="departureCanceled", deserialize=_str_to_bool))
    arrival_delay: int = field(metadata=field_options(alias="arrivalDelay"))
    arrival_canceled: bool = field(metadata=field_options(alias="arrivalCanceled", deserialize=_str_to_bool))
    left: bool = field(metadata=field_options(deserialize=_str_to_bool))
    arrived: bool = field(metadata=field_options(deserialize=_str_to_bool))
    is_extra_stop: bool = field(metadata=field_options(alias="isExtraStop", deserialize=_str_to_bool))
    occupancy: Occupancy | None = field(default=None)
    departure_connection: str | None = field(default=None, metadata=field_options(alias="departureConnection"))


@dataclass(slots=True)
class VehicleApiResponse(ApiResponse):
    """Provides detailed data about a particular vehicle, including a list of its stops."""

    vehicle: str
    vehicle_info: VehicleInfo = field(metadata=field_options(alias="vehicleinfo"))
    stops: list[VehicleStop] = field(default_factory=list)

    @classmethod
    @override
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Extract the 'stop' list from 'stops' before deserialization, defaulting to an empty list."""
        d = d.copy()
        stops = d.get("stops")
        d["stops"] = stops.get("stop", []) if isinstance(stops, dict) else []
        return d


@dataclass(slots=True)
class MaterialType(DataClassORJSONMixin):
    """Represents the material type of a train unit."""

    parent_type: str
    sub_type: str
    orientation: Orientation


@dataclass(slots=True)
class Unit(DataClassORJSONMixin):
    """Represents a single train unit, including its material type."""

    id: str
    material_type: MaterialType = field(metadata=field_options(alias="materialType"))
    has_toilets: bool = field(metadata=field_options(alias="hasToilets", deserialize=_str_to_bool))
    has_second_class_outlets: bool = field(
        metadata=field_options(alias="hasSecondClassOutlets", deserialize=_str_to_bool)
    )
    has_first_class_outlets: bool = field(
        metadata=field_options(alias="hasFirstClassOutlets", deserialize=_str_to_bool)
    )
    has_heating: bool = field(metadata=field_options(alias="hasHeating", deserialize=_str_to_bool))
    has_airco: bool = field(metadata=field_options(alias="hasAirco", deserialize=_str_to_bool))
    can_pass_to_next_unit: bool = field(metadata=field_options(alias="canPassToNextUnit", deserialize=_str_to_bool))
    seats_first_class: int = field(metadata=field_options(alias="seatsFirstClass"))
    seats_coupe_first_class: int = field(metadata=field_options(alias="seatsCoupeFirstClass"))
    standing_places_first_class: int = field(metadata=field_options(alias="standingPlacesFirstClass"))
    seats_second_class: int = field(metadata=field_options(alias="seatsSecondClass"))
    seats_coupe_second_class: int = field(metadata=field_options(alias="seatsCoupeSecondClass"))
    standing_places_second_class: int = field(metadata=field_options(alias="standingPlacesSecondClass"))
    length_in_meter: int = field(metadata=field_options(alias="lengthInMeter"))
    has_semi_automatic_interior_doors: bool = field(
        metadata=field_options(alias="hasSemiAutomaticInteriorDoors", deserialize=_str_to_bool)
    )
    traction_position: int = field(metadata=field_options(alias="tractionPosition"))
    has_prm_section: bool = field(metadata=field_options(alias="hasPrmSection", deserialize=_str_to_bool))
    has_priority_places: bool = field(metadata=field_options(alias="hasPriorityPlaces", deserialize=_str_to_bool))
    has_bike_section: bool = field(metadata=field_options(alias="hasBikeSection", deserialize=_str_to_bool))
    traction_type: str | None = field(default=None, metadata=field_options(alias="tractionType"))
    material_number: str | None = field(default=None, metadata=field_options(alias="materialNumber"))
    material_sub_type_name: str | None = field(default=None, metadata=field_options(alias="materialSubTypeName"))
    has_tables: bool | None = field(default=None, metadata=field_options(alias="hasTables", deserialize=_str_to_bool))
    has_luggage_section: bool | None = field(
        default=None,
        metadata=field_options(alias="hasLuggageSection", deserialize=_str_to_bool),
    )


@dataclass(slots=True)
class SegmentComposition(DataClassORJSONMixin):
    """Describes a collection of train units and related metadata."""

    source: str
    units: list[Unit] = field(default_factory=list)

    @classmethod
    @override
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Extract the 'unit' list from 'units' before deserialization, defaulting to an empty list."""
        d = d.copy()
        units = d.get("units")
        d["units"] = units.get("unit", []) if isinstance(units, dict) else []
        return d


@dataclass(slots=True)
class Segment(DataClassORJSONMixin):
    """Defines a single segment within a journey, including composition details."""

    id: str
    origin: StationDetails
    destination: StationDetails
    composition: SegmentComposition


@dataclass(slots=True)
class CompositionApiResponse(ApiResponse):
    """Encapsulates the response containing composition details of a specific train."""

    composition: list[Segment] = field(default_factory=list)

    @classmethod
    @override
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Extract the 'segment' list from 'composition' before deserialization, defaulting to an empty list."""
        d = d.copy()
        composition = d.get("composition")
        segments = composition.get("segments") if isinstance(composition, dict) else None
        d["composition"] = segments.get("segment", []) if isinstance(segments, dict) else []
        return d


@dataclass(slots=True)
class DescriptionLink(DataClassORJSONMixin):
    """Represents a single link within a disturbance description."""

    id: str
    link: str
    text: str


@dataclass(slots=True)
class Disturbance(DataClassORJSONMixin):
    """Represents a railway system disturbance, including description and metadata."""

    id: str
    title: str
    description: str
    type: DisturbanceType
    link: str
    timestamp: datetime = field(metadata=field_options(deserialize=_timestamp_to_datetime))
    richtext: str
    description_links: list[DescriptionLink] = field(
        metadata=field_options(alias="descriptionLinks"), default_factory=list
    )

    @classmethod
    @override
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Extract the 'descriptionLink' list from 'descriptionLinks' before deserialization, defaulting to an empty list."""
        d = d.copy()
        links = d.get("descriptionLinks")
        d["descriptionLinks"] = links.get("descriptionLink", []) if isinstance(links, dict) else []
        return d


@dataclass(slots=True)
class DisturbancesApiResponse(ApiResponse):
    """Encapsulates multiple disturbances returned by the disturbances endpoint."""

    disturbances: list[Disturbance] = field(metadata=field_options(alias="disturbance"), default_factory=list)
