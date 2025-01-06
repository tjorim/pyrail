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
    # Corresponds to "@id" in the schema
    at_id: str = field(metadata=field_options(alias="@id"))
    location_x: float = field(metadata=field_options(
        alias="locationX"))  # Longitude of the station
    location_y: float = field(metadata=field_options(
        alias="locationY"))  # Latitude of the station
    standard_name: str = field(metadata=field_options(
        alias="standardname"))  # Consistent name of the station
    name: str  # Default name of the station


@dataclass
class StationsApiResponse(ApiResponse):
    """Holds a list of station objects returned by the 'stations' endpoint."""

    stations: List[Station] = field(metadata=field_options(
        alias="station"))  # List of stations information
