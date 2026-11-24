"""Public client for iRail data."""

from __future__ import annotations

import asyncio as asyncio  # noqa: PLC0414
from collections.abc import Callable
from types import CoroutineType, TracebackType
from typing import Any, Literal, Self

from aiohttp import ClientSession

from pyrail.api_backend import (
    _DEFAULT_MAX_RETRIES,
    _DEFAULT_REQUEST_TIMEOUT,
    _ETAG_CACHE_LIMIT as _ETAG_CACHE_LIMIT,  # noqa: PLC0414
    ApiBackend,
    _parse_retry_after as _parse_retry_after,  # noqa: PLC0414
)
from pyrail.backend import Backend
from pyrail.models import (
    CompositionApiResponse,
    ConnectionsApiResponse,
    DisturbancesApiResponse,
    LiveboardApiResponse,
    StationsApiResponse,
    VehicleApiResponse,
)


class IRail:
    """An async client for iRail data, backed by the iRail HTTP API by default."""

    def __init__(
        self,
        lang: str = "en",
        session: ClientSession | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        request_timeout: float = _DEFAULT_REQUEST_TIMEOUT,
        *,
        backend: Backend | None = None,
    ) -> None:
        """Configure the data source and set its response language.

        With the default backend, session supplies an externally managed HTTP
        session, max_retries controls retries, and request_timeout is in seconds.
        When supplying a backend instance, configure its transport on the backend.
        """
        if backend is None:
            backend = ApiBackend(lang, session, max_retries, request_timeout)
        else:
            if (
                session is not None
                or max_retries != _DEFAULT_MAX_RETRIES
                or request_timeout != _DEFAULT_REQUEST_TIMEOUT
            ):
                msg = "Configure session, max_retries and request_timeout on the supplied backend"
                raise ValueError(msg)
            backend.lang = lang
        self._backend = backend

    async def __aenter__(self) -> Self:
        """Prepare the backend and return this client."""
        await self._backend.open()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        """Close resources owned by the backend."""
        await self.close()

    async def close(self) -> None:
        """Close resources owned by the backend."""
        await self._backend.close()

    @property
    def lang(self) -> str:
        """Return the language used for responses."""
        return self._backend.lang

    @lang.setter
    def lang(self, value: str) -> None:
        self._backend.lang = value

    def clear_etag_cache(self) -> None:
        """Clear the HTTP API's ETag cache when using the API backend."""
        if isinstance(self._backend, ApiBackend):
            self._backend.clear_etag_cache()

    def _api_backend(self) -> ApiBackend:
        """Return the API backend for settings specific to the HTTP client."""
        if not isinstance(self._backend, ApiBackend):
            msg = "This attribute is only available with the iRail API backend"
            raise AttributeError(msg)  # noqa: TRY004
        return self._backend

    @property
    def session(self) -> ClientSession | None:
        """The HTTP session, if one has been opened or supplied."""
        return self._api_backend().session

    @session.setter
    def session(self, value: ClientSession | None) -> None:
        self._api_backend().session = value

    @property
    def max_retries(self) -> int:
        """The maximum number of HTTP retries per request."""
        return self._api_backend().max_retries

    @max_retries.setter
    def max_retries(self, value: int) -> None:
        self._api_backend().max_retries = value

    @property
    def request_timeout(self) -> float:
        """The timeout in seconds for each HTTP attempt."""
        return self._api_backend().request_timeout

    @request_timeout.setter
    def request_timeout(self, value: float) -> None:
        self._api_backend().request_timeout = value

    @property
    def _tokens(self) -> float:
        """The number of regular API rate-limit tokens."""
        return self._api_backend()._tokens  # noqa: SLF001

    @_tokens.setter
    def _tokens(self, value: float) -> None:
        self._api_backend()._tokens = value  # noqa: SLF001

    @property
    def _burst_tokens(self) -> float:
        """The number of burst API rate-limit tokens."""
        return self._api_backend()._burst_tokens  # noqa: SLF001

    @_burst_tokens.setter
    def _burst_tokens(self, value: float) -> None:
        self._api_backend()._burst_tokens = value  # noqa: SLF001

    @property
    def _handle_rate_limit(self) -> Callable[[], CoroutineType[Any, Any, None]]:
        """Forward the API rate limiter, including temporary test overrides."""
        return self._api_backend()._handle_rate_limit  # noqa: SLF001

    @_handle_rate_limit.setter
    def _handle_rate_limit(self, value: Callable[[], CoroutineType[Any, Any, None]]) -> None:
        self._api_backend()._handle_rate_limit = value  # noqa: SLF001

    @_handle_rate_limit.deleter
    def _handle_rate_limit(self) -> None:
        delattr(self._api_backend(), "_handle_rate_limit")

    def __getattr__(self, name: str) -> Any:
        """Forward the legacy private API hooks used by the existing tests."""
        if name in {
            "_build_request_headers",
            "_do_request",
            "_etag_cache",
            "_handle_success_response",
            "_refill_tokens",
            "_store_etag",
            "_validate_date",
            "_validate_time",
        }:
            return getattr(self._api_backend(), name)
        msg = f"{type(self).__name__!r} object has no attribute {name!r}"
        raise AttributeError(msg)

    async def get_stations(self) -> StationsApiResponse | None:
        """Retrieve a list of all train stations from the iRail API.

        This method fetches the complete list of available train stations without any additional filtering parameters.

        Returns:
            StationsApiResponse or None: A StationsApiResponse object containing a list of all train stations and their details, or None if the data is not modified.

        Raises:
            NotSupportedError: If the selected backend cannot answer this call.
            RuntimeError: If the active session has been closed.
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            InvalidResponseError: If the response body cannot be used or does not match the response model.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with IRail() as client:
                stations = await client.get_stations()
                if stations:
                    print(f"Total stations: {len(stations.stations)}")

        """
        return await self._backend.get_stations()

    async def get_liveboard(
        self,
        station: str | None = None,
        station_id: str | None = None,
        date: str | None = None,
        time: str | None = None,
        arrdep: Literal["departure", "arrival"] = "departure",
    ) -> LiveboardApiResponse | None:
        """Retrieve a liveboard for a specific train station.

        Asynchronously fetches live departure or arrival information for a given station.
        Provide exactly one of 'station' or 'station_id'.

        Args:
            station (str): Name of the train station.
            station_id (str): Unique identifier of the train station.
            date (str, optional): Date for the liveboard in format 'DDMMYY', in Belgian local time. Defaults to current date.
            time (str, optional): Time for the liveboard in format 'HHMM', in Belgian local time. Defaults to current time.
            arrdep (str, optional): Type of board to retrieve. Either 'departure' (default) or 'arrival'.

        Returns:
            LiveboardApiResponse or None: A LiveboardApiResponse object containing liveboard information, or None if the data is not modified.

        Raises:
            NotSupportedError: If the selected backend cannot answer this call.
            ValueError: If the parameters are invalid.
            RuntimeError: If the active session has been closed.
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            InvalidResponseError: If the response body cannot be used or does not match the response model.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with IRail() as client:
                liveboard = await client.get_liveboard(station='Brussels-South')
                if liveboard:
                    print(f"Liveboard for Brussels-South: {liveboard}")

        """
        return await self._backend.get_liveboard(station, station_id, date, time, arrdep)

    async def get_connections(
        self,
        from_station: str,
        to_station: str,
        date: str | None = None,
        time: str | None = None,
        timesel: Literal["departure", "arrival"] = "departure",
        type_of_transport: Literal["automatic", "trains", "no_international_trains", "all"] = "automatic",
    ) -> ConnectionsApiResponse | None:
        """Retrieve train connections between two stations using the iRail API.

        Args:
            from_station (str): Name or ID of the departure station
            to_station (str): Name or ID of the arrival station
            date (str, optional): Date of travel in format 'DDMMYY', in Belgian local time (default: current date)
            time (str, optional): Time of travel in format 'HHMM', in Belgian local time (default: current time)
            timesel (str, optional): Time selection type, either 'departure' or 'arrival' (default: 'departure')
            type_of_transport (str, optional): Type of transport, one of 'automatic', 'trains', 'no_international_trains'
                or 'all' (default: 'automatic')

        Returns:
            ConnectionsApiResponse or None: A ConnectionsApiResponse object containing connection details, or None if the data is not modified.

        Raises:
            NotSupportedError: If the selected backend cannot answer this call.
            ValueError: If the parameters are invalid.
            RuntimeError: If the active session has been closed.
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            InvalidResponseError: If the response body cannot be used or does not match the response model.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with IRail() as client:
                connections = await client.get_connections("Antwerpen-Centraal", "Brussel-Centraal")
                if connections:
                    print(f"Connections from Antwerpen-Centraal to Brussel-Centraal: {connections}")

        """
        return await self._backend.get_connections(from_station, to_station, date, time, timesel, type_of_transport)

    async def get_vehicle(
        self,
        vehicle_id: str,
        date: str | None = None,
    ) -> VehicleApiResponse | None:
        """Retrieve detailed information about a specific train vehicle.

        Args:
            vehicle_id (str): Unique identifier of the train vehicle to retrieve information for.
            date (str, optional): Specific date for which vehicle information is requested. Defaults to None (current date).

        Returns:
            VehicleApiResponse or None: A VehicleApiResponse object containing vehicle details, or None if the data is not modified.

        Raises:
            NotSupportedError: If the selected backend cannot answer this call.
            ValueError: If the parameters are invalid.
            RuntimeError: If the active session has been closed.
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            InvalidResponseError: If the response body cannot be used or does not match the response model.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with IRail() as client:
                vehicle_info = await client.get_vehicle("BE.NMBS.IC1832")

        """
        return await self._backend.get_vehicle(vehicle_id, date)

    async def get_composition(
        self,
        vehicle_id: str,
        date: str | None = None,
    ) -> CompositionApiResponse | None:
        """Retrieve the composition details of a specific train.

        Args:
            vehicle_id (str): The unique identifier of the train for which composition details are requested.
            date (str, optional): Date of the train in format 'DDMMYY', in Belgian local time. Defaults to None (current date).

        Returns:
            CompositionApiResponse or None: A CompositionApiResponse object containing train composition details, or None if the data is not modified.

        Raises:
            NotSupportedError: If the selected backend cannot answer this call.
            ValueError: If the parameters are invalid.
            RuntimeError: If the active session has been closed.
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            InvalidResponseError: If the response body cannot be used or does not match the response model.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with IRail() as client:
                composition = await client.get_composition('S51507')

        """
        return await self._backend.get_composition(vehicle_id, date)

    async def get_disturbances(self) -> DisturbancesApiResponse | None:
        """Retrieve information about current disturbances on the rail network.

        Returns:
            DisturbancesApiResponse or None: A DisturbancesApiResponse object containing disturbance information, or None if the data is not modified.

        Raises:
            NotSupportedError: If the selected backend cannot answer this call.
            RuntimeError: If the active session has been closed.
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            InvalidResponseError: If the response body cannot be used or does not match the response model.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with IRail() as client:
                disturbances = await client.get_disturbances()
                if disturbances:
                    print(f"Current disturbances: {disturbances}")

        """
        return await self._backend.get_disturbances()
