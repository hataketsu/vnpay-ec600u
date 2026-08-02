#!/usr/bin/env python3
"""Cross GPIO14 against the power-off duration.

Two things are known to move the ESP:

* GPIO44 switches its 3V3 rail, so toggling it is a genuine power cycle
* GPIO14 has some influence too - driven high the ESP goes completely silent
  (0 bytes), and after driving it the ESP stopped boot-looping and settled to
  a single banner per cycle

A short off-time may not drain the rail's bulk capacitance, so the chip sees a
dip rather than a true power-down, and the straps latch differently. This
walks GPIO14 (high-impedance / low / high) against several off-times and, for
each, reports the total bytes and how many arrived as clean text.

Clean text at 115200 means the firmware ran: the ROM's divisor assumes a
40 MHz crystal and this board has 26 MHz, so ROM output is 74880 and unreadable
here, while the application fixes the divisor.
"""

import time

from qpy import Qpy
import pinmap

BAUD = 115200
LISTEN_S = 6.0
OFF_MS = (150, 400, 800, 2000)
G14_MODES = ("hiz", "low", "high")

PROLOGUE = """
from machine import UART, Pin
import utime
_u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)
def _g14(mode):
    if mode == 'hiz':
        Pin(Pin.GPIO14, Pin.IN, Pin.PULL_DISABLE)
    else:
        Pin(Pin.GPIO14, Pin.OUT, Pin.PULL_DISABLE, 1 if mode == 'high' else 0)
def _cycle(off_ms):
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)
    utime.sleep_ms(off_ms)
    try:
        _u.read(_u.any())
    except Exception:
        pass
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)
    tot = 0
    clean = 0
    best = b''
    bursts = 0
    for _i in range(%(ticks)d):
        utime.sleep_ms(50)
        n = _u.any()
        if n:
            b = bytes(_u.read(n))
            tot += len(b)
            bursts += 1
            k = 0
            for c in b:
                if 32 <= c < 127 or c in (10, 13):
                    k += 1
            if len(b) > 8 and k * 100 // len(b) >= 85:
                clean += len(b)
                if len(b) > len(best):
                    best = b
    return tot, clean, bursts, best
print('ready')
"""

STEP = """
_g14('%(mode)s')
utime.sleep_ms(200)
t, c, n, b = _cycle(%(off)d)
print('%(mode)s off=%(off)d tot=%%d clean=%%d bursts=%%d' %% (t, c, n))
if b:
    print('   TEXT', b[:150])
"""


def main():
    q = Qpy()
    rows = []
    try:
        out, err = q.exec(PROLOGUE % {"uart": pinmap.ESP_UART, "baud": BAUD,
                                      "en": pinmap.ESP_EN,
                                      "ticks": int(LISTEN_S * 20)},
                          read_for=25)
        print("prologue:", out.strip(), err[:120])
        for mode in G14_MODES:
            for off in OFF_MS:
                out, err = q.exec(STEP % {"mode": mode, "off": off},
                                  read_for=LISTEN_S + 25)
                for line in (out or "").splitlines():
                    print("  " + line[:170])
                    if "clean=" in line:
                        rows.append(line)
                if err:
                    print("   err:", err[:140])
        q.exec("try:\n    _u.close()\nexcept Exception:\n    pass\n"
               "print('closed')", read_for=15)
    finally:
        q.close()

    print("\n" + "=" * 58)
    winners = [r for r in rows if "clean=0" not in r]
    if winners:
        print("firmware ran in these combinations:")
        for w in winners:
            print("  " + w)
    else:
        print("no combination reached firmware")
    with open("logs/combo_test.log", "a") as fh:
        fh.write("=== %s ===\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                       "\n".join(rows)))


if __name__ == "__main__":
    main()
