# Public Third-Party Drivers & Integrations for DISH / EchoStar Receivers — Protocol Survey

Scope: Hopper / Joey / Wally / XiP813 / HEVC211. Goal: document the **port-443 "SGS"** local
control protocol (channel/now-playing/tune/power/capabilities) from **public plaintext sources**.

Status legend: **[CONFIRMED]** = read directly from a driver/repo/doc in plaintext ·
**[INFERRED]** = deduced from surrounding code/behaviour · **[GATED]** = exists but not public/plaintext.

---

## 1. Headline finding

The single most valuable public source is **not** a vendor driver — it is a set of GitHub
repositories by user **`askjake`** (a DISH/EchoStar STB automation/test toolkit) that implement
the SGS protocol in **plaintext Python**, including the richer commands that vendor drivers keep
compiled or encrypted. These give the actual port-443 JSON wire format.

Vendor drivers (Control4, Crestron, RTI, URC) only expose an **abstract command layer**
(key-press names + pairing); their real 443 wire bodies are compiled/encrypted. The askjake repos
fill that gap.

---

## 2. Vendor / integration matrix

| Vendor / Project | Transport / Port | Auth | State feedback (channel/now-playing)? | Where the wire protocol lives |
|---|---|---|---|---|
| **Control4** (Hopper + MSP drivers) | SSL / **443** | EchoStar-issued partner client certificate + paired creds | Yes — Recordings/PTAT/Rentals/Favorites browse, NowPlaying, channel tune/change | `driver.xml` = abstract `Type>PROTOCOL` command names only; real JSON in **[GATED]** encrypted driver logic |
| **Crestron – DISH Hopper v1.1** (Application Market) | TCP/IP (SGS) | Pairing PIN + STB IDs | **No** — key-presses + discrete channel preset only | Help PDF (commands are SIMPL signal names, not wire) |
| **Crestron – DISH 2.0** (drivers.crestron.io, Crestron Home only) | TCP/IP (SGS) | Pairing | Auto-discovery; not inspected (gated download) | **[GATED]** compiled driver |
| **RTI** (driverstore.rticontrol.com) | TCP / **port 80** (per prior work) | Pairing/auth | key-press emulation + auth | decompiled previously; no MSP-class RTI driver found |
| **URC (Total Control)** | TCP/IP (SGS), via driver DB | Pairing | key-press class (same family) | driver DB entry; no public wire doc found |
| **askjake GitHub repos** (JAMboree / JAMboreeLite / aBitTesty / JAMboree-full / GardeBien / DP) | **HTTP 80/8080 + HTTPS 443** `/www/sgs` | Digest + mutual-TLS client cert (443) | **Yes — full plaintext**: tuner usage, services list, EPG data-search, DVR query, settings, async events | **Plaintext Python** — see §3 |
| **DISH "Second Screen API" / develop-for-hopper** | — | Vetted partner program (email devprogram@dish.com, 2013) | Documented capabilities: EPG queries, tuning + tuner-usage, DVR/on-demand | **[GATED]** partner-only; internal Confluence referenced in code (see §3.9) |
| **Home Assistant / Homebridge / npm / OpenHAB / Node-RED** | — | — | No native integration exists | Community threads only; users fall back to IR (Broadlink) |

---

## 3. The SGS transport (CONFIRMED, plaintext)

Source: `askjake/JAMboreeLite/jamboree/sgs_lib.py`, `askjake/JAMboree/sgs_lib.py`, `askjake/aBitTesty/sgs_lib.py`.

Three endpoints, all POST JSON, all path **`/www/sgs`** except pairing:

| Purpose | Method / URL | Auth |
|---|---|---|
| **Production / secure** | `POST https://<ip>/www/sgs` (port **443**) | `HTTPDigestAuth(login, passwd)` **+** mutual-TLS client cert `cert=(cert.pem, key.pem)`, `verify=False` |
| **Dev / unsecure** | `POST http://<ip>:<port>/www/sgs` (port default **8080**, often 80) | none |
| **Pairing (no auth)** | `POST http://<ip>:<port>/sgs_noauth` (falls back to `:8080`) | none |

