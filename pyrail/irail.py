"""Module providing the IRail class for interacting with the iRail API."""

import asyncio
from asyncio import Lock
from collections import OrderedDict
from collections.abc import Callable, Mapping
import contextlib
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http import HTTPStatus
import logging
import time
from types import MappingProxyType, TracebackType
from typing import Any, Literal, Self

from aiohttp import ClientError, ClientResponse, ClientSession

from pyrail.exceptions import (
    ApiUnavailableError,
    InvalidRequestError,
    InvalidResponseError,
    NotFoundError,
    RateLimitError,
)
from pyrail.models import (
    CompositionApiResponse,
    ConnectionsApiResponse,
    DisturbancesApiResponse,
    LiveboardApiResponse,
    StationsApiResponse,
    VehicleApiResponse,
)

logger: logging.Logger = logging.getLogger(__name__)

_API_BASE_URL = "https://api.irail.be/v1"

_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 10.0

_DEFAULT_REQUEST_TIMEOUT = 30.0

_ETAG_CACHE_LIMIT = 128

_SERVER_ERROR_STATUSES = range(500, 600)

_TOKEN_CAPACITY = 3
_TOKEN_REFILLS_PER_SECOND = 3
_BURST_CAPACITY = 5

_LANGUAGES: frozenset[str] = frozenset({"en", "nl", "fr", "de"})

_ALLOWED_VALUES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "arrdep": frozenset({"departure", "arrival"}),
        "timesel": frozenset({"departure", "arrival"}),
        "typeOfTransport": frozenset({"automatic", "trains", "no_international_trains", "all"}),
    }
)


type _EndpointSpec = Mapping[str, tuple[str, ...]]


def _frozen_spec(spec: dict[str, tuple[str, ...]]) -> _EndpointSpec:
    """Freeze one endpoint spec, so the endpoint table cannot be mutated at any level."""
    return MappingProxyType(spec)


_ENDPOINTS: Mapping[str, _EndpointSpec] = MappingProxyType(
    {
        "stations": _frozen_spec({}),
        "liveboard": _frozen_spec({"xor": ("station", "id"), "optional": ("date", "time", "arrdep", "alerts")}),
        "connections": _frozen_spec(
            {"required": ("from", "to"), "optional": ("date", "time", "timesel", "typeOfTransport")}
        ),
        "vehicle": _frozen_spec({"required": ("id",), "optional": ("date", "alerts")}),
        "composition": _frozen_spec({"required": ("id",), "optional": ("data",)}),
        "disturbances": _frozen_spec({"optional": ("lineBreakCharacter",)}),
    }
)


def _describe(error: BaseException) -> str:
    """Describe an exception for log and error messages, including its type when it has no message."""
    return f"{type(error).__name__}: {error}" if str(error) else type(error).__name__


def _parse_retry_after(value: str | None) -> int | None:
    """Parse a Retry-After header, given as seconds or an HTTP date, into whole seconds.

    Returns None when the header is missing or cannot be parsed.
    """
    if value is None:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0, int((retry_at - datetime.now(UTC)).total_seconds()))


class _ServerError(ClientError):
    """Raised for 5xx responses so that they are retried like network failures."""

    def __init__(self, status: int) -> None:
        super().__init__(f"Server error {status}")
        self.status = status


type _RequestKey = tuple[str, tuple[tuple[str, Any], ...]]


