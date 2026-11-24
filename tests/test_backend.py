"""Tests for selecting a data backend through the public client."""

from datetime import UTC, datetime
from typing import override
from unittest.mock import create_autospec

import pytest

from pyrail import Backend, IRail, NotSupportedError, PyRailError, StationsApiResponse

_STATIONS = StationsApiResponse(version="1", timestamp=datetime(2026, 11, 24, tzinfo=UTC))


class StationsBackend(Backend):
    """A backend which can serve stations without opening an HTTP session."""

    @override
    async def get_stations(self) -> StationsApiResponse:
        """Return a model from the data source."""
        return _STATIONS


async def test_custom_backend_serves_models_and_uses_client_language() -> None:
    """Verify a backend can answer requests through IRail without an aiohttp session."""
    backend = StationsBackend()
    async with IRail(lang="nl", backend=backend) as api:
        assert api.lang == backend.lang == "nl"
        api.lang = "de"
        assert backend.lang == "de"
        api.clear_etag_cache()
        assert await api.get_stations() == _STATIONS


async def test_client_delegates_backend_lifecycle_and_endpoint_arguments() -> None:
    """Forward setup, cleanup and query options to the selected backend."""
    backend = create_autospec(Backend, instance=True)
    backend.get_liveboard.return_value = None
    backend.get_connections.return_value = None
    backend.get_vehicle.return_value = None
    backend.get_composition.return_value = None
    backend.get_disturbances.return_value = None
    async with IRail(backend=backend) as api:
        assert await api.get_liveboard("Gent-Sint-Pieters", None, "241126", "1030", "arrival") is None
        assert await api.get_connections("Gent", "Brussel", "241126", "1030", "arrival", "trains") is None
        assert await api.get_vehicle("IC123", "241126") is None
        assert await api.get_composition("IC123", "241126") is None
        assert await api.get_disturbances() is None
    backend.open.assert_awaited_once_with()
    backend.close.assert_awaited_once_with()
    backend.get_liveboard.assert_awaited_once_with("Gent-Sint-Pieters", None, "241126", "1030", "arrival")
    backend.get_connections.assert_awaited_once_with("Gent", "Brussel", "241126", "1030", "arrival", "trains")
    backend.get_vehicle.assert_awaited_once_with("IC123", "241126")
    backend.get_composition.assert_awaited_once_with("IC123", "241126")
    backend.get_disturbances.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("get_stations", ()),
        ("get_liveboard", ("Gent",)),
        ("get_connections", ("Gent", "Brussel")),
        ("get_vehicle", ("IC123",)),
        ("get_composition", ("IC123",)),
        ("get_disturbances", ()),
    ],
)
async def test_unavailable_operations_raise_a_dedicated_error(method: str, args: tuple[str, ...]) -> None:
    """Make unsupported calls distinguishable from API or transport failures."""
    api = IRail(backend=Backend())
    with pytest.raises(NotSupportedError, match=f"Backend does not support {method}") as exc_info:
        await getattr(api, method)(*args)
    assert isinstance(exc_info.value, PyRailError)


def test_http_options_must_be_configured_on_a_supplied_backend() -> None:
    """Reject API transport options rather than ignoring them."""
    with pytest.raises(ValueError, match="Configure session, max_retries and request_timeout"):
        IRail(max_retries=0, backend=Backend())
