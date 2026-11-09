# Moving data collection to a Raspberry Pi Pico W

Status, on the `pico` branch:

| Part | State |
|---|---|
| P1-data client reads `socket://` addresses (phase 2) | Done and tested, also against a stand-in for the Pico |
| Docker stack in `docker/` (phase 1) | Done, tested on a development machine against the Pi. Not yet on apollo |
| Pico firmware in `pico/` (phase 3) | Written and tested with stand-ins for the Pico hardware. Not yet on a Pico |
| Switch-over (phase 4) and clean-up (phase 5) | To do, needs the Pico and apollo |

Today a Raspberry Pi Zero next to the meter does everything: it reads the P1 port and runs the P1-data client, the weather client, Prometheus and Grafana (see [INSTALL.md](INSTALL.md)). This plan moves that work apart:

- A **Raspberry Pi Pico W** at the meter does one job: it passes the raw P1 data on to the network.
- **apollo**, a server on the home network, runs the P1-data client, the weather client, Prometheus and Grafana as Docker containers.

```
meter --P1--> Pico W --WiFi, TCP port 2000, raw telegrams--> apollo (docker compose)
                                                               ├─ p1dataclient  (:8000)  reads socket://<pico>:2000
                                                               ├─ weather       (:8001)
                                                               ├─ prometheus    (:9090)
                                                               └─ grafana       (:3000)
```

## Design

### The Pico is a network serial port

The Pico does not parse anything. It forwards every byte the meter sends to whoever is connected to TCP port 2000.

The P1-data client keeps doing all the work: it frames the telegrams, checks the CRC, parses them and publishes the metrics. Only how it opens its input changes. It uses pyserial's `serial_for_url()` instead of `Serial()`. That accepts both a serial device such as `/dev/serial0` and a network address such as `socket://pico:2000`, so the Pi setup keeps working with the same code.

This keeps:
- **The tested code:** the parser, the CRC check, the metric names and their tests stay unchanged.
- **The recovery behaviour:** if the connection to the Pico drops, the P1-data client crashes and Docker restarts it, as supervisord does today.
- **Outage detection:** the "Last telegram" panel shows when data stops arriving, whether the cause is the meter, the Pico or the network.
- **A small Pico program:** about 80 lines of MicroPython. New metrics never need the Pico to be reprogrammed.

### Alternative considered: the Pico publishes the metrics

The Pico could parse the telegrams and serve `/metrics` for Prometheus itself, without a P1-data client container. This was not chosen: the parser and its tests would have to be rewritten in MicroPython, and every new metric would need a firmware update at the meter.

## Hardware

### Parts

- Raspberry Pi Pico W or Pico 2 W. The plain Pico has no network.
- A USB power supply and a micro-USB cable for the Pico.
- An RJ12 (6P6C) cable for the P1 port.
- One resistor of 1 kΩ to 2.2 kΩ.

### Power

Power the Pico from USB, not from the P1 port.
- A DSMR 4.x meter, like the Kaifa here (DSMR 4.2), supplies at most 100 mA on P1 pin 1, and the WiFi chip of the Pico W draws peaks above that.
- A DSMR 5 meter supplies up to 250 mA, which would be enough, but USB power works for both.

### P1 port

From the DSMR P1 specifications in [doc/](doc/):

| P1 pin | Signal | Direction | Specification |
|---|---|---|---|
| 1 | +5 V | power from the meter | DSMR 4: max 100 mA. DSMR 5: max 250 mA |
| 2 | Data Request | to the meter | High (4.0 to 5.5 V) makes the meter send. It may stay high. Never pull it to ground |
| 3 | Data GND | | Ground of the data lines |
| 4 | not connected | | |
| 5 | Data | from the meter | Open collector, logically inverted, 115200 baud 8N1 |
| 6 | Power GND | | Ground of the +5 V supply |

Check the pin numbering of the RJ12 plug against the figure in the DSMR specification before soldering.

### Connections

| P1 pin | Signal | Pico W pin | Pico W signal | Why |
|---|---|---|---|---|
| 2 | Data Request | 40 | VBUS (5 V from USB) | The request needs at least 4.0 V. The Pico's 3.3 V outputs are not enough |
| 3 | Data GND | 38 | GND | Common ground for the data line |
| 5 | Data | 2 | GP1 (UART0 RX) | Read by UART0 |
| 5 | Data | 36, through R1 | 3V3(OUT) | Pull-up for the open collector |
| 1, 4, 6 | | | | Not connected |

### Wiring diagram

