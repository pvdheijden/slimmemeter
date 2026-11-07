import unittest

from .p1telegram import MAX_LINE_LENGTH, StalenessMonitor, TelegramAssembler, crc16, is_valid

TELEGRAM = (
    b'/KFM5KAIFA-METER\r\n'
    b'\r\n'
    b'1-3:0.2.8(42)\r\n'
    b'0-0:1.0.0(161129002535W)\r\n'
    b'0-0:96.1.1(4530303236303030303331313138333136)\r\n'
    b'1-0:1.8.1(000458.330*kWh)\r\n'
    b'1-0:1.8.2(000364.935*kWh)\r\n'
    b'1-0:2.8.1(000000.000*kWh)\r\n'
    b'1-0:2.8.2(000000.000*kWh)\r\n'
    b'0-0:96.14.0(0001)\r\n'
    b'1-0:1.7.0(00.513*kW)\r\n'
    b'1-0:2.7.0(00.000*kW)\r\n'
    b'0-0:96.7.21(00001)\r\n'
    b'0-0:96.7.9(00001)\r\n'
    b'1-0:99.97.0(1)(0-0:96.7.19)(000101000014W)(2147483647*s)\r\n'
    b'1-0:32.32.0(00000)\r\n'
    b'1-0:52.32.0(00000)\r\n'
    b'1-0:72.32.0(00102)\r\n'
    b'1-0:32.36.0(00000)\r\n'
    b'1-0:52.36.0(00000)\r\n'
    b'1-0:72.36.0(00000)\r\n'
    b'0-0:96.13.1()\r\n'
    b'0-0:96.13.0()\r\n'
    b'1-0:31.7.0(000*A)\r\n'
    b'1-0:51.7.0(001*A)\r\n'
    b'1-0:71.7.0(000*A)\r\n'
    b'1-0:21.7.0(00.171*kW)\r\n'
    b'1-0:41.7.0(00.330*kW)\r\n'
    b'1-0:61.7.0(00.012*kW)\r\n'
    b'1-0:22.7.0(00.000*kW)\r\n'
    b'1-0:42.7.0(00.000*kW)\r\n'
    b'1-0:62.7.0(00.000*kW)\r\n'
    b'0-1:24.1.0(003)\r\n'
    b'0-1:96.1.0(4730303235303033343137303833333136)\r\n'
    b'0-1:24.2.1(161129000000W)(00528.862*m3)\r\n'
    b'!D21C\r\n'
)


def feed_all(assembler, data):
    """Feed data line by line, return the telegrams that were completed"""
    frames = [assembler.feed(line) for line in data.splitlines(keepends=True)]
    return [frame for frame in frames if frame is not None]


class TestCrc(unittest.TestCase):
    """CRC validation tests"""

    def test_crc16_known_value(self):
        self.assertEqual(crc16(TELEGRAM[:TELEGRAM.rindex(b'!') + 1]), 0xD21C)

    def test_valid_telegram(self):
        self.assertTrue(is_valid(TELEGRAM))

    def test_lowercase_crc(self):
        self.assertTrue(is_valid(TELEGRAM.replace(b'!D21C', b'!d21c')))

    def test_changed_byte(self):
        self.assertFalse(is_valid(TELEGRAM.replace(b'00.513*kW', b'00.913*kW')))

    def test_wrong_crc(self):
        self.assertFalse(is_valid(TELEGRAM.replace(b'!D21C', b'!D21D')))

    def test_missing_crc(self):
        self.assertFalse(is_valid(TELEGRAM.replace(b'!D21C', b'!')))

    def test_malformed_crc(self):
        self.assertFalse(is_valid(TELEGRAM.replace(b'!D21C', b'!D2')))

    def test_truncated_telegram(self):
        self.assertFalse(is_valid(TELEGRAM[:len(TELEGRAM) // 2]))

    def test_removed_line(self):
        self.assertFalse(is_valid(TELEGRAM.replace(b'1-0:1.7.0(00.513*kW)\r\n', b'')))


class TestTelegramAssembler(unittest.TestCase):
    """Telegram framing tests"""

    def setUp(self):
        self.assembler = TelegramAssembler()

    def test_complete_telegram(self):
        self.assertEqual(feed_all(self.assembler, TELEGRAM), [TELEGRAM])

    def test_consecutive_telegrams(self):
        self.assertEqual(feed_all(self.assembler, TELEGRAM + TELEGRAM), [TELEGRAM, TELEGRAM])

    def test_garbage_before_start(self):
        data = b'(00.513*kW)\r\n!D21C\r\n' + TELEGRAM
        self.assertEqual(feed_all(self.assembler, data), [TELEGRAM])

    def test_lost_end_line_keeps_next_telegram(self):
        data = TELEGRAM.replace(b'!D21C\r\n', b'') + TELEGRAM
        self.assertEqual(feed_all(self.assembler, data), [TELEGRAM])

    def test_empty_read(self):
        self.assertIsNone(self.assembler.feed(b''))
        for line in TELEGRAM.splitlines(keepends=True)[:3]:
            self.assembler.feed(line)
        self.assertIsNone(self.assembler.feed(b''))
        self.assertEqual(feed_all(self.assembler, b''.join(TELEGRAM.splitlines(keepends=True)[3:])), [TELEGRAM])

    def test_timeout_inside_any_line(self):
        for split in range(1, len(TELEGRAM)):
            assembler = TelegramAssembler()
            frames = feed_all(assembler, TELEGRAM[:split])
            self.assertIsNone(assembler.feed(b''))
            frames += feed_all(assembler, TELEGRAM[split:])
            self.assertEqual(frames, [TELEGRAM], 'split at byte %d' % split)

    def test_line_ending_never_arrives(self):
        self.assertIsNone(self.assembler.feed(b'x' * (MAX_LINE_LENGTH + 1)))
        self.assertEqual(self.assembler.partial, b'')
        self.assertEqual(feed_all(self.assembler, TELEGRAM), [TELEGRAM])


class TestStalenessMonitor(unittest.TestCase):
    """Outage detection tests"""

    def setUp(self):
        self.now = 1000
        self.monitor = StalenessMonitor(30, clock=lambda: self.now)

    def test_not_stale_before_limit(self):
        self.now += 29
        self.monitor.check()
        self.assertFalse(self.monitor.stale)

    def test_stale_at_limit(self):
        self.now += 30
        with self.assertLogs('root', 'WARNING'):
            self.monitor.check()
        self.assertTrue(self.monitor.stale)

    def test_warns_once_per_outage(self):
        self.now += 30
        with self.assertLogs('root', 'WARNING') as logs:
            self.monitor.check()
            self.now += 30
            self.monitor.check()
        self.assertEqual(len(logs.records), 1)

    def test_received_resets(self):
        self.now += 29
        self.monitor.received()
        self.now += 29
        self.monitor.check()
        self.assertFalse(self.monitor.stale)

    def test_warns_again_after_recovery(self):
        self.now += 30
        with self.assertLogs('root', 'WARNING'):
            self.monitor.check()
        self.monitor.received()
        self.assertFalse(self.monitor.stale)
        self.now += 30
        with self.assertLogs('root', 'WARNING'):
            self.monitor.check()


if __name__ == '__main__':
    unittest.main()
