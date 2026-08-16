#!/usr/bin/env python3
"""Probe a DISH receiver (Hopper / Joey / Wally) for a local control API.

No public documentation exists for the DISH "2nd Screen" API that Control4,
RTI, Crestron and Roomie drivers use. What *is* documented behaviourally:

  * control is over TCP, and Roomie lists port 443 for the Hopper/Joey type
  * pairing shows a PIN on the TV and registers the controller's MAC
  * DISH implemented Control4's SDDP for discovery (multicast 239.255.255.250:1902)

This script answers, empirically, whether any of that is reachable on *your*
receiver. It is read-only: it opens connections and sends GET requests, it
never sends a control or pairing command.

Stdlib only, Python 3.8+. Nothing to install.

Usage:
    python3 probe_receiver.py 192.168.1.50
    python3 probe_receiver.py 192.168.1.50 192.168.1.51 --full
    python3 probe_receiver.py --discover-only

Before running, on the receiver:
    Menu > Settings > Paired Devices > enable "Pairing Request"
The control port may only listen while pairing is open, so probe both with it
enabled and disabled and diff the two reports.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import select
import socket
import ssl
import struct
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

MCAST_GRP = "239.255.255.250"
SSDP_PORT = 1900
SDDP_PORT = 1902
MDNS_GRP = "224.0.0.251"
MDNS_PORT = 5353

# Ports worth trying first: 443 is the documented Roomie port for Hopper/Joey;
# the rest cover the usual embedded-HTTP, UPnP and DIAL hiding places.
CURATED_PORTS = [
    80, 81, 88, 443, 554, 631, 1080, 1900, 2869, 3000, 3001, 3128, 4443,
    5000, 5001, 5555, 6000, 7000, 7100, 7777, 8000, 8001, 8008, 8009, 8060,
    8080, 8081, 8088, 8090, 8188, 8443, 8888, 9000, 9080, 9090, 9999,
    10000, 10001, 11000, 32768, 32769, 32770,
    49152, 49153, 49154, 49155, 49156, 50000, 51000, 52000, 55000, 60000,
]

# Endpoint guesses. Order matters only for readability of the report.
CANDIDATE_PATHS = [
    "/",
    "/api",
    "/api/v1",
    "/api/system_info",
    "/api/status",
    "/api/tuner",
    "/api/remote_key",
    "/api/pairing",
    "/rest",
    "/pairing",
    "/device",
    "/info",
    "/status",
    "/system",
    "/description.xml",
    "/ssdp/device-desc.xml",
    "/dd.xml",
    "/apps",
]

PRINTABLE = re.compile(rb"[ -~]{4,}")


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def _multicast_socket(port: int, group: str) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    sock.bind(("", port))
    mreq = struct.pack("4sl", socket.inet_aton(group), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
    local = _local_ip()
    if local:
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local))
        except OSError:
            pass
    return sock


def _local_ip() -> Optional[str]:
    """Address of the interface facing the default route.

    Multicast sends fail with EHOSTUNREACH when the kernel picks the wrong
    interface, which is exactly the machine most likely to be probing a
    receiver (laptop with VPN/utun devices up).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 53))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def _send(sock: socket.socket, payload: bytes, addr: Tuple[str, int], label: str) -> None:
    try:
        sock.sendto(payload, addr)
    except OSError as err:
        print("  ! {} search failed ({}); still listening passively".format(label, err))


def _listen(sock: socket.socket, seconds: float, label: str) -> List[Dict[str, Any]]:
    """Collect datagrams for `seconds`, decoding them loosely as text.

    Synchronous and select-based so it works on the stock macOS Python 3.9
    (loop.sock_recvfrom only landed in 3.11); callers run it in an executor.
    """
    found: List[Dict[str, Any]] = []
    seen: set = set()
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ready, _, _ = select.select([sock], [], [], min(remaining, 1.0))
        if not ready:
            continue
        try:
            data, addr = sock.recvfrom(65535)
        except OSError:
            continue
        text = data.decode("utf-8", "replace").strip()
        key = (addr[0], text[:200])
        if key in seen:
            continue
        seen.add(key)
        found.append({"protocol": label, "source": addr[0], "payload": text})
        print("  [{}] {} -> {}".format(label, addr[0], text.splitlines()[0] if text else "<empty>"))
    return found


