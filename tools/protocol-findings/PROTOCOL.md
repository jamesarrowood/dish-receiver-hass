# DISH/EchoStar Hopper Local Control Protocol — extracted from RTI driver

Source (CONFIRMED FROM SOURCE): RTI "Dish Network" driver v1.0, author Remote Technologies Inc.,
Copyright 2022. Downloaded from RTI Driver Store.

- Driver package URL: https://driverstore.rticontrol.com/driver/dish-network
- Direct download: https://driverstore.rticontrol.com/download/file/6d477af39693fffb85bcafc742f566dd4a36975d3b53812f3399aaee53c51c08
- The `.rtidriver` is a ZIP; inner `Dish Network.rtidriver` is an OLE compound file whose
  streams (ConfigSettings.xml, SystemFunctions.xml, dish.js, HTTPDigest.js, keyboard.js, init.js)
  are individually zlib-compressed. All extracted under `rti-extracted/streams/`.
- "Tested and developed on a Dish Hopper" (from instructions.rtf).

## Ports (CONFIRMED)
- **80/tcp**  — the SGS command API (pairing + remote_key). Digest auth for remote_key. `g_postPort = 80`
- **49310/tcp** — UPnP-style device description: `GET /device.xml` (returns `<serialNumber>`). `IPPort` default 49310
- **239.255.255.250:1900/udp** — SSDP multicast discovery to locate the box + extract its UUID
- **443** — `g_sslPort = 443` is DECLARED and SSL handshake callbacks exist, but this driver
  NEVER connects on 443. RTI does everything over port-80 Digest. (mTLS/443 path unused here.)

## Discovery (CONFIRMED)
1. Join SSDP multicast 239.255.255.250:1900, match your known Hopper IP in responses,
   regex out the UUID: `\b[0-9a-f]{8}\b-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-\b[0-9a-f]{12}\b`
2. `GET /device.xml HTTP/1.1` on port 49310 → parse `<serialNumber>...</serialNumber>`.
   Verbatim request:
   `GET /device.xml HTTP/1.1\r\nHost: <ip>:49310\r\nUser-Agent: RTI/1.0\r\nAccept: */*\r\n\r\n`

## Client identity fields used in every body
- `stb`      = the Hopper serial number from device.xml (e.g. `R1887413544-55` style receiver ID)
- `receiver` = `"XT1" + <lowercaseMAC>`  (controller MAC, no colons, lowercased, prefixed `XT1`)
- `mac`      = `<lowercaseMAC>`
- `id`       = `"T1"`
- `tv_id`    = `"0"` (TV/output index; Hopper+Joey systems select output here)

## Pairing — port 80, endpoint `POST /sgs_noauth` (CONFIRMED, verbatim)

On-screen enable first: Hopper Menu -> Settings -> (Paired Devices) enable Pairing.

### Step 1: device_pairing_start
```
POST /sgs_noauth HTTP/1.1
Host: <ip>
Content-Type: application/json
Content-Length: <len>

{"command": "device_pairing_start","stb": "<serial>","receiver": "XT1<mac>","app": "RTI Control Driver","name": "RTI Dish Driver","type": "application/json","id": "T1","mac": "<mac>"}
```
=> Hopper shows a PIN on the TV.

### Step 2: device_pairing_complete
```
POST /sgs_noauth HTTP/1.1
Host: <ip>
Content-Type: application/json
Content-Length: <len>

{"command": "device_pairing_complete","pin": "<PIN>","stb": "<serial>","receiver": "XT1<mac>","app": "RTI Control Driver","name": "RTI Dish Driver","type": "application/json","id": "T1","mac": "<mac>"}
```
=> Response JSON contains `name` and `passwd`. These become the Digest credentials:
   - **Digest username = response `name`**  (NOT a fixed string — the box assigns it)
   - **Digest password = response `passwd`**
   Driver detects success by regex `/passwd/` in the response body.

## Remote key command — port 80, endpoint `POST /www/sgs`, HTTP Digest (CONFIRMED, verbatim)

### First (unauthenticated) request — triggers 401
```
POST /www/sgs HTTP/1.1
Host: <ip>
Content-Type: application/json
Connection: Keep-Alive
WWW-Authenticate: Digest
Content-Length: <len>

{"receiver": "XT1<mac>","key_name": "<KEY>","tv_id": "0","stb": "<serial>","command": "remote_key"}
```
=> Box returns 401 with `WWW-Authenticate: Digest ... realm=... nonce=...`

### Second (authorized) request
```
POST /www/sgs HTTP/1.1
Host: <ip>:80
Authorization: Digest username=<user>, realm="Please provide user name and password", nonce="<nonce>", uri="/www/sgs", algorithm="MD5", qop=auth, nc=00000001, cnonce="<8hex>", response="<resp>", message-digest="<md>"
Content-Type: application/json
Content-Length: <len>

{"receiver": "XT1<mac>","key_name": "<KEY>","tv_id": "0","stb": "<serial>","command": "remote_key"}
```

### Digest computation (CONFIRMED from HTTPDigest.js) — MD5, qop=auth
- realm = `Please provide user name and password` (hard-coded constant)
- HA1 = MD5( username : realm : password )
- HA2 = MD5( "POST:" + "/www/sgs" )
- response = MD5( HA1 : nonce : nc : cnonce : qop : HA2 )     [standard RFC 2617]
- nc = `00000001` (always; new nonce每 request), cnonce = 8 random lowercase-hex chars
- **EchoStar-specific extra field** appended to the Authorization header:
  `message-digest="<MD>"` where **MD = MD5( HA1 : nonce : MD5(body) )**
  (body = the JSON payload string). This is a non-standard body-integrity extension;
  the box appears to require it.

## key_name values (CONFIRMED — the token after `remoteCommand:` in SystemFunctions.xml)
power, enter, cancel, guide, dvr, search, keypad, pauseplay, rewind, fastforward, stop,
skipback, stepforward, input, number, pagedown, pageup, pause, play, record, blue, green,
red, yellow, left, right, up, down, info, livetv, recall, piptoggle, pipposition, pipswap,
dish, sysinfo, home, infotoggle, options, applications, help, microphone, abctoggle,
123toggle, backspace, channelup, channeldown

Notes / UNCERTAIN:
- Number keypad digits map through `remoteCommand:number` -> the driver sends `key_name":"number"`
  literally (the chosen digit is NOT injected). Likely a driver limitation; the real firmware
  key_name for digits is probably the digit itself or `num_<n>` — NOT confirmed from this source.
- `sendCmd:RAW` ("RAW Command") is exposed in SystemFunctions.xml but has NO implementation in
  dish.js — dead/stub.
- Volume/mute/direct-channel-tune are NOT in the API. RTI docs state "Dish does not support these
  commands in their remote emulation API" — they use IR for volume/mute/channel. There is NO
  confirmed SetChannel/tune JSON command in this driver (only channelup/channeldown key presses).

## Config note (from instructions.rtf)
Assign a static IP / DHCP reservation to the Hopper or it grabs a new IP after sleep.
Static IP menu on Hopper: Internet Settings -> Advanced, then press "recall","recall","Pause/Play".
