"""UPnP/SSDP discovery for EchoStar receivers.

The receiver advertises a UPnP root device with
`urn:schemas-echostar-com:device:EchoStarDevice:1`. Its SSDP `LOCATION` header
points at a `device.xml` whose `<serialNumber>` is the SGS protocol's `stb`
field (e.g. `R0000000000-00`), and whose `<friendlyName>` / `<modelDescription>`
name the box. This is how the config flow pre-fills host, serial, and model.

Best-effort: never raises; an empty result just means manual entry.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from dataclasses import dataclass
from typing import Optional

import aiohttp

from .const import ECHOSTAR_DEVICE_URN, SSDP_ADDRESS, SSDP_PORT

_LOGGER = logging.getLogger(__name__)

_LOCATION = re.compile(r"^LOCATION:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_ST_USN = re.compile(r"^(?:ST|USN):.*echostar", re.IGNORECASE | re.MULTILINE)


def _tag(xml: str, name: str) -> Optional[str]:
    m = re.search(rf"<{name}>(.*?)</{name}>", xml, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else None


ECHO_SVC = "urn:schemas-echostar-com:service:EchostarService:1"


@dataclass
class DiscoveredReceiver:
    host: str
    location: Optional[str] = None
    serial: Optional[str] = None
    model: Optional[str] = None
    friendly_name: Optional[str] = None
    udn: Optional[str] = None
    control_url: Optional[str] = None  # EchoStar UPnP control endpoint
    event_url: Optional[str] = None  # EchoStar UPnP GENA event-subscription URL
    dial_url: Optional[str] = None  # DIAL Application-URL for app launch


async def _msearch(timeout: float) -> dict[str, str]:
    """Return {host: location} for EchoStar responders to an SSDP M-SEARCH."""
    loop = asyncio.get_running_loop()
    locations: dict[str, str] = {}

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.setblocking(False)

    search = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDRESS}:{SSDP_PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        f"ST: {ECHOSTAR_DEVICE_URN}\r\n\r\n"
    ).encode()

    try:
        sock.sendto(search, (SSDP_ADDRESS, SSDP_PORT))
        # Also do a broad search — some firmwares only answer ssdp:all.
        broad = search.replace(ECHOSTAR_DEVICE_URN.encode(), b"ssdp:all")
        sock.sendto(broad, (SSDP_ADDRESS, SSDP_PORT))
    except OSError as err:
        _LOGGER.debug("SSDP send failed: %s", err)

    async def collect() -> None:
        while True:
            data, addr = await loop.sock_recvfrom(sock, 4096)
            text = data.decode("utf-8", "replace")
            if not _ST_USN.search(text):
                continue
            loc = _LOCATION.search(text)
            if loc:
                locations[addr[0]] = loc.group(1)

    try:
        await asyncio.wait_for(collect(), timeout=timeout)
    except (asyncio.TimeoutError, OSError):
        pass
    finally:
        sock.close()

    return locations


async def _fetch_description(
    session: aiohttp.ClientSession, host: str, location: str
) -> DiscoveredReceiver:
    receiver = DiscoveredReceiver(host=host, location=location)
    try:
        async with session.get(
            location, timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            xml = await resp.text()
            app_url = resp.headers.get("Application-URL")
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        _LOGGER.debug("device.xml fetch failed for %s: %s", location, err)
        return receiver

    receiver.serial = _tag(xml, "serialNumber")
    receiver.model = _tag(xml, "modelName") or _tag(xml, "modelDescription")
    receiver.friendly_name = _tag(xml, "friendlyName")
    receiver.udn = _tag(xml, "UDN")

    # EchoStar UPnP control + event URLs (for reading/subscribing to state).
    base = location.rsplit("/", 1)[0]  # http://host:port
    for svc in re.findall(r"<service>(.*?)</service>", xml, re.S | re.I):
        if "EchostarService" in svc:
            m = re.search(r"<controlURL>(.*?)</controlURL>", svc, re.I)
            if m:
                receiver.control_url = base + m.group(1).strip()
            e = re.search(r"<eventSubURL>(.*?)</eventSubURL>", svc, re.I)
            if e:
                receiver.event_url = base + e.group(1).strip()
    # DIAL Application-URL (for launching apps).
    if app_url:
        receiver.dial_url = app_url if app_url.endswith("/") else app_url + "/"
    return receiver


async def async_echostar_devinfo(
    session: aiohttp.ClientSession, control_url: str
) -> dict[str, str]:
    """Call the EchoStar UPnP GetEchostarDevInfo action → {field: value}.

    Unauthenticated. Returns keys like Standby_Status ("LIVE"/standby), Status,
    Version, Name, Type. Empty dict on failure.
    """
    action = "GetEchostarDevInfo"
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{ECHO_SVC}"></u:{action}></s:Body></s:Envelope>'
    )
    try:
        async with session.post(
            control_url,
            data=body.encode(),
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPAction": f'"{ECHO_SVC}#{action}"',
            },
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            xml = await resp.text()
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        _LOGGER.debug("GetEchostarDevInfo failed: %s", err)
        return {}
    out: dict[str, str] = {}
    for key, value in re.findall(r"<(\w+)>([^<]*)</\1>", xml):
        if value.strip() and key not in ("s:Body",):
            out[key] = value.strip()
    return out


async def async_discover(
    timeout: float = 4.0, session: aiohttp.ClientSession | None = None
) -> list[DiscoveredReceiver]:
    """Discover EchoStar receivers and read their device descriptions."""
    locations = await _msearch(timeout)
    if not locations:
        return []

    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        results = await asyncio.gather(
            *(
                _fetch_description(session, host, loc)
                for host, loc in locations.items()
            )
        )
    finally:
        if own_session:
            await session.close()
    return list(results)


async def async_get_serial(
    host: str, timeout: float = 4.0, session: aiohttp.ClientSession | None = None
) -> Optional[str]:
    """Resolve just the serial (`stb`) for a known host, via SSDP + device.xml."""
    for receiver in await async_discover(timeout=timeout, session=session):
        if receiver.host == host and receiver.serial:
            return receiver.serial
    return None
