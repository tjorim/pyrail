"""Module providing the iRail class for interacting with the iRail API."""

import asyncio
from asyncio import Lock
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import time
from types import TracebackType
from typing import Any, Type

from aiohttp import ClientError, ClientResponse, ClientSession

from pyrail.exceptions import ApiUnavailableError, InvalidRequestError, NotFoundError, RateLimitError
from pyrail.models import (
    CompositionApiResponse,
    ConnectionsApiResponse,
    DisturbancesApiResponse,
    LiveboardApiResponse,
    StationsApiResponse,
    VehicleApiResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger: logging.Logger = logging.getLogger(__name__)

# API base URL constant
_API_BASE_URL = "https://api.irail.be/v1"

# Retry policy: exponential backoff starting at _RETRY_BASE_DELAY seconds, capped at _RETRY_MAX_DELAY seconds
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 10.0

# The API silently falls back to 'automatic' for a typeOfTransport it does not recognise, and it only
# recognises 'no_international_trains', so the spelling without underscores is translated.
_TYPE_OF_TRANSPORT_ALIASES = {"nointernationaltrains": "no_international_trains"}


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
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0, int((retry_at - datetime.now(timezone.utc)).total_seconds()))


class _ServerError(ClientError):
    """Raised for 5xx responses so that they are retried like network failures."""

    def __init__(self, status: int) -> None:
        super().__init__(f"Server error {status}")
        self.status = status


