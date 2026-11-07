import unittest

from .p1datametrics import P1DataMetrics

class TestP1DataMetrics(unittest.TestCase):
    """p1dataparser module tests"""

    def setUp(self):
        raw = '\
/KFM5KAIFA-METER\r\n\
\r\n\
1-3:0.2.8(42)\r\n\
0-0:1.0.0(161129002535W)\r\n\
0-0:96.1.1(4530303236303030303331313138333136)\r\n\
1-0:1.8.1(000458.330*kWh)\r\n\
1-0:1.8.2(000364.935*kWh)\r\n\
1-0:2.8.1(000000.000*kWh)\r\n\
1-0:2.8.2(000000.000*kWh)\r\n\
0-0:96.14.0(0001)\r\n\
1-0:1.7.0(00.513*kW)\r\n\
1-0:2.7.0(00.000*kW)\r\n\
0-0:96.7.21(00001)\r\n\
0-0:96.7.9(00001)\r\n\
1-0:99.97.0(1)(0-0:96.7.19)(000101000014W)(2147483647*s)\r\n\
1-0:32.32.0(00000)\r\n\
1-0:52.32.0(00000)\r\n\
1-0:72.32.0(00102)\r\n\
1-0:32.36.0(00000)\r\n\
1-0:52.36.0(00000)\r\n\
1-0:72.36.0(00000)\r\n\
0-0:96.13.1()\r\n\
0-0:96.13.0()\r\n\
1-0:31.7.0(000*A)\r\n\
1-0:51.7.0(001*A)\r\n\
1-0:71.7.0(000*A)\r\n\
1-0:21.7.0(00.171*kW)\r\n\
1-0:41.7.0(00.330*kW)\r\n\
1-0:61.7.0(00.012*kW)\r\n\
1-0:22.7.0(00.000*kW)\r\n\
1-0:42.7.0(00.000*kW)\r\n\
1-0:62.7.0(00.000*kW)\r\n\
0-1:24.1.0(003)\r\n\
0-1:96.1.0(4730303235303033343137303833333136)\r\n\
0-1:24.2.1(161129000000W)(00528.862*m3)\r\n\
!D21C\r\n'
        self.metrics = P1DataMetrics(raw)

    def test_elec_eid(self):
        eid = self.metrics.elec_eid()
        self.assertEqual(eid, '4530303236303030303331313138333136', 'invalid elec_eid')

    def test_gas_eid(self):
        eid = self.metrics.gas_eid()
        self.assertEqual(eid, '4730303235303033343137303833333136', 'invalid gas_eid')

    def test_tariff1_delivered_reading(self):
        tariff = self.metrics.tariff1_delivered_reading()
        self.assertEqual(tariff, (458.330, 'kWh'), 'invalid tariff 1 delivered reading')

    def test_tariff2_delivered_reading(self):
        tariff = self.metrics.tariff2_delivered_reading()
        self.assertEqual(tariff, (364.935, 'kWh'), 'invalid tariff 2 delivered reading')

    def test_tariff_indicator(self):
        indicator = self.metrics.tariff_indicator()
        self.assertEqual(indicator, 1, 'invalid tariff indicator')

    def test_power_delivered(self):
        power = self.metrics.power_delivered()
        self.assertEqual(power, (0.513, 'kW'), 'invalid power delivered')

    def test_gas_delivered_reading(self):
        gas = self.metrics.gas_delivered_reading()
        self.assertEqual(gas, (528.862, 'm3'), 'invalid gas delivered reading')

    def test_samples(self):
        eid = '4530303236303030303331313138333136'
        samples = self.metrics.samples()
        self.assertEqual(len(samples), 11)
        self.assertIn(('tariff1_delivered_reading', {'elec_eid': eid}, 458.330), samples)
        self.assertIn(('power_delivered', {'elec_eid': eid, 'tariff_indicator': 1}, 0.513), samples)
        self.assertIn(('power_delivered', {'elec_eid': eid, 'tariff_indicator': 2}, 0), samples)
        self.assertIn(('l3_power_delivered', {'elec_eid': eid, 'tariff_indicator': 1}, 0.012), samples)
        self.assertIn(('gas_delivered_reading', {'gas_eid': '4730303235303033343137303833333136'}, 528.862), samples)


