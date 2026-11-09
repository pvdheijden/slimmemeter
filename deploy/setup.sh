#!/usr/bin/env bash
#
# Install or upgrade slimmemeter on this Raspberry Pi: the P1-data and weather clients,
# Prometheus, Grafana and their supervisor configuration. Safe to run again, it only
# downloads what is missing and keeps the Prometheus data across upgrades.
#
# Run as root from a copy of the repository, deploy/install-remote.sh does this over SSH:
#   sudo deploy/setup.sh [service-user]
#
# service-user runs the P1-data and weather clients and needs access to the serial port,
# default 'pi'.

set -euo pipefail

PROMETHEUS_VERSION=3.16.0
# 13.1 is the last Grafana with the Prometheus data source built in. From 13.2 it is a
# separate plugin, and its ARM build crashes on the ARMv6 of a Pi Zero (illegal instruction).
GRAFANA_VERSION=13.1.9

SERVICE_USER=${1:-pi}
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
APP=/opt/slimmemeter
VENV=/opt/slimmemeter-venv
PROGRAMS=(p1dataclient weather prometheus grafana)

log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; WARNINGS=$((WARNINGS + 1)); }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
WARNINGS=0

# --- Checks before anything is changed -------------------------------------------------

[ "$(id -u)" -eq 0 ] || die "run as root: sudo $0 $*"
id "$SERVICE_USER" >/dev/null 2>&1 \
    || die "user '$SERVICE_USER' does not exist, pass the user that should run the clients"
SERVICE_HOME=$(getent passwd "$SERVICE_USER" | cut -d: -f6)

case "$(uname -m)" in
    armv6l) ARCH=armv6 ;;
    armv7l) ARCH=armv7 ;;
    aarch64) ARCH=arm64 ;;
    x86_64) ARCH=amd64 ;;
    *) die "no Prometheus and Grafana downloads for architecture $(uname -m)" ;;
esac

# The installation links to versioned directories, a real directory in their place would
# be replaced by a link inside it
for name in p1dataclient weather prometheus grafana; do
    if [ -e "/opt/$name" ] && [ ! -L "/opt/$name" ]; then
        die "/opt/$name is a directory, not a symbolic link. Move it away and run again"
    fi
done

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# --- Helpers ----------------------------------------------------------------------------

download() {  # download URL SHA256 FILE
    local url=$1 sum=$2 file=$3
    [[ $sum =~ ^[0-9a-f]{64}$ ]] || die "no checksum for $url"
    curl -fL --retry 3 --progress-bar -o "$file" "$url"
    echo "$sum  $file" | sha256sum -c --quiet - || die "checksum of $url does not match"
}

wait_for() {  # wait_for NAME URL SECONDS
    local name=$1 url=$2 seconds=$3 waited=0
    until curl -fs -o /dev/null "$url"; do
        if [ "$waited" -ge "$seconds" ]; then
            warn "$name does not respond on $url after ${seconds}s, see /var/log/$name*.log"
            return 1
        fi
        sleep 5
        waited=$((waited + 5))
    done
    echo "$name is up"
}

# --- System packages --------------------------------------------------------------------

log "Installing system packages"
apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-venv supervisor curl
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
    || die "Python 3.9 or newer is needed, this is $(python3 --version)"

# --- Application ------------------------------------------------------------------------

log "Installing the application in $APP"
if [ "$SRC" != "$APP" ]; then
    rm -rf "$APP.new"
    cp -r "$SRC" "$APP.new"
    # The copy is owned by root and readable for the service user, whatever the source was
    chown -R root:root "$APP.new"
    chmod -R u=rwX,go=rX "$APP.new"
    rm -rf "$APP"
    mv "$APP.new" "$APP"
fi
ln -sfn "$APP/p1dataclient" /opt/p1dataclient
ln -sfn "$APP/weather" /opt/weather

