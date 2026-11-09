"""
Receive P1-data from slimmemeter via UART and store into Prometeus to be presented with Grafana.

The input is a serial device such as /dev/serial0, or a network address such as
socket://pico:2000 where a Raspberry Pi Pico forwards the P1 data (see PICO.md). It is the
first argument, or P1_URL when there is no argument.
"""

import os
import sys
import signal
import logging

from serial import serial_for_url, EIGHTBITS, PARITY_NONE, STOPBITS_ONE

import prometheus_client as PrometheusClient
from p1datametrics import P1DataMetrics
from p1telegram import StalenessMonitor, TelegramAssembler, is_valid

logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO').upper(),
                    format='%(asctime)s - %(levelname)s - %(message)s')

SERIAL_TIMEOUT_SECONDS = 5
METRICS_PORT = int(os.environ.get('METRICS_PORT', '8000'))
STALE_AFTER_SECONDS = 30

GAUGES = [
    ('tariff1_delivered_reading', 'tariff-1 delivered reading', ['elec_eid']),
    ('tariff2_delivered_reading', 'tariff-2 delivered reading', ['elec_eid']),
    ('power_delivered', 'Power delivered', ['elec_eid', 'tariff_indicator']),
    ('l1_power_delivered', 'L1 Power delivered', ['elec_eid', 'tariff_indicator']),
    ('l2_power_delivered', 'L2 Power delivered', ['elec_eid', 'tariff_indicator']),
    ('l3_power_delivered', 'L3 Power delivered', ['elec_eid', 'tariff_indicator']),
    ('gas_delivered_reading', 'Gas delivered', ['gas_eid']),
    ('gas_reading_timestamp_seconds', 'Unix time of the last gas reading, the gas meter reports once an hour',
     ['gas_eid']),
    ('tariff1_returned_reading', 'tariff-1 returned reading in kWh', ['elec_eid']),
    ('tariff2_returned_reading', 'tariff-2 returned reading in kWh', ['elec_eid']),
    ('power_returned', 'Power returned to the grid in kW', ['elec_eid']),
    ('phase_power_returned', 'Power returned to the grid per phase in kW', ['elec_eid', 'phase']),
    ('phase_current', 'Current per phase in A, whole amperes', ['elec_eid', 'phase']),
    ('voltage_sags', 'Number of voltage sags per phase, counted by the meter', ['elec_eid', 'phase']),
    ('voltage_swells', 'Number of voltage swells per phase, counted by the meter', ['elec_eid', 'phase']),
    ('power_failures', 'Number of power failures in any phase, counted by the meter', ['elec_eid']),
    ('long_power_failures', 'Number of long power failures in any phase, counted by the meter', ['elec_eid']),
]


class P1DataClient(object):
    """P1DataClient class"""

    def __init__(self, serial):
        # A socket:// connection that drops raises SerialException, and the restart reconnects
        self.serial = serial_for_url(serial, 115200,
                                     bytesize=EIGHTBITS, parity=PARITY_NONE, stopbits=STOPBITS_ONE,
                                     timeout=SERIAL_TIMEOUT_SECONDS)
        self.assembler = TelegramAssembler()
        self.staleness = StalenessMonitor(STALE_AFTER_SECONDS)

        self.gauges = {name: PrometheusClient.Gauge(name, description, labels)
                       for name, description, labels in GAUGES}
        self.crc_errors_counter = PrometheusClient.Counter(
            'p1_telegram_crc_errors', 'Telegrams discarded because of an invalid CRC')
        self.last_telegram_gauge = PrometheusClient.Gauge(
            'p1_last_telegram_timestamp_seconds', 'Unix time of the last valid telegram')

        PrometheusClient.start_http_server(METRICS_PORT)

    def receive(self):
        """receive p1 data, telegrams with an invalid CRC are discarded"""

        while True:
            p1data = self.assembler.feed(self.serial.readline())
            if p1data is not None:
                logging.debug('received raw p1data:\n%s', p1data)
                if is_valid(p1data):
                    self.staleness.received()
                    self.last_telegram_gauge.set_to_current_time()
                    return p1data.decode('utf-8')

                self.crc_errors_counter.inc()
                logging.warning('discarded telegram with invalid CRC')

            self.staleness.check()

    def store(self, metrics):
        """expose metrics to prometheus"""
        for name, labels, value in metrics.samples():
            self.gauges[name].labels(**labels).set(value)

    def run(self):
        """receive p1 data and expose the data and again and again ..."""
        while True:
            self.store(P1DataMetrics(self.receive()))


if __name__ == '__main__':
    def sigterm_handler(_signo, _stack_frame):
        """When sysvinit sends the TERM signal, cleanup before exiting."""
        logging.info('received signal %d, exiting...', _signo)
        logging.debug(_stack_frame)
        sys.exit(0)

    signal.signal(signal.SIGTERM, sigterm_handler)

    SERIAL = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('P1_URL')
    if not SERIAL:
        sys.exit('usage: p1dataclient.py <serial device or socket://host:port>, or set P1_URL')

    logging.info('running p1dataclient (%s)', SERIAL)
    P1DataClient(SERIAL).run()