def names(samples):
    return {sample[0] for sample in samples}


class TestAbsentAndMalformed(unittest.TestCase):
    """Telegrams with missing or unusable values"""

    def test_absent_reading(self):
        self.assertIsNone(P1DataMetrics('/X\r\n!0000\r\n').power_delivered())

    def test_absent_identifiers(self):
        metrics = P1DataMetrics('/X\r\n!0000\r\n')
        self.assertEqual(metrics.elec_eid(), '')
        self.assertEqual(metrics.gas_eid(), '')
        self.assertIsNone(metrics.tariff_indicator())

    def test_empty_telegram_has_no_samples(self):
        self.assertEqual(P1DataMetrics('/X\r\n!0000\r\n').samples(), [])

    def test_empty_value(self):
        self.assertIsNone(P1DataMetrics('1-0:1.7.0()\r\n').power_delivered())

    def test_value_without_unit(self):
        self.assertIsNone(P1DataMetrics('1-0:1.7.0(00.513)\r\n').power_delivered())

    def test_value_not_a_number(self):
        self.assertIsNone(P1DataMetrics('1-0:1.7.0(abc*kW)\r\n').power_delivered())

    def test_value_without_parentheses(self):
        self.assertIsNone(P1DataMetrics('1-0:1.7.0\r\n').power_delivered())

    def test_gas_without_value(self):
        self.assertIsNone(P1DataMetrics('0-1:24.2.1(161129000000W)\r\n').gas_delivered_reading())

    def test_malformed_tariff_indicator(self):
        self.assertIsNone(P1DataMetrics('0-0:96.14.0()\r\n').tariff_indicator())

    def test_identifier_without_value(self):
        self.assertEqual(P1DataMetrics('0-0:96.1.1\r\n').elec_eid(), '')

    def test_single_phase_meter_has_no_l2_l3_samples(self):
        samples = P1DataMetrics('0-0:96.14.0(0001)\r\n1-0:21.7.0(00.171*kW)\r\n').samples()
        self.assertEqual(names(samples), {'l1_power_delivered'})

    def test_unknown_tariff_has_no_power_samples(self):
        samples = P1DataMetrics('1-0:1.7.0(00.513*kW)\r\n1-0:1.8.1(000458.330*kWh)\r\n').samples()
        self.assertEqual(names(samples), {'tariff1_delivered_reading'})


class TestGasChannel(unittest.TestCase):
    """The gas meter can be on any M-Bus channel"""

    def test_gas_on_channel_2(self):
        metrics = P1DataMetrics('0-2:24.1.0(003)\r\n'
                                '0-2:96.1.0(4730)\r\n'
                                '0-2:24.2.1(161129000000W)(00528.862*m3)\r\n')
        self.assertEqual(metrics.gas_eid(), '4730')
        self.assertEqual(metrics.gas_delivered_reading(), (528.862, 'm3'))

    def test_other_device_on_channel_1(self):
        metrics = P1DataMetrics('0-1:24.1.0(007)\r\n'
                                '0-1:24.2.1(161129000000W)(00012.345*m3)\r\n'
                                '0-2:24.1.0(003)\r\n'
                                '0-2:24.2.1(161129000000W)(00528.862*m3)\r\n')
        self.assertEqual(metrics.gas_delivered_reading(), (528.862, 'm3'))

    def test_no_device_type_uses_channel_1(self):
        metrics = P1DataMetrics('0-1:24.2.1(161129000000W)(00528.862*m3)\r\n')
        self.assertEqual(metrics.gas_delivered_reading(), (528.862, 'm3'))


if __name__ == '__main__':
    unittest.main()
