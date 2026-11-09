## Rapsberry Pi Zero Slimmemeter installation

Slimmemeter:
- P1-data client --> collects the P1-data from the Slimmemeter and exposes this data as 'Prometheus metrics'.
- [prometheus](https://prometheus.io/docs/introduction/overview/) --> scrapes the metrics. 
- [grafana](https://grafana.com/docs/) --> presents the overview of the energy consumption.

The process are controlled/monitored via [Supervisor: A Process Control system](http://supervisord.org/)

Overall functionality, i.e. 'slimmemeter' consists of 4 applications
- p1dataclient --> the p1-data 'collector'
- weather --> collects the local weather from Buienradar
- prometheus --> stores the collected p1-data
- grafana --> presents the stored p1-data

The 4 applications are installed in /opt/<application> (logical link to /opt/<application>) managed with supervisord.

### Python environment
- The P1-data client and the weather client share one virtual environment in `/opt/slimmemeter-venv`, with the pinned versions from `requirements.txt`. Raspberry Pi OS (Bookworm and later) does not allow pip to install into the system Python
- Requires Python 3.9 or newer, check with `python3 --version`
```shell script
git clone https://github.com/projectx2-nl/slimmemeter.git

sudo apt install python3-venv
sudo python3 -m venv /opt/slimmemeter-venv
sudo /opt/slimmemeter-venv/bin/pip install -r slimmemeter/requirements.txt
```
- After a `git pull` that changes `requirements.txt`, run the `pip install` again and restart both clients

### P1-data client installation
```shell script
sudo ln -s <src-dir> /opt/p1dataclient
```

### Weather client installation
- Uses the Buienradar station Herwijnen by default. For another station, add `BUIENRADAR_STATION_ID` with its `stationid` from https://data.buienradar.nl/2.0/feed/json to the `environment` line in `conf/weather.conf`
- Weather data: [Buienradar.nl](https://www.buienradar.nl), free for non-commercial use with attribution
```shell script
sudo ln -s <src-dir> /opt/weather
```

### Prometheus installation
- Download (and unpack) Prometheus ARMv6 binary from: https://prometheus.io/download/
- Configure Prometheus to scrape the P1-data metrics (exposed on fixed port 8000) and the weather metrics (exposed on fixed port 8001)
```shell script
tar xvf prometheus-2.13.1.linux-armv6.tar.gz
sudo ln -s ./prometheus-2.13.1.linux-armv6 /opt/prometheus
sudo cp conf/prometheus.yml /opt/prometheus/
```

### Grafana installation
- Download (and unpack) Grafana ARMv6 binary from: https://grafana.com/grafana/download?platform=arm
- Import the dashboard for the P1-data (`conf/dashboard.json`)
```shell script
tar xvf grafana-6.4.3.linux-armv6.tar.gz
sudo ln -s ./grafana-6.4.3 /opt/grafana
```

### Supervisor installation
- Install the Supervisor package 
```shell script
sudo apt install supervisor

sudo cp conf/p1dataclient.conf /etc/supervisor/conf.d/
sudo cp conf/weather.conf /etc/supervisor/conf.d/
sudo cp conf/prometheus.conf /etc/supervisor/conf.d/
sudo cp conf/grafana.conf /etc/supervisor/conf.d/
```
- Restart the supervisor service to load the configuration files

### Logging
The P1-data client and the weather client log at INFO. For more detail, including the raw telegrams, add `LOG_LEVEL="DEBUG"` to the `environment` line of the program in its supervisor configuration file.

### Upgrading to 1.2.0
The clients now run from the shared virtual environment. Create it as described under 'Python environment', then install the new supervisor configuration files. `supervisorctl update` restarts the programs whose configuration changed:
```shell script
sudo cp conf/p1dataclient.conf conf/weather.conf /etc/supervisor/conf.d/
sudo supervisorctl reread
sudo supervisorctl update
```
Telegrams with an invalid CRC are now discarded, so check straight after the restart that data is still arriving:
```shell script
curl -s localhost:8000/metrics | grep '^p1_'
```
- `p1_last_telegram_timestamp_seconds` should keep increasing and `p1_telegram_crc_errors_total` should stay at or near 0
- If every telegram is rejected, `/var/log/p1dataclient.log` shows `discarded telegram with invalid CRC` and no new data is stored
- Import `conf/dashboard.json` again to get the 'Time since last telegram' panel
- Metrics a meter does not provide now show 'no value' instead of 0, for example L2 and L3 on a single-phase meter
- The weather client now uses Buienradar, because the OpenWeatherMap API it used was closed. It needs no API key
- The packages installed earlier with `sudo pip install` are no longer used and can be removed
