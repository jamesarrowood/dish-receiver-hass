# Wally — additional local interfaces (beyond SGS remote_key)

Discovered by live probing after the SGS protocol was working. All confirmed
against the real Wally (192.168.1.50, serial R0000000000-00).

## 1. App launching — DIAL (unauthenticated, port 80)

The receiver implements the DIAL protocol (`dial-multiscreen-org`). The base URL
comes from the `Application-URL` header on the UPnP device description:
`http://<host>/dial/`.

- **Query**:  `GET  /dial/<App>`      → `<service>…<state>stopped|running</state></service>`
- **Launch**: `POST /dial/<App>` with `Content-Length: 0` → `201 Created`,
  `Location: http://<host>/dial/<App>/run`
- **Stop**:   `DELETE /dial/<App>/run` → `200`

Confirmed apps present: **Netflix**, **YouTube**. No auth required.

## 2. Device state — EchoStar UPnP service (unauthenticated)

The receiver is a UPnP root device (`urn:schemas-echostar-com:device:EchoStarDevice:1`).
Discover its `device.xml` via SSDP (the `LOCATION` header; port is model-specific
— 49316 on this Wally). The `EchostarService` control URL is
`<base>/upnp/control/EchostarService`.

SOAP POST (no auth) `GetEchostarDevInfo` returns live state:

```
Name = Living Room        Standby_Status = LIVE      (← power/standby state!)
Type = XiP813               Status         = ON        (GetEchostarDevStatus)
Version = W5961618NJTD       Connection    = wl0
IP = 192.168.1.50          MAC           = AA:BB:CC:DD:EE:FF
```

All 7 service actions are read-only `Get*` — **no set-power action exists**, so
power/standby can be *read* but not *set*. Other actions: GetEchostarDevStatus,
GetEchostarLinkedReceiverID, GetEchostarSmartcardID, GetEchostarConnType,
GetEchostarInterfaceInfo, GetEchostarApksBundleID.

Also a DIAL SCPD (`DialSVC_SCPD.xml`) and DialService control URL exist.

## 3. Additional SGS key_names (confirmed live)

Beyond the earlier list: **Mute** (receiver-side mute — works, despite RTI docs
claiming volume/mute are IR-only), **Mode**, **Space**, and the full **A–Z**
on-screen keyboard plus `Comma`, `Tab`. Volume up/down remain absent.

## 4. UPnP GENA eventing — WORKS (real-time state push)

The EchoStar service has 22 evented state variables (`sendEvents="yes"`). A
standard GENA `SUBSCRIBE` to the eventSubURL (`/upnp/event/EchostarService`,
port 49316, no auth) succeeds:

```
SUBSCRIBE /upnp/event/EchostarService HTTP/1.1
CALLBACK: <http://<my-ip>:<port>/notify>
NT: upnp:event
TIMEOUT: Second-300
→ HTTP 200, SID: uuid:…, TIMEOUT: Second-300
```

The box then POSTs a NOTIFY to the callback with the full state (and again on
every change), including **`Standby_Status`**, Name, Type, Version, MAC,
Smartcard_ID, and full network config. This enables **event-driven** power/standby
updates in Home Assistant instead of polling. Renew the subscription before the
TIMEOUT expires (~every 300s).

## 5. Port 8888 — silent server-push channel (protocol unknown)

TCP-open but answers nothing: no HTTP/1.0, HTTP/1.1, h2c, TLS, or raw input gets
a response; every read times out. Consistent with a one-way server-initiated
notification socket. Not drivable client-side without its (unknown) wire format.

## 6. DIAL apps — complete set

Only **Netflix** and **YouTube** are registered (aliases like YouTubeTV/NetflixApp
resolve to these). No other streaming apps are present via DIAL.

## 7. Unresolved lead — the `sgs_*` endpoint family

Real endpoints exist on port 80 (they return `400`, not `501`):
`/www/sgs_query`, `/www/sgs_capabilities`, `/www/sgs_status`, `/www/sgs_info`,
`/www/sgs_system`, `/www/sgs_subscribe`, `/www/sgs_event`, `/www/sgs_notify`,
`/www/sgs_command`. Every body shape returns `400` on port 80 — they appear to
require a different method/header or are only functional on port **443** (the
mutual-TLS endpoint gated to an EchoStar-CA client certificate). The `capabilities`
and `subscribe` SGS commands are recognized but "not supported for this URI/port"
on port 80. If set-power exists anywhere, `sgs_system` on 443 is the candidate —
unreachable without the device certificate (see the main notes).
