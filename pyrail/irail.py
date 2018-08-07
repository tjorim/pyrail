import requests

session = requests.Session()

base_url = 'https://api.irail.be/{}/'

methods = {
    'stations': [],
    'liveboard': ['station'],
    'connections': ['from', 'to'],
    'vehicle': ['id'],
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
            return session.get(url, params=params, headers=headers)

    def get_stations(self):
        """Retrieve a list of all stations."""
        response = self.do_request('stations')
        return response.json()