Common JSON envelope fields on every command: `command`, `cid`, `receiver` (the controller's own
Receiver ID, format `XAF<mac>`), and for targeted commands `stb` (the box's Receiver ID, e.g.
`R1911705054-56`) and `tv_id`. Success is `result == 1`; `result == 56` = accepted, async event to
follow; failures carry a `reason` string. `cid` **65535** is used as the broadcast/global cid.

**Pairing handshake** (CONFIRMED):
```json
// 1) start  -> POST /sgs_noauth
{"command":"device_pairing_start","receiver":"<XAFmac>","stb":"<Rxxxx-xx>","app":"JAMboree","name":"JAMboree","type":"python","id":"S9","mac":"<mac>"}
// 2) complete (after PIN shown on TV)
{"command":"device_pairing_complete", ...,"pin":"<PIN>"}
// response returns the Digest credentials to use thereafter:
//   response["name"]  -> login
//   response["passwd"]-> passwd
```
**Attach / detach** (establishes the `cid` used for feedback/events):
```json
{"command":"attach","receiver":"<XAFmac>","stb":"<Rxxxx-xx>","tv_id":0,"attr":1}   // -> {"result":1,"cid":<n>}
{"command":"detach","receiver":"<XAFmac>","cid":<n>}
```

The port-443 path additionally requires a partner-issued mutual-TLS client certificate, which is
outside the scope of this project — see the main integration notes for why that tier isn't pursued.

---

## 4. Port-443 SGS command structure (CONFIRMED verbatim from plaintext Python)

### 4.1 Remote key / power  (`askjake/.../sgs_remote.py`)
Power on/off/toggle and all navigation are key-presses (there is **no** separate "power" verb):
```json
{"command":"remote_key","stb":"<Rxxxx-xx>","tv_id":"0","key_name":"Power On"}   // also "Power Off","Power Toggle","Guide","DVR","Live TV","Jump", digits 0-9, etc.
{"command":"remote_key_automation","key_code":<int>,"state":0,"tv_id":<n>,"data":[...],"dev_id":<n>}   // state 0 = press+release
```
Supported `key_name` set and numeric key_code map are fully enumerated in `sgs_remote.py` /
`commands.py` (e.g. Channel Up=19, Channel Down=22, Enter/Select=9, Live TV=110, Sys Info=42).

### 4.2 Current channel / NOW-PLAYING  →  `get_tuner_usage_v2`  (CONFIRMED — this is the now-playing query)
Source: `askjake/JAMboree/get_tuner_usage_v2.py`
```json
{"command":"get_tuner_usage_v2"}
```
Returns `tuner_usage_list`, one object per tuner with fields:
`tuner`, `tuner_type` (0 inval,1 sat,2 offair,3 rem-sat,4 broadband), `usage` (0 free,1 TV+,2 TV-,
3 sling,4 PTAT-,5 EPG,6 RMS,7 swDw,8 chSw,9 Acq, …), `status` (0 locked,1 lost,2 acq,3 rainfade,…),
`attr` (bitmask: 0x1 rec, 0x2 pause, 0x4 PIP, 0x8 owner, 0x10 sharing, 0x20 avail, 0x40 PTAT,
0x100 PIPact, 0x1000 AV), `cid`, `name`, **`svc`** (service/channel id), **`title`** (program title).

