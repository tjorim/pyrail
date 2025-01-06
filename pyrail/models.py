from dataclasses import dataclass, field
from typing import List

from mashumaro import field_options
from mashumaro.mixins.orjson import DataClassORJSONMixin


@dataclass
class ApiResponse(DataClassORJSONMixin):
    version: str  # Version of the response schema
    timestamp: int  # Timestamp of the response


@dataclass
class Station(DataClassORJSONMixin):
    id: str  # The (iRail) ID of the station
    at_id: str = field(metadata=field_options(alias="@id"))  # Corresponds to "@id" in the schema
    location_x: float = field(metadata=field_options(alias="locationX"))  # Longitude of the station
    location_y: float = field(metadata=field_options(alias="locationY"))  # Latitude of the station
    standard_name: str = field(metadata=field_options(alias="standardname"))  # Consistent name of the station
    name: str  # Default name of the station


@dataclass
class StationsApiResponse(ApiResponse):
    stations: List[Station] = field(metadata=field_options(alias="station"))  # List of stations information
