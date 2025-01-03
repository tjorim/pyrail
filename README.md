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
            async with iRail() as client:
                # Get the total number of stations
                stations = await api.get_stations()
                if stations:
                    print(f"Total stations: {len(stations)}")
                # Get the liveboard for a specific station
                liveboard = await client.get_liveboard(station='Brussels-South')
                if liveboard:
                    print(f"Liveboard for Brussels-South: {liveboard}")
        except Exception as e:
            print(f"Error occurred: {e}")
    # Parallel requests example
    async with iRail() as api:
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

# Run the async code
if __name__ == "__main__":
    asyncio.run(main())
```

## Configuration
You can configure the format and language for the API requests:

```python
api = iRail(format='json', lang='en')
```

- Supported formats: json, xml, jsonp
- Supported languages: nl, fr, en, de

## Development
1. Clone the repository:
    ```bash
    git clone https://github.com/tjorim/pyrail.git
    ```
2. Open the project in a devcontainer:
    ```bash
    cd pyrail
    code .
    ```
Make sure you have the Remote - Containers extension installed in VS Code. The devcontainer setup includes all necessary dependencies and tools for development.

## Logging
You can set the logging level at runtime to get detailed logs:

```python
import logging

api.set_logging_level(logging.DEBUG)
```

## Contributing
Contributions are welcome! Please open an issue or submit a pull request.

## Contributors
- @tjorim
- @jcoetsie
- @lgnap

## License
This project is licensed under the Apache 2.0 License. See the LICENSE file for details.
