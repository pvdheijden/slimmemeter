# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Reads Dutch smart-meter ("slimme meter") P1 telegrams over a serial port on a Raspberry Pi Zero and charts them. Production is a single Pi running four supervisord-managed processes; see [INSTALL.md](INSTALL.md) for deployment.

```
meter --UART--> p1dataclient (:8000) --\
OpenWeatherMap --> weather   (:8001) ---+--> Prometheus (:9090, 10s scrape) --> Grafana
```

## Commands

Run from the repo root. There is no build step and no root `requirements.txt`, so CI installs only `flake8` and `pytest`. The tests need nothing else because `p1datametrics.py` and `p1telegram.py` are stdlib-only, so anything tested must stay free of `serial` and `prometheus_client` imports.

```shell
pip install flake8 pytest

pytest                                                                   # all tests
pytest p1dataclient/test_p1datametrics.py::TestP1DataMetrics::test_gas_eid   # single test

flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics       # CI gate, fails the build
flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics   # CI, advisory
```

Running the services for real needs their dependencies (`pip install -r <service>/requirements.txt`, or `pipenv` with each service's `Pipfile`). Each service has its own dependency set.

```shell
cd p1dataclient && python3 p1dataclient.py /dev/serial0   # needs the meter on a serial port
cd weather && python3 weather.py
```

## Architecture

The two services are independent long-running scripts with the same shape: a client class that creates Prometheus gauges and starts the metrics HTTP server in `__init__`, then a `run()` loop of fetch and `store()`, plus a SIGTERM handler under `__main__`.

**`p1dataclient/`** separates I/O from parsing:
- `p1dataclient.py` owns the serial port (115200 8N1) and the metrics. `receive()` blocks until it has a telegram with a valid CRC.
- `p1telegram.py` does the framing (`/` line to `!` line) and CRC check on raw bytes, before anything is decoded. Telegrams that fail are dropped and counted in `p1_telegram_crc_errors_total`. `readline()` has a timeout and can return part of a line, so `TelegramAssembler.feed()` buffers until a line is complete.
- `p1datametrics.py` is the pure parser. Its module docstring is an annotated example telegram, and `P1DataMetrics` maps OBIS codes (such as `1-0:1.8.1`) to lists of parenthesised values.

**`weather/weather.py`** polls the OpenWeatherMap One Call API every 60s for a fixed location. `weather/__init__.py` imports a nonexistent `temperature` module, so `weather` also only works as a script.

**`conf/`** holds the deployed config: supervisord programs, `prometheus.yml`, and the Grafana dashboard. `doc/` holds the DSMR P1 specs and hardware schematics.

## Behaviour to preserve

- **Run as scripts, tested as a package.** `p1dataclient.py` uses `from p1datametrics import ...` and needs that directory as its cwd (supervisord sets it), while the test uses `from .p1datametrics import ...`. Don't change either style without updating the other.
- **Absent metrics are normal.** Not all meters report every OBIS code. Accessors return `None` for an absent or malformed reading (`''` for identifiers) instead of raising, and `samples()` leaves it out, so Prometheus gets no value rather than a false 0. New readings should go through `_reading()`.
- **`samples()` decides what is published, `store()` only writes it.** Keep that logic in `P1DataMetrics`, where it can be tested without `prometheus_client`. Calling `.labels()` alone creates a series with value 0, so only call it for values that exist.
- **Gas is a special case.** Its OBIS entry has the timestamp first, so the reading is at index `[1]`, and its M-Bus channel is looked up from device type `003` rather than assumed to be 1.
- **Metric names are an interface.** `conf/dashboard.json` queries gauges by name and label, so renaming one breaks the dashboard, and Prometheus history stays under the old name.
- **`power_delivered` and `l{1,2,3}_power_delivered` are published for both `tariff_indicator` labels.** The active tariff gets the value and the other gets 0, which the dashboard's per-tariff panels rely on.
- **A silent meter must stay visible.** Gauges keep their last value when telegrams stop, so `p1_last_telegram_timestamp_seconds` is what shows an outage (`time() - p1_last_telegram_timestamp_seconds` on the dashboard).
- **Crashing is the recovery path.** supervisord restarts the client on unhandled exceptions such as `SerialException`, so don't add a broad `except` around the receive loop.
- **Temperature is in Kelvin.** The API call sets no `units`, and the dashboard subtracts 273.15.
- **Target platform is old.** Binaries are ARMv6 on a Pi Zero, so check that new dependencies are available there.

## Config gotchas

- `conf/p1dataclient.conf` is the deployed supervisord file. `p1dataclient/p1dataclient.conf` is a stale copy that still uses `/home/pi` and `/usr/bin/python`.
- INSTALL.md does not cover the `weather` service, although `conf/weather.conf` and its scrape job exist. It also misspells the config path as `conf/p1dataclint.conf`.
- `prometheus.yml` scrapes a `node` job on `:9100`, but no node exporter is set up in this repo.
