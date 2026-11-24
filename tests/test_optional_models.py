"""Coverage for model fields that can be unknown to a timetable data source."""

import json
from pathlib import Path

from mashumaro.mixins.orjson import DataClassORJSONMixin
import pytest

from pyrail import (
    ConnectionArrival,
    ConnectionDeparture,
    ConnectionStop,
    LiveboardArrival,
    LiveboardDeparture,
    PlatformInfo,
    VehicleInfo,
    VehicleStop,
)

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize("missing", [True, False], ids=["omitted", "null"])
@pytest.mark.parametrize(
    ("filename", "path", "model", "fields"),
    [
        (
            "liveboard.json",
            ("departures", "departure", 0),
            LiveboardDeparture,
            {"platforminfo": "platform_info", "platform": "platform", "isExtra": "is_extra", "occupancy": "occupancy"},
        ),
        (
            "liveboard_arrivals.json",
            ("arrivals", "arrival", 0),
            LiveboardArrival,
            {"platforminfo": "platform_info", "platform": "platform", "isExtra": "is_extra"},
        ),
        (
            "connections.json",
            ("connection", 0, "departure"),
            ConnectionDeparture,
            {"platforminfo": "platform_info", "platform": "platform", "occupancy": "occupancy"},
        ),
        (
            "connections.json",
            ("connection", 0, "arrival"),
            ConnectionArrival,
            {"platforminfo": "platform_info", "platform": "platform"},
        ),
        (
            "vehicle.json",
            ("stops", "stop", 0),
            VehicleStop,
            {
                "platforminfo": "platform_info",
                "platform": "platform",
                "isExtraStop": "is_extra_stop",
                "occupancy": "occupancy",
            },
        ),
        (
            "connections.json",
            ("connection", 0, "departure", "stops", "stop", 0),
            ConnectionStop,
            {"platforminfo": "platform_info", "platform": "platform", "isExtraStop": "is_extra_stop"},
        ),
        ("vehicle.json", ("vehicleinfo",), VehicleInfo, {"locationX": "longitude", "locationY": "latitude"}),
        ("liveboard.json", ("departures", "departure", 0, "platforminfo"), PlatformInfo, {"normal": "normal"}),
    ],
)
def test_unknown_values_deserialize_as_none(
    filename: str,
    path: tuple[str | int, ...],
    model: type[DataClassORJSONMixin],
    fields: dict[str, str],
    *,
    missing: bool,
) -> None:
    """Omitted and null JSON fields represent unknown data."""
    data = json.loads((_EXAMPLES / filename).read_bytes())
    for key in path:
        data = data[key]
    for alias in fields:
        if missing:
            data.pop(alias)
        else:
            data[alias] = None
    result = model.from_dict(data)
    for attr in fields.values():
        assert getattr(result, attr) is None
