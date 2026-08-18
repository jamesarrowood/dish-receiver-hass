# Driving a DISH receiver with a SofaBaton X2

The X2 is a hub-based universal remote with an official **Home Assistant device
type**: you point the SofaBaton app at an MQTT broker, and every press of a button
on that device publishes a small JSON message. This integration turns those
messages into real receiver commands, so the X2 ends up controlling your Wally
over IP — through Home Assistant, on your LAN, with no cloud in the path.

## IR and IP are complements, not alternatives

**The Wally does accept IR.** This was verified on real hardware: transmitting the
SofaBaton library's DISH "Power toggle" code flipped `media_player.wally` between
`on` and `off` within three seconds, reproducibly, with no IP command involved.

That is worth stating plainly because it is easy to conclude otherwise. The DISH
remote talks to the receiver over **RF4CE** (ZigBee's 802.15.4 radio, proprietary
profile — a Zigbee coordinator can't pair it), and the
[Wally manual](https://www.manualslib.com/manual/1169016/Dish-Network-Wally.html?page=15)
says the remote controls the Wally **by RF**, using IR only for the TV and aux
devices. Both statements describe *the bundled remote*. Neither says the receiver
lacks an IR sensor — and it has one.

So use each transport for what it's good at:

| Use IR for | Use Home Assistant for |
| --- | --- |
| Power on/off | Direct tuning — one press to a channel |
| Channel up/down, page up/down | Launching Netflix / YouTube |
| Fast-forward | Reading standby state into automations |
| Volume (via your TV) | Receivers in other rooms the blaster can't reach |

IR covers exactly the gaps in the IP transport (see [Limits](#limits)), which is
why a hybrid activity beats either one alone. The rest of this document covers the
Home Assistant half.

## What you need

- A DISH receiver already added and paired in Home Assistant (see the main
  [README](../README.md)).
- An MQTT broker. The **Mosquitto broker** add-on is fine: Settings → Add-ons →
  Add-on Store → Mosquitto broker → Install, set a username/password in its
  Configuration tab, start it, then add the **MQTT** integration under Settings →
  Devices & Services pointing at it.
- `paho-mqtt` on whatever machine you run the capture helper from:

```bash
python3 -m pip install paho-mqtt
```

- **If you want `fav_next` / `fav_prev` to work**: an `input_number` helper for the
  automation to keep its place in the favorites list, and some favorites defined
  in the integration's *Configure* dialog (one per line, `Name=Channel`). Create
  the helper under Settings → Devices & Services → Helpers → Create helper →
  Number, with **min 0, max 99, step 1**.

  This is needed because no DISH transport reports the tuned channel — the
  receiver simply doesn't expose it — so `media_player.source` is always unknown
  and the automation has nowhere else to remember which favorite you're on.
  Without the helper, every press lands on the first favorite instead of stepping.

## 1. Add the Home Assistant device in the SofaBaton app

In the SofaBaton app, add a device, choose the **Wi-Fi / Home Assistant** type, and
enter your broker's address, port (1883 by default), username and password. Then
create one command per DISH button you want — name them however you like, since
the name is only a label in the app. Assign the commands to hard buttons and
touchscreen positions inside an Activity.

The app assigns each command a numeric `device_id` / `key_id` pair that **you
cannot choose or rename**. That's why the next step exists.

## 2. Find your topic and confirm the hub is publishing

The hub publishes to one topic for the whole device — the remote's MAC address
followed by `/up`. Watch for it with the wildcard default:

```bash
python3 tools/sofabaton_map.py --listen --host <broker-ip> --user <user> --password <pass>
```

Press any button. You should see something like:

```
  aabbccddeeff/up              code 7:1        {"device_id":7,"key_id":1}
```

Note the topic — you'll need it in step 4. If nothing arrives, jump to
[Troubleshooting](#troubleshooting).

## 3. Capture the key map

Run the capture walk. It prompts for one DISH action at a time; press the button
you want to own that action, or type `s` to skip and `q` to stop early.

```bash
python3 tools/sofabaton_map.py --host <broker-ip> --user <user> --password <pass> --topic aabbccddeeff/up
```

It refuses ids that are already claimed, ignores held-button repeats, and ends by
printing a paste-ready block:

```yaml
key_map:
  "7:1": wake
  "7:2": up
  "7:3": down
  "7:8": guide
  "7:14": tune:140
```

Every action is validated against [keys.py](../custom_components/dish_receiver/keys.py)
before it's written out, because the underlying service calls log-and-ignore bad
names rather than raising — an unvalidated typo would just be a dead button.

## 4. Import the blueprint and create the automation

Settings → Automations & Scenes → Blueprints → **Import blueprint**, and paste:

```
https://github.com/jamesarrowood/dish-receiver-hass/blob/main/blueprints/automation/dish_receiver/sofabaton_x2.yaml
```

Create an automation from it and fill in:

- **MQTT topic** — from step 2, e.g. `aabbccddeeff/up`
- **DISH remote entity** — `remote.<your receiver>_remote`
- **DISH media player entity** — `media_player.<your receiver>`
- **Key map** — the block from step 3 (keep the quotes around `"7:1"`; bare
  `7:1` isn't valid YAML)
- **Favorite cursor helper** — the `input_number` from the requirements above.
  Leave it empty if you aren't using `fav_next` / `fav_prev`.

Unmapped presses are ignored silently, so a partial map is perfectly fine while
you're still building it up.

## 5. Suggested button layout

Leave **volume up/down** assigned to the TV device in the SofaBaton app — it's a
TV-side function and the X2 already does it natively over IR. Everything else goes
to the Home Assistant device:

| X2 button | Action | Why |
| --- | --- | --- |
| Power | `wake` | Only if you aren't using IR for power. IR power-toggle works on the Wally and is the better choice; `wake` just nudges it out of standby and no-ops when it's already on. |
| Channel ▲ | `fav_next` | No channel-step over IP. This walks your configured favorites instead. |
| Channel ▼ | `fav_prev` | As above, in reverse. |
| D-pad | `up` | |
| D-pad | `down` | |
| D-pad | `left` | |
| D-pad | `right` | |
| OK | `select` | |
| Back | `back` | |
| Exit | `exit` | Canonical name for the key DISH calls "Cancel". |
| Guide | `guide` | |
| Menu | `menu` | |
| Info | `info` | |
| DVR | `dvr` | |
| Live TV | `live_tv` | Canonical name for the key DISH calls "TV". |
| Options | `options` | |
| Play / Pause / Stop | `play` | |
| Rewind | `rewind` | |
| Skip forward | `jump` | The Wally exposes skip-forward, not fast-forward. |
| Record | `record` | |
| Mute | `mute` | Receiver-side mute — confirmed working over IP. |
| Digits 0–9 | `5` | Digits are their own key names. |
| Dash | `dash` | For sub-channels like 140-01. |
| Enter | `enter` | |
| Favorite 1 | `tune:140` | One-press tune. The real win over a plain remote. |
| Favorite 2 | `app:Netflix` | Launches the app over DIAL. |

## Limits

- **One-way.** The hub publishes; nothing comes back. The X2's screen can't show
  what channel you're on or whether the receiver is awake.
- **No power off over IP.** Nothing on any reachable network interface sets power —
  standby is readable only, and `wake` is the honest version of a power button.
  **Use IR for real power control**; it works on the Wally.
- **No channel/page step, no fast-forward, no volume** over IP. IR does all three;
  `fav_next` / `fav_prev` are the IP-only fallback for channel stepping, and volume
  belongs to the TV either way.
- **The receiver never reports its current channel.** `media_player.source` and
  the `channel_number` attribute stay empty on a Wally, which is why favorite
  stepping needs its own cursor helper. It also means the cursor can drift out of
  sync if you tune by any other route — press the favorite button twice to
  resynchronise.
- **Ids can shift.** If you delete and recreate commands in the app, the
  `device_id`/`key_id` pairs may change. Re-run the capture if buttons start
  doing the wrong thing.
- **Broker credentials live in the SofaBaton app in plaintext.** Give it its own
  MQTT user rather than reusing an admin account.
- **App launch needs the local transport** — `app:` actions do nothing on the
  delegate transport, which has no DIAL.

## Troubleshooting

**Nothing on `--listen`.** Check the hub and the broker are on the same network,
that the broker's username/password in the SofaBaton app match the ones you set in
Mosquitto, and that you're pressing a button belonging to the *Home Assistant*
device rather than an IR device. Confirm the broker itself is reachable by
publishing a test message from Developer Tools → Actions → `mqtt.publish`.

**Messages arrive but nothing happens.** Open the automation's trace. If it stops
at the condition, the pressed id isn't in your key map. If it dispatched but the
receiver didn't move, check the integration's own log — a key name that isn't in
`keys.py` is logged and dropped there.

**A button does the wrong thing.** Two actions ended up sharing an id, or the app
reassigned ids. Re-run the capture for the affected buttons with
`--only guide info dvr`.

## Status

The Home Assistant / MQTT device type, the `<mac>/up` topic and the
`{"device_id":N,"key_id":M}` payload are as documented by SofaBaton and reported by
users; the blueprint and helper were built and tested against simulated messages.
Anything in this document that hasn't been confirmed against a physical X2 yet is
flagged as such here rather than in the steps above — treat the topic format in
step 2 as the first thing to verify with `--listen`.
