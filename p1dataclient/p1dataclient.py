"""
Receive P1-data from slimmemeter via UART and store into Prometeus to be presented with Grafana.
"""

import sys
import signal
import logging

from serial import Serial, EIGHTBITS, PARITY_NONE, STOPBITS_ONE

import prometheus_client as PrometheusClient
from p1datametrics import P1DataMetrics
from p1telegram import StalenessMonitor, TelegramAssembler, is_valid

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

SERIAL_TIMEOUT_SECONDS = 5
STALE_AFTER_SECONDS = 30

GAUGES = [
    ('tariff1_delivered_reading', 'tariff-1 delivered reading', ['elec_eid']),
    ('tariff2_delivered_reading', 'tariff-2 delivered reading', ['elec_eid']),
    ('power_delivered', 'Power delivered', ['elec_eid', 'tariff_indicator']),
    ('l1_power_delivered', 'L1 Power delivered', ['elec_eid', 'tariff_indicator']),
    ('l2_power_delivered', 'L2 Power delivered', ['elec_eid', 'tariff_indicator']),
    ('l3_power_delivered', 'L3 Power delivered', ['elec_eid', 'tariff_indicator']),
    ('gas_delivered_reading', 'Gas delivered', ['gas_eid']),
]


class P1DataClient(object):
    """P1DataClient class"""

    def __init__(self, serial):
        self.serial = Serial(serial, 115200,
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

        PrometheusClient.start_http_server(8000)

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

    SERIAL = sys.argv[1]

    logging.info('running p1dataclient (%s)', SERIAL)
    P1DataClient(SERIAL).run()
