from datetime import datetime, timedelta
import logging

import requests
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
import homeassistant.helpers.config_validation as cv
from homeassistant.const import ATTR_ATTRIBUTION, CONF_NAME
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

REQUIREMENTS = ['pyrail==0.0.3']

_LOGGER = logging.getLogger(__name__)

CONF_ATTRIBUTION = "Data provided by iRail"
CONF_ROUTES = 'routes'
CONF_FROM = 'from'
CONF_TO = 'to'
CONF_VIA = 'via'

ICON = 'mdi:train'

SCAN_INTERVAL = timedelta(seconds=90)

def setup(hass, config):
    cfg = config.get(DOMAIN)
    hass.states.set('hello.world', 'Paulus')

    return True