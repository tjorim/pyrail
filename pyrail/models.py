from dataclasses import dataclass, field
from typing import List

from mashumaro import field_options
from mashumaro.mixins.orjson import DataClassORJSONMixin


@dataclass
class Station(DataClassORJSONMixin):
    id: str = field(metadata=field_options(alias="id"))
    name: str = field(metadata=field_options(alias="name"))
    location_x: str = field(metadata=field_options(alias="locationX"))
    location_y: str = field(metadata=field_options(alias="locationY"))
    standardname: str = field(metadata=field_options(alias="standardname"))


@dataclass
class APIResponse(DataClassORJSONMixin):
    version: str
    timestamp: str


@dataclass
class StationAPIResponse(APIResponse):
    station: List[Station]