class iRail:
    """A Python wrapper for the iRail API, handling rate limiting and endpoint requests.

    Attributes:
        lang (str): The language for API responses ('nl', 'fr', 'en', 'de').
        session (ClientSession, optional): The HTTP session used for API requests.
            If not provided, a new session will be created and managed internally.
            If provided, the session lifecycle must be managed externally.
        max_retries (int): How many times a request is retried after a network error, timeout or
            server error (5xx). Each attempt goes through the rate limiter. 0 disables retrying.

    Endpoints:
        stations: Retrieve all stations.
        liveboard: Retrieve a liveboard for a station or ID.
        connections: Retrieve connections between two stations.
        vehicle: Retrieve information about a specific train.
        composition: Retrieve the composition of a train.
        disturbances: Retrieve information about current disturbances on the rail network.

    """

    # Available iRail API endpoints and their parameter requirements.
    # Each endpoint is configured with required parameters, optional parameters, and XOR
    # parameter groups (where exactly one parameter from the group must be provided).
    endpoints: dict[str, dict[str, Any]] = {
        "stations": {},
        "liveboard": {"xor": ["station", "id"], "optional": ["date", "time", "arrdep", "alerts"]},
        "connections": {
            "required": ["from", "to"],
            "optional": ["date", "time", "timesel", "typeOfTransport"],
        },
        "vehicle": {"required": ["id"], "optional": ["date", "alerts"]},
        "composition": {"required": ["id"], "optional": ["data"]},
        "disturbances": {"optional": ["lineBreakCharacter"]},
    }

    def __init__(self, lang: str = "en", session: ClientSession | None = None, max_retries: int = 2) -> None:
        """Initialize the iRail API client.

        Args:
            lang (str): The language for API responses. Default is 'en'.
            session (ClientSession, optional): An existing aiohttp session. Defaults to None.
            max_retries (int): Number of retries after a transient failure. Default is 2 (3 attempts in total).
                Use 0 to disable retrying.

        Raises:
            ValueError: If max_retries is negative.

        """
        if max_retries < 0:
            raise ValueError("max_retries must be 0 or greater")
        self.max_retries: int = max_retries
        self.lang: str = lang
        self.tokens: int = 3
        self.burst_tokens: int = 5
        self.last_request_time: float = time.time()
        self.lock: Lock = Lock()
        self.session: ClientSession | None = session
        self._owns_session = session is None  # Track ownership
        self.etag_cache: dict[str, str] = {}
        logger.info("iRail instance created")

    async def __aenter__(self) -> "iRail":
        """Initialize the aiohttp client session when entering the async context."""
        if self.session and not self.session.closed:
            logger.debug("Using externally provided session")
        elif not self.session:
            logger.debug("Creating new internal aiohttp session")
            self.session = ClientSession()
        return self

    async def __aexit__(
        self, exc_type: Type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        """Close the aiohttp client session when exiting the async context."""
        if self.session:
            if self.session.closed:
                logger.debug("Session is already closed, skipping closure")
            elif not self._owns_session:
                logger.debug("Session is externally provided; not closing it")
            else:
                logger.debug("Closing aiohttp session")
                try:
                    await self.session.close()
                except Exception as e:
                    logger.error("Error while closing aiohttp session: %s", e)

    @property
    def lang(self) -> str:
        """Get the language setting for API requests.

        Returns:
            str: The current language setting ('nl', 'fr', 'en', 'de').

        """
        return self.__lang

    @lang.setter
    def lang(self, value: str) -> None:
        """Set the language for API requests.

        Args:
            value (str): The language to use. Must be one of: 'nl', 'fr', 'en', 'de'.
                        If an invalid value is provided, defaults to 'en'.

        """
        if value in ["nl", "fr", "en", "de"]:
            self.__lang = value
        else:
            self.__lang = "en"

    def clear_etag_cache(self) -> None:
        """Clear the ETag cache."""
        self.etag_cache.clear()
        logger.info("ETag cache cleared")

    def _refill_tokens(self) -> None:
        """Refill tokens for rate limiting using a token bucket algorithm.

        - Standard tokens: Refill rate of 3 tokens/second, max 3 tokens.
        - Burst tokens: Refilled only when standard tokens are full, max 5 tokens.
        """
        logger.debug("Refilling tokens")
        current_time: float = time.time()
        elapsed: float = current_time - self.last_request_time
        self.last_request_time = current_time

        # Refill tokens, 3 tokens per second, cap tokens at 3
        self.tokens = min(3, self.tokens + int(elapsed * 3))

        # Refill burst tokens only if the request rate is below 3 requests per second
        if self.tokens == 3:
            self.burst_tokens = min(5, self.burst_tokens + int(elapsed * 3))

    async def _handle_rate_limit(self) -> None:
        """Handle rate limiting using a token bucket algorithm.

        - Standard tokens: 3 requests/second.
        - Burst tokens: Additional 5 requests/second for spikes.
        - Waits and refills tokens if both are exhausted.
        """
        logger.debug("Handling rate limit")
        self._refill_tokens()
        if self.tokens < 1:
            if self.burst_tokens >= 1:
                self.burst_tokens -= 1
            else:
                logger.warning("Rate limiting active, waiting for tokens")
                wait_time = max(0, 1 - (time.time() - self.last_request_time))
                await asyncio.sleep(wait_time)
                self._refill_tokens()
                self.tokens -= 1
        else:
            self.tokens -= 1

    def _add_etag_header(self, method: str) -> dict[str, str]:
        """Add ETag header for the given method if a cached ETag is available.

        Args:
            method (str): The API endpoint for which the header is being generated.

        Returns:
            dict[str, str]: A dictionary containing HTTP headers, including the ETag header
            if a cached value exists.

        """
        headers: dict[str, str] = {"User-Agent": "pyRail (https://github.com/tjorim/pyrail; tielemans.jorim@gmail.com)"}
        if method in self.etag_cache:
            logger.debug("Adding If-None-Match header with value: %s", self.etag_cache[method])
            headers["If-None-Match"] = self.etag_cache[method]
        return headers

    def _validate_date(self, date: str | None) -> bool:
        """Validate the date format (DDMMYY).

        Args:
            date (str, optional): The date string to validate. Expected format is DDMMYY,
            e.g., '150923' for September 15, 2023.

        Returns:
            bool: True if the date is valid or None is provided, False otherwise.

        """
        if date is None:
            return True
        try:
            datetime.strptime(date, "%d%m%y")
            return True
        except ValueError:
            logger.error("Invalid date format. Expected DDMMYY (e.g., 150923 for September 15, 2023), got: %s", date)
            return False

    def _validate_time(self, time: str | None) -> bool:
        """Validate the time format (HHMM).

        Args:
            time (str, optional): The time string to validate. Expected format is HHMM,
            e.g., '1430' for 2:30 PM.

        Returns:
            bool: True if the time is valid or None is provided, False otherwise.

        """
        if time is None:
            return True
        try:
            datetime.strptime(time, "%H%M")
            return True
        except ValueError:
            logger.error("Invalid time format. Expected HHMM (e.g., 1430 for 2:30 PM), got: %s", time)
            return False

    def _validate_params(self, method: str, params: dict[str, Any] | None = None) -> bool:
        """Validate parameters for a specific iRail API endpoint based on predefined requirements.

        Args:
            method (str): The API endpoint method to validate parameters for.
            params (dict[str, Any], optional): Dictionary of parameters to validate. Defaults to None.

        Returns:
            bool: True if parameters are valid, False otherwise.

        Raises:
            No explicit exceptions raised. Uses logging to report validation errors.

        Validates the following conditions:
            1. Checks if the method is a known endpoint
            2. Ensures all required parameters are present
            3. Enforces XOR (exclusive OR) parameter logic where applicable
            4. Prevents unexpected parameters from being included

        Example:
            # Validates parameters for the liveboard endpoint
            is_valid = self._validate_params('liveboard', {'station': 'Brussels', 'date': '150923'})

        """
        if method not in self.endpoints:
            logger.error("Unknown API endpoint: %s", method)
            return False

        endpoint = self.endpoints[method]
        required = endpoint.get("required", [])
        xor = endpoint.get("xor", [])
        optional = endpoint.get("optional", [])

        params = params or {}

        # Validate date and time formats if present
        if "date" in params and not self._validate_date(params["date"]):
            return False
        if "time" in params and not self._validate_time(params["time"]):
            return False

        # Ensure all required parameters are present
        for param in required:
            if param not in params or params[param] is None:
                logger.error("Missing required parameter: %s for endpoint: %s", param, method)
                return False

        # Check XOR logic (only one of XOR parameters can be set)
        if xor:
            xor_values = [params.get(param) is not None for param in xor]
            if sum(xor_values) != 1:
                logger.error("Exactly one of the XOR parameters %s must be provided for endpoint: %s", xor, method)
                return False

        # Ensure no unexpected parameters are included
        all_params = required + xor + optional
        for param in params.keys():
            if param not in all_params:
                logger.error("Unexpected parameter: %s for endpoint: %s", param, method)
                return False

        return True

    async def _handle_success_response(self, response: ClientResponse, method: str) -> dict[str, Any] | None:
        """Handle a successful API response."""
        if "Etag" in response.headers:
            self.etag_cache[method] = response.headers["Etag"]
        try:
            json_data: dict[str, Any] | None = await response.json()
            if json_data is None or not json_data:
                logger.warning("Empty response received")
            return json_data
        except ValueError:
            logger.error("Failed to parse JSON response")
            return None

    async def _handle_response(
        self, response: ClientResponse, method: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Handle the API response based on status code."""
        if response.status == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            logger.warning("Rate limited on %s, the API asks to retry after %s seconds", method, retry_after)
            raise RateLimitError(f"Rate limit exceeded for method {method}", retry_after=retry_after)
        elif response.status == 400:
            error_message = await response.text()
            try:
                error_message = (await response.json()).get("error", error_message)
            except (ValueError, AttributeError):
                pass
            logger.error("Bad request: %s", error_message)
            raise InvalidRequestError(error_message)
        elif response.status == 404:
            error_message = await response.text()
            logger.error("Endpoint %s not found, response: %s", method, error_message)
            raise NotFoundError(error_message)
        elif response.status == 200:
            return await self._handle_success_response(response, method)
        elif response.status == 304:
            logger.info("Data not modified, using cached data for method %s", method)
            return None
        else:
            logger.error("Request failed with status code: %s, response: %s", response.status, await response.text())
            return None

    def _should_retry_on_status(self, response: ClientResponse) -> bool:
        """Determine if a response status code should trigger a retry.

        Args:
            response: The HTTP response to check

        Returns:
            bool: True if the status should trigger a retry, False otherwise

        """
        # Retry on server errors (5xx) but not on client errors (4xx except 429)
        # 429 is handled separately in _handle_response
        return 500 <= response.status < 600

    async def _execute_http_request(
        self, url: str, params: dict[str, Any], headers: dict[str, str], method: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Perform a single HTTP request attempt.

        Args:
            url: The URL to request
            params: Query parameters
            headers: Request headers
            method: API method name for logging
            args: Original method arguments, passed on to the response handler

        Returns:
            dict or None: Parsed response, or None if the response is not usable

        Raises:
            ClientError: On network failures and, as a ``_ServerError``, on 5xx responses.
            TimeoutError: If the request times out.

        """
        if self.session is None:
            logger.error("Session not initialized")
            return None

        async with self.session.get(url, params=params, headers=headers) as response:
            if self._should_retry_on_status(response):
                raise _ServerError(response.status)

            return await self._handle_response(response, method, args)

    async def _do_request(self, method: str, args: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Send an asynchronous request to the specified iRail API endpoint.

        This method handles API requests with rate limiting, parameter validation,
        and ETag-based caching. It supports conditional requests and manages
        various HTTP response scenarios. Network errors, timeouts and server errors (5xx)
        are retried up to ``max_retries`` times with exponential backoff.

        Args:
            method (str): The iRail API endpoint method to request.
            args (dict, optional): Additional query parameters for the request.
                Defaults to None.

        Returns:
            dict or None: Parsed JSON response from the API if successful,
                None if the data is not modified (304), the server returns an unexpected
                status, or the body cannot be parsed.

        Raises:
            RateLimitError: If the API responds with HTTP 429. The exception's ``retry_after`` holds the
                Retry-After delay in seconds, if given. The request is not retried.
            InvalidRequestError: If the API responds with HTTP 400.
            NotFoundError: If the API responds with HTTP 404.
            ApiUnavailableError: If the request still fails after all retries (network error, timeout or HTTP 5xx).

        Notes:
            - Implements rate limiting using a token-based mechanism
            - Supports ETag-based conditional requests
            - Raises RateLimitError immediately on rate limit (429) responses, without waiting or retrying
            - Retries network failures, timeouts and server errors with exponential backoff;
              every attempt, including retries, goes through the rate limiter
            - Logs detailed information about request processing

        """
        logger.info("Starting request to endpoint: %s", method)
        if self.session is None:
            logger.error("Session not initialized. Use 'async with' context manager to initialize the client.")
            return None
        if not self._validate_params(method, args or {}):
            logger.error("Validation failed for method: %s with args: %s", method, args)
            return None

        # Construct the request URL and parameters
        url: str = f"{_API_BASE_URL}/{method}/"
        params = {"format": "json", "lang": self.lang}
        if args is not None:
            params.update(args)

        max_attempts = self.max_retries + 1
        for attempt in range(1, max_attempts + 1):
            # Every attempt consumes a rate limit token, so retries cannot exceed the API limits
            async with self.lock:
                await self._handle_rate_limit()

            request_headers: dict[str, str] = self._add_etag_header(method)
            try:
                return await self._execute_http_request(url, params, request_headers, method, args)
            except (ClientError, TimeoutError) as e:
                if attempt == max_attempts:
                    logger.error("Request to %s failed after %d attempt(s): %s", method, attempt, _describe(e))
                    raise ApiUnavailableError(
                        f"Request to {method} failed after {attempt} attempt(s): {_describe(e)}"
                    ) from e
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
        return None  # pragma: no cover - the loop always returns or raises

    async def get_stations(self) -> StationsApiResponse | None:
        """Retrieve a list of all train stations from the iRail API.

        This method fetches the complete list of available train stations without any additional filtering parameters.

        Returns:
            StationsApiResponse or None: A StationsApiResponse object containing a list of all train stations and their details, or None if the data is not modified.

        Raises:
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with iRail() as client:
                stations = await client.get_stations()
                if stations:
                    print(f"Total stations: {len(stations.stations)}")

        """
        stations_response_dict = await self._do_request("stations")
        if stations_response_dict is None:
            return None
        return StationsApiResponse.from_dict(stations_response_dict)

    async def get_liveboard(
        self,
        station: str | None = None,
        id: str | None = None,
        date: str | None = None,
        time: str | None = None,
        arrdep: str = "departure",
        alerts: bool = False,
    ) -> LiveboardApiResponse | None:
        """Retrieve a liveboard for a specific train station.

        Asynchronously fetches live departure or arrival information for a given station.
        Provide exactly one of 'station' or 'id'.

        Args:
            station (str): Name of the train station.
            id (str): Unique identifier of the train station.
            date (str, optional): Date for the liveboard in format 'DDMMYY', in Belgian local time. Defaults to current date.
            time (str, optional): Time for the liveboard in format 'HHMM', in Belgian local time. Defaults to current time.
            arrdep (str, optional): Type of board to retrieve. Either 'departure' (default) or 'arrival'.
            alerts (bool, optional): Whether to request service alerts. Defaults to False. The iRail API currently
                ignores this for liveboards: the response has the same shape either way and carries no alerts.

        Returns:
            LiveboardApiResponse or None: A LiveboardApiResponse object containing liveboard information, or None if the data is not modified.

        Raises:
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with iRail() as client:
                liveboard = await client.get_liveboard(station='Brussels-South')
                if liveboard:
                    print(f"Liveboard for Brussels-South: {liveboard}")

        """
        extra_params: dict[str, Any] = {
            "station": station,
            "id": id,
            "date": date,
            "time": time,
            "arrdep": arrdep,
            "alerts": "true" if alerts else "false",
        }
        liveboard_response_dict = await self._do_request(
            "liveboard", {k: v for k, v in extra_params.items() if v is not None}
        )
        if liveboard_response_dict is None:
            return None
        return LiveboardApiResponse.from_dict(liveboard_response_dict)

    async def get_connections(
        self,
        from_station: str,
        to_station: str,
        date: str | None = None,
        time: str | None = None,
        timesel: str = "departure",
        type_of_transport: str = "automatic",
    ) -> ConnectionsApiResponse | None:
        """Retrieve train connections between two stations using the iRail API.

        Args:
            from_station (str): Name or ID of the departure station
            to_station (str): Name or ID of the arrival station
            date (str, optional): Date of travel in format 'DDMMYY', in Belgian local time (default: current date)
            time (str, optional): Time of travel in format 'HHMM', in Belgian local time (default: current time)
            timesel (str, optional): Time selection type, either 'departure' or 'arrival' (default: 'departure')
            type_of_transport (str, optional): Type of transport, one of 'automatic', 'trains', 'no_international_trains'
                or 'all' (default: 'automatic'). The spelling 'nointernationaltrains' is accepted as an alias.
                The API silently treats any other value as 'automatic'.

        Returns:
            ConnectionsApiResponse or None: A ConnectionsApiResponse object containing connection details, or None if the data is not modified.

        Raises:
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with iRail() as client:
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
            "typeOfTransport": _TYPE_OF_TRANSPORT_ALIASES.get(type_of_transport, type_of_transport),
        }
        connections_response_dict = await self._do_request(
            "connections", {k: v for k, v in extra_params.items() if v is not None}
        )
        if connections_response_dict is None:
            return None
        return ConnectionsApiResponse.from_dict(connections_response_dict)

    async def get_vehicle(self, id: str, date: str | None = None, alerts: bool = False) -> VehicleApiResponse | None:
        """Retrieve detailed information about a specific train vehicle.

        Args:
            id (str): Unique identifier of the train vehicle to retrieve information for.
            date (str, optional): Specific date for which vehicle information is requested. Defaults to None (current date).
            alerts (bool, optional): Flag to include service alerts for the vehicle. Defaults to False.

        Returns:
            VehicleApiResponse or None: A VehicleApiResponse object containing vehicle details, or None if the data is not modified.

        Raises:
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with iRail() as client:
                vehicle_info = await client.get_vehicle("BE.NMBS.IC1832")

        """
        extra_params: dict[str, Any] = {"id": id, "date": date, "alerts": "true" if alerts else "false"}
        vehicle_response_dict = await self._do_request(
            "vehicle", {k: v for k, v in extra_params.items() if v is not None}
        )
        if vehicle_response_dict is None:
            return None
        return VehicleApiResponse.from_dict(vehicle_response_dict)

    async def get_composition(self, id: str, data: str | None = None) -> CompositionApiResponse | None:
        """Retrieve the composition details of a specific train.

        Args:
            id (str): The unique identifier of the train for which composition details are requested.
            data (str, optional): Additional data parameter to get all raw unfiltered data as iRail fetches it from the NMBS (set to 'all'). Defaults to None, which requests the filtered data.

        Returns:
            CompositionApiResponse or None: A CompositionApiResponse object containing train composition details, or None if the data is not modified.

        Raises:
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with iRail() as client:
                composition = await client.get_composition('S51507')

        """
        extra_params: dict[str, str | None] = {"id": id, "data": data}
        composition_response_dict = await self._do_request(
            "composition", {k: v for k, v in extra_params.items() if v is not None}
        )
        if composition_response_dict is None:
            return None
        return CompositionApiResponse.from_dict(composition_response_dict)

    async def get_disturbances(self, line_break_character: str | None = None) -> DisturbancesApiResponse | None:
        """Retrieve information about current disturbances on the rail network.

        Args:
            line_break_character (str, optional): A custom character to use for line breaks in the disturbance description. Defaults to ''.

        Returns:
            DisturbancesApiResponse or None: A DisturbancesApiResponse object containing disturbance information, or None if the data is not modified.

        Raises:
            RateLimitError: If the API rate limit is exceeded.
            InvalidRequestError: If the request is invalid.
            NotFoundError: If the requested resource is not found.
            ApiUnavailableError: If the API cannot be reached after all retries.

        Example:
            async with iRail() as client:
                disturbances = await client.get_disturbances()
                if disturbances:
                    print(f"Current disturbances: {disturbances}")

        """
        extra_params = {"lineBreakCharacter": line_break_character}
        disturbances_response_dict = await self._do_request(
            "disturbances", {k: v for k, v in extra_params.items() if v is not None}
        )
        if disturbances_response_dict is None:
            return None
        return DisturbancesApiResponse.from_dict(disturbances_response_dict)