async def discover(seconds: float) -> Dict[str, Any]:
    """Active SSDP + SDDP search, plus passive listen on both, plus mDNS."""
    print("Discovery ({}s) — SSDP :1900, SDDP :1902, mDNS :5353".format(int(seconds)))
    results: Dict[str, Any] = {"ssdp": [], "sddp": [], "mdns": []}

    ssdp_sock = _multicast_socket(SSDP_PORT, MCAST_GRP)
    sddp_sock = _multicast_socket(SDDP_PORT, MCAST_GRP)
    mdns_sock = _multicast_socket(MDNS_PORT, MDNS_GRP)

    msearch = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: {}:{}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 3\r\n"
        "ST: ssdp:all\r\n\r\n"
    ).format(MCAST_GRP, SSDP_PORT).encode()

    # SDDP's search verb, mirroring the SSDP shape Control4 modelled it on.
    sddp_search = (
        "SEARCH * SDDP/1.0\r\n"
        "Host: {}:{}\r\n\r\n"
    ).format(MCAST_GRP, SDDP_PORT).encode()

    _send(ssdp_sock, msearch, (MCAST_GRP, SSDP_PORT), "SSDP")
    _send(sddp_sock, sddp_search, (MCAST_GRP, SDDP_PORT), "SDDP")
    _send(
        mdns_sock,
        _mdns_query("_services._dns-sd._udp.local"),
        (MDNS_GRP, MDNS_PORT),
        "mDNS",
    )

    loop = asyncio.get_running_loop()
    ssdp, sddp, mdns = await asyncio.gather(
        loop.run_in_executor(None, _listen, ssdp_sock, seconds, "SSDP"),
        loop.run_in_executor(None, _listen, sddp_sock, seconds, "SDDP"),
        loop.run_in_executor(None, _listen, mdns_sock, seconds, "mDNS"),
    )
    results["ssdp"], results["sddp"], results["mdns"] = ssdp, sddp, mdns

    for sock in (ssdp_sock, sddp_sock, mdns_sock):
        sock.close()

    if not any(results.values()):
        print("  nothing announced itself.")
    return results


def _mdns_query(name: str) -> bytes:
    """Minimal mDNS PTR query."""
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    qname = b"".join(
        struct.pack("B", len(label)) + label.encode() for label in name.split(".")
    ) + b"\x00"
    return header + qname + struct.pack(">HH", 12, 1)  # PTR, IN


# --------------------------------------------------------------------------
# TCP scan
# --------------------------------------------------------------------------

async def _is_open(host: str, port: int, timeout: float) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except (OSError, AttributeError):
        pass
    del reader
    return True


async def scan(host: str, ports: List[int], timeout: float, concurrency: int) -> List[int]:
    sem = asyncio.Semaphore(concurrency)
    open_ports: List[int] = []

    async def one(port: int) -> None:
        async with sem:
            if await _is_open(host, port, timeout):
                open_ports.append(port)
                print("  open: {}".format(port))

    await asyncio.gather(*(one(p) for p in ports))
    return sorted(open_ports)


# --------------------------------------------------------------------------
# per-port fingerprinting
# --------------------------------------------------------------------------

def _describe_cert(der: bytes) -> Dict[str, Any]:
    """Decode a DER cert. Uses openssl when present, else salvages strings.

    The certificate subject is one of the strongest tells available: an
    EchoStar/Sling/DISH CN on a self-signed cert means we have found the
    receiver's own service rather than some unrelated daemon.
    """
    pem = ssl.DER_cert_to_PEM_cert(der)
    try:
        proc = subprocess.run(
            ["openssl", "x509", "-noout", "-subject", "-issuer", "-dates", "-ext", "subjectAltName"],
            input=pem.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout:
            return {"openssl": proc.stdout.decode("utf-8", "replace").strip()}
    except (OSError, subprocess.SubprocessError):
        pass
    strings = sorted({m.decode() for m in PRINTABLE.findall(der)})
    return {"strings": strings[:40]}


async def _tls_info(host: str, port: int, timeout: float) -> Optional[Dict[str, Any]]:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=0")
    except ssl.SSLError:
        pass
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx), timeout=timeout
        )
    except (OSError, asyncio.TimeoutError, ssl.SSLError) as err:
        return {"error": "{}: {}".format(type(err).__name__, err)}
    ssl_obj = writer.get_extra_info("ssl_object")
    info: Dict[str, Any] = {}
    if ssl_obj is not None:
        info["version"] = ssl_obj.version()
        cipher = ssl_obj.cipher()
        info["cipher"] = cipher[0] if cipher else None
        der = ssl_obj.getpeercert(binary_form=True)
        if der:
            info["certificate"] = _describe_cert(der)
    writer.close()
    try:
        await writer.wait_closed()
    except (OSError, AttributeError):
        pass
    del reader
    return info


