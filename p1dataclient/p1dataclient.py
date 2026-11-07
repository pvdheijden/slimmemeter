"""
Receive P1-data from slimmemeter via UART and store into Prometeus to be presented with Grafana.
"""

import sys
import signal
import logging

from serial import Serial, EIGHTBITS, PARITY_NONE, STOPBITS_ONE

import prometheus_client as PrometheusClient
from p1datametrics import P1DataMetrics
from p1telegram import TelegramAssembler, is_valid

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


class P1DataClient(object):
    """P1DataClient class"""

    def __init__(self, serial):
        self.serial = Serial(serial, 115200,
                             bytesize=EIGHTBITS, parity=PARITY_NONE, stopbits=STOPBITS_ONE)
        self.assembler = TelegramAssembler()

        self.tariff1_delivered_reading_gauge = PrometheusClient.Gauge(
            'tariff1_delivered_reading', 'tariff-1 delivered reading', ['elec_eid'])
        self.tariff2_delivered_reading_gauge = PrometheusClient.Gauge(
            'tariff2_delivered_reading', 'tariff-2 delivered reading', ['elec_eid'])
        self.power_delivered_gauge = PrometheusClient.Gauge(
            'power_delivered', 'Power delivered', ['elec_eid', 'tariff_indicator'])
        self.l1_power_delivered_gauge = PrometheusClient.Gauge(
            'l1_power_delivered', 'L1 Power delivered', ['elec_eid', 'tariff_indicator'])
        self.l2_power_delivered_gauge = PrometheusClient.Gauge(
            'l2_power_delivered', 'L2 Power delivered', ['elec_eid', 'tariff_indicator'])
        self.l3_power_delivered_gauge = PrometheusClient.Gauge(
            'l3_power_delivered', 'L3 Power delivered', ['elec_eid', 'tariff_indicator'])
        self.gas_delivered_reading_gauge = PrometheusClient.Gauge(
            'gas_delivered_reading', 'Gas delivered', ['gas_eid'])
        self.crc_errors_counter = PrometheusClient.Counter(
            'p1_telegram_crc_errors', 'Telegrams discarded because of an invalid CRC')

        PrometheusClient.start_http_server(8000)

    def receive(self):
        """receive p1 data, telegrams with an invalid CRC are discarded"""

        while True:
            p1data = self.assembler.feed(self.serial.readline())
            if p1data is None:
                continue

            logging.debug('received raw p1data:\n%s', p1data)
            if is_valid(p1data):
                return p1data.decode('utf-8')

            self.crc_errors_counter.inc()
            logging.warning('discarded telegram with invalid CRC')

    def store(self, metrics):
        """expose metrics to prometheus"""
        self.tariff1_delivered_reading_gauge.labels(
            elec_eid=metrics.elec_eid()
        ).set(metrics.tariff1_delivered_reading()[0])

        self.tariff2_delivered_reading_gauge.labels(
            elec_eid=metrics.elec_eid()
        ).set(metrics.tariff2_delivered_reading()[0])

        for tariff_indicator in [1, 2]:
            self.power_delivered_gauge.labels(
                elec_eid=metrics.elec_eid(),
                tariff_indicator=tariff_indicator
            ).set(metrics.power_delivered()[0] if tariff_indicator == metrics.tariff_indicator() else 0)

            self.l1_power_delivered_gauge.labels(
                elec_eid=metrics.elec_eid(),
                tariff_indicator=tariff_indicator
            ).set(metrics.l1_power_delivered()[0] if tariff_indicator == metrics.tariff_indicator() else 0)

            self.l2_power_delivered_gauge.labels(
                elec_eid=metrics.elec_eid(),
                tariff_indicator=tariff_indicator
            ).set(metrics.l2_power_delivered()[0] if tariff_indicator == metrics.tariff_indicator() else 0)

            self.l3_power_delivered_gauge.labels(
                elec_eid=metrics.elec_eid(),
                tariff_indicator=tariff_indicator
            ).set(metrics.l3_power_delivered()[0] if tariff_indicator == metrics.tariff_indicator() else 0)

        self.gas_delivered_reading_gauge.labels(
            gas_eid=metrics.gas_eid()
        ).set(metrics.gas_delivered_reading()[0])

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
