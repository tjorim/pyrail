"""Interface for pyRail data sources."""

from typing import Literal

from pyrail.exceptions import NotSupportedError
from pyrail.models import (
    CompositionApiResponse,
    ConnectionsApiResponse,
    DisturbancesApiResponse,
    LiveboardApiResponse,
    StationsApiResponse,
    VehicleApiResponse,
)

_LANGUAGES = frozenset({"en", "nl", "fr", "de"})


class Backend:
    """Provide pyRail response models and manage the resources used to fetch them.

    Implement the operations your data source can answer. Inherited operations
    raise NotSupportedError. Override open and close if the source needs setup
    or cleanup. Backends used without a context manager must support lazy setup.
    """

    def __init__(self, lang: str = "en") -> None:
        """Set the initial response language."""
        self.lang = lang

    @property
    def lang(self) -> str:
        """Get the language setting for API requests.

        Returns:
            str: The current language setting ('nl', 'fr', 'en', 'de').

        """
        return self._lang

    @lang.setter
    def lang(self, value: str) -> None:
        """Set the language for API requests.

        Args:
            value (str): The language to use. Must be one of: 'nl', 'fr', 'en', 'de'.

        Raises:
            ValueError: If the value is not one of the supported languages.

        """
        if value not in _LANGUAGES:
            msg = f"Invalid language: {value}. Expected one of {sorted(_LANGUAGES)}"
            raise ValueError(msg)
        self._lang = value

    async def open(self) -> None:
        """Prepare the backend when the client enters an async context."""

    async def close(self) -> None:
        """Release resources owned by the backend."""

    async def get_stations(self) -> StationsApiResponse | None:
        """Return the stations response when supported by this backend."""
        msg = f"{type(self).__name__} does not support get_stations"
        raise NotSupportedError(msg)

    async def get_liveboard(
        self,
        station: str | None = None,  # noqa: ARG002
        station_id: str | None = None,  # noqa: ARG002
        date: str | None = None,  # noqa: ARG002
        time: str | None = None,  # noqa: ARG002
        arrdep: Literal["departure", "arrival"] = "departure",  # noqa: ARG002
    ) -> LiveboardApiResponse | None:
        """Return the liveboard response when supported by this backend."""
        msg = f"{type(self).__name__} does not support get_liveboard"
        raise NotSupportedError(msg)

    async def get_connections(
        self,
        from_station: str,  # noqa: ARG002
        to_station: str,  # noqa: ARG002
        date: str | None = None,  # noqa: ARG002
        time: str | None = None,  # noqa: ARG002
        timesel: Literal["departure", "arrival"] = "departure",  # noqa: ARG002
        type_of_transport: Literal["automatic", "trains", "no_international_trains", "all"] = "automatic",  # noqa: ARG002
    ) -> ConnectionsApiResponse | None:
        """Return the connections response when supported by this backend."""
        msg = f"{type(self).__name__} does not support get_connections"
        raise NotSupportedError(msg)

    async def get_vehicle(
        self,
        vehicle_id: str,  # noqa: ARG002
        date: str | None = None,  # noqa: ARG002
    ) -> VehicleApiResponse | None:
        """Return the vehicle response when supported by this backend."""
        msg = f"{type(self).__name__} does not support get_vehicle"
        raise NotSupportedError(msg)

    async def get_composition(
        self,
        vehicle_id: str,  # noqa: ARG002
        date: str | None = None,  # noqa: ARG002
    ) -> CompositionApiResponse | None:
        """Return the composition response when supported by this backend."""
        msg = f"{type(self).__name__} does not support get_composition"
        raise NotSupportedError(msg)

    async def get_disturbances(self) -> DisturbancesApiResponse | None:
        """Return the disturbances response when supported by this backend."""
        msg = f"{type(self).__name__} does not support get_disturbances"
        raise NotSupportedError(msg)