class IRail:
    """A Python wrapper for the iRail API, handling rate limiting and endpoint requests.

    Attributes:
        lang (str): The language for API responses ('nl', 'fr', 'en', 'de').
        session (ClientSession, optional): The HTTP session used for API requests. None until the
            context manager is entered or the first request, and after close() of an owned session.
            Remains set when the caller provided the session.
            If not provided, a new session will be created and managed internally.
            If provided, the session lifecycle must be managed externally.
        max_retries (int): How many times a request is retried after a network error, timeout or
            server error (5xx). Each attempt goes through the rate limiter. 0 disables retrying.
        request_timeout (float): Timeout in seconds for each individual request attempt.

    Supported endpoints:
        stations: Retrieve all stations.
        liveboard: Retrieve a liveboard for a station or ID.
        connections: Retrieve connections between two stations.
        vehicle: Retrieve information about a specific train.
        composition: Retrieve the composition of a train.
        disturbances: Retrieve information about current disturbances on the rail network.

    """

    def __init__(
        self,
        lang: str = "en",
        session: ClientSession | None = None,
        max_retries: int = 2,
        request_timeout: float = _DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        """Initialize the iRail API client.

        Args:
            lang (str): The language for API responses. Default is 'en'.
            session (ClientSession, optional): An existing aiohttp session. Defaults to None.
            max_retries (int): Number of retries after a transient failure. Default is 2 (3 attempts in total).
                Use 0 to disable retrying.
            request_timeout (float): Timeout in seconds for each individual request attempt.
                Default is 30 seconds.

        Raises:
            ValueError: If max_retries is negative, request_timeout is not positive, or lang is
                not one of 'en', 'nl', 'fr', 'de'.

        """
        if max_retries < 0:
            msg = "max_retries must be 0 or greater"
            raise ValueError(msg)
        if request_timeout <= 0:
            msg = "request_timeout must be greater than 0"
            raise ValueError(msg)
        self.max_retries: int = max_retries
        self.request_timeout: float = request_timeout
        self.lang: str = lang
        self._tokens: float = _TOKEN_CAPACITY
        self._burst_tokens: float = _BURST_CAPACITY
        self._last_request_time: float = time.monotonic()
        self._lock: Lock = Lock()
        self.session: ClientSession | None = session
        self._owns_session = session is None
        self._etag_cache: OrderedDict[_RequestKey, str] = OrderedDict()
        self._etag_generation: int = 0

    async def __aenter__(self) -> Self:
        """Initialize the aiohttp client session when entering the async context."""
        self._ensure_session()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        """Close the owned aiohttp client session when exiting the async context.

        A session provided by the caller is left open.
        """
        await self.close()

    async def close(self) -> None:
        """Close the aiohttp client session when this client owns it.

        A session provided by the caller is never closed, so a client can be
        used without the async context manager and closed explicitly.
        After close of an owned session, the next request creates a fresh one.
        """
        if self.session and not self.session.closed and self._owns_session:
            logger.debug("Closing aiohttp session")
            await self.session.close()
            self.session = None

    def _ensure_session(self) -> ClientSession:
        """Return the active session, creating an owned one when none exists yet."""
        if self.session is None:
            logger.debug("Creating new internal aiohttp session")
            self.session = ClientSession()
        return self.session

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

    def clear_etag_cache(self) -> None:
        """Clear the ETag cache.

        A response that was already in flight when the cache was cleared
        does not repopulate it.
        """
        self._etag_cache.clear()
        self._etag_generation += 1
        logger.debug("ETag cache cleared")

    def _store_etag(self, request_key: _RequestKey, etag: str) -> None:
        """Cache the ETag for a request, dropping the least recently used entry above the limit."""
        if request_key in self._etag_cache:
            self._etag_cache.move_to_end(request_key)
        self._etag_cache[request_key] = etag
        if len(self._etag_cache) > _ETAG_CACHE_LIMIT:
            self._etag_cache.popitem(last=False)

    def _refill_tokens(self) -> None:
        """Refill the rate limiting token buckets.

        Standard tokens refill at 3 tokens per second and hold at most 3. Burst
        tokens take only the credit that overflows while the standard tokens are
        full and hold at most 5. Credit is fractional and nothing is rounded away.
        """
        logger.debug("Refilling tokens")
        current_time: float = time.monotonic()
        elapsed: float = current_time - self._last_request_time
        self._last_request_time = current_time

        credit: float = elapsed * _TOKEN_REFILLS_PER_SECOND
        used_for_tokens: float = max(0.0, min(credit, _TOKEN_CAPACITY - self._tokens))
        self._tokens = min(_TOKEN_CAPACITY, self._tokens + used_for_tokens)
        overflow: float = credit - used_for_tokens
        if overflow > 0:
            self._burst_tokens = min(_BURST_CAPACITY, self._burst_tokens + overflow)

    async def _handle_rate_limit(self) -> None:
        """Take one token for a request, or wait for the next one.

        Standard tokens allow 3 requests per second, burst tokens are an extra
        pool of 5 for spikes. When both are exhausted, the request waits only
        until the next standard token refills.
        """
        logger.debug("Handling rate limit")
        self._refill_tokens()
        if self._tokens >= 1:
            self._tokens -= 1
        elif self._burst_tokens >= 1:
            self._burst_tokens -= 1
        else:
            logger.warning("Rate limiting active, waiting for a token")
            wait_time: float = (1.0 - self._tokens) / _TOKEN_REFILLS_PER_SECOND
            await asyncio.sleep(wait_time)
            self._refill_tokens()
            self._tokens -= 1

    def _build_request_headers(self, request_key: _RequestKey) -> dict[str, str]:
        """Build the request headers, adding If-None-Match for a cached ETag.

        The cache is keyed by the endpoint and its full query, so the header
        is only sent for a repeat of the exact request the ETag came from.
        A hit marks the entry as recently used, which protects it from eviction.
        """
        headers: dict[str, str] = {"User-Agent": "pyRail (https://github.com/tjorim/pyrail; tielemans.jorim@gmail.com)"}
        if request_key in self._etag_cache:
            self._etag_cache.move_to_end(request_key)
            logger.debug("Adding If-None-Match header with value: %s", self._etag_cache[request_key])
            headers["If-None-Match"] = self._etag_cache[request_key]
        return headers

    def _validate_date(self, date: str | None) -> None:
        """Validate the date format (DDMMYY).

        Args:
            date (str, optional): The date string to validate. Expected format is DDMMYY,
            e.g., '150923' for September 15, 2023.

        Raises:
            ValueError: If the date is not in DDMMYY format.

        """
        if date is None:
            return
        msg = f"Invalid date format: {date}. Expected DDMMYY (e.g., 150923 for September 15, 2023)"
        if len(date) != len("DDMMYY") or not date.isascii() or not date.isdigit():
            raise ValueError(msg)
        try:
            time.strptime(date, "%d%m%y")
        except ValueError:
            raise ValueError(msg) from None

    def _validate_time(self, time_str: str | None) -> None:
        """Validate the time format (HHMM).

        Args:
            time_str (str, optional): The time string to validate. Expected format is HHMM,
            e.g., '1430' for 2:30 PM.

        Raises:
            ValueError: If the time is not in HHMM format.

        """
        if time_str is None:
            return
        msg = f"Invalid time format: {time_str}. Expected HHMM (e.g., 1430 for 2:30 PM)"
        if len(time_str) != len("HHMM") or not time_str.isascii() or not time_str.isdigit():
            raise ValueError(msg)
        try:
            time.strptime(time_str, "%H%M")
        except ValueError:
            raise ValueError(msg) from None

    def _validate_values(self, params: dict[str, Any]) -> None:
        """Validate the date, the time and the parameters that only accept a fixed set of values.

        The API silently replaces a value it does not recognise with a default
        (typeOfTransport with 'automatic', arrdep and timesel with 'departure'),
        so these parameters are checked here before the request is sent.

        Args:
            params (dict[str, Any]): The request parameters.

        Raises:
            ValueError: If a parameter present in the request holds an unaccepted value.

        """
        self._validate_date(params.get("date"))
        self._validate_time(params.get("time"))
        for name, allowed in _ALLOWED_VALUES.items():
            if name in params and params[name] not in allowed:
                msg = f"Invalid {name}: expected one of {sorted(allowed)}, got: {params[name]}"
                raise ValueError(msg)

    def _validate_params(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Validate parameters for a specific iRail API endpoint based on predefined requirements.

        Checks that the method is a known endpoint, that all required parameters are present,
        that the XOR parameter logic holds, that no unexpected parameters are given, and that
        date, time and fixed-value parameters hold accepted values.

        Args:
            method (str): The API endpoint method to validate parameters for.
            params (dict[str, Any], optional): Dictionary of parameters to validate. Defaults to None.

        Raises:
            ValueError: If any of the checks fails.

        """
        if method not in _ENDPOINTS:
            msg = f"Unknown API endpoint: {method}"
            raise ValueError(msg)

        endpoint = _ENDPOINTS[method]
        required = endpoint.get("required", ())
        xor = endpoint.get("xor", ())
        optional = endpoint.get("optional", ())

        params = params or {}

        self._validate_values(params)

        for param in required:
            if param not in params or params[param] is None:
                msg = f"Missing required parameter: {param} for endpoint: {method}"
                raise ValueError(msg)

        if xor:
            xor_values = [params.get(param) is not None for param in xor]
            if sum(xor_values) != 1:
                msg = f"Exactly one of the XOR parameters {xor} must be provided for endpoint: {method}"
                raise ValueError(msg)

        all_params = required + xor + optional
        for param in params:
            if param not in all_params:
                msg = f"Unexpected parameter: {param} for endpoint: {method}"
                raise ValueError(msg)

    async def _handle_success_response(
        self, response: ClientResponse, method: str
    ) -> tuple[dict[str, Any], str | None]:
        """Handle a successful API response.

        Returns:
            tuple: The parsed body, and the ETag the response carries or None
                when it carries none.

        Raises:
            InvalidResponseError: If the body is empty, is not valid JSON or is
                not a JSON object.

        """
        etag: str | None = response.headers.get("Etag")
        try:
            json_data: Any = await response.json(content_type=None)
        except ValueError as e:
            msg = f"Response from {method} is not valid JSON: {_describe(e)}"
            raise InvalidResponseError(msg, status=200) from e
        if not isinstance(json_data, dict):
            msg = f"Response from {method} is not a JSON object"
            raise InvalidResponseError(msg, status=200)
        if not json_data:
            msg = f"Response body from {method} is empty"
            raise InvalidResponseError(msg, status=200)
        return json_data, etag

    async def _handle_response(self, response: ClientResponse, method: str) -> tuple[dict[str, Any] | None, str | None]:
        """Handle the API response based on status code.

        Returns:
            tuple: The parsed body, which is None for a 304 response when the
                data has not been modified since the previous identical
                request, and the ETag the response carries or None when it
                carries none.

        Raises:
            RateLimitError: On HTTP 429.
            InvalidRequestError: On HTTP 400.
            NotFoundError: On HTTP 404.
            InvalidResponseError: On an empty or unparseable body, a body that
                is not a JSON object, or a status outside the set this method
                handles (200, 304, 400, 404, 429).

        """
        if response.status == HTTPStatus.TOO_MANY_REQUESTS:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            logger.warning("Rate limited on %s, the API asks to retry after %s seconds", method, retry_after)
            msg = f"Rate limit exceeded for method {method}"
            raise RateLimitError(msg, retry_after=retry_after)
        if response.status == HTTPStatus.BAD_REQUEST:
            error_message = await response.text()
            with contextlib.suppress(ValueError, AttributeError):
                error_message = (await response.json(content_type=None)).get("error", error_message)
            raise InvalidRequestError(error_message)
        if response.status == HTTPStatus.NOT_FOUND:
            raise NotFoundError(await response.text())
        if response.status == HTTPStatus.OK:
            return await self._handle_success_response(response, method)
        if response.status == HTTPStatus.NOT_MODIFIED:
            logger.debug("Data not modified for method %s", method)
            return None, response.headers.get("Etag")
        msg = f"Request to {method} returned an unexpected status {response.status}"
        raise InvalidResponseError(msg, status=response.status)

    def _should_retry_on_status(self, response: ClientResponse) -> bool:
        """Determine if a response status code should trigger a retry.

        Args:
            response: The HTTP response to check

        Returns:
            bool: True if the status should trigger a retry, False otherwise

        """
        return response.status in _SERVER_ERROR_STATUSES

    async def _execute_http_request(
        self,
        url: str,
        params: dict[str, Any],
        headers: dict[str, str],
        method: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Perform a single HTTP request attempt.

        Args:
            url: The URL to request
            params: Query parameters
            headers: Request headers
            method: API method name for logging

        Returns:
            tuple: The parsed response, or None if the data is not modified
                (304), and the ETag the response carries or None when it
                carries none.

        Raises:
            ClientError: On network failures and, as a ``_ServerError``, on 5xx responses.
            TimeoutError: If the attempt exceeds ``request_timeout`` seconds.
            InvalidResponseError: On an empty or unparseable body, a body that is
                not a JSON object, or an unexpected status.
            RateLimitError: On HTTP 429.
            InvalidRequestError: On HTTP 400.
            NotFoundError: On HTTP 404.

        """
        session = self._ensure_session()
        async with asyncio.timeout(self.request_timeout):
            async with session.get(url, params=params, headers=headers) as response:
                if self._should_retry_on_status(response):
                    raise _ServerError(response.status)

                return await self._handle_response(response, method)

    async def _do_request[T](
        self, method: str, from_dict: Callable[[dict[str, Any]], T], args: dict[str, Any] | None = None
    ) -> T | None:
        """Send an asynchronous request to the specified iRail API endpoint.

        This method handles API requests with rate limiting, parameter validation,
        and ETag-based caching. It supports conditional requests and manages
        various HTTP response scenarios. Network errors, timeouts and server errors (5xx)
        are retried up to ``max_retries`` times with exponential backoff. The response
        is deserialized with ``from_dict``, and its ETag is cached only after the
        response is fully accepted, so a rejected response never leaves a cache entry.

        Args:
            method (str): The iRail API endpoint method to request.
            from_dict (Callable): The deserialization function for the response body.
            args (dict, optional): Additional query parameters for the request.
                Defaults to None.

        Returns:
            The deserialized response from the API, or None if the data is
            not modified (304).

        Raises:
            ValueError: If the method is not a known endpoint or the parameters are invalid.
            RateLimitError: If the API responds with HTTP 429. The exception's ``retry_after`` holds the
                Retry-After delay in seconds, if given. The request is not retried.
            InvalidRequestError: If the API responds with HTTP 400.
            NotFoundError: If the API responds with HTTP 404.
            InvalidResponseError: If the response body is empty, is not valid JSON,
                is not a JSON object, does not match the expected model, or the status
                is outside the set the client handles (200, 304, 400, 404, 429 and the 5xx range).
            ApiUnavailableError: If the request still fails after all retries (network error,
                timeout or HTTP 5xx).

        Notes:
            - Implements rate limiting using a token-based mechanism
            - Supports ETag-based conditional requests
            - Raises RateLimitError immediately on rate limit (429) responses, without waiting or retrying
            - Retries network failures, timeouts and server errors with exponential backoff.
              Every attempt, including retries, goes through the rate limiter and the request timeout
            - An ETag is stored only for a fully accepted response, and only when the cache
              was not cleared while the request was in flight

        """
        logger.debug("Starting request to endpoint: %s", method)
        self._validate_params(method, args or {})

        url: str = f"{_API_BASE_URL}/{method}/"
        params = {"format": "json", "lang": self.lang}
        if args is not None:
            params.update(args)
        request_key: _RequestKey = (method, tuple(sorted(params.items())))
        etag_generation = self._etag_generation

        max_attempts = self.max_retries + 1
        attempt = 1
        while True:
            async with self._lock:
                await self._handle_rate_limit()

            request_headers: dict[str, str] = self._build_request_headers(request_key)
            try:
                data, etag = await self._execute_http_request(url, params, request_headers, method)
            except (ClientError, TimeoutError) as e:
                if attempt == max_attempts:
                    msg = f"Request to {method} failed after {attempt} attempt(s): {_describe(e)}"
                    raise ApiUnavailableError(msg) from e
                delay = min(_RETRY_BASE_DELAY * 2 ** (attempt - 1), _RETRY_MAX_DELAY)
                logger.warning(
                    "Request to %s failed (%s), retrying in %.1f seconds (attempt %d of %d)",
                    method,
                    _describe(e),
                    delay,
                    attempt,
                    max_attempts,
                )
                await asyncio.sleep(delay)
                attempt += 1
                continue

            if data is None:
                if etag is not None and self._etag_generation == etag_generation:
                    self._store_etag(request_key, etag)
                return None
            parsed = self._parse_response(method, data, from_dict)
            if etag is not None and self._etag_generation == etag_generation:
                self._store_etag(request_key, etag)
            return parsed

    def _parse_response[T](self, method: str, data: dict[str, Any], from_dict: Callable[[dict[str, Any]], T]) -> T:
        """Deserialize a response with the given deserialization function.

        Raises:
            InvalidResponseError: If the data does not match the response model.

        """
        try:
            return from_dict(data)
        except (LookupError, ValueError, OverflowError) as e:
            msg = f"Response from {method} does not match the expected model: {_describe(e)}"
            raise InvalidResponseError(msg) from e

    async def get_stations(self) -> StationsApiResponse | None:
        """Retrieve a list of all train stations from the iRail API.

        This method fetches the complete list of available train stations without any additional filtering parameters.

        Returns:
            StationsApiResponse or None: A StationsApiResponse object containing a list of all train stations and their details, or None if the data is not modified.

        Raises:
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
        return await self._do_request("stations", StationsApiResponse.from_dict)

    async def get_liveboard(
        self,
        station: str | None = None,
        station_id: str | None = None,
        date: str | None = None,
        time: str | None = None,
        arrdep: Literal["departure", "arrival"] = "departure",
        *,
        alerts: bool = False,
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
            alerts (bool, optional): Whether to request service alerts. Defaults to False. The iRail API currently
                ignores this for liveboards: the response has the same shape either way and carries no alerts.

        Returns:
            LiveboardApiResponse or None: A LiveboardApiResponse object containing liveboard information, or None if the data is not modified.

        Raises:
            ValueError: If the parameters are invalid.
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
        extra_params: dict[str, Any] = {
            "station": station,
            "id": station_id,
            "date": date,
            "time": time,
            "arrdep": arrdep,
            "alerts": "true" if alerts else "false",
        }
        return await self._do_request(
            "liveboard",
            LiveboardApiResponse.from_dict,
            {k: v for k, v in extra_params.items() if v is not None},
        )

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
            ValueError: If the parameters are invalid.
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
        extra_params: dict[str, Any] = {
            "from": from_station,
            "to": to_station,
            "date": date,
            "time": time,
            "timesel": timesel,
            "typeOfTransport": type_of_transport,
        }
        return await self._do_request(
            "connections",
            ConnectionsApiResponse.from_dict,
            {k: v for k, v in extra_params.items() if v is not None},
        )

    async def get_vehicle(
        self,
        vehicle_id: str,
        date: str | None = None,
        *,
        alerts: bool = False,
    ) -> VehicleApiResponse | None:
        """Retrieve detailed information about a specific train vehicle.

        Args:
            vehicle_id (str): Unique identifier of the train vehicle to retrieve information for.
            date (str, optional): Specific date for which vehicle information is requested. Defaults to None (current date).
            alerts (bool, optional): Whether to request service alerts. Defaults to False. The iRail API currently
                ignores this for vehicles: the response has the same shape either way and carries no alerts.

        Returns:
            VehicleApiResponse or None: A VehicleApiResponse object containing vehicle details, or None if the data is not modified.

        Raises:
            ValueError: If the parameters are invalid.
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            InvalidResponseError: If the response body cannot be used or does not match the response model.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with IRail() as client:
                vehicle_info = await client.get_vehicle("BE.NMBS.IC1832")

        """
        extra_params: dict[str, Any] = {"id": vehicle_id, "date": date, "alerts": "true" if alerts else "false"}
        return await self._do_request(
            "vehicle",
            VehicleApiResponse.from_dict,
            {k: v for k, v in extra_params.items() if v is not None},
        )

    async def get_composition(
        self,
        vehicle_id: str,
        data: str | None = None,
    ) -> CompositionApiResponse | None:
        """Retrieve the composition details of a specific train.

        Args:
            vehicle_id (str): The unique identifier of the train for which composition details are requested.
            data (str, optional): Additional data parameter to get all raw unfiltered data as iRail fetches it from the NMBS (set to 'all'). Defaults to None, which requests the filtered data.

        Returns:
            CompositionApiResponse or None: A CompositionApiResponse object containing train composition details, or None if the data is not modified.

        Raises:
            ValueError: If the parameters are invalid.
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            InvalidResponseError: If the response body cannot be used or does not match the response model.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with IRail() as client:
                composition = await client.get_composition('S51507')

        """
        extra_params: dict[str, str | None] = {"id": vehicle_id, "data": data}
        return await self._do_request(
            "composition",
            CompositionApiResponse.from_dict,
            {k: v for k, v in extra_params.items() if v is not None},
        )

    async def get_disturbances(self, line_break_character: str | None = None) -> DisturbancesApiResponse | None:
        """Retrieve information about current disturbances on the rail network.

        Args:
            line_break_character (str, optional): A custom character to use for line breaks in the
                disturbance description. Defaults to None, which sends no lineBreakCharacter and
                lets the API choose.

        Returns:
            DisturbancesApiResponse or None: A DisturbancesApiResponse object containing disturbance information, or None if the data is not modified.

        Raises:
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
        extra_params = {"lineBreakCharacter": line_break_character}
        return await self._do_request(
            "disturbances",
            DisturbancesApiResponse.from_dict,
            {k: v for k, v in extra_params.items() if v is not None},
        )