```
   P1 port (RJ12, meter side)                  Raspberry Pi Pico W (powered by USB)

   1  +5 V       --x  not connected
   2  Request    ------------------------------------------ pin 40  VBUS (5 V)
   3  Data GND   ------------------------------------------ pin 38  GND
   4  n.c.       --x
   5  Data       -----------------+------------------------ pin 2   GP1 (UART0 RX)
                                  |
                                 +-+
                                 | |  R1 1 kΩ to 2.2 kΩ
                                 | |
                                 +-+
                                  |
                                  +------------------------ pin 36  3V3(OUT)
   6  Power GND  --x  not connected
```

Notes:
- **Pull the data line up to 3.3 V, never to 5 V.** The Pico's inputs take at most 3.3 V, and 5 V on GP1 can damage it.
- **Use a pull-up of 1 kΩ to 2.2 kΩ.** A higher value, such as the Pico's internal pull-up of about 50 kΩ, makes the edges too slow for 115200 baud. With 1 kΩ the meter sinks 3.3 mA, within the 5 mA of its output.
- **No inverter is needed.** The P1 data signal is inverted. The current Pi uses a transistor circuit for that ([doc/p1_connector-opencollector.png](doc/p1_connector-opencollector.png)), while the Pico inverts its UART input in software.
- **Request is tied to 5 V permanently,** so the meter sends a telegram every 10 seconds (DSMR 4) or every second (DSMR 5), as long as the Pico has power.

## Pico firmware

The firmware goes in `pico/` in this repository, written in MicroPython.

`pico/main.py`:
- Joins the WiFi network, and reconnects when the connection drops.
- Reads UART0 at 115200 baud 8N1 with an inverted receive line and a 4 KB receive buffer: `UART(0, 115200, rx=Pin(1), invert=UART.INV_RX, rxbuf=4096)`.
- Runs a TCP server on port 2000 and forwards everything it receives from the meter. A new connection replaces the old one, and anything sent to the Pico is ignored.
- Blinks the LED for each telegram, which shows at a glance in the meter cupboard that data arrives.
- Uses the hardware watchdog to restart itself if it hangs.

`pico/config.example.py` shows the settings: the WiFi name, the password, the hostname, the port and the watchdog. The real values go in `pico/config.py`, which `.gitignore` keeps out of git. Set `WATCHDOG = False` while developing: once started, the watchdog also resets the Pico while it waits at the REPL.

`pico/test_main.py` runs the firmware with CPython, with stand-ins for the MicroPython modules `machine`, `network` and `rp2`, and a real TCP server on localhost. It checks:
- the UART settings;
- that data arrives unchanged;
- that a new connection replaces the old one;
- that data without a client is dropped;
- the LED flashes;
- that a client that went away is dropped.

What only the Pico can show, such as the inverted UART and the WiFi connection, needs the device. `mpy-cross pico/main.py` (`pip install mpy-cross`) checks that MicroPython compiles it.

Installing:
```shell script
pip install mpremote
# Flash MicroPython for the Pico W first, see https://micropython.org/download/RPI_PICO_W/
cp pico/config.example.py pico/config.py   # then fill in the WiFi name and password
mpremote cp pico/config.py pico/main.py :
mpremote reset
```

Testing:
- **On the bench:** a USB-serial adapter replaying a captured telegram stands in for the meter.
- **At the meter:** `nc <pico> 2000` shows the telegrams arriving every 10 seconds.

Give the Pico a fixed address in the router, so apollo can always find it.

## apollo: Docker stack

Files in `docker/`:
- **`Dockerfile`:** one image for the P1-data and weather clients, based on `python:3.13-slim` with the root `requirements.txt`. Each client runs with its own folder as the working directory, because the scripts import their modules directly.
- **`compose.yaml`:** four services, all with `restart: unless-stopped`:

| Service | Image | Port | Data |
|---|---|---|---|
| `p1dataclient` | built from `docker/Dockerfile` | 8000, internal | `P1_URL=socket://<pico>:2000` |
| `weather` | built from `docker/Dockerfile` | 8001, internal | `BUIENRADAR_STATION_ID`, default 6356 |
| `prometheus` | `prom/prometheus:v3.16.0` | 9090 | volume `prometheus-data`, retention 10 years capped at 4 GB |
| `grafana` | `grafana/grafana:13.3.0` | 3000 | volume `grafana-data`, provisioning from `conf/grafana/` |

- **Prometheus configuration:** inside Docker, Prometheus scrapes the clients by service name (`p1dataclient:8000`, `weather:8001`), so it gets its own `docker/prometheus.yml`. For the same reason Grafana gets `docker/grafana-datasource.yaml`, with `http://prometheus:9090` as the data source.
- **`compose.pi.yaml`:** for the time the Pi still reads the meter. It leaves out the P1-data client container and lets Prometheus scrape the P1-data client on the Pi instead (`docker/prometheus-pi.yml`).

