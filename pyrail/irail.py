import logging
from threading import Lock
import time
from .api_endpoints import endpoints

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

session = requests.Session()

base_url = 'https://api.irail.be/{}/'

headers = {'user-agent': 'pyRail (tielemans.jorim@gmail.com)'}

"""
This module provides the iRail class for interacting with the iRail API.
"""

class iRail:
    """A Python wrapper for the iRail API.

    Attributes:
        format (str): The data format for API responses ('json', 'xml', 'jsonp').
        lang (str): The language for API responses ('nl', 'fr', 'en', 'de').

    """

    def __init__(self, format='json', lang='en'):
        """Initialize the iRail API client.

        Args:
            format (str): The format of the API responses. Default is 'json'.
            lang (str): The language for API responses. Default is 'en'.

        """
        self.format = format
        self.lang = lang
        self.tokens = 3
        self.burst_tokens = 5
        self.last_request_time = time.time()
        self.lock = Lock()
        self.etag_cache = {}
        logger.info("iRail instance created")

    @property
    def format(self):
        return self.__format

    @format.setter
    def format(self, value):
        if value in ['xml', 'json', 'jsonp']:
            self.__format = value
        else:
            self.__format = 'json'

    @property
    def lang(self):
        return self.__lang

    @lang.setter
    def lang(self, value):
        if value in ['nl', 'fr', 'en', 'de']:
            self.__lang = value
        else:
            self.__lang = 'en'

    def _refill_tokens(self):
        logger.debug("Refilling tokens")
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        self.last_request_time = current_time

        # Refill tokens, 3 tokens per second, cap tokens at 3
        self.tokens = min(3, self.tokens + elapsed * 3)
        # Refill burst tokens, 3 burst tokens per second, cap burst tokens at 5
        self.burst_tokens = min(5, self.burst_tokens + elapsed * 3)  # Cap burst tokens at 5

    def _handle_rate_limit(self):
        """Handles rate limiting by refilling tokens or waiting."""
        self._refill_tokens()

        if self.tokens < 1:
            if self.burst_tokens >= 1:
                self.burst_tokens -= 1
            else:
                logger.warning("Rate limiting active, waiting for tokens")
                time.sleep(1 - (time.time() - self.last_request_time))
                self._refill_tokens()
                self.tokens -= 1
        else:
            self.tokens -= 1

    def _add_etag_header(self, method):
        """Adds ETag header if a cached ETag exists."""
        headers = {}
        if method in self.etag_cache:
            logger.debug("Adding If-None-Match header with value: %s", self.etag_cache[method])
            headers['If-None-Match'] = self.etag_cache[method]
        return headers

    def do_request(self, method, args=None):
        logger.info("Starting request to endpoint: %s", method)
        with self.lock:
            self._handle_rate_limit()

        if method in endpoints:
            url = base_url.format(method)
            params = {'format': self.format, 'lang': self.lang}
            if args:
                params.update(args)

            request_headers = self._add_etag_header(method)

            try:
                response = session.get(url, params=params, headers=request_headers)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 1))
                    logger.warning("Rate limited, retrying after %d seconds", retry_after)
                    time.sleep(retry_after)
                    return self.do_request(method, args)
                if response.status_code == 200:
                    # Cache the ETag from the response
                    if 'Etag' in response.headers:
                        self.etag_cache[method] = response.headers['Etag']
                    try:
                        json_data = response.json()
                        return json_data
                    except ValueError:
                        logger.error("Failed to parse JSON response")
                        return -1
                elif response.status_code == 304:
                    logger.info("Data not modified, using cached data")
                    return None
                else:
                    logger.error("Request failed with status code: %s", response.status_code)
                    return None
            except requests.exceptions.RequestException as e:
                logger.error("Request failed: %s", e)
                try:
                    session.get('https://1.1.1.1/', timeout=1)
                except requests.exceptions.ConnectionError:
                    logger.error("Internet connection failed")
                    return -1
                else:
                    logger.error("iRail API failed")
                    return -1

    def get_stations(self):
        """Retrieve a list of all stations."""
        return self.do_request('stations')

    def get_liveboard(self, station=None, id=None):
        if bool(station) ^ bool(id):
            extra_params = {'station': station, 'id': id}
            return self.do_request('liveboard', extra_params)

    def get_connections(self, from_station=None, to_station=None):
        if from_station and to_station:
            extra_params = {'from': from_station, 'to': to_station}
            return self.do_request('connections', extra_params)

    def get_vehicle(self, id=None):
        if id:
            extra_params = {'id': id}
            return self.do_request('vehicle', extra_params)
