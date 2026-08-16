# DISH Receiver for Home Assistant

Control a DISH **Wally** (or Hopper) satellite receiver from Home Assistant over
your LAN — a `media_player` entity plus a full `remote` entity — installable via
HACS. No IR blaster, no cloud, no hub.

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
2. Install **DISH Receiver**, restart Home Assistant.
3. Home Assistant auto-discovers the receiver on the network (it matches the
   real SSDP announcement a Wally/Hopper broadcasts) — look for a **"DISH
   Receiver found"** card under Settings → Devices & Services, or add it
   manually via **Add Integration** → **DISH Receiver** if you'd rather.
4. Submit — a **PIN appears on the TV**. Enter it. Done.

The integration's icon in the UI/HACS depends on a logo submission to Home
Assistant's separate [`brands`](https://github.com/home-assistant/brands) repo
— see [branding/](branding/) for the prepared assets and submission status.

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
data: { command: [Guide, Down, Down, Enter], delay_secs: 0.4 }
```

Confirmed working keys (case-sensitive): `Home Guide Info Menu Up Down Left Right
Enter Cancel Back Options Search Input Format Play Pause Stop Record Rewind Jump
Recall DVR TV Red Green Yellow Blue Applications Help Microphone Keypad Backspace
Delete`, and digits `0`–`9`. You can also use the integration's friendly names
(`channel_up`→ etc.) via `dish_receiver.send_key`; see
[keys.py](custom_components/dish_receiver/keys.py).

### Wally limitations (by design, not a bug)

DISH does not expose these over IP on the Wally — they are IR-only, so the
integration can't send them:

- **Power** on/off — the Wally sleeps on its own; commands wake it.
- **Channel up/down** and **page up/down** — use **direct tuning** instead
  (`dish_receiver.tune_channel` or `play_media`), which works perfectly.
- **Fast-forward** — only **Rewind** and **Jump** (skip-forward) exist.
- **Volume/mute** — a TV-side function; route it through your TV/AVR entity.

## Services

- `dish_receiver.tune_channel` — `{ channel: "140" }`
- `dish_receiver.send_key` — `{ key: "guide" }` (friendly name or raw token)
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
