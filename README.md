# pyRail

An async Python wrapper for the iRail API, designed to make interacting with iRail simple and efficient.
Built with aiohttp, it provides non-blocking I/O operations for optimal performance in async applications.

## Overview

pyRail is a Python library that provides a convenient interface for interacting with the iRail API. It supports various endpoints such as stations, liveboard, connections, vehicle, composition, and disturbances. The library includes features like caching and rate limiting to optimize API usage.

## Features

- Async handling
- Retrieve real-time train information, including liveboards and vehicle details.
- Access train station data, connections, and disturbances.
- Supports API endpoints: stations, liveboard, connections, vehicle, composition, and disturbances.
- Conditional GET requests using ETags, when the API sends them (see [Cache Management](#cache-management)).
- Rate limiting to handle API request limits efficiently.
- Automatic retry with exponential backoff for network resilience.

## Installation

pyRail requires Python 3.12 or newer. Install it with pip:

```bash
pip install pyrail
```

or with uv:

```bash
uv add pyrail
```

## Usage

Here is an example of how to use pyRail asynchronously:

```python
import asyncio
from pyrail import iRail, PyRailError


async def main():
    # Sequential requests example
    async with iRail() as api:
        try:
            # Get the total number of stations
            stations = await api.get_stations()
            if stations:
                print(f"Total stations: {len(stations.stations)}")
                # Example output: Total stations: 691
                # stations.stations = [
                #     StationDetails(name="Brussels-South", id="BE.NMBS.008814001", ...),
                #     ...
                # ]
            # Get the liveboard for a specific station
            liveboard = await api.get_liveboard(station="Brussels-South")
            if liveboard:
                print(f"Liveboard for Brussels-South: {liveboard}")
        except PyRailError as e:
            print(f"Error occurred: {e}")
    # Parallel requests example
    async with iRail() as api:
        try:
            connections, vehicle_info = await asyncio.gather(
                # Get connections between stations
                api.get_connections(from_station="Antwerpen-Centraal", to_station="Brussel-Centraal"),
                # Get vehicle information
                api.get_vehicle("BE.NMBS.IC1832"),
            )
            print("Parallel results:")
            print(f"Connections from Antwerpen-Centraal to Brussel-Centraal: {connections}")
            print(f"Vehicle information for BE.NMBS.IC1832: {vehicle_info}")
        except PyRailError as e:
            print(f"Error occurred in parallel requests: {e}")


# Run the async code
if __name__ == "__main__":
    asyncio.run(main())
```

### Response Objects

Every method returns the full iRail response object, mirroring the API: `version` and `timestamp` sit next to the data. For list endpoints the list is an attribute of that object, so use `stations.stations`, `disturbances.disturbances` and `connections.connections`:

```python
stations = await api.get_stations()
print(stations.version, stations.timestamp)
print(len(stations.stations))
```

pyRail only changes the type of values, not their meaning: string flags become `bool`, epoch strings become `datetime`, names are snake_case, and count-only wrappers such as `departures.departure` are flattened. Data is never converted or derived.

### Date and Time

The `date` (`DDMMYY`) and `time` (`HHMM`) request parameters are interpreted as Belgian local time, so pass local clock times, not UTC.

Timestamps in responses are Unix epochs, which pyRail returns as timezone-aware `datetime` objects in UTC. Convert them for display:

```python
from zoneinfo import ZoneInfo

liveboard = await api.get_liveboard(station="Brussels-South")
if liveboard and liveboard.departures:
    departure = liveboard.departures[0]
    print(departure.time.astimezone(ZoneInfo("Europe/Brussels")).strftime("%H:%M"))
```

### Empty Liveboards

A liveboard without departures (for example at night) is a valid answer, not an error. `departures` is then an empty list, so check for `None` explicitly if you need to tell the cases apart:

```python
liveboard = await api.get_liveboard(station="Brussels-South")
if liveboard is None:
    ...  # the data was not modified since the previous request (HTTP 304)
elif not liveboard.departures:
    ...  # no departures right now
```

`liveboard` is `None` only when the data has not been modified since the previous request (HTTP 304). Invalid parameters raise a `ValueError` and an unusable response raises an `InvalidResponseError`. `liveboard.departures` is `None` when the response carries no usable departures wrapper, as on an arrival board (`arrdep="arrival"`).

### Language Selection

You can configure the language for the API requests:

```python
api = iRail(lang="nl")
```

Supported languages are:

- `en` (English, default)
- `fr` (French)
- `de` (German)
- `nl` (Dutch)

An unsupported language raises a `ValueError`, both in the constructor and on the `lang` attribute.

### Session Management

You can provide an external aiohttp ClientSession:

```python
from aiohttp import ClientSession


async def main():
    # Using an external session
    async with ClientSession() as session:
        async with iRail(session=session) as api:
            stations = await api.get_stations()
            print(f"Total stations: {len(stations.stations)}")

    # Or let iRail manage its own session
    async with iRail() as api:
        stations = await api.get_stations()
```

Without the context manager, close the owned session yourself:

```python
api = iRail()
stations = await api.get_stations()
await api.close()
```

An externally provided session is never closed by pyRail, with or without the context manager.

### Cache Management

pyRail sends `If-None-Match` for a method once the API has returned an `ETag` for it. The iRail API does not send ETags at the moment (checked October 2026), so for now this has no effect and every request returns fresh data. You can clear the ETag cache when needed:

```python
async with iRail() as api:
    # Clear the ETag cache
    api.clear_etag_cache()
    # Subsequent requests will fetch fresh data
    stations = await api.get_stations()
```

### Rate Limiting

pyRail implements rate limiting to comply with iRail API's guidelines:

- Maximum of 3 requests per second per source IP address
- 5 burst requests available, allowing up to 8 requests in 1 second

The library automatically handles rate limiting:

```python
# Rate limiting is handled automatically
async with iRail() as api:
    # These requests will be rate-limited if needed
    for station in ["Brussels-South", "Antwerp-Central", "Ghent-Sint-Pieters"]:
        liveboard = await api.get_liveboard(station=station)
```

When the limits are exhausted, a request waits only as long as the next token takes to refill, about a third of a second, so polling stays smooth instead of freezing for a full second.

Exceeding the request limit will cause the server to return 429 responses, which raise a `RateLimitError` (see [Error Handling](#error-handling)). Rate limit waits and 429 answers are logged as warnings.

### Error Handling

pyRail raises exceptions for errors returned by the iRail API and for connection failures. All of them inherit from `PyRailError`:

| Exception             | Raised when                                                                         |
| --------------------- | ----------------------------------------------------------------------------------- |
| `InvalidRequestError` | The API responds with HTTP 400 (invalid request)                                    |
| `NotFoundError`       | The API responds with HTTP 404 (resource not found)                                 |
| `RateLimitError`      | The API responds with HTTP 429 (rate limit exceeded); see `retry_after`             |
| `InvalidResponseError` | The response body is empty, is not valid JSON, does not match the response models, or has a status outside 200, 304, 400, 404 and 429. Carries the HTTP status in `status` when the failure has one |
| `ApiUnavailableError` | The API cannot be reached (network error, timeout or HTTP 5xx) after all retries   |

```python
from pyrail import iRail, NotFoundError, PyRailError, RateLimitError

async with iRail() as api:
    try:
        liveboard = await api.get_liveboard(station="Unknown station")
    except NotFoundError:
        print("Station not found")
    except RateLimitError as err:
        print(f"Rate limited, retry in {err.retry_after} seconds")
    except PyRailError as err:
        print(f"Request failed: {err}")
```

Invalid parameters, including an unsupported language, raise a `ValueError` before any request is sent. A method returns `None` only when the data has not been modified since the previous request (HTTP 304).

### Network Resilience and Retry Logic

pyRail automatically retries transient failures with exponential backoff:

- **Network Errors and Timeouts**: Connection failures, DNS errors and request timeouts are retried. Each attempt is bounded by `request_timeout` (30 seconds by default, set it on the constructor), and a timed-out attempt counts as a failure and is retried like a network error.
- **Server Errors**: HTTP 5xx responses are retried, allowing recovery from temporary server issues.
- **Client Errors**: HTTP 4xx errors are never retried, as they indicate a problem with the request. This includes 429 rate limits, which raise a `RateLimitError` immediately; its `retry_after` attribute holds the server's `Retry-After` delay in seconds (or `None`), so you decide when to try again (see [Error Handling](#error-handling)).
- **Rate Limiting**: Every attempt, including each retry, goes through the client's rate limiter.

By default a request is attempted up to 3 times in total, waiting 1s and then 2s between attempts (the delay doubles each time, capped at 10s). Use `max_retries` to change this, or set it to `0` to disable retrying:

```python
async with iRail(max_retries=5) as api:
    stations = await api.get_stations()

async with iRail(max_retries=0) as api:  # fail fast, no retries
    stations = await api.get_stations()
```

When all attempts fail, an `ApiUnavailableError` is raised, chained to the underlying error. Intermediate failures are logged as warnings. The final failure is not logged, its details travel in the raised exception.

## Development

pyRail uses [uv](https://docs.astral.sh/uv/) to manage the Python version, the virtual environment and the dependencies.

### Setup

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. Clone the repository and install the dependencies from the lock file:
   ```bash
   git clone https://github.com/tjorim/pyrail.git
   cd pyrail
   uv sync
   ```

Alternatively, use the devcontainer, which has uv and all dependencies preinstalled. You need Docker and Visual Studio Code with the *Dev Containers* extension: open the repository in VS Code and choose "Reopen in Container" when prompted.

### Running Tests

There are two test suites:

- **Offline suite** (default): runs against the recorded API responses in examples/, no network needed. It covers field assertions, validation and error handling (HTTP 400, 404, 429, retries and outages, ETags, invalid JSON, ...) and runs on every pull request and on pushes to main.
- **Live smoke suite** (`tests/live`): calls all six endpoints of the real iRail API and checks that the responses still deserialize into the library models. It asserts only stable structure, never specific trains, times or disturbances. It catches upstream API changes that the recorded responses cannot.

To run the offline suite:

```bash
uv run pytest
```

CI also enforces a coverage threshold: branch coverage over `pyrail/` must stay at or above 92 percent. Run it locally with:

```bash
uv run coverage run -m pytest && uv run coverage report
```

To run the live suite, which needs network access:

```bash
uv run pytest -m live
```

The live tests are excluded from a plain `pytest` run. Run them locally before a release. They also run daily and on demand through the *Live API Smoke Tests* workflow (Actions tab, *Run workflow*), where a failure notifies the maintainers.

The vehicle and composition requests use a vehicle id taken from a Brussels-Central liveboard, as ids go stale with the timetable. A live test fails in one of three ways:

- `API UNAVAILABLE`: no usable response after 3 attempts, for example a network error, a timeout or an HTTP error. This is usually transient on the iRail side; re-run before investigating.
- `API REJECTED REQUEST`: the API answered HTTP 400 or 404, for example an invalid parameter or a stale vehicle id. This is a request problem, not an outage.
- `API INCOMPATIBLE`: iRail answered successfully but the response no longer deserializes. The message names the endpoint and the error, and the models in `pyrail/models.py` probably need updating.

### Code Style

We use ruff for code formatting and linting. To check your code style, run:

```bash
uv run ruff check .
uv run ruff format --check .
```

To automatically fix style issues and format the code, run:

```bash
uv run ruff check . --fix
uv run ruff format .
```

We use ty for type checking:

```bash
uv run ty check .
```

ty runs every rule as an error. The settings live in `[tool.ty]` in pyproject.toml.

## Logging

pyRail uses Python's built-in logging module and adds a NullHandler to its logger, so library logs stay silent until your application adds a handler. You can set the logging level at runtime to get detailed logs.

```python
import logging

# Set the logging level to DEBUG
logging.basicConfig(level=logging.DEBUG)
```

## Contributing

Contributions are welcome! Here's how you can contribute to pyRail:

### Issue Reporting

- Use the GitHub issue tracker to report bugs or suggest features.
- Check existing issues before opening a new one.
- Provide as much detail as possible, including steps to reproduce for bugs.

### Pull Requests

1. Fork the repository and create your branch from `main`.
2. Ensure your code adheres to the project's style guidelines (run `uv run ruff check .`).
3. Add or update tests as necessary.
4. Update documentation to reflect your changes.
5. Submit a pull request with a clear title and description.
6. Your pull request will be automatically reviewed by CodeRabbit for code quality and consistency.

## Contributors

- [@tjorim](https://github.com/tjorim)
- [@Bertware](https://github.com/Bertware)
- [@DaanVervacke](https://github.com/DaanVervacke)
- [@jcoetsie](https://github.com/jcoetsie)
- [@lgnap](https://github.com/lgnap)
- [@silamon](https://github.com/silamon)

## License

This project is licensed under the Apache 2.0 License. See the LICENSE file for details.
