"""
P1 telegram framing and CRC validation.

A telegram runs from a line starting with '/' to a line starting with '!', which
carries the CRC as 4 hex digits. The CRC is CRC16 (polynomial 0xA001, initial value 0)
over the raw bytes from the '/' up to and including the '!'.

Kept free of serial and Prometheus dependencies so it can be tested on its own.
"""

import re
import logging

CRC_LINE = re.compile(rb'!([0-9A-Fa-f]{4})\s*\Z')


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
    """Build telegrams from lines of serial data"""

    def __init__(self):
        self.frame = None

    def feed(self, line):
        """Add a line (bytes), return the complete raw telegram or None if there is none yet"""
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
