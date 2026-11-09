"""
The P1-data client reading from the network, as from a Raspberry Pi Pico (see PICO.md).

p1dataclient.py is a script with script-style imports, so it runs in a subprocess against a
local TCP server that replays a real telegram.
"""

import importlib.util
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.request

from .p1telegram import is_valid

CLIENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Captured from the Kaifa meter (DSMR 4.2) this was developed with
TELEGRAM = ('\r\n'.join([
    '/KFM5KAIFA-METER',
    '',
    '1-3:0.2.8(42)',
    '0-0:1.0.0(261109162145W)',
    '0-0:96.1.1(4530303236303030303331313138333136)',
    '1-0:1.8.1(025169.974*kWh)',
    '1-0:1.8.2(021672.738*kWh)',
    '1-0:2.8.1(000000.000*kWh)',
    '1-0:2.8.2(000000.000*kWh)',
    '0-0:96.14.0(0002)',
    '1-0:1.7.0(01.354*kW)',
    '1-0:2.7.0(00.000*kW)',
    '0-0:96.7.21(00000)',
    '0-0:96.7.9(00000)',
    '1-0:99.97.0(1)(0-0:96.7.19)(000101000014W)(2147483647*s)',
    '1-0:32.32.0(00000)',
    '1-0:52.32.0(00000)',
    '1-0:72.32.0(02214)',
    '1-0:32.36.0(00000)',
    '1-0:52.36.0(00000)',
    '1-0:72.36.0(00000)',
    '0-0:96.13.1()',
    '0-0:96.13.0()',
    '1-0:31.7.0(004*A)',
    '1-0:51.7.0(001*A)',
    '1-0:71.7.0(000*A)',
    '1-0:21.7.0(01.110*kW)',
    '1-0:41.7.0(00.235*kW)',
    '1-0:61.7.0(00.009*kW)',
    '1-0:22.7.0(00.000*kW)',
    '1-0:42.7.0(00.000*kW)',
    '1-0:62.7.0(00.000*kW)',
    '0-1:24.1.0(003)',
    '0-1:96.1.0(4730303235303033343137303833333136)',
    '0-1:24.2.1(261109160000W)(22844.471*m3)',
    '!D1A8',
]) + '\r\n').encode()


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class ReplayServer(threading.Thread):
    """Accept one connection and send the telegram, in two parts, until stopped, then hang up"""

    def __init__(self):
        super().__init__(daemon=True)
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(1)
        self.listener.settimeout(10)
        self.port = self.listener.getsockname()[1]
        self.stop = threading.Event()

    def run(self):
        connection, _ = self.listener.accept()
        with connection:
            while not self.stop.is_set():
                # Split mid-line, as WiFi packets arrive
                connection.sendall(TELEGRAM[:100])
                time.sleep(0.05)
                connection.sendall(TELEGRAM[100:])
                time.sleep(0.2)
        self.listener.close()


def metrics(port):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/metrics' % port, timeout=1) as response:
            return response.read().decode()
    except OSError:
        return ''


def value(text, sample):
    for line in text.splitlines():
        if line.startswith(sample + ' '):
            return float(line.split()[-1])
    return None


@unittest.skipUnless(importlib.util.find_spec('serial') and importlib.util.find_spec('prometheus_client'),
                     'needs pyserial and prometheus_client from requirements.txt')
class TestNetworkInput(unittest.TestCase):

    def setUp(self):
        self.assertTrue(is_valid(TELEGRAM), 'the replayed telegram must have a valid CRC')
        self.server = ReplayServer()
        self.server.start()
        self.metrics_port = free_port()
        env = dict(os.environ, METRICS_PORT=str(self.metrics_port), LOG_LEVEL='WARNING')
        env.pop('P1_URL', None)
        self.client = subprocess.Popen(
            [sys.executable, 'p1dataclient.py', 'socket://127.0.0.1:%d' % self.server.port],
            cwd=CLIENT_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def tearDown(self):
        self.server.stop.set()
        if self.client.poll() is None:
            self.client.kill()
        self.client.wait()
        self.client.stdout.close()

    def wait_for_telegram(self):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            text = metrics(self.metrics_port)
            if (value(text, 'p1_last_telegram_timestamp_seconds') or 0) > 0:
                return text
            self.assertIsNone(self.client.poll(), 'the client exited early')
            time.sleep(0.2)
        self.fail('no telegram stored within 15 seconds')

    def test_publishes_metrics_from_socket(self):
        text = self.wait_for_telegram()
        eid = 'elec_eid="4530303236303030303331313138333136"'
        self.assertEqual(value(text, 'tariff1_delivered_reading{%s}' % eid), 25169.974)
        self.assertEqual(value(text, 'power_delivered{%s,tariff_indicator="2"}' % eid), 1.354)
        self.assertEqual(value(text, 'voltage_sags{%s,phase="L3"}' % eid), 2214)
        self.assertEqual(value(text, 'p1_telegram_crc_errors_total'), 0)

    def test_exits_when_the_connection_drops(self):
        # supervisord or Docker restarts the client, which reconnects
        self.wait_for_telegram()
        self.server.stop.set()
        try:
            status = self.client.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.fail('the client kept running after the connection dropped')
        self.assertNotEqual(status, 0)


if __name__ == '__main__':
    unittest.main()
