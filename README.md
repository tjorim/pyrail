# pyRail

A Python wrapper for the iRail API.

## Overview

pyRail is a Python library that provides a convenient interface for interacting with the iRail API. It supports various endpoints such as stations, liveboard, vehicle, connections, and disturbances. The library also includes features like caching and rate limiting to optimize API usage.

## Installation

To install pyRail, use pip:

```sh
pip install pyrail
```

## Usage
Here is an example of how to use pyRail:

```python
from pyrail.irail import iRail

# Create an instance of the iRail class
api = iRail(format='json', lang='en')

# Make a request to the 'stations' endpoint
response = api.do_request('stations')

# Print the response
print(response)
```

## Features

- Supports multiple endpoints: stations, liveboard, vehicle, connections, disturbances
- Caching and conditional GET requests using ETag
- Rate limiting to handle API rate limits

## Configuration

You can configure the format and language for the API requests:

```python
api = iRail(format='json', lang='en')
```

Supported formats: json, xml, jsonp

Supported languages: nl, fr, en, de

## Logging

You can set the logging level at runtime to get detailed logs:

```python
api.set_logging_level(logging.DEBUG)
```

## Contributing
Contributions are welcome! Please open an issue or submit a pull request.

## Contributors
- @tjorim
- @jcoetsie

## License

This project is licensed under the MIT License. See the LICENSE file for details.


