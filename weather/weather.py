"""
Publish the latest measurements of a Buienradar weather station as Prometheus metrics.

Weather data: Buienradar.nl (https://www.buienradar.nl)
"""

import os
import sys
from signal import SIGTERM, signal
import logging

import requests
import time

import prometheus_client as PrometheusClient
from buienradar import FEED_URL, find_station, readings

logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO').upper(),
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Meetstation Herwijnen, see the feed for the other station IDs
STATION_ID = int(os.environ.get('BUIENRADAR_STATION_ID', '6356'))

# Buienradar updates its measurements every 10 minutes
POLL_SECONDS = 300
REQUEST_TIMEOUT_SECONDS = 10

GAUGES = [
    ('temperature', 'temperature_reading', 'temperature reading in Kelvin'),
    ('humidity', 'humidity_reading', 'relative humidity reading in percent'),
    ('pressure', 'pressure_reading', 'air pressure reading in hPa'),
]


class WeatherClient(object):
    def __init__(self, station_id):
        self.station_id = station_id
        self.gauges = {reading: PrometheusClient.Gauge(name, description, ['lat', 'lon'])
                       for reading, name, description in GAUGES}

        PrometheusClient.start_http_server(8001)

    def fetch(self):
        response = requests.get(FEED_URL, timeout=REQUEST_TIMEOUT_SECONDS,
                                headers={'User-Agent': 'slimmemeter'})
        response.raise_for_status()
        return response.json()

    def update(self):
        """Fetch the feed and store the station's readings, a failure is logged and retried next time"""
        try:
            feed = self.fetch()
        except (requests.RequestException, ValueError) as error:
            logging.warning('could not fetch the Buienradar feed: %s', error)
            return

        station = find_station(feed, self.station_id)
        if station is None:
            logging.warning('station %d is not in the Buienradar feed', self.station_id)
            return

        logging.debug('station %d measurements: %s', self.station_id, station)
        labels = {'lat': station.get('lat'), 'lon': station.get('lon')}
        for reading, value in readings(station).items():
            self.gauges[reading].labels(**labels).set(value)

    def run(self):
        while True:
            self.update()
            time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    def sigterm_handler(_signo, _stack_frame):
        """When sysvinit sends the TERM signal, cleanup before exiting."""
        logging.info('received signal %d, exiting...', _signo)
        logging.debug(_stack_frame)
        sys.exit(0)

    signal(SIGTERM, sigterm_handler)

    logging.info('running weather for Buienradar station %d', STATION_ID)
    WeatherClient(STATION_ID).run()
