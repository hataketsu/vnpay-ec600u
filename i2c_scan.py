#!/usr/bin/env python3
"""Scan every I2C bus for the board's separate audio chip.

The module's own audio path produces nothing on the speaker: `aud_tone_play`
and `play` return 0 on all three device indices while `getState()` stays 0. The
board has a dedicated audio chip, so the speaker most likely hangs off that
rather than off the module's codec.

It will not be on I2S: the EC600U's i2s2 lines are GPIO1/2/30/4, which are the
same pads SPI1 uses for the NOR flash, and the NOR is definitely there. That
leaves I2C or a UART as the control interface.

Addresses are probed with a one-byte read; a return of 0 means the device
acknowledged.

    python3 i2c_scan.py
"""

import time

from qpy import Qpy

PROBE = """
from machine import I2C
try:
    b = I2C(I2C.%(port)s, I2C.STANDARD_MODE)
except Exception as e:
    print('%(port)s open failed: ' + repr(e)[:60])
else:
    found = []
    for a in range(0x08, 0x78):
        try:
            buf = bytearray(1)
            if b.read(a, bytearray(0), 0, buf, 1, 0) == 0:
                found.append(a)
        except Exception:
            pass
    print('%(port)s: ' + (', '.join(hex(x) for x in found) if found else 'none'))
"""

# Known control addresses for audio parts that turn up on boards like this.
KNOWN = {
    0x18: "TAS5731 / TLV320 family",
    0x1A: "WM8960, TLV320AIC3x",
    0x1B: "TAS57xx",
    0x2C: "ES8388 / ES8374 (CE low)",
    0x2D: "ES8374 (CE high)",
    0x10: "ES8311 (CE low)",
    0x18: "ES8311 (CE high) / TAS",
    0x4A: "audio codec, common",
    0x34: "voice playback chip, common",
    0x40: "amplifier, common",
}


if __name__ == "__main__":
    q = Qpy()
    hits = []
    try:
        for port in ("I2C0", "I2C1", "I2C2", "I2C3"):
            out, err = q.exec(PROBE % {"port": port}, read_for=90)
            line = (out or "").strip()
            print("  " + (line or ("ERR " + (err or "")[:100])))
            if ":" in line and "none" not in line and "failed" not in line:
                for tok in line.split(":", 1)[1].split(","):
                    tok = tok.strip()
                    if tok.startswith("0x"):
                        hits.append((port, int(tok, 16)))
    finally:
        q.close()

    print("\n" + "=" * 56)
    if hits:
        for port, addr in hits:
            print("%s 0x%02x  %s" % (port, addr, KNOWN.get(addr, "")))
    else:
        print("no I2C device answered on any bus - the audio chip is either "
              "on a UART, on a one-wire protocol, or not powered")
    with open("logs/i2c_scan.log", "a") as fh:
        fh.write("%s: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), hits))