Running it, from `docker/`:
```shell script
# While the Pi reads the meter
PI_ADDRESS=192.168.1.244 docker compose -f compose.yaml -f compose.pi.yaml up -d --build

# With the Pico
P1_URL=socket://<pico>:2000 docker compose up -d --build
```
- Grafana is on port 3000, first login `admin`/`admin`. Prometheus is on port 9090.
- `P1_URL` is not required by the compose file, so the Pi variant works without it. Without it, the P1-data client container stops with a message saying to set it.
- While the Pico is unreachable, the P1-data client fails to connect and Docker keeps restarting it. Docker waits longer between restarts, up to about a minute, so data returns within a minute after the Pico is back.
- **Grafana version:** on apollo the newest Grafana works. The pin to 13.1 is only needed on the Pi Zero, where newer Grafana plugins crash on its ARMv6 processor. `conf/grafana/custom.ini`, which turns off background plugin installs, is not needed on apollo either.
- **The dashboard:** `conf/dashboard.json` and the provisioning files are used unchanged.

## Changes to this repository

| Change | Phase | State |
|---|---|---|
| `p1dataclient.py` opens its input with `serial_for_url()`, from the command line or `P1_URL`. `METRICS_PORT` sets the metrics port, default 8000 | 2 | Done |
| `p1dataclient/test_network_input.py`: replays a captured telegram through a local TCP server, and checks the client exits when the connection drops | 2 | Done |
| `docker/`: `Dockerfile`, `compose.yaml`, `compose.pi.yaml`, `prometheus.yml`, `prometheus-pi.yml`, `grafana-datasource.yaml` | 1 | Done |
| `pico/main.py`, `pico/config.example.py`, `pico/test_main.py`, and `pico/config.py` in `.gitignore` | 3 | Done |
| `INSTALL.md` describes the Pico and apollo setup | 5 | To do |
| A Pico wiring diagram in `doc/` | 5 | To do |

The Pi files (`deploy/`, the supervisor configuration in `conf/`) stay until the Pi is retired.

## Migration

The steps keep the current Pi running until the new setup has proven itself.

**0. Prepare apollo**
- Make SSH access to apollo work for deployment.
- Check:
    - the processor architecture (amd64 or arm64);
    - that Docker and `docker compose` are installed;
    - that ports 3000, 9090, 8000 and 8001 are free;
    - the free disk space.
- Measure the WiFi signal in the meter cupboard, for example with a phone.

**1. Run the Docker stack on apollo, fed by the Pi**
- Copy the repository to apollo and start the stack with `compose.pi.yaml`, while the Pi keeps running. No hardware changes yet.
- Prometheus on apollo scrapes the P1-data client on the Pi (`slimmemeter:8000`).
- Check that the dashboard on apollo shows live meter data.

**2. Let the P1-data client read from the network**
- Switch the P1-data client to `serial_for_url()`.
- Add the replay test. The Pi keeps working with `/dev/serial0`.

**3. Build and test the Pico**
- Write and install the firmware.
- Test it on the bench, then at the meter, with the Pi unplugged for the test only.

**4. Switch over**
- Move the history:
    1. Stop Prometheus on the Pi.
    2. Copy its data folder `/opt/prometheus/data` into the `prometheus-data` volume on apollo.
    3. Give the copy owner `65534`, the user the Prometheus container runs as.
- Unplug the Pi from the meter and plug in the Pico.
- Restart the stack on apollo without `compose.pi.yaml` and with `P1_URL` set to the Pico.
- Check:
    - "Last telegram" stays under 15 seconds;
    - "Telegrams with CRC errors" stays at 0;
    - the history from before the switch is still on the dashboard.
- Leave the Pi intact for a week. Going back only means moving the P1 cable back.

**5. Clean up**
- Update `INSTALL.md` and `CLAUDE.md`.
- Add the wiring diagram to `doc/`.
- Decide what happens to the Pi and its files.

## Risks

| Risk | Mitigation |
|---|---|
| Weak WiFi in the meter cupboard | Measure it in step 0. If it is too weak, a W5500-EVB-Pico has wired Ethernet, and only the network part of the firmware changes |
| Telegrams lost while WiFi or apollo is down | The meter sends every 10 seconds and its readings are totals, so a gap loses detail but no energy. "Last telegram" shows the gap |
| The Pico's port is open on the home network | It only sends meter data and ignores what it receives. If needed, limit access to apollo in the router |
| 5 V on a Pico input | Only VBUS carries 5 V, to the Request line. The data line is pulled up to 3.3 V |
| A DSMR 5 meter later, sending every second | The 4 KB receive buffer and WiFi handle that easily |

## Open points

- Pico W or Pico 2 W, and whether one is available.
- What happens to the Pi Zero after the move: keep it as a fallback or reuse it.
- SSH access to apollo: its SSH configuration points at `~/.ssh/apollo.pub`, a public key, so logging in fails.
