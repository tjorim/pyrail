# pyRail

An async Python wrapper for the iRail API, designed to make interacting with iRail simple and efficient.
Built with aiohttp, it provides non-blocking I/O operations for optimal performance in async applications.

## Overview

pyRail is a Python library that provides a convenient interface for interacting with the iRail API. It supports various endpoints such as stations, liveboard, vehicle, connections, and disturbances. The library includes features like caching and rate limiting to optimize API usage.

## Features

- Async handling
- Retrieve real-time train information, including liveboards and vehicle details.
- Access train station data, connections, and disturbances.
- Supports API endpoints: stations, liveboard, vehicle, connections, and disturbances.
- Caching and conditional GET requests using ETags.
- Rate limiting to handle API request limits efficiently.

## Installation

To install pyRail, use pip:

```bash
pip install pyrail
```

## Usage

Here is an example of how to use pyRail asynchronously:

```python
import asyncio
from pyrail.irail import iRail

async def main():
    # Sequential requests example
    async with iRail() as api:
        try:
            # Get the total number of stations
            stations = await api.get_stations()
            if stations:
                print(f"Total stations: {len(stations)}")
            # Get the liveboard for a specific station
            liveboard = await api.get_liveboard(station='Brussels-South')
            if liveboard:
                print(f"Liveboard for Brussels-South: {liveboard}")
        except Exception as e:
            print(f"Error occurred: {e}")
    # Parallel requests example
    async with iRail() as api:
        try:
            connections, vehicle_info = await asyncio.gather(
                # Get connections between stations
                api.get_connections(
                    from_station='Antwerpen-Centraal',
                    to_station='Brussel-Centraal'
                ),
                # Get vehicle information
                api.get_vehicle("BE.NMBS.IC1832")
            )
            print("Parallel results:")
            print(f"Connections from Antwerpen-Centraal to Brussel-Centraal: {connections}")
            print(f"Vehicle information for BE.NMBS.IC1832: {vehicle_info}")
        except Exception as e:
            print(f"Error occurred in parallel requests: {e}")

# Run the async code
if __name__ == "__main__":
    asyncio.run(main())
```

### Language Selection

You can configure the language for the API requests:

```python
api = iRail(lang='nl')
```

Supported languages are:

- `en` (English, default)
- `fr` (French)
- `de` (German)
- `nl` (Dutch)

If no language is specified or an invalid value is provided, English (`en`) will be used as the default language.

### Session Management

You can provide an external aiohttp ClientSession:

```python
from aiohttp import ClientSession

async def main():
    # Using an external session
    async with ClientSession() as session:
        async with iRail(session=session) as api:
            stations = await api.get_stations()
            print(f"Total stations: {len(stations)}")

    # Or let iRail manage its own session
    async with iRail() as api:
        stations = await api.get_stations()
```

### Cache Management

You can clear the ETag cache when needed:

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
    for station in ['Brussels-South', 'Antwerp-Central', 'Ghent-Sint-Pieters']:
        liveboard = await api.get_liveboard(station=station)
```

Exceeding the request limit will cause the server to return 429 responses. You can monitor rate limiting through debug logs.

## Development

The devcontainer setup includes all necessary dependencies and tools for development.

### Prerequisites

- Docker
- Visual Studio Code
- Remote - Containers extension

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/tjorim/pyrail.git
   ```
2. Open the project in a devcontainer:
   ```bash
    cd pyrail
    code .
   ```
3. Once VS Code opens, it will detect the devcontainer configuration and prompt you to reopen the project in a container. Click "Reopen in Container" to start the development environment.

### Running Tests

To run the tests, use the following command in the terminal within the devcontainer:

```
pytest
```

### Code Style

We use ruff for code formatting and linting. To check your code style, run:

```
ruff check .
```

To automatically fix style issues, run:

```
ruff check . --fix
```

## Logging

pyRail uses Python's built-in logging module. You can set the logging level at runtime to get detailed logs.

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
2. Ensure your code adheres to the project's style guide (run `ruff check .`).
3. Add or update tests as necessary.
4. Update documentation to reflect your changes.
5. Submit a pull request with a clear title and description.

## Contributors

- @tjorim
- @jcoetsie
- @lgnap

## License

This project is licensed under the Apache 2.0 License. See the LICENSE file for details.