log "Installing the Python packages in $VENV"
[ -x "$VENV/bin/python3" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --disable-pip-version-check -r "$APP/requirements.txt"

# The P1 port is a serial device of group dialout
usermod -aG dialout "$SERVICE_USER"
[ -e /dev/serial0 ] || warn "/dev/serial0 does not exist, enable the serial port with raspi-config \
(Interface Options > Serial Port: no login shell, hardware enabled) and reboot"

# --- Prometheus -------------------------------------------------------------------------

PROMETHEUS=prometheus-$PROMETHEUS_VERSION.linux-$ARCH
if [ ! -x "/opt/$PROMETHEUS/prometheus" ]; then
    log "Downloading Prometheus $PROMETHEUS_VERSION"
    base=https://github.com/prometheus/prometheus/releases/download/v$PROMETHEUS_VERSION
    sum=$(curl -fsSL "$base/sha256sums.txt" | awk -v f="$PROMETHEUS.tar.gz" '$2 == f { print $1 }')
    download "$base/$PROMETHEUS.tar.gz" "$sum" "$TMP/prometheus.tar.gz"
    tar xzf "$TMP/prometheus.tar.gz" -C /opt --no-same-owner
fi

log "Configuring Prometheus $PROMETHEUS_VERSION"
# Prometheus keeps its data in the version directory, take it along to the new version
current=$(readlink -f /opt/prometheus || true)
if [ -n "$current" ] && [ "$current" != "/opt/$PROMETHEUS" ] && [ -d "$current/data" ] \
        && [ ! -e "/opt/$PROMETHEUS/data" ]; then
    echo "moving the data of $current"
    supervisorctl stop prometheus >/dev/null 2>&1 || true
    mv "$current/data" "/opt/$PROMETHEUS/"
fi
ln -sfn "$PROMETHEUS" /opt/prometheus
cp "$APP/conf/prometheus.yml" "/opt/$PROMETHEUS/"

# --- Grafana ----------------------------------------------------------------------------

GRAFANA=grafana-$GRAFANA_VERSION
if [ ! -x "/opt/$GRAFANA/bin/grafana" ]; then
    log "Downloading Grafana $GRAFANA_VERSION"
    url=https://dl.grafana.com/oss/release/$GRAFANA.linux-$ARCH.tar.gz
    sum=$(curl -fsSL "$url.sha256" | tr -d '[:space:]')
    download "$url" "$sum" "$TMP/grafana.tar.gz"
    tar xzf "$TMP/grafana.tar.gz" -C /opt --no-same-owner
fi

log "Configuring Grafana $GRAFANA_VERSION"
# The Prometheus data source and the dashboard are provisioned, a new Grafana needs no setup
ln -sfn "$GRAFANA" /opt/grafana
cp "$APP/conf/grafana/datasource.yaml" "/opt/$GRAFANA/conf/provisioning/datasources/slimmemeter.yaml"
cp "$APP/conf/grafana/dashboards.yaml" "/opt/$GRAFANA/conf/provisioning/dashboards/slimmemeter.yaml"
cp "$APP/conf/grafana/custom.ini" "/opt/$GRAFANA/conf/custom.ini"

# --- Supervisor -------------------------------------------------------------------------

log "Configuring supervisor"
for program in p1dataclient weather; do
    sed -e "s|^user = .*|user = $SERVICE_USER|" \
        -e "s|HOME=\"[^\"]*\",USER=\"[^\"]*\"|HOME=\"$SERVICE_HOME\",USER=\"$SERVICE_USER\"|" \
        "$APP/conf/$program.conf" > "/etc/supervisor/conf.d/$program.conf"
done
cp "$APP/conf/prometheus.conf" "$APP/conf/grafana.conf" /etc/supervisor/conf.d/

systemctl enable --now supervisor
supervisorctl reread
supervisorctl update
# update only restarts programs whose configuration changed, the code may have changed too
supervisorctl restart "${PROGRAMS[@]}"

# --- Check ------------------------------------------------------------------------------

log "Checking the services"
wait_for p1dataclient http://localhost:8000/metrics 60 || true
wait_for weather http://localhost:8001/metrics 60 || true
wait_for prometheus http://localhost:9090/-/ready 120 || true
# Grafana migrates its database on the first start, which takes minutes on a Pi Zero
wait_for grafana http://localhost:3000/api/health 600 || true

# The meter sends a telegram every 1 or 10 seconds, the gauge is 0 until the first one
sleep 15
if curl -fs http://localhost:8000/metrics \
        | awk '$1 == "p1_last_telegram_timestamp_seconds" && $2 + 0 > 0 { found = 1 } END { exit !found }'; then
    echo "telegrams are arriving from the meter"
else
    warn "no telegram received yet, check the P1 cable and /var/log/p1dataclient.log"
fi
supervisorctl status "${PROGRAMS[@]}" || true

log "Done"
host=$(hostname -I 2>/dev/null | awk '{ print $1 }')
echo "Grafana:    http://${host:-<pi>}:3000 (first login admin/admin), dashboard 'Energy consumption'"
echo "Prometheus: http://${host:-<pi>}:9090/targets ('node' stays down, no node exporter is installed)"
if [ "$WARNINGS" -gt 0 ]; then
    echo "$WARNINGS warning(s), see above"
    exit 1
fi
