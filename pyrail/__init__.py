"""Package initialization for pyrail."""

from importlib.metadata import PackageNotFoundError, version
import logging

from .exceptions import (
    ApiUnavailableError,
    InvalidRequestError,
    InvalidResponseError,
    NotFoundError,
    PyRailError,
    RateLimitError,
)
from .irail import iRail
from .models import (
    Alert,
    ApiResponse,
    CompositionApiResponse,
    ConnectionArrival,
    ConnectionDeparture,
    ConnectionDetails,
    ConnectionsApiResponse,
    ConnectionStop,
    DescriptionLink,
    Direction,
    Disturbance,
    DisturbancesApiResponse,
    DisturbanceType,
    LiveboardApiResponse,
    LiveboardArrival,
    LiveboardDeparture,
    MaterialType,
    Occupancy,
    OccupancyName,
    Orientation,
    PlatformInfo,
    Remark,
    Segment,
    SegmentComposition,
    StationDetails,
    StationsApiResponse,
    Unit,
    VehicleApiResponse,
    VehicleInfo,
    VehicleStop,
    Via,
)

logging.getLogger(__name__).addHandler(logging.NullHandler())

try:
    __version__ = version("pyrail")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = [
    "Alert",
    "ApiResponse",
    "ApiUnavailableError",
    "CompositionApiResponse",
    "ConnectionArrival",
    "ConnectionDeparture",
    "ConnectionDetails",
    "ConnectionStop",
    "ConnectionsApiResponse",
    "DescriptionLink",
    "Direction",
    "Disturbance",
    "DisturbanceType",
    "DisturbancesApiResponse",
    "InvalidRequestError",
    "InvalidResponseError",
    "LiveboardApiResponse",
    "LiveboardArrival",
    "LiveboardDeparture",
    "MaterialType",
    "NotFoundError",
    "Occupancy",
    "OccupancyName",
    "Orientation",
    "PlatformInfo",
    "PyRailError",
    "RateLimitError",
    "Remark",
    "Segment",
    "SegmentComposition",
    "StationDetails",
    "StationsApiResponse",
    "Unit",
    "VehicleApiResponse",
    "VehicleInfo",
    "VehicleStop",
    "Via",
    "__version__",
    "iRail",
]
