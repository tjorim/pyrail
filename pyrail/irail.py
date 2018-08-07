import requests

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

    def __init__(self, format=None, lang=None):
        if format is None:
            format = 'json'
        self.format = format
        if lang is None:
            lang = 'en'
        self.lang = lang

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

    def do_request(self, method, args=None):
        if method in methods:
            url = base_url.format(method)
            params = {'format': self.format, 'lang': self.lang}
            if args:
                params.update(args)
            try:
                response = session.get(url, params=params, headers=headers)
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

    def get_connections(self, from=None, to=None):
        if from and to:
            extra_params = {'from': from, 'to': to}
            json_data = self.do_request('connections', extra_params)
            return json_data

    def get_vehicle(self, id=None):
        if id:
            extra_params = {'id': id}
            json_data = self.do_request('vehicle', extra_params)
            return json_data
