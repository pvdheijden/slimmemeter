# Settings of the Pico firmware. Copy this file to config.py and fill in the WiFi network.
# config.py is not stored in git, as it holds the WiFi password.

WIFI_SSID = 'my-network'
WIFI_PASSWORD = 'my-password'

# Name of the Pico on the network, and the country for the WiFi radio regulations
HOSTNAME = 'p1-pico'
COUNTRY = 'NL'

# TCP port the P1 data is sent on, P1_URL on apollo is socket://<pico>:2000
PORT = 2000

# The hardware watchdog restarts the Pico if it hangs. Set to False while developing,
# as it also resets the Pico while it waits at the REPL.
WATCHDOG = True
