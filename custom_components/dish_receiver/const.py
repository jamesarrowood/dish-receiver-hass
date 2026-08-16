"""Constants for the DISH receiver integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "dish_receiver"

# Config entry keys
CONF_HOST = "host"
CONF_NAME = "name"
CONF_MODEL = "model"
CONF_MAC = "mac"
CONF_TRANSPORT = "transport"
CONF_PIN = "pin"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_VERIFY_SSL = "verify_ssl"
# The STB serial number / Receiver ID (an "R…-NN" value, e.g. R0000000000-00).
# Read from the receiver's UPnP device.xml <serialNumber>, or Menu → Settings →
# Diagnostics → System Status. This is the SGS protocol's `stb` field.
CONF_RECEIVER_ID = "receiver_id"
CONF_SERIAL = "serial"
# Controller identity: a stable locally-administered MAC (12 lowercase hex, no
# separators) generated once per entry. The receiver pairs against "XT1<mac>",
# so it must stay constant between pairing and every command.
CONF_CONTROLLER_MAC = "controller_mac"
# Digest credentials minted by the receiver during pairing (response name/passwd).

# Options keys
CONF_FAVORITES = "favorites"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_DELEGATE_ENTITY = "delegate_entity_id"

# Transport identifiers — must match transport.registry keys.
TRANSPORT_LOCAL_HTTP = "local_http"
TRANSPORT_CLOUD = "cloud"
TRANSPORT_DELEGATE = "delegate"

DEFAULT_TRANSPORT = TRANSPORT_LOCAL_HTTP
DEFAULT_SCAN_INTERVAL = timedelta(seconds=10)
DEFAULT_VERIFY_SSL = False  # EchoStar receivers present a self-signed device cert.

# EchoStar's SGS control API lives on port 80. Confirmed against the RTI driver
# source and live hardware: pairing is unauthenticated, remote keys use HTTP
# Digest (MD5, qop=auth) with an EchoStar `message-digest` body-integrity field.
LOCAL_HTTP_PORT = 80
SGS_PAIR_PATH = "/sgs_noauth"  # POST, unauthenticated: device_pairing_start/_complete
SGS_KEY_PATH = "/www/sgs"      # POST, Digest-authed: remote_key
DIGEST_REALM = "Please provide user name and password"

# Application identity presented to the receiver's "Paired Devices" list.
APP_NAME = "Home Assistant"
APP_LABEL = "Home Assistant DISH"
APP_ID = "T1"
APP_TYPE = "application/json"

# UPnP/SSDP discovery. The receiver advertises an EchoStar device description
# whose LOCATION gives the device.xml URL (port varies by model: 49310 on the
# Hopper, 49316 on the Wally — always take it from the SSDP LOCATION).
SSDP_ADDRESS = "239.255.255.250"
SSDP_PORT = 1900
ECHOSTAR_DEVICE_URN = "urn:schemas-echostar-com:device:EchoStarDevice:1"

MANUFACTURER = "EchoStar"

PLATFORMS = ["media_player", "remote"]
