#!/usr/bin/env python3
"""Measure how often a power cycle actually reaches the ESP firmware.

The ROM computes its UART divisor assuming a 40 MHz crystal, but this board
has 26 MHz, so the ROM banner leaves at 74880 baud and reads as garbage when
UART2 is opened at 115200. Once the application loads it reconfigures UART0
to a true 115200, and UART2 starts reading clean text.

That gives a reliable pass/fail signal without needing a 74880-capable port:

    only garbage for the whole window  -> never got past the ROM
    printable text appears             -> firmware is running

Repeating the power cycle shows whether boot mode is stable or a coin flip,
which is what a marginal GPIO0 strap looks like.
"""

import sys
import time

from qpy import Qpy
import pinmap

BAUD = 115200

CODE = """
from machine import UART, Pin
import utime
_u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)
try:
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)
    utime.sleep_ms(700)
    try:
        _u.read(_u.any())
    except Exception:
        pass
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)
    total = 0
    good = 0
    best = b''
    for _i in range(%(ticks)d):
        utime.sleep_ms(50)
        n = _u.any()
        if n:
            b = bytes(_u.read(n))
            total += len(b)
            k = 0
            for c in b:
                if 32 <= c < 127 or c in (10, 13):
                    k += 1
            if len(b) > 8 and k * 100 // len(b) >= 85:
                good += len(b)
                if len(b) > len(best):
                    best = b
    print('total', total, 'clean', good)
    if best:
        print('TEXT', best[:160])
finally:
    try:
        _u.close()
    except Exception:
        pass
"""


def one(q, seconds=5.0):
    out, err = q.exec(CODE % {
        "uart": pinmap.ESP_UART, "baud": BAUD, "en": pinmap.ESP_EN,
        "ticks": int(seconds * 20)}, read_for=seconds + 30)
    total = clean = 0
    text = ""
    for line in (out or "").splitlines():
        if line.startswith("total"):
            p = line.split()
            total, clean = int(p[1]), int(p[3])
        elif line.startswith("TEXT"):
            text = line[5:]
    return total, clean, text, err


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    q = Qpy()
    ok = 0
    try:
        for i in range(1, n + 1):
            total, clean, text, err = one(q)
            verdict = "FIRMWARE RAN" if clean else "stuck in ROM"
            if clean:
                ok += 1
            print("cycle %d/%d: %4d bytes, %4d clean -> %s"
                  % (i, n, total, clean, verdict))
            if text:
                print("      " + text[:150])
            if err:
                print("      err: " + err[:120])
    finally:
        q.close()
    print("\n%d of %d power cycles reached firmware" % (ok, n))
    with open("logs/boot_success.log", "a") as fh:
        fh.write("%s: %d/%d reached firmware\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), ok, n))
