# DISH Receiver for Home Assistant

Control a DISH **Wally**, **Hopper**, or **Joey** receiver from Home Assistant
over your LAN — a `media_player` entity plus a full `remote` entity — installable
via HACS. No IR blaster, no cloud, no hub.

**Multiple boxes?** A standalone **Wally** pairs on its own. A **Hopper** with
**Joeys** works as a group: a Joey routes all control through its Hopper (over the
internal MoCA network, which the LAN can't reach directly), so you **add the
Hopper first and pair it**, then each Joey is added instantly — it reuses the
Hopper's pairing (no separate PIN) and targets that Joey by its serial. Every box
auto-discovers (see below); the discovery card shows room + model
(*Living Room (ZiP Hopper)*, *Bedroom 1 (HEVC Joey)*) so they stay distinct — a
Wally and Hopper in the same room are told apart by model.

> **Status: working and hardware-verified.** The local control protocol was
> reverse-engineered from the RTI driver source and confirmed live against a
> Wally (model XiP813 / 211HEVC): discovery, PIN pairing, authenticated
> keypresses, and direct tuning all work end-to-end. See
> [tools/protocol-findings/](tools/protocol-findings/) for the full protocol and
> the verified key list.

## How it works

EchoStar receivers expose a local **SGS** control API on port 80:

- **Discovery** — the receiver advertises a UPnP device (`urn:schemas-echostar-com:device`);
  its `device.xml` gives the serial number used in every request.
- **Pairing** — `POST /sgs_noauth` with `device_pairing_start` puts a PIN on the
  TV; `device_pairing_complete` with that PIN returns a username/password.
- **Commands** — `POST /www/sgs` authenticated with HTTP Digest (MD5, plus
  EchoStar's non-standard `message-digest` body-integrity field) sends remote
  keys and tunes channels.

The integration is transport-agnostic (a `DishTransport` seam), but the
**local** transport is the real one and the default. Cloud and delegate
transports exist as stubs/fallbacks and are not needed for a Wally.

## Install (HACS)

1. HACS → Integrations → ⋮ → Custom repositories → add this repo as an
   *Integration*.
2. Install **DISH Receiver**, then **fully restart Home Assistant** — not just
   "reload"/"redownload". SSDP discovery matchers are registered only at Home
   Assistant startup, so a restart is required before auto-discovery can fire.
3. Each receiver on the network appears as its own **"DISH Receiver found"** card
   under Settings → Devices & Services (a Hopper + 4 Joeys shows 5 cards). Or add
   any of them manually via **Add Integration** → **DISH Receiver** by IP.
4. **Add the Hopper (or Wally) first.** Submit its card → a **PIN appears on that
   box's TV** → enter it. For a Joey, submit its card *after* its Hopper is set
   up; it links to the Hopper automatically with no PIN. (A Joey added before its
   Hopper shows a message telling you to add the Hopper first.)

*Discovery not showing up?* Confirm you did a full HA restart (step 2), that the
box is on the same subnet as HA (SSDP is link-local — it won't cross VLANs
without an mDNS/SSDP reflector), and that HA's built-in **SSDP** integration is
enabled (it is by default via `default_config`).

The DISH logo ships inline with the integration
([custom_components/dish_receiver/brand/](custom_components/dish_receiver/brand/))
via Home Assistant's Brands Proxy API (HA 2026.3+) — no external submission
needed, it just shows up. On older HA cores the icon slot is simply blank; the
integration still works. Logo source: DISH's current wordmark (2019–), from
[Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Dish_Network_2019.svg).

## What you get

**`media_player`** — play / pause / stop, direct tuning (`play_media` with
`media_content_type: channel`), **live on/standby state** (read from the
receiver's UPnP service, and **pushed instantly** via UPnP GENA eventing so
standby changes reflect immediately, with polling as a fallback), and a **source
list** combining your favorite channels with launchable apps (**Netflix**,
**YouTube**). Define favorites in the integration's *Configure* dialog, one per
line as `Name=Channel` (e.g. `ESPN=140`); selecting an app name launches it,
selecting a favorite tunes it.

**`remote`** — every key the Wally exposes over IP, via `remote.send_command`:

```yaml
service: remote.send_command
target: { entity_id: remote.living_room_1_remote }
data: { command: [guide, down, down, select], delay_secs: 0.4 }
```

Key names are **case-insensitive**, and both the canonical name and the enum name
work (`live_tv` or `LIVE_TV`, `channel_up` or `ch_up`). Confirmed working on the
Wally: `home guide info menu up down left right select enter exit back options
search input format play pause stop record rewind jump recall dvr live_tv red
green yellow blue applications help microphone keypad backspace delete mute mode
space`, plus digits `0`–`9` and `dash`. Two names to watch: DISH's own "Cancel"
and "TV" buttons are `exit` and `live_tv` here — the raw wire tokens aren't
accepted. The full list is [keys.py](custom_components/dish_receiver/keys.py);
`dish_receiver.send_key` takes the same vocabulary for a single key.

### Wally limitations (by design, not a bug)

DISH does not expose these over IP on the Wally — they are IR-only, so the
integration can't send them:

- **Power** on/off — the Wally sleeps on its own; commands wake it.
- **Channel up/down** and **page up/down** — use **direct tuning** instead
  (`dish_receiver.tune_channel` or `play_media`), which works perfectly.
- **Fast-forward** — only **Rewind** and **Jump** (skip-forward) exist.
- **Volume up/down** — a TV-side function; route it through your TV/AVR entity.
  (**Mute** is different — it *is* exposed and works over IP.)

## Custom remote card

A Lovelace card ships with the integration and registers itself automatically
— no manual "add resource" step. It renders the physical remote's photo with
clickable regions mapped to each button:

```yaml
type: custom:dish-remote-card
entity: remote.living_room_1_remote
```

Buttons with no working IP command (Power, volume, channel step) are still
shown, matching the physical remote, but tapping them shows why instead of
silently failing. Click the ⚙ in the card's corner to see and drag the hit-box
outlines if any button needs nudging — a "Copy map" button exports the result
as JSON to paste back into the card config as a `buttons:` override.

Prefer a grid-style remote instead of a photo?
[example-universal-remote-card.yaml](custom_components/dish_receiver/www/example-universal-remote-card.yaml)
is a ready-to-paste config for the separate [Universal Remote Card](https://github.com/Nerwyn/universal-remote-card)
(install that card via HACS first) covering every confirmed-working key.

## Universal remotes (SofaBaton X2)

A **SofaBaton X2** can drive the receiver through this integration. Its app has a
Home Assistant device type that publishes each button press to MQTT; a shipped
blueprint maps those presses onto keys, direct tunes, app launches and favorite
stepping, and `tools/sofabaton_map.py` builds the map for you by asking you to
press each button. Full walkthrough: **[docs/SOFABATON_X2.md](docs/SOFABATON_X2.md)**.

Pair it with IR rather than replacing IR. The **Wally does accept IR** — verified
by transmitting a DISH power-toggle code and watching `media_player` flip between
`on` and `off` — so a universal remote can cover power, channel up/down and
fast-forward, which this integration can't send over IP. Home Assistant then adds
what IR can't do: one-press direct tuning, app launches, standby state, and
receivers in rooms the blaster can't see.

(The DISH *remote* does use **RF4CE** rather than IR, so you can't clone it or pair
it to a Zigbee coordinator. That's a fact about the remote, not the receiver.)

## Services

- `dish_receiver.tune_channel` — `{ channel: "140" }`
- `dish_receiver.send_key` — `{ key: "guide" }` (canonical or enum name, case-insensitive)
- `dish_receiver.launch_app` — `{ app: "Netflix" }` (Netflix, YouTube)

## Try it without Home Assistant

`tools/remote_server.py` is a standalone local web remote — buttons, Netflix/
YouTube launch, direct tuning, a Mute key, and a live on/standby indicator:

```bash
python3 tools/remote_server.py     # opens http://127.0.0.1:8765
```

It reads `tools/remote_creds.json` and discovers the UPnP/DIAL endpoints
automatically. Copy `tools/remote_creds.example.json` to `tools/remote_creds.json`
and fill it in with your own receiver's host/serial/credentials — get those by
pairing with `tools/verify_control.py <ip> --pair`, then `--complete <PIN>`.
`remote_creds.json` is gitignored since it holds live credentials for your
specific receiver; never commit it.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

Pure-logic tests (the Digest algorithm, SGS body format, key mapping) run with
just pytest and match the RTI source byte-for-byte. Entity/config-flow tests use
`pytest-homeassistant-custom-component` with a `FakeTransport`, exercising the
full surface with no hardware.

`tools/probe_receiver.py` fingerprints a receiver; `tools/verify_control.py`
sends an authenticated key from the shell for troubleshooting.

## Scope

Interoperability work with your own receiver on your own network. Don't
redistribute any credential minted during pairing.
