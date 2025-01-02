# pyRail

A async Python wrapper for the iRail API, designed to make interacting with iRail simple and efficient.

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
Here is an example of how to use pyRail (async):

```python
from pyrail.irail import iRail

# Create an instance of the iRail class
async with iRail(format='json', lang='en') as api:

    # Make a request to the 'stations' endpoint
    stations = await api.get_stations()

    # Print the response
    print(stations)
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
2. Use docker compose
    ```bash
    docker compose run --rm pydev
    ```

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
