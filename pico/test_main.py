"""
Tests of the Pico firmware (main.py), run with CPython.

The MicroPython modules machine, network and rp2 are replaced by stand-ins: a UART fed by
the test, and a WiFi network that is always connected. The TCP server is real, on localhost.
What only the Pico can show, such as the inverted UART and the WiFi connection, is tested on
the device (see PICO.md).
"""

import importlib.util
import os
import queue
import socket
import sys
import threading
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
TELEGRAM = b'/KFM5KAIFA-METER\r\n\r\n1-0:1.8.1(025169.974*kWh)\r\n!1234\r\n'


class Stopped(Exception):
    """Ends the firmware's main loop"""


class FakeUART:
    INV_RX = 2

    def __init__(self, *args, **kwargs):
        self.settings = kwargs
        self.incoming = queue.Queue()
        self.stop = threading.Event()
        FakeUART.instance = self

    def any(self):
        if self.stop.is_set():
            raise Stopped()
        try:
            self.pending = self.incoming.get(timeout=0.01)
        except queue.Empty:
            return 0
        return len(self.pending)

    def read(self, count):
        return self.pending[:count]


class FakePin:
    OUT = 1

    def __init__(self, *args):
        self.flashes = 0
        if args[0] == 'LED':
            FakePin.led = self

    def on(self):
        self.flashes += 1

    def off(self):
        pass


class FakeWLAN:
    def __init__(self, interface):
        pass

    def isconnected(self):
        return True

    def ifconfig(self):
        return ('127.0.0.1', '255.0.0.0', '127.0.0.1', '127.0.0.1')


def stand_ins(port):
    machine = types.ModuleType('machine')
    machine.Pin, machine.UART = FakePin, FakeUART
    machine.WDT = mock.Mock()
    network = types.ModuleType('network')
    network.STA_IF = 0
    network.WLAN = FakeWLAN
    network.hostname = mock.Mock()
    rp2 = types.ModuleType('rp2')
    rp2.country = mock.Mock()
    config = types.ModuleType('config')
    config.WIFI_SSID, config.WIFI_PASSWORD = 'test', 'test'
    config.PORT = port
    config.WATCHDOG = False
    return {'machine': machine, 'network': network, 'rp2': rp2, 'config': config}


def micropython_time():
    """The MicroPython time functions the firmware uses, added to CPython's time module"""
    ticks_ms = lambda: int(time.monotonic() * 1000)  # noqa: E731
    return [mock.patch.object(time, name, function, create=True) for name, function in (
        ('ticks_ms', ticks_ms),
        ('ticks_add', lambda ticks, delta: ticks + delta),
        ('ticks_diff', lambda new, old: new - old),
        ('sleep_ms', lambda ms: time.sleep(ms / 1000)),
    )]


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class TestFirmware(unittest.TestCase):

    def setUp(self):
        self.port = free_port()
        self.patches = [mock.patch.dict(sys.modules, stand_ins(self.port))] + micropython_time()
        for patch in self.patches:
            patch.start()

        spec = importlib.util.spec_from_file_location('pico_main', os.path.join(HERE, 'main.py'))
        self.firmware = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.firmware)

        self.errors = []
        self.thread = threading.Thread(target=self.run_firmware, daemon=True)
        self.thread.start()
        self.wait_for(lambda: hasattr(FakeUART, 'instance') and self.listening())
        self.uart = FakeUART.instance

    def run_firmware(self):
        try:
            self.firmware.main()
        except Stopped:
            pass
        except Exception as error:  # reported by tearDown
            self.errors.append(error)

    def tearDown(self):
        FakeUART.instance.stop.set()
        self.thread.join(timeout=5)
        del FakeUART.instance
        for patch in reversed(self.patches):
            patch.stop()
        self.assertEqual(self.errors, [])

    def wait_for(self, condition, seconds=5):
        deadline = time.monotonic() + seconds
        while not condition():
            self.assertLess(time.monotonic(), deadline, 'timed out')
            time.sleep(0.02)

    def listening(self):
        try:
            socket.create_connection(('127.0.0.1', self.port), timeout=0.2).close()
            return True
        except OSError:
            return False

    def connect(self):
        client = socket.create_connection(('127.0.0.1', self.port), timeout=5)
        # Let the firmware accept it before the test sends data
        time.sleep(0.2)
        return client

    def receive(self, client, size):
        data = b''
        while len(data) < size:
            chunk = client.recv(size - len(data))
            if not chunk:
                break
            data += chunk
        return data

    def test_uart_settings(self):
        settings = self.uart.settings
        self.assertEqual(settings['baudrate'], 115200)
        self.assertEqual(settings['invert'], FakeUART.INV_RX)
        self.assertEqual(settings['rxbuf'], 4096)

    def test_forwards_uart_data_unchanged(self):
        with self.connect() as client:
            # The UART returns a telegram in parts, as it arrives
            self.uart.incoming.put(TELEGRAM[:20])
            self.uart.incoming.put(TELEGRAM[20:])
            self.assertEqual(self.receive(client, len(TELEGRAM)), TELEGRAM)

    def test_new_connection_replaces_the_current_one(self):
        with self.connect() as first, self.connect() as second:
            self.uart.incoming.put(TELEGRAM)
            self.assertEqual(self.receive(second, len(TELEGRAM)), TELEGRAM)
            first.settimeout(2)
            self.assertEqual(first.recv(100), b'', 'the first connection should be closed')

    def test_data_without_client_is_dropped(self):
        self.uart.incoming.put(b'before anyone connected\r\n')
        self.wait_for(self.uart.incoming.empty)
        with self.connect() as client:
            self.uart.incoming.put(TELEGRAM)
            self.assertEqual(self.receive(client, len(TELEGRAM)), TELEGRAM)

    def test_led_flashes_for_each_telegram(self):
        with self.connect() as client:
            for _ in range(3):
                self.uart.incoming.put(TELEGRAM)
            self.receive(client, 3 * len(TELEGRAM))
        self.assertEqual(FakePin.led.flashes, 3)

    def test_client_that_goes_away_is_dropped(self):
        client = self.connect()
        client.close()
        for _ in range(5):
            self.uart.incoming.put(TELEGRAM)
        self.wait_for(self.uart.incoming.empty)
        with self.connect() as second:
            self.uart.incoming.put(TELEGRAM)
            self.assertEqual(self.receive(second, len(TELEGRAM)), TELEGRAM)


if __name__ == '__main__':
    unittest.main()