### 4.3 Channel / service list  →  `services_list_xip`  (CONFIRMED)
Source: `askjake/aBitTesty/r_rated_finder.py`
```json
{"command":"services_list_xip","cid":65535,"start_svc":0,"size":0,"req_total_size":false,"receiver":"<Rxxxx-xx>"}
```
Returns `svc_list[]`, each service: `svc_name`, `svc` (internal id), `disp_ch` (display channel
string), `major`, `stype` (service type int), `category` (bitmask), plus `locked`/`adult`/`ppv`/
`interactive`/`placeholder` flags.
Category bitmask (verbatim): music 0x0001, movies 0x0002, spanish 0x0004, local 0x0008,
entertainment 0x0010, sports 0x0020, adult 0x0040, ppv 0x0080, vod 0x0100, news 0x0200,
series 0x0400, homeandgarden 0x0800, kids 0x1000, shopping 0x2000, international 0x4000, streaming 0x8000.

### 4.4 Server-side filtered service list  →  `services_list_filtered`  (CONFIRMED)
```json
{"command":"services_list_filtered","cid":65535,"adult":0,"locked":0,"downmap":0,"vod":0,"attr":0,"exclude":0}
```
`attr` include-bits: placeholder 0x1, ppv 0x2, interactive 0x4. `exclude` type-bits: 3d 0x1, 4k 0x2,
ott 0x4, barker 0x8. Returns `svc_id_info_list[]` with `svc`.

### 4.5 EPG / program search  →  `start_data_search` → `get_data_search_result`  (CONFIRMED)
```json
{"command":"start_data_search","cid":65535,"type":"Events","num_before_notify":1,"size":1,
 "sort":["avail_now_later"],
 "filter_tree":{"compound_and":[{"scope":["EPG"]},{"evt_avail":["Now"]},{"content_rating":["R"]}]}}
// -> {"result":1,"search_id":<sid>}   (poll async_events for ver/done, then:)
{"command":"get_data_search_result","cid":65535,"ver":<ver>,"search_id":<sid>,"start_idx":1,"level_details":"Large","size":1}
{"command":"stop_data_search","cid":65535,"search_id":<sid>}
```
Result path: `search_result.data_list[]` → item has `ser_mpaa_tv` (rating), `episode[].events.evt_service[].chn_sid` (channel).

### 4.6 DVR listing  →  `dvr_query_sideloading_info`  (CONFIRMED)
Source: `askjake/JAMboree/dvr_query_sideloading_info.py`
```json
{"command":"dvr_query_sideloading_info","req_total_size":true,"order":1,"main_sort":9,"sub_sort":1,
 "before":0,"after":<n>,"include":true,"src":1,"type":1,"filter":0,"search_type":0,
 "evt":{"start_dvr_id":0,"rec_tm":0,"name":"","theme":0,"grp_id":0,"network_id":0}}
```

### 4.7 Settings / capabilities  →  `get_stb_settings` / `set_stb_settings`  (CONFIRMED)
Source: `askjake/aBitTesty/reset_stb_user_settings.py`, `askjake/JAMboree/sgs.py`
```json
{"command":"get_stb_settings","receiver":"R0000000000-00","cid":"1004","name":"dish_ip_mode","id":63}
{"command":"set_stb_settings","id":<gid>,"name":"<group>","data":{...}}
```
Settings are addressed by numbered **data-groups** (`id`+`name`). Full enumeration (verbatim subset):
1 closed_caption_enable, 4 parental_controls, 6 guide, 9 channel_preference, 10 multi_channel_swap,
11 multi_channel_recall, 15 timer_defaults, 16 ptat_enable, 17 video_format, 36 control_4_enable,
40 dvr_sort, 48 dvr_schedule, 50 guide_appearance, 53 ui_theme, 57 home_screen, 63 dish_ip_mode,
64 large_dvr_images_enable, 65 voice_control_mode, 67 dvr_filter … (70 = PIP group).

### 4.8 PIP / multi-view  (CONFIRMED)
Source: `askjake/aBitTesty/normal_pip.py`
```json
{"command":"get_pip_status"}                                                  // status 0 unknown,1 closed,2 background,3 foreground
{"command":"close_multi_pip","main":65535,"pip":65535,"close_other":true}     // modes: 0 single,1 multi4,2 multi6
{"command":"pip_release_permit"}
{"command":"pip_status_notification","position":-1,"size":0}
```

