# Wally (HEVC211 / XiP813) confirmed key_name vocabulary

Tested LIVE against the receiver over the authenticated `POST /www/sgs` channel
(serial R0000000000-00). Response `{"result":1}` = accepted, `{"result":20,
"reason":"Unsupported key(X)"}` = rejected.

**Naming rule:** words are CamelCase (`Home`, `Guide`, `FastForward`-style), pure
acronyms are all-caps (`DVR`, `TV`), digits are the bare character (`0`–`9`).
Lowercase (the RTI Hopper driver's tokens) is REJECTED by the Wally.

## Supported (result:1) — verified working

Navigation:  Home, Guide, Info, Menu, Up, Down, Left, Right, Enter, Cancel,
             Back, Options, Search, Input, Format
Select/OK:   Enter   (there is no "Select"/"Ok" — Enter is the D-pad center)
Media:       Play, Pause, Stop, Record, Rewind, Jump   (Jump = skip-forward)
Recall:      Recall  (jump to previous channel)
Screens:     DVR, TV  (TV = live TV)
Digits:      0 1 2 3 4 5 6 7 8 9   (bare digit; direct-tune = digits then Enter)
Colors:      Red, Green, Yellow, Blue
Extras:      Applications, Help, Microphone, Keypad, Backspace, Delete

## NOT supported over IP on the Wally (every casing/variant rejected)

Power (Power/PowerOn/PowerOff/PowerToggle/Pwr/Standby/Sleep/Wake all rejected)
ChannelUp / ChannelDown   (no working token — use direct-tune instead)
PageUp / PageDown
FastForward / discrete Skip-back   (only Rewind + Jump exist)
PIP keys, InfoToggle, AbcToggle, 123Toggle, Dash, Sat

DISH documents that some keys (power, volume, direct channel step) are handled
via IR only and are intentionally absent from the IP emulation API — consistent
with the above. Direct tuning by digits fully covers channel changes.

## Result codes seen
- 1  = command accepted
- 20 = unsupported key
- (pairing) 1 with name/passwd = paired; 42 = no pending/expired pairing
