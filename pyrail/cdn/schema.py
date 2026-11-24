"""Required Arrow column types in the iRail CDN LC 2-alpha contract."""

# https://github.com/iRail/iRail-cdn/blob/main/specs/lc-core-schemas.json
COLUMNS = {
    "connections": {
        "departureStopIdx": "i",
        "arrivalStopIdx": "i",
        "departureTimeOffset": "I",
        "arrivalTimeOffset": "I",
        "tripIdx": "i",
        "pickupType": "B",
        "dropOffType": "B",
        "serviceDate": "I",
        "stopSequence": "I",
        "arrivalStopSequence": "I",
        "iri": "utf8",
    },
    "stops": {
        "name": "utf8",
        "lat": "d",
        "lon": "d",
        "parentIdx": "i",
        "minTransferTime": "I",
        "iri": "utf8",
        "regionIri": "utf8",
    },
    "trips": {
        "routeIdx": "i",
        "headsign": "utf8",
        "shortName": "utf8",
        "iri": "utf8",
    },
    "routes": {
        "shortName": "utf8",
        "longName": "utf8",
        "routeType": "i",
        "iri": "utf8",
    },
    "transfers": {
        "fromStopIdx": "i",
        "toStopIdx": "i",
        "transferType": "B",
        "minTransferTime": "I",
        "fromTripIdx": "i",
        "toTripIdx": "i",
        "fromRouteIdx": "i",
        "toRouteIdx": "i",
    },
}
