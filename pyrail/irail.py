from .api_methods import methods
import aiohttp
import asyncio

base_url = 'https://api.irail.be/{}/'
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

    async def do_request(self, method, args=None):
        if method in methods:
            url = base_url.format(method)
            params = {'format': self.format, 'lang': self.lang}
            if args:
                params.update(args)
            
            async with aiohttp.ClientSession(headers=headers) as session:
                try:
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            try:
                                return await response.json()
                            except aiohttp.ContentTypeError:
                                return -1
                        else:
                            print(f"HTTP error: {response.status}")
                            return -1
                except aiohttp.ClientError as e:
                    print(f"Request failed: {e}")
                    return -1

            

    async def get_stations(self):
        """Retrieve a list of all stations."""
        return await self.do_request('stations')

    async def get_liveboard(self, station=None, id=None):
        if bool(station) ^ bool(id):
            extra_params = {'station': station, 'id': id}
            return await self.do_request('liveboard', extra_params)

    async def get_connections(self, from_station=None, to_station=None):
        if from_station and to_station:
            extra_params = {'from': from_station, 'to': to_station}
            return await self.do_request('connections', extra_params)

    async def get_vehicle(self, id=None):
        if id:
            extra_params = {'id': id}
            return await self.do_request('vehicle', extra_params)
