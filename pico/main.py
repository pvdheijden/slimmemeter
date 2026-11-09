"""
Raspberry Pi Pico W: pass the P1 data of the smart meter on to the network.

Reads the P1 port on UART0 (GP1) and forwards every byte to the client connected to TCP
port 2000, the P1-data client on apollo reading socket://<pico>:2000. The Pico does not
parse the telegrams, the P1-data client checks and parses them. See PICO.md for the wiring.

MicroPython. Settings are in config.py, see config.example.py.
"""

import time

import network
import rp2
import socket
from machine import Pin, UART, WDT

import config

PORT = getattr(config, 'PORT', 2000)
WIFI_TIMEOUT_MS = 20000
CLIENT_SEND_TIMEOUT_S = 2
LED_FLASH_MS = 50
# The rp2 watchdog allows at most 8.3 seconds
WATCHDOG_TIMEOUT_MS = 8000


class Watchdog:
    """The hardware watchdog restarts the Pico if the main loop stops feeding it

    config.WATCHDOG = False turns it off, which is easier while developing: once started,
    the watchdog cannot be stopped and also resets the Pico while it is idle at the REPL.
    """

    def __init__(self, enabled):
        self.wdt = WDT(timeout=WATCHDOG_TIMEOUT_MS) if enabled else None

    def feed(self):
        if self.wdt is not None:
            self.wdt.feed()


class Led:
    """Flash the on-board LED for each telegram, without blocking"""

    def __init__(self):
        self.pin = Pin('LED', Pin.OUT)
        self.off_at = None

    def flash(self):
        self.pin.on()
        self.off_at = time.ticks_add(time.ticks_ms(), LED_FLASH_MS)

    def update(self):
        if self.off_at is not None and time.ticks_diff(time.ticks_ms(), self.off_at) >= 0:
            self.pin.off()
            self.off_at = None


def log(message):
    print('%d %s' % (time.ticks_ms() // 1000, message))


def connect_wifi(wlan, watchdog):
    """Connect to the WiFi network, return True when connected"""
    if wlan.isconnected():
        return True

    log('connecting to WiFi network %s' % config.WIFI_SSID)
    wlan.active(True)
    # Power saving delays packets, which is not needed with USB power
    wlan.config(pm=0xa11140)
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    start = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), start) > WIFI_TIMEOUT_MS:
            log('WiFi connection failed, status %d' % wlan.status())
            wlan.disconnect()
            return False
        watchdog.feed()
        time.sleep_ms(200)

    log('connected, address %s, port %d' % (wlan.ifconfig()[0], PORT))
    return True


def open_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', PORT))
    server.listen(1)
    server.setblocking(False)
    return server


def accept(server, client):
    """Return the client to send to: a new connection replaces the current one"""
    try:
        connection, address = server.accept()
    except OSError:
        return client

    if client is not None:
        log('new connection from %s replaces the current one' % address[0])
        client.close()
    else:
        log('connection from %s' % address[0])
    connection.settimeout(CLIENT_SEND_TIMEOUT_S)
    return connection


def send(client, data):
    """Send data to the client, return the client, or None when the connection is gone"""
    try:
        client.sendall(data)
        return client
    except OSError as error:
        log('connection closed: %s' % error)
        client.close()
        return None


def main():
    watchdog = Watchdog(getattr(config, 'WATCHDOG', True))
    led = Led()

    rp2.country(getattr(config, 'COUNTRY', 'NL'))
    network.hostname(getattr(config, 'HOSTNAME', 'p1-pico'))
    wlan = network.WLAN(network.STA_IF)

    # P1: 115200 baud 8N1, the data line is inverted. The 4 KB buffer holds several telegrams
    # while the network is slow. TX is not used, the Pico never sends to the meter.
    uart = UART(0, baudrate=115200, bits=8, parity=None, stop=1, rx=Pin(1), tx=Pin(0),
                invert=UART.INV_RX, rxbuf=4096)

    server = None
    client = None
    while True:
        watchdog.feed()
        led.update()

        if not wlan.isconnected():
            if client is not None:
                client.close()
                client = None
            if not connect_wifi(wlan, watchdog):
                time.sleep_ms(1000)
                continue

        if server is None:
            server = open_server()
        client = accept(server, client)

        waiting = uart.any()
        if not waiting:
            time.sleep_ms(10)
            continue

        # Read even without a client, so the buffer holds current data when one connects
        data = uart.read(waiting)
        if b'!' in data:
            led.flash()
        if client is not None:
            client = send(client, data)


# MicroPython runs main.py at boot as __main__. The test imports it without running it.
if __name__ == '__main__':
    main()
