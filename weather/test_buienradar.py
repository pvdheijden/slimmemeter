import unittest

from .buienradar import find_station, readings

HERWIJNEN = {
    'stationid': 6356,
    'stationname': 'Meetstation Herwijnen',
    'lat': 51.87,
    'lon': 5.15,
    'timestamp': '2026-11-08T11:00:00',
    'temperature': 9.2,
    'humidity': 89.0,
    'airpressure': 1023.1,
}

FEED = {
    'actual': {
        'stationmeasurements': [
            {'stationid': 6275, 'stationname': 'Meetstation Arnhem', 'temperature': 8.5},
            HERWIJNEN,
        ]
    }
}


class TestFindStation(unittest.TestCase):
    """Station lookup tests"""

    def test_station_found(self):
        self.assertIs(find_station(FEED, 6356), HERWIJNEN)

    def test_station_missing(self):
        self.assertIsNone(find_station(FEED, 9999))

    def test_unexpected_feed(self):
        for feed in ({}, [], None, {'actual': None}, {'actual': {'stationmeasurements': None}},
                     {'actual': {'stationmeasurements': [None, 'x']}}):
            self.assertIsNone(find_station(feed, 6356), repr(feed))


class TestReadings(unittest.TestCase):
    """Reading conversion tests"""

    def test_all_readings(self):
        result = readings(HERWIJNEN)
        self.assertAlmostEqual(result['temperature'], 282.35)
        self.assertEqual(result['humidity'], 89.0)
        self.assertEqual(result['pressure'], 1023.1)

    def test_freezing_point_is_273_15_kelvin(self):
        self.assertAlmostEqual(readings({'temperature': 0})['temperature'], 273.15)

    def test_missing_and_null_values_left_out(self):
        self.assertEqual(readings({'temperature': None, 'humidity': 90.0}), {'humidity': 90.0})

    def test_non_numeric_values_left_out(self):
        self.assertEqual(readings({'temperature': '9.2', 'humidity': True, 'airpressure': 1023.1}),
                         {'pressure': 1023.1})


if __name__ == '__main__':
    unittest.main()