### 4.9 Async event stream  →  `async_events_xip_v2`  (CONFIRMED — powers all live feedback)
Source: `askjake/JAMboree/sgs_ae.py`
```json
{"command":"async_events_xip_v2","error":false,"ack_list":[],"cid_list":[65535,<cid>],
 "poll_delay":10000,"receiver":"<XAFmac>","cid":<cid>}
```
Long-poll: response has `cid_list[].uc_list[]` where each event = `{evt:<int index>, time, info:{...}}`.
The client must echo back an `ack_list` of `{evt,time}` per cid to advance the stream.
`evt` indexes the **`AE_EVENTS_NAMES`** table (defined verbatim in `sgs_lib.py`, ~350 entries).
The channel/now-playing-relevant events include:
`AE_TUNER_STATUS`, `AE_CHANNEL_CHANGE_STATUS`, `AE_REMOTE_CHANNEL_CHANGING`, `AE_TUNER_USAGE_UPDATE`,
`AE_TUNER_USAGE_UPDATE_V2`, `AE_PLAY_STATUS_CHANGED`, `AE_PLAY_EVENT_STATUS`, `AE_EPG_UPDATED`,
`AE_VIEW_SHARING_STATUS`, `AE_PIP_STATUS`, `AE_SYSTEM_STANDBY_STATUS`, `AE_RECEIVER_STANDBY_STATUS`,
`AE_NOTIFY_TO_POWER_OFF`, `AE_HAS_PLAYBACK_STATUS`, `AE_EXTERNAL_RAE_TUNE_CH_XIP_V2`,
`AE_EXTERNAL_RAE_GET_PLAY_STATUS_XIP`.

### 4.10 Other confirmed commands
- `get_stb_information` (get-info), `attach`/`detach`, generic passthrough `{"command":<any>,...}`.
- Remote-management backend verbs enumerated in `askjake/GardeBien/stb_sgs.py` `ALL_COMMANDS`:
  `start_remote_pairing_monitor`, `stop_remote_pairing_monitor`, `get_paired_remote_list`,
  `unpair_remote`, `locate_remote`, `get_remote_settings`, `set_remote_setting`, `backup_devices`,
  `restore_device`, `query_stb_settings_from_remote`, `reset_user_settings`, `start_elcc_download`.
- `get_network_diagnosis_metrics` (example in `sgs_simple.py`).
- **Internal DISH doc referenced in a code comment** (GATED, not public): a Confluence page at
  `confluence.dtc.dish.corp/…pageId=113606854#ChannelChange…tuner_usage_information` documents the
  `tuner_usage` structure. Corporate-internal; only the URL was seen, not the content.

**Channel tuning:** none of the public code uses a dedicated "tune to channel N" SGS verb — tuning is
performed by sending `remote_key` digit presses, and the resulting channel is read back via
`get_tuner_usage_v2` and the `AE_CHANNEL_CHANGE_STATUS` / `AE_TUNER_USAGE_UPDATE` async events.
**[INFERRED]** an `AE_EXTERNAL_RAE_TUNE_CH_XIP_V2` event name implies a tune request path exists in
the full API, but its request body does not appear in public plaintext.

---

## 5. Crestron DISH Hopper v1.1 (CONFIRMED — Help PDF)

Source: `applicationmarket.crestron.com/content/Help/Dish/DISH_Hopper_v1_1_Help.pdf`
(extracted locally to `.../protocol-findings/crestron_v1_1_help.txt`).

- Controls **1 Hopper + up to 3 Joeys via TCP/IP**. Vendor firmware v3.009.0013.
- Setup = enter Hopper IP + STB Receiver IDs (format `R1887413544-55`), enable Pairing, then
  `Hopper_Send_Pairing_Start` → PIN on screen → `PIN_Entry_Text` → `Hopper_Send_Pairing_Complete`.
