# Protocol capture — no longer needed

The DISH/EchoStar local control protocol has been **fully recovered and
hardware-verified**, so the traffic-capture path this file used to describe is
obsolete. Everything is documented from source and confirmed live:

- **[protocol-findings/PROTOCOL.md](protocol-findings/PROTOCOL.md)** — the SGS
  protocol (ports, pairing, Digest with the `message-digest` extension),
  extracted verbatim from the RTI driver source.
- **[protocol-findings/WALLY_KEYS.md](protocol-findings/WALLY_KEYS.md)** — the
  key_name vocabulary confirmed by live testing against a Wally.

If you need to re-derive or extend it (e.g. new key names on a different model),
the fastest path is the same one that worked here: decompile a vendor driver
(the RTI `.rtidriver` is an OLE compound file of zlib-compressed JS) rather than
sniffing traffic. For live key discovery, `tools/verify_control.py` sends an
authenticated keypress and reports the receiver's `result` code (1 = accepted,
20 = unsupported), which is how the Wally key list was built.
