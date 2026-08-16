#!/usr/bin/env python3
"""Pair with and control an EchoStar receiver from the shell (confirmed SGS).

This mirrors exactly what the Home Assistant integration does, in a single
stdlib script — handy for troubleshooting or for discovering key names on a
model other than the Wally.

Pair (puts a PIN on the TV, then completes it and prints the credentials):
    python3 verify_control.py 192.168.1.50 --pair
    # read the PIN off the TV, then:
    python3 verify_control.py 192.168.1.50 --complete 1234

Send a key once you have credentials (from --complete, or the HA config entry):
    python3 verify_control.py 192.168.1.50 --user <name> --passwd <passwd> --key Guide

Discover which key names a receiver accepts (result 1 = ok, 20 = unsupported):
    python3 verify_control.py 192.168.1.50 --user <n> --passwd <p> \
        --discover Home Guide Info Up Down Enter DVR TV 1 2 3

Serial is auto-detected via UPnP; pass --serial to override.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import struct
import sys
import urllib.request
import urllib.error

REALM = "Please provide user name and password"
KEY_URI = "/www/sgs"
PAIR_URI = "/sgs_noauth"
md5 = lambda s: hashlib.md5(s.encode()).hexdigest()  # noqa: E731


# -- discovery --------------------------------------------------------------

def discover_serial(host: str, timeout: float = 4.0) -> str | None:
    """Find the receiver's serial via UPnP SSDP + device.xml."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    msg = (
        "M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n'
    ).encode()
    location = None
    try:
        sock.sendto(msg, ("239.255.255.250", 1900))
        import time as _t

        end = _t.monotonic() + timeout
        while _t.monotonic() < end:
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                break
            if addr[0] == host and b"echostar" in data.lower():
                m = re.search(rb"LOCATION:\s*(\S+)", data, re.I)
                if m:
                    location = m.group(1).decode()
                    break
    finally:
        sock.close()
    if not location:
        return None
    try:
        with urllib.request.urlopen(location, timeout=5) as r:
            xml = r.read().decode("utf-8", "replace")
    except OSError:
        return None
    m = re.search(r"<serialNumber>(.*?)</serialNumber>", xml, re.I | re.S)
    return m.group(1).strip() if m else None


# -- HTTP -------------------------------------------------------------------

def post(host: str, path: str, body: str, headers: dict) -> tuple[int, dict, str]:
    req = urllib.request.Request(
        f"http://{host}{path}", data=body.encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


def controller_mac(persist=".verify_mac") -> str:
    if os.path.exists(persist):
        return open(persist).read().strip()
    o = bytearray(os.urandom(6))
    o[0] = (o[0] | 0x02) & 0xFE
    mac = o.hex()
    open(persist, "w").write(mac)
    return mac


def pairing_body(command, serial, mac, pin=None):
    pin_field = f'"pin": "{pin}",' if pin is not None else ""
    return (
        f'{{"command": "{command}",{pin_field}"stb": "{serial}",'
        f'"receiver": "XT1{mac}","app": "Home Assistant","name": "Home Assistant DISH",'
        f'"type": "application/json","id": "T1","mac": "{mac}"}}'
    )


def echostar_auth(user, pw, nonce, body):
    ha1 = md5(f"{user}:{REALM}:{pw}")
    ha2 = md5(f"POST:{KEY_URI}")
    cn = os.urandom(4).hex()
    resp = md5(f"{ha1}:{nonce}:00000001:{cn}:auth:{ha2}")
    mdg = md5(f"{ha1}:{nonce}:{md5(body)}")
    return (
        f'Digest username={user}, realm="{REALM}", nonce="{nonce}", uri="{KEY_URI}", '
        f'algorithm="MD5", qop=auth, nc=00000001, cnonce="{cn}", '
        f'response="{resp}", message-digest="{mdg}"'
    )


def send_key(host, serial, mac, user, pw, key) -> str:
    body = (
        f'{{"receiver": "XT1{mac}","key_name": "{key}","tv_id": "0",'
        f'"stb": "{serial}","command": "remote_key"}}'
    )
    st, hd, _ = post(host, KEY_URI, body, {"Content-Type": "application/json"})
    if st != 401:
        return f"(no challenge, HTTP {st})"
    nonce = re.search(r'nonce="([^"]+)"', hd.get("WWW-Authenticate", "")).group(1)
    auth = echostar_auth(user, pw, nonce, body)
    st, _, text = post(
        host, KEY_URI, body, {"Content-Type": "application/json", "Authorization": auth}
    )
    return text.strip()


# -- main -------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("host")
    ap.add_argument("--serial")
    ap.add_argument("--mac", help="controller MAC (default: generated & cached)")
    ap.add_argument("--pair", action="store_true", help="send pairing_start (PIN on TV)")
    ap.add_argument("--complete", metavar="PIN", help="complete pairing with PIN")
    ap.add_argument("--user")
    ap.add_argument("--passwd")
    ap.add_argument("--key", help="a single key_name to send")
    ap.add_argument("--discover", nargs="+", metavar="KEY", help="test many key names")
    args = ap.parse_args()

    serial = args.serial or discover_serial(args.host)
    if not serial:
        print("Could not determine serial; pass --serial", file=sys.stderr)
        return 2
    mac = (args.mac or controller_mac()).lower().replace(":", "")
    print(f"host={args.host} serial={serial} controller_mac={mac}")

    if args.pair:
        st, _, text = post(
            args.host, PAIR_URI, pairing_body("device_pairing_start", serial, mac),
            {"Content-Type": "application/json"},
        )
        print(f"pairing_start -> HTTP {st} {text.strip()}")
        print("Read the PIN off the TV, then: --complete <PIN>")
        return 0

    if args.complete:
        st, _, text = post(
            args.host, PAIR_URI,
            pairing_body("device_pairing_complete", serial, mac, args.complete),
            {"Content-Type": "application/json"},
        )
        print(f"pairing_complete -> HTTP {st} {text.strip()}")
        data = json.loads(text[text.index("{"):])
        if data.get("passwd"):
            print(f"\nPAIRED.  --user {data['name']} --passwd {data['passwd']}")
        else:
            print("No credentials (PIN wrong/expired). Re-run --pair.")
        return 0

    if args.key or args.discover:
        if not (args.user and args.passwd):
            ap.error("--key/--discover require --user and --passwd")
        keys = args.discover or [args.key]
        for k in keys:
            print(f"  {k:16s} -> {send_key(args.host, serial, mac, args.user, args.passwd, k)}")
        return 0

    ap.error("nothing to do — use --pair, --complete, --key, or --discover")


if __name__ == "__main__":
    sys.exit(main())
