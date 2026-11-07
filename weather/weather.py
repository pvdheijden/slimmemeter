"""
Example Open Weathermap API onecall call

https://api.openweathermap.org/data/2.5/onecall?lat=33.441792&lon=-94.037689&exclude=hourly,daily&appid={API key}

"""

import os
import sys
from signal import SIGTERM, signal
import logging

import requests
import time

import prometheus_client as PrometheusClient

logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO').upper(),
                    format='%(asctime)s - %(levelname)s - %(message)s')

class TemperatureClient(object):
    def __init__(self):
        self.lat = 51.685550
        self.lon = 5.298640

        self.onecall_url = 'https://api.openweathermap.org/data/2.5/onecall'
        self.onecall_params = {
            'lat': self.lat,
            'lon': self.lon,
            'appid': 'e1a3a17c5355826f12a697385aed7530'
        }

        self.temperature_reading_gauge = PrometheusClient.Gauge(
            'temperature_reading', 'temperature reading', ['lat', 'lon'])
        self.humidity_reading_gauge = PrometheusClient.Gauge(
            'humidity_reading', 'humidity reading', ['lat', 'lon'])
        self.pressure_reading_gauge = PrometheusClient.Gauge(
            'pressure_reading', 'pressure reading', ['lat', 'lon'])

        PrometheusClient.start_http_server(8001)

    def fetch(self):
        data = requests.get(self.onecall_url, params=self.onecall_params).json()

        temp = data['current']['temp']
        humidity = data['current']['humidity']
        pressure = data['current']['pressure']

        return (temp, humidity, pressure)

    def store(self, metrics):
        self.temperature_reading_gauge.labels(
            lat=self.lat, lon=self.lon
        ).set(metrics[0])
        self.humidity_reading_gauge.labels(
            lat=self.lat, lon=self.lon
        ).set(metrics[1])
        self.pressure_reading_gauge.labels(
            lat=self.lat, lon=self.lon
        ).set(metrics[2])

    def run(self):
        while (True):
            time.sleep(60);
            self.store(self.fetch());

if __name__ == '__main__':
    def sigterm_handler(_signo, _stack_frame):
        """When sysvinit sends the TERM signal, cleanup before exiting."""
        logging.info('received signal %d, exiting...', _signo)
        logging.debug(_stack_frame)
        sys.exit(0)

    signal(SIGTERM, sigterm_handler)

    logging.info('running weather')
    TemperatureClient().run()