- Command set is **key-press only** (SIMPL signals): Power On/Off, Enter, Cancel, Guide, Menu, DVR,
  Search, transport, keypad 0-9/*/#, colour buttons, Live TV, Jump, Info, Sys Info, PIP, and
  `Preset_Channel_In` (3-digit analog channel recall). **No now-playing / current-channel / state
  feedback.** This is the same key-press class as the port-80 SGS remote_key API.
- A **Crestron Home 2.0** driver exists on `drivers.crestron.io` but is gated (Crestron Home only);
  not inspected.

---

## 6. Other ecosystems (searched; no plaintext 443 protocol found)

- **RTI**: driver present (driverstore.rticontrol.com); prior work established **port 80** key-press
  emulation + auth. No MSP-class RTI driver surfaced.
- **URC Total Control**: DISH Hopper supported via driver DB; same pairing/key-press family; no public
  wire-level doc found.
- **Home Assistant**: only a long community thread (t/dish-network-hopper-control/100397) — no native
  integration; users point at the "Dish 2nd Screen" API or fall back to Broadlink **IR** on Hopper 2.
- **Homebridge / npm / OpenHAB / Node-RED / iRule / Roomie / Simple Control / The Home Remote**:
  no DISH/EchoStar/Hopper SGS integration located.
- **DISH "Second Screen API" (2013)**: partner-gated (email `devprogram@dish.com`). Publicly
  documented *capabilities* match the SGS commands above: remote key-press emulation, key system
  settings, EPG queries for current + specific events, and channel changing incl. tuning + tuner
  usage on all tuners. No public SDK/reference PDF found (archive.org fetch blocked in this env).

---

## 7. Source URLs

- Crestron v1.1 Help: `https://applicationmarket.crestron.com/content/Help/Dish/DISH_Hopper_v1_1_Help.pdf`
- Crestron listing: `https://applicationmarket.crestron.com/dish-hopper/`  · Crestron Home 2.0: `https://drivers.crestron.io/`
- RTI: `https://driverstore.rticontrol.com/driver/dish-network`
- **GitHub (plaintext SGS protocol):**
  - `https://github.com/askjake/JAMboree`  (get_tuner_usage_v2.py, sgs_ae.py, sgs.py, sgs_simple.py, dvr_query_sideloading_info.py, sgs_lib.py)
  - `https://github.com/askjake/JAMboreeLite`  (jamboree/sgs_lib.py, sgs_remote.py, commands.py, sgs_bridge.py)
  - `https://github.com/askjake/aBitTesty`  (r_rated_finder.py, normal_pip.py, reset_stb_user_settings.py, sgs_lib.py)
  - `https://github.com/askjake/GardeBien`  (stb_sgs.py — ALL_COMMANDS)
  - `https://github.com/askjake/DP`  (TuneToRatedChannel.py)
- DISH Second Screen API announcements: about.dish.com/2013-09-26-…, programmableweb.com/news/dish-opens-second-screen-api-to-partners
- HA community: `https://community.home-assistant.io/t/dish-network-hopper-control/100397`

## 8. Bottom line

The full port-443 SGS command structure for **now-playing/current-channel** (`get_tuner_usage_v2`),
**channel/service enumeration** (`services_list_xip` / `services_list_filtered`), **EPG**
(`start_data_search`/`get_data_search_result`), **DVR** (`dvr_query_sideloading_info`), **settings /
capabilities** (`get_stb_settings`/`set_stb_settings` data-groups), **PIP** (`get_pip_status` etc.),
and **live state** (`async_events_xip_v2` + the `AE_*` event table) is fully documented above from
plaintext public GitHub sources. Power and channel tuning are done via `remote_key` presses with
state confirmed through tuner-usage + async events. Reaching port 443 in practice still requires a
partner-issued client certificate, which is outside the scope of this project.
