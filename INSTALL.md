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

### Serial port
The meter is connected to the serial port of the Pi (GPIO 15, RXD). Raspberry Pi OS runs a login console on that port by default, so first enable the port without the console, on the Pi itself, and reboot. This is needed for both the installation over SSH and the installation by hand.
- Interactively: `sudo raspi-config`, Interface Options > Serial Port, answer 'No' to a login shell over serial and 'Yes' to enabling the serial port hardware
- Or without questions:
```shell script
sudo raspi-config nonint do_serial_cons 1   # 1 = no login console on the serial port
sudo raspi-config nonint do_serial_hw 0     # 0 = serial port enabled
sudo reboot
```
- After the reboot `ls -l /dev/serial0` shows the port, and `cat /proc/cmdline` no longer contains `console=serial0`
- The user that runs the P1-data client needs to be in the `dialout` group, check with `groups`. On Raspberry Pi OS the first user is, otherwise add it with `sudo usermod -aG dialout <user>` (the installation over SSH does this)

### Installation over SSH
`deploy/install-remote.sh` does the complete installation, or an upgrade, from another computer with a checkout of this repository. It copies the working tree to the Pi and runs `deploy/setup.sh` there with sudo, which carries out the steps below:
```shell script
deploy/install-remote.sh pi@raspberrypi.local
```
- The P1-data and weather clients run as the SSH login user, or as the user given as second argument. That user is added to the `dialout` group for the serial port
- Enable the serial port first, see 'Serial port'. Without it the script warns that `/dev/serial0` does not exist and the P1-data client keeps restarting
- Grafana gets the Prometheus data source and the dashboard through provisioning (`conf/grafana/`), so no manual setup is needed
- Run it again after a change, it only downloads what is missing. The application goes to `/opt/slimmemeter`, `DEPLOYED` there shows the version
- The supervisor configuration files in `/etc/supervisor/conf.d/` are replaced, so put settings such as `LOG_LEVEL` in the files in `conf/`
- The script ends with a check of all services and the meter data, and exits with an error if something is wrong

The sections below describe the same installation by hand.

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
- Download (and unpack) the Prometheus ARMv6 binary, see https://prometheus.io/download/ for newer versions
- Configure Prometheus to scrape the P1-data metrics (exposed on fixed port 8000) and the weather metrics (exposed on fixed port 8001)
- Prometheus stores its data in `/opt/prometheus/data`, inside the version directory, see 'Upgrading Prometheus and Grafana'
```shell script
cd /opt
sudo curl -LO https://github.com/prometheus/prometheus/releases/download/v3.16.0/prometheus-3.16.0.linux-armv6.tar.gz
sudo tar xzf prometheus-3.16.0.linux-armv6.tar.gz
sudo ln -s prometheus-3.16.0.linux-armv6 /opt/prometheus
sudo cp ~/slimmemeter/conf/prometheus.yml /opt/prometheus/
```

### Grafana installation
- Download (and unpack) the Grafana ARMv6 binary
- Stay on Grafana 13.1 on a Pi Zero. From 13.2 the Prometheus data source is a separate plugin, and its ARM build crashes on the ARMv6 of a Pi Zero, so every panel shows an error. Newer 13.1.x releases are fine
- `conf/grafana/custom.ini` stops Grafana from installing plugins from grafana.com in the background, for the same reason
- Grafana stores its settings and users in `/opt/grafana/data`, inside the version directory
```shell script
cd /opt
sudo curl -LO https://dl.grafana.com/oss/release/grafana-13.1.9.linux-armv6.tar.gz
sudo tar xzf grafana-13.1.9.linux-armv6.tar.gz --no-same-owner
sudo ln -s grafana-13.1.9 /opt/grafana
sudo cp ~/slimmemeter/conf/grafana/custom.ini /opt/grafana/conf/
```
- After starting Grafana (port 3000, first login `admin`/`admin`), add a Prometheus data source with URL `http://localhost:9090` as the default data source
- Import the dashboard for the P1-data (`conf/dashboard.json`)

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

### Upgrading Prometheus and Grafana
Install the new versions next to the old ones as described above, then move the Prometheus data across and point the links at the new versions. Prometheus 3 reads the data of Prometheus 2, but once it has written to it Prometheus 2.55 is the oldest version that can go back to it.
```shell script
sudo supervisorctl stop prometheus grafana

sudo mv /opt/prometheus/data /opt/prometheus-3.16.0.linux-armv6/
sudo ln -sfn prometheus-3.16.0.linux-armv6 /opt/prometheus
sudo ln -sfn grafana-13.1.9 /opt/grafana

sudo cp conf/grafana.conf /etc/supervisor/conf.d/
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start prometheus grafana
```
- Grafana 13 is started with `bin/grafana server`, `bin/grafana-server` no longer exists, hence the new `conf/grafana.conf`
- A fresh Grafana is simpler than migrating the database of Grafana 6: add the data source and import `conf/dashboard.json` as for a new installation. The old Grafana directory keeps its data in case it is needed
- The dashboard uses the old 'Graph' and 'Singlestat' panels. Grafana 13 converts them to 'Time series' and 'Stat' panels when it opens the dashboard. Save it to keep the conversion
- Check that `p1dataclient`, `weather` and `prometheus` are 'UP' on http://\<pi\>:9090/targets. The `node` target stays 'DOWN' as no node exporter is installed
- Remove the old version directories when everything works
