"""
Slimmemeter p1-data parser.

Example p1data block
--------------------
/KFM5KAIFA-METER

1-3:0.2.8(42) --> Version information for P1 output
0-0:1.0.0(161121140935W) --> Date-time stamp of the P1 message (21-nov-16 14:09:35 Wintertime)
0-0:96.1.1(4530303236303030303331313138333136) --> Equipment identifier
1-0:1.8.1(000387.958*kWh) --> Meter Reading electricity delivered TO client Tariff 1
1-0:1.8.2(000311.200*kWh) --> Meter Reading electricity delivered TO client Tariff 2
1-0:2.8.1(000000.000*kWh) --> Meter Reading electricity delivered BY client Tariff 1
1-0:2.8.2(000000.000*kWh) --> Meter Reading electricity delivered BY client Tariff 2
0-0:96.14.0(0002) --> Tariff indicator electricity. 
1-0:1.7.0(00.601*kW) --> Actual electricity power delivered (+P)
1-0:2.7.0(00.000*kW) --> Actual electricity power received (-P) 
0-0:96.7.21(00001) --> Number of power failures in any phase 
0-0:96.7.9(00001) --> Number of long power failures in any phase 
1-0:99.97.0(1)(0-0:96.7.19)(000101000014W)(2147483647*s) --> Power Failure Event Log (long power failures) 
1-0:32.32.0(00000) --> Number of voltage sags in phase L1 
1-0:52.32.0(00000) --> Number of voltage sags in phase L2 (polyphase meters only)
1-0:72.32.0(00083) --> Number of voltage sags in phase L3 (polyphase meters only) 
1-0:32.36.0(00000) --> Number of voltage swells in phase L1 
1-0:52.36.0(00000) --> Number of voltage swells in phase L2 (polyphase meters only)
1-0:72.36.0(00000) --> Number of voltage swells in phase L3 (polyphase meters only) 
0-0:96.13.1() --> Text message codes: numeric 8 digits
0-0:96.13.0() --> Text message max 1024 characters. 
1-0:31.7.0(001*A) --> Instantaneous current L1 in A resolution.
1-0:51.7.0(001*A) --> Instantaneous current L2 in A resolution.
1-0:71.7.0(000*A) --> Instantaneous current L3 in A resolution.
1-0:21.7.0(00.250*kW) --> Instantaneous active power L1 (+P) in W resolution
1-0:41.7.0(00.340*kW) --> Instantaneous active power L2 (+P) in W resolution
1-0:61.7.0(00.013*kW) --> Instantaneous active power L3 (+P) in W resolution
1-0:22.7.0(00.000*kW) --> Instantaneous active power L1 (-P) in W resolution
1-0:42.7.0(00.000*kW) --> Instantaneous active power L2 (-P) in W resolution
1-0:62.7.0(00.000*kW) --> Instantaneous active power L3 (-P) in W resolution
0-1:24.1.0(003) --> Gas Data: Device-Type
0-1:96.1.0(4730303235303033343137303833333136) --> Gas Data: Equipment identifier 
0-1:24.2.1(161121140000W)(00443.690*m3) --> Gas Data: Last hourly value (temperature converted), gas delivered to client in m3, including decimal values and capture time 
!9645
---------------------
"""

import re
import logging


class P1DataMetrics(object):

    def __init__(self, raw):
        """ Parse 'raw' p1data block and return dictionary of p1data metrics"""

        self.metrics = {}

        tmp_metrics = [re.match('(^\\d+-\\d+:\\d+.\\d+.\\d+)(.*$)', entry) for entry in raw.split()]
        tmp_metrics = [entry for entry in tmp_metrics if entry is not None]
        for entry in tmp_metrics:
            self.metrics[entry.group(1)] = re.findall('\\(([\\w\\*\\.]*)\\)', entry.group(2))

        logging.debug('parsed p1data:\n%s', str(self.metrics))

        self.gas_channel = self._find_gas_channel()

    def _find_gas_channel(self):
        """Return the M-Bus channel of the gas meter, device type 003, which is not always channel 1"""
        for obis, values in sorted(self.metrics.items()):
            match = re.fullmatch('0-(\\d+):24\\.1\\.0', obis)
            if match is not None and values[:1] == ['003']:
                return match.group(1)
        return '1'

    def _text(self, obis):
        """Return the first value of obis as text, '' if it is absent or empty"""
        values = self.metrics.get(obis)
        return values[0] if values else ''

    def _reading(self, obis, index=0):
        """Return the 'value*unit' at index of obis as (value, unit), None if it is absent or malformed"""
        values = self.metrics.get(obis)
        if values is None:
            return None

        try:
            value, unit = values[index].split('*')
            return float(value), unit
        except (IndexError, ValueError):
            logging.warning('ignoring malformed value for %s: %s', obis, values)
            return None

    def elec_eid(self):
        return self._text('0-0:96.1.1')

    def gas_eid(self):
        return self._text('0-%s:96.1.0' % self.gas_channel)

    def tariff1_delivered_reading(self):
        return self._reading('1-0:1.8.1')

    def tariff2_delivered_reading(self):
        return self._reading('1-0:1.8.2')

    def tariff_indicator(self):
        text = self._text('0-0:96.14.0')
        return int(text) if text.isdigit() else None

    def power_delivered(self):
        return self._reading('1-0:1.7.0')

    def l1_power_delivered(self):
        return self._reading('1-0:21.7.0')

    def l2_power_delivered(self):
        return self._reading('1-0:41.7.0')

    def l3_power_delivered(self):
        return self._reading('1-0:61.7.0')

    def gas_delivered_reading(self):
        return self._reading('0-%s:24.2.1' % self.gas_channel, 1)

    def samples(self):
        """Return (metric name, labels, value) for each metric to publish, leaving out unavailable readings"""
        samples = []

        elec_labels = {'elec_eid': self.elec_eid()}
        for name, reading in (('tariff1_delivered_reading', self.tariff1_delivered_reading()),
                              ('tariff2_delivered_reading', self.tariff2_delivered_reading())):
            if reading is not None:
                samples.append((name, elec_labels, reading[0]))

        active_tariff = self.tariff_indicator()
        if active_tariff is not None:
            for name, reading in (('power_delivered', self.power_delivered()),
                                  ('l1_power_delivered', self.l1_power_delivered()),
                                  ('l2_power_delivered', self.l2_power_delivered()),
                                  ('l3_power_delivered', self.l3_power_delivered())):
                if reading is not None:
                    for tariff in [1, 2]:
                        labels = dict(elec_labels, tariff_indicator=tariff)
                        samples.append((name, labels, reading[0] if tariff == active_tariff else 0))

        gas = self.gas_delivered_reading()
        if gas is not None:
            samples.append(('gas_delivered_reading', {'gas_eid': self.gas_eid()}, gas[0]))

        return samples
