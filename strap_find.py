#!/usr/bin/env python3
"""Find the pin that lets the ESP flash-boot, using a module-only detector.

A bare power cycle never reaches the firmware (0 of 8 tries), yet the ESP did
flash-boot once while pins were being driven by hand from the panel. So some
EC600U pin holds the ESP's GPIO0 strap high.

The detector needs no 74880-capable port. The ROM's divisor assumes a 40 MHz
crystal while this board runs 26 MHz, so the ROM banner leaves at 74880 and is
garbage when UART2 is read at 115200. The application fixes the divisor, so
clean printable text on UART2 @115200 means, and only means, that the firmware
started.

For every candidate pin and level: drive it, power-cycle the ESP with GPIO44,
listen, and check for clean text.
"""

import sys
import time

from qpy import Qpy
import pinmap

BAUD = 115200
LISTEN_S = 3.0

SKIP = set(pinmap.EXTERNALLY_DRIVEN) | {pinmap.ESP_EN}
CANDIDATES = [g for g in sorted(pinmap.PINS) if g not in SKIP]

PROLOGUE = """
from machine import UART, Pin
import utime
_u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)
def _cycle():
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)
    utime.sleep_ms(600)
    try:
        _u.read(_u.any())
    except Exception:
        pass
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)
    tot = 0
    clean = 0
    best = b''
    for _i in range(%(ticks)d):
        utime.sleep_ms(50)
        n = _u.any()
        if n:
            b = bytes(_u.read(n))
            tot += len(b)
            k = 0
            for c in b:
                if 32 <= c < 127 or c in (10, 13):
                    k += 1
            if len(b) > 8 and k * 100 // len(b) >= 85:
                clean += len(b)
                if len(b) > len(best):
                    best = b
    return tot, clean, best
print('prologue ok')
"""

STEP = """
for _pin in %(pins)s:
    _pid = getattr(Pin, 'GPIO%%d' %% _pin, None)
    if _pid is None:
        continue
    for _lvl in (1, 0):
        try:
            Pin(_pid, Pin.OUT, Pin.PULL_DISABLE, _lvl)
        except Exception:
            print('GPIO%%d ERR' %% _pin)
            break
        t, c, b = _cycle()
        if c:
            print('HIT GPIO%%d lvl=%%d clean=%%d %%s' %% (_pin, _lvl, c, b[:120]))
        else:
            print('.GPIO%%d lvl=%%d tot=%%d' %% (_pin, _lvl, t))
    try:
        Pin(_pid, Pin.IN, Pin.PULL_DISABLE)
    except Exception:
        pass
print('chunk done')
"""

EPILOGUE = """
try:
    _u.close()
except Exception:
    pass
print('uart closed')
"""


def main(pins, chunk=3):
    q = Qpy()
    hits = []
    try:
        out, err = q.exec(PROLOGUE % {"uart": pinmap.ESP_UART, "baud": BAUD,
                                      "en": pinmap.ESP_EN,
                                      "ticks": int(LISTEN_S * 20)},
                          read_for=25)
        print("prologue:", out.strip(), err[:120])
        for i in range(0, len(pins), chunk):
            part = pins[i:i + chunk]
            budget = len(part) * 2 * (LISTEN_S + 1.2) + 30
            out, err = q.exec(STEP % {"pins": repr(part)}, read_for=budget)
            for line in (out or "").splitlines():
                print("  " + line[:170])
                if line.startswith("HIT"):
                    hits.append(line)
            if err:
                print("   err:", err[:150])
            with open("logs/strap_find.log", "a") as fh:
                fh.write((out or "") + "\n")
        q.exec(EPILOGUE, read_for=15)
    finally:
        q.close()

    print("\n" + "=" * 58)
    if hits:
        for h in hits:
            print(h[:200])
    else:
        print("no pin produced a firmware boot")
    return hits


if __name__ == "__main__":
    pins = ([int(x) for x in sys.argv[1].split(",")]
            if len(sys.argv) > 1 else CANDIDATES)
    with open("logs/strap_find.log", "a") as fh:
        fh.write("=== strap find %s pins=%s ===\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), pins))
    main(pins)
