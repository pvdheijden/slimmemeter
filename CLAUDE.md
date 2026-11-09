# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Reads Dutch smart-meter ("slimme meter") P1 telegrams over a serial port on a Raspberry Pi Zero and charts them. Production is a single Pi running four supervisord-managed processes; see [INSTALL.md](INSTALL.md) for deployment.

```
meter --UART--> p1dataclient (:8000) --\
Buienradar     --> weather   (:8001) ---+--> Prometheus (:9090, 10s scrape) --> Grafana
```

## Commands

Run from the repo root. There is no build step. CI installs the root `requirements.txt` plus `flake8` and `pytest`. The parsing modules (`p1datametrics.py`, `p1telegram.py`, `weather/buienradar.py`) are kept stdlib-only. Tests import the services as packages, so they can't import the script modules `p1dataclient.py` and `weather.py`, which use script-style imports.

```shell
pip install -r requirements.txt flake8 pytest

pytest                                                                   # all tests
pytest p1dataclient/test_p1datametrics.py::TestP1DataMetrics::test_gas_eid   # single test

flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics       # CI gate, fails the build
flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics   # CI, advisory
```

Both services share one pinned `requirements.txt` at the root and, on the Pi, one virtual environment in `/opt/slimmemeter-venv` that the supervisord configs run. Pins must keep working on Python 3.9, and on ARMv6, so only pure-Python packages or ones with ARMv6 wheels. Add new dependencies there with an exact version.

```shell
cd p1dataclient && python3 p1dataclient.py /dev/serial0   # needs the meter on a serial port
cd weather && python3 weather.py
```

Both services log at INFO. Set `LOG_LEVEL=DEBUG` to include raw telegrams and parsed values, which on the Pi goes in the program's `environment` line in its supervisord config.

## Architecture

The two services are independent long-running scripts with the same shape: a client class that creates Prometheus gauges and starts the metrics HTTP server in `__init__`, then a `run()` loop of fetch and `store()`, plus a SIGTERM handler under `__main__`.

**`p1dataclient/`** separates I/O from parsing:
- `p1dataclient.py` owns the serial port (115200 8N1) and the metrics. `receive()` blocks until it has a telegram with a valid CRC.
- `p1telegram.py` does the framing (`/` line to `!` line) and CRC check on raw bytes, before anything is decoded. Telegrams that fail are dropped and counted in `p1_telegram_crc_errors_total`. `readline()` has a timeout and can return part of a line, so `TelegramAssembler.feed()` buffers until a line is complete.
- `p1datametrics.py` is the pure parser. Its module docstring is an annotated example telegram, and `P1DataMetrics` maps OBIS codes (such as `1-0:1.8.1`) to lists of parenthesised values.

**`weather/`** follows the same split. `weather.py` fetches the Buienradar JSON feed every 5 minutes and publishes one station's readings (`BUIENRADAR_STATION_ID`, default 6356 Herwijnen), and `buienradar.py` is the stdlib-only parser. Buienradar's measurements are KNMI station data, updated every 10 minutes. Its terms require attribution with a link to buienradar.nl, which the dashboard carries.

**`conf/`** holds the deployed config: supervisord programs, `prometheus.yml`, the Grafana dashboard, and Grafana provisioning for the data source and dashboard (`conf/grafana/`). `doc/` holds the DSMR P1 specs and hardware schematics.

**`deploy/`** installs everything on a Pi. `install-remote.sh [user@]host` copies the working tree over SSH and runs `setup.sh` there as root. `setup.sh` is idempotent, pins the Prometheus and Grafana versions at its top (keep them in step with `INSTALL.md`), and moves the Prometheus data, which lives in the version directory, to a new version.

## Behaviour to preserve

- **Run as scripts, tested as a package.** `p1dataclient.py` uses `from p1datametrics import ...` and needs that directory as its cwd (supervisord sets it), while the test uses `from .p1datametrics import ...`. Don't change either style without updating the other.
- **Absent metrics are normal.** Not all meters report every OBIS code. Accessors return `None` for an absent or malformed reading (`''` for identifiers) instead of raising, and `samples()` leaves it out, so Prometheus gets no value rather than a false 0. New readings should go through `_reading()`.
- **`samples()` decides what is published, `store()` only writes it.** Keep that logic in `P1DataMetrics`, where it can be tested without `prometheus_client`. Calling `.labels()` alone creates a series with value 0, so only call it for values that exist.
- **Gas is a special case.** Its OBIS entry has the timestamp first, so the reading is at index `[1]`, and its M-Bus channel is looked up from device type `003` rather than assumed to be 1.
- **Metric names are an interface.** `conf/dashboard.json` queries gauges by name and label, so renaming one breaks the dashboard, and Prometheus history stays under the old name.
- **`power_delivered` and `l{1,2,3}_power_delivered` are published for both `tariff_indicator` labels.** The active tariff gets the value and the other gets 0, which the dashboard's per-tariff panels rely on.
- **A silent meter must stay visible.** Gauges keep their last value when telegrams stop, so `p1_last_telegram_timestamp_seconds` is what shows an outage (`time() - p1_last_telegram_timestamp_seconds` on the dashboard).
- **Crashing is the recovery path for the P1 client.** supervisord restarts it on unhandled exceptions such as `SerialException`, so don't add a broad `except` around the receive loop. The weather client is different: network failures are expected, so it logs them and retries. Crashing there at boot would count as failed starts, and supervisord gives up after 3.
- **Temperature is in Kelvin.** Buienradar reports Celsius, `buienradar.py` adds 273.15, and the dashboard subtracts it again. This keeps the history from the earlier OpenWeatherMap source consistent.
- **Target platform is old.** Binaries are ARMv6 on a Pi Zero, so check that new dependencies are available there. A download labelled ARMv6 is not proof: Grafana's ARMv6 archive runs, but from 13.2 its separate Prometheus plugin is built for ARMv7 and crashes with 'illegal instruction', so Grafana is pinned to 13.1 and its background plugin installs are off (`conf/grafana/custom.ini`). Test an upgrade on the Pi with the dashboard open.

## Config gotchas

- `prometheus.yml` scrapes a `node` job on `:9100`, but no node exporter is set up in this repo.
