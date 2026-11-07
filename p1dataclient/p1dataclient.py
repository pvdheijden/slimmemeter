"""
Receive P1-data from slimmemeter via UART and store into Prometeus to be presented with Grafana.
"""

import sys
import signal
import logging

from serial import Serial, EIGHTBITS, PARITY_NONE, STOPBITS_ONE

import prometheus_client as PrometheusClient
from p1datametrics import P1DataMetrics

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


class P1DataClient(object):
    """P1DataClient class"""

    def __init__(self, serial):
        self.serial = Serial(serial, 115200,
                             bytesize=EIGHTBITS, parity=PARITY_NONE, stopbits=STOPBITS_ONE)

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

        PrometheusClient.start_http_server(8000)

    def receive(self):
        """receive p1 data"""

        p1data = ''
        while True:
            p1data_line = self.serial.readline()
            if len(p1data) == 0:
                if p1data_line[0] == 47:
                    p1data = p1data_line
                else:
                    pass
            else:
                p1data += p1data_line
                if p1data_line[0] == 33:
                    logging.debug('received raw p1data:\n%s', p1data)
                    return p1data.decode('utf-8')
                else:
                    pass

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
