import requests
import time
from threading import Lock

session = requests.Session()

base_url = 'https://api.irail.be/{}/'

methods = {
    'stations': [],
    'liveboard': ['id', 'station', 'date', 'time', 'arrdep', 'alerts'],
    'connections': ['from', 'to', 'date', 'time', 'timesel', 'typeOfTransport', 'alerts', 'results'],
    'vehicle': ['id', 'date', 'alerts'],
    'disturbances': []
    }

headers = {'user-agent': 'pyRail (tielemans.jorim@gmail.com)'}

class iRail:

    def __init__(self, format='json', lang='en'):
        self.format = format
        self.lang = lang
        self.tokens = 3
        self.burst_tokens = 5
        self.last_request_time = time.time()
        self.lock = Lock()

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
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        self.last_request_time = current_time

        # Refill tokens based on elapsed time
        self.tokens += elapsed * 3  # 3 tokens per second
        if self.tokens > 3:
            self.tokens = 3

        # Refill burst tokens
        self.burst_tokens += elapsed * 3  # 3 burst tokens per second
        if self.burst_tokens > 5:
            self.burst_tokens = 5

    def do_request(self, method, args=None):
        with self.lock:
            self._refill_tokens()

            if self.tokens < 1:
                if self.burst_tokens >= 1:
                    self.burst_tokens -= 1
                else:
                    time.sleep(1 - (time.time() - self.last_request_time))
                    self._refill_tokens()
                    self.tokens -= 1
            else:
                self.tokens -= 1

        if method in methods:
            url = base_url.format(method)
            params = {'format': self.format, 'lang': self.lang}
            if args:
                params.update(args)
            try:
                response = session.get(url, params=params, headers=headers)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 1))
                    time.sleep(retry_after)
                    return self.do_request(method, args)
                try:
                    json_data = response.json()
                    return json_data
                except ValueError:
                    return -1
            except requests.exceptions.RequestException as e:
                print(e)
                try:
                    session.get('https://1.1.1.1/', timeout=1)
                except requests.exceptions.ConnectionError:
                    print("Your internet connection doesn't seem to be working.")
                    return -1
                else:
                    print("The iRail API doesn't seem to be working.")
                    return -1

    def get_stations(self):
        """Retrieve a list of all stations."""
        json_data = self.do_request('stations')
        return json_data

    def get_liveboard(self, station=None, id=None):
        if bool(station) ^ bool(id):
            extra_params = {'station': station, 'id': id}
            json_data = self.do_request('liveboard', extra_params)
            return json_data

    def get_connections(self, from_station=None, to_station=None):
        if from_station and to_station:
            extra_params = {'from': from_station, 'to': to_station}
            json_data = self.do_request('connections', extra_params)
            return json_data

    def get_vehicle(self, id=None):
        if id:
            extra_params = {'id': id}
            json_data = self.do_request('vehicle', extra_params)
            return json_data
