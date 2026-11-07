"""
P1 telegram framing and CRC validation.

A telegram runs from a line starting with '/' to a line starting with '!', which
carries the CRC as 4 hex digits. The CRC is CRC16 (polynomial 0xA001, initial value 0)
over the raw bytes from the '/' up to and including the '!'.

Kept free of serial and Prometheus dependencies so it can be tested on its own.
"""

import re
import time
import logging

CRC_LINE = re.compile(rb'!([0-9A-Fa-f]{4})\s*\Z')
MAX_LINE_LENGTH = 4096


def crc16(data):
    """Return the P1 CRC16 of data (bytes)"""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def is_valid(frame):
    """Return True if frame (bytes) ends with a CRC that matches its content"""
    match = CRC_LINE.search(frame)
    if match is None:
        return False
    return int(match.group(1), 16) == crc16(frame[:match.start() + 1])


class TelegramAssembler(object):
    """Build telegrams from serial data, as returned by readline()"""

    def __init__(self):
        self.frame = None
        self.partial = b''

    def _complete_line(self, data):
        """Return the line completed by data, None if there is none yet

        A readline() that times out returns what it has so far, which can be part of a line.
        """
        self.partial += data
        if self.partial.endswith(b'\n'):
            line, self.partial = self.partial, b''
            return line

        if len(self.partial) > MAX_LINE_LENGTH:
            logging.warning('discarding %d bytes of serial data without a line ending', len(self.partial))
            self.partial = b''
        return None

    def feed(self, data):
        """Add data (bytes), return the complete raw telegram or None if there is none yet"""
        line = self._complete_line(data)
        if line is None:
            return None

        if line.startswith(b'/'):
            if self.frame is not None:
                logging.warning('new telegram started before the end of the previous one, discarding it')
            self.frame = line
            return None

        if self.frame is None:
            return None

        self.frame += line
        if line.startswith(b'!'):
            frame, self.frame = self.frame, None
            return frame
        return None


class StalenessMonitor(object):
    """Log a warning, once per outage, when no valid telegram has arrived for a while"""

    def __init__(self, stale_after, clock=time.monotonic):
        self.stale_after = stale_after
        self.clock = clock
        self.last_received = clock()
        self.stale = False

    def received(self):
        """Record that a valid telegram has arrived"""
        if self.stale:
            logging.info('receiving valid telegrams again')
        self.stale = False
        self.last_received = self.clock()

    def check(self):
        """Log a warning if this is the start of an outage"""
        if not self.stale and self.clock() - self.last_received >= self.stale_after:
            logging.warning('no valid telegram received for %d seconds', self.stale_after)
            self.stale = True
