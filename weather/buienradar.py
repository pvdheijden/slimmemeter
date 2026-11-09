"""
Buienradar weather feed parsing.

The feed at FEED_URL holds the latest 10-minute measurements of the KNMI weather stations.
Weather data: Buienradar.nl (https://www.buienradar.nl), free for non-commercial use with
attribution.

Kept free of requests and Prometheus dependencies so it can be tested on its own.
"""

FEED_URL = 'https://data.buienradar.nl/2.0/feed/json'

KELVIN_OFFSET = 273.15

# (reading name, feed field, offset added to the feed value)
FIELDS = [
    ('temperature', 'temperature', KELVIN_OFFSET),  # degrees Celsius in the feed, published in Kelvin
    ('humidity', 'humidity', 0),                    # percent
    ('pressure', 'airpressure', 0),                 # hPa
]


def find_station(feed, station_id):
    """Return the measurements of station_id from the feed, None if the feed does not have it"""
    actual = feed.get('actual') if isinstance(feed, dict) else None
    stations = actual.get('stationmeasurements') if isinstance(actual, dict) else None
    for station in stations if isinstance(stations, list) else []:
        if isinstance(station, dict) and station.get('stationid') == station_id:
            return station
    return None


def readings(station):
    """Return {reading name: value} for the station, leaving out values it did not report"""
    result = {}
    for name, field, offset in FIELDS:
        value = station.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[name] = value + offset
    return result
