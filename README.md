# slimmemeter
"Slimmme-meter" P1-data reader and presenter

Latest version: 1.2.0

## The P1-data collection

![P1-data collector schematics](https://raw.githubusercontent.com/pvdheijden/slimmemeter/master/doc/p1_connector-opencollector.png)

![P1-data collector assembled](https://raw.githubusercontent.com/pvdheijden/slimmemeter/master/doc/p1_connector_assembled.jpg)


## The P1-data presentation

![Grafana dashboard](https://raw.githubusercontent.com/pvdheijden/slimmemeter/master/doc/grafana-screenshot.png)

## Version history
- 1.0.0: First deployed version
- 1.1.0: Not all Slimmemeters provide all metrics, be abel to cope with absent metrics. If metric value is absend a 'no value' will be stored.
- 1.2.0: Telegrams with an invalid CRC are discarded. Absent or malformed values are stored as 'no value' instead of 0, as intended since 1.1.0. Gas meters on any M-Bus channel are supported. A meter that stops sending shows up on the dashboard and in the log. Logging defaults to INFO, set `LOG_LEVEL` to change it. Weather data now comes from [Buienradar.nl](https://www.buienradar.nl), as the OpenWeatherMap API used before was closed.