async def _banner(host: str, port: int, timeout: float) -> Optional[str]:
    """Read anything the service volunteers before we say a word."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
    except (OSError, asyncio.TimeoutError):
        return None
    try:
        data = await asyncio.wait_for(reader.read(512), timeout=2.0)
    except (asyncio.TimeoutError, OSError):
        data = b""
    writer.close()
    try:
        await writer.wait_closed()
    except (OSError, AttributeError):
        pass
    return data.decode("utf-8", "replace").strip() or None


async def _http_get(
    host: str, port: int, path: str, use_tls: bool, timeout: float
) -> Optional[Dict[str, Any]]:
    ctx = None
    if use_tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers("DEFAULT@SECLEVEL=0")
        except ssl.SSLError:
            pass
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx), timeout=timeout
        )
    except (OSError, asyncio.TimeoutError, ssl.SSLError):
        return None

    request = (
        "GET {} HTTP/1.1\r\n"
        "Host: {}:{}\r\n"
        "User-Agent: dish-probe/1.0\r\n"
        "Accept: */*\r\n"
        "Connection: close\r\n\r\n"
    ).format(path, host, port).encode()

    try:
        writer.write(request)
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(8192), timeout=timeout)
    except (OSError, asyncio.TimeoutError, ssl.SSLError):
        raw = b""
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, AttributeError):
            pass

    if not raw:
        return None

    text = raw.decode("utf-8", "replace")
    head, _, body = text.partition("\r\n\r\n")
    lines = head.splitlines()
    status = lines[0] if lines else ""
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
    return {
        "status": status,
        "headers": headers,
        "body_prefix": body[:600],
        "body_len": len(body),
    }


def _interesting(result: Dict[str, Any]) -> bool:
    """Anything that is not a plain 404/400 is worth a human look."""
    status = result.get("status", "")
    return not any(code in status for code in (" 404", " 400", " 501"))


async def fingerprint(host: str, port: int, timeout: float) -> Dict[str, Any]:
    print("\n  port {} —".format(port))
    entry: Dict[str, Any] = {"port": port}

    banner = await _banner(host, port, timeout)
    if banner:
        entry["banner"] = banner
        print("    banner: {}".format(banner.splitlines()[0][:120]))

    tls = await _tls_info(host, port, timeout)
    if tls and "error" not in tls:
        entry["tls"] = tls
        print("    TLS: {} / {}".format(tls.get("version"), tls.get("cipher")))
        cert = tls.get("certificate", {})
        if "openssl" in cert:
            for line in cert["openssl"].splitlines():
                print("      {}".format(line))
    speaks_tls = bool(tls and "error" not in tls)

    entry["http"] = {}
    for scheme, use_tls in (("https", True), ("http", False)):
        if use_tls and not speaks_tls:
            continue
        if not use_tls and speaks_tls:
            # A TLS-only port answers plaintext with garbage; skip the noise.
            continue
        for path in CANDIDATE_PATHS:
            result = await _http_get(host, port, path, use_tls, timeout)
            if result is None:
                continue
            entry["http"]["{}://{}:{}{}".format(scheme, host, port, path)] = result
            if _interesting(result):
                print("    {} {} -> {}".format(scheme.upper(), path, result["status"]))
                snippet = result["body_prefix"].strip().replace("\n", " ")[:160]
                if snippet:
                    print("        {}".format(snippet))
    return entry


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

async def probe_host(host: str, args: argparse.Namespace) -> Dict[str, Any]:
    print("\n=== {} ===".format(host))
    ports = list(range(1, 65536)) if args.full else CURATED_PORTS
    print("Scanning {} ports (timeout {}s, concurrency {})".format(
        len(ports), args.timeout, args.concurrency))

    started = time.monotonic()
    open_ports = await scan(host, ports, args.timeout, args.concurrency)
    elapsed = time.monotonic() - started

    if not open_ports:
        print("  no open TCP ports found in {:.1f}s.".format(elapsed))
        if not args.full:
            print("  -> re-run with --full before concluding anything.")
    else:
        print("\n  {} open port(s) in {:.1f}s: {}".format(
            len(open_ports), elapsed, ", ".join(str(p) for p in open_ports)))

    services = []
    for port in open_ports:
        services.append(await fingerprint(host, port, args.timeout))

    return {
        "host": host,
        "scanned_ports": len(ports),
        "full_scan": args.full,
        "open_ports": open_ports,
        "services": services,
        "mac": arp_lookup(host),
    }


def arp_lookup(host: str) -> Optional[str]:
    """MAC address — the pairing flow registers the controller's MAC, and the
    receiver's own MAC is the natural unique_id for the config entry."""
    try:
        proc = subprocess.run(
            ["arp", "-n", host], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(
        rb"(([0-9a-f]{1,2}:){5}[0-9a-f]{1,2})", proc.stdout, re.IGNORECASE
    )
    if not match:
        return None
    parts = match.group(1).decode().split(":")
    return ":".join(p.zfill(2).lower() for p in parts)


def summarise(report: Dict[str, Any]) -> None:
    print("\n" + "=" * 68)
    print("SUMMARY")
    print("=" * 68)

    disc = report.get("discovery", {})
    sddp = disc.get("sddp", [])
    if sddp:
        print("\nSDDP announcements ({}) — DISH implements SDDP on the Hopper, so".format(len(sddp)))
        print("this is the strongest confirmation available that IP control exists:")
        for item in sddp:
            print("  {}: {}".format(item["source"], item["payload"][:300]))
    else:
        print("\nSDDP: nothing. Either the receiver does not announce, or it only")
        print("announces at boot — power-cycle the receiver and re-run --discover-only.")

    for host_report in report.get("hosts", []):
        host = host_report["host"]
        open_ports = host_report["open_ports"]
        print("\n{} — {} open port(s){}".format(
            host,
            len(open_ports),
            " [MAC {}]".format(host_report["mac"]) if host_report.get("mac") else "",
        ))
        if not open_ports:
            print("  No local control surface. Next step is the DISH Anywhere")
            print("  capture in tools/SNIFFING.md.")
            continue
        for service in host_report["services"]:
            hits = [
                url for url, res in service.get("http", {}).items() if _interesting(res)
            ]
            note = ""
            if service["port"] == 443:
                note = "  <- documented Roomie port for Hopper/Joey"
            print("  {}{}".format(service["port"], note))
            if service.get("tls"):
                cert = service["tls"].get("certificate", {}).get("openssl", "")
                subject = next(
                    (l for l in cert.splitlines() if l.startswith("subject")), ""
                )
                if subject:
                    print("     {}".format(subject))
            for url in hits:
                print("     responds: {}".format(url))


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe a DISH receiver for a local control API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("hosts", nargs="*", help="receiver IP address(es)")
    parser.add_argument("--full", action="store_true", help="scan all 65535 ports")
    parser.add_argument("--timeout", type=float, default=2.0, help="per-connection timeout")
    parser.add_argument("--concurrency", type=int, default=400, help="parallel connections")
    parser.add_argument("--discover-seconds", type=float, default=45.0)
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--no-discover", action="store_true")
    parser.add_argument("--out", help="report path (default probe-<ts>.json)")
    args = parser.parse_args()

    if not args.hosts and not args.discover_only:
        parser.error("give at least one receiver IP, or use --discover-only")

    report: Dict[str, Any] = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "discovery": {},
        "hosts": [],
    }

    if not args.no_discover:
        report["discovery"] = await discover(args.discover_seconds)

    if not args.discover_only:
        for host in args.hosts:
            report["hosts"].append(await probe_host(host, args))

    summarise(report)

    out = args.out or "probe-{}.json".format(datetime.now().strftime("%Y%m%d-%H%M%S"))
    with open(out, "w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    print("\nFull report: {}".format(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)
