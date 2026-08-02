#!/usr/bin/env python3
"""Test the 13 pins the earlier strap sweeps never actually drove.

`strap_sweep.py` covered 33 of the 47 GPIOs and found nothing, but it skipped
13 on two assumptions that were both wrong:

* Seven pins were skipped as "externally driven" (2, 23, 24, 35, 36, 40, 41) to
  avoid output contention. But a pin reading as driven does not mean an
  external circuit holds it - **the module itself may be driving it**.
  Quectel's own GPIO sheet notes that pins 39, 40, 48, 49 and 50 "have a 3 V
  output voltage and a level jump when the module is just turned on", and
  GPIO22-26 are the `sdmmc1_*` group, which the SD controller drives whenever
  that peripheral is enabled - regardless of how Pin() is configured. If
  QuecPython brings SDIO1 up by default, one of those pins could be what holds
  the ESP's GPIO0 low.
* Six were skipped as "UART pins" (3, 7, 18, 19, 20, 21) to protect the link
  being read. Also wrong: the link is `UART2` on module pins **31/32**, and
  those two cannot be muxed as GPIO at all, so no GPIO can disturb them.
  3/7/18/19/20/21 are pins 34/123/33/124/122/121 on a different UART, and
  GPIO7/GPIO19 read floating anyway.

Procedure per pin, which is the only thing that can reveal the strap: cut the
ESP's 3V3 rail with GPIO44, set the candidate pin, restore the rail, then see
which mode the ESP came up in.

Detection: the ROM emits at 74880 because its divisor assumes a 40 MHz crystal
against this board's 26 MHz, so it is garbage when UART2 is read at 115200. A
successful flash boot makes the application reprogram the divisor to a true
115200, so **readable text at 115200 means flash boot** - the signal a strap
change would produce.

Top candidates, by analogy with the EC600M board where MAIN_RI drove the ESP:
GPIO24 (pin 40, MAIN_RI) and GPIO23 (pin 39, MAIN_DTR), both currently held
low.

    python3 strap_untested.py              # all 13
    python3 strap_untested.py 24,23        # just the prime suspects
"""

import sys
import time

from qpy import Qpy
import pinmap

BAUD = 115200
LISTEN_S = 3.0

# Never driven by strap_sweep.py or strap_find.py, in suspicion order.
UNTESTED = [24, 23, 22, 26, 25, 2, 40, 41, 35, 36, 3, 18, 20, 21]

PROLOGUE = """
from machine import UART, Pin
import utime
_u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)
def _cycle():
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)
    utime.sleep_ms(700)
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
print('ready')
"""

STEP = """
for _pin in %(pins)s:
    _pid = getattr(Pin, 'GPIO%%d' %% _pin, None)
    if _pid is None:
        print('GPIO%%d missing' %% _pin)
        continue
    for _lvl in (1, 0):
        try:
            Pin(_pid, Pin.OUT, Pin.PULL_DISABLE, _lvl)
        except Exception as _e:
            print('GPIO%%d lvl=%%d ERR %%s' %% (_pin, _lvl, repr(_e)[:30]))
            continue
        t, c, b = _cycle()
        if c:
            print('HIT GPIO%%d lvl=%%d clean=%%d %%s' %% (_pin, _lvl, c, b[:110]))
        else:
            print('.GPIO%%d lvl=%%d tot=%%d' %% (_pin, _lvl, t))
    try:
        Pin(_pid, Pin.IN, Pin.PULL_DISABLE)
    except Exception:
        pass
print('chunk done')
"""


def main(pins, chunk=2):
    q = Qpy()
    hits = []
    try:
        out, err = q.exec(PROLOGUE % {"uart": pinmap.ESP_UART, "baud": BAUD,
                                      "en": pinmap.ESP_EN,
                                      "ticks": int(LISTEN_S * 20)}, read_for=25)
        print("prologue:", (out or "").strip(), (err or "")[:120])
        for i in range(0, len(pins), chunk):
            part = pins[i:i + chunk]
            budget = len(part) * 2 * (LISTEN_S + 1.4) + 30
            out, err = q.exec(STEP % {"pins": repr(part)}, read_for=budget)
            for line in (out or "").splitlines():
                print("  " + line[:170])
                if line.startswith("HIT"):
                    hits.append(line)
            if err:
                print("   err:", err[:150])
            with open("logs/strap_untested.log", "a") as fh:
                fh.write((out or "") + "\n")
        q.exec("try:\n    _u.close()\nexcept Exception:\n    pass\nprint('closed')",
               read_for=15)
    finally:
        q.close()

    print("\n" + "=" * 58)
    if hits:
        for h in hits:
            print(h[:200])
        print("\nThat pin is the strap control. Holding it at the level shown "
              "lets the ESP flash-boot; the other level forces download mode.")
    else:
        print("none of the untested pins changed the boot mode either - which "
              "would leave a resistor on the PCB as the remaining explanation")
    return hits


if __name__ == "__main__":
    pins = ([int(x) for x in sys.argv[1].split(",")]
            if len(sys.argv) > 1 else UNTESTED)
    with open("logs/strap_untested.log", "a") as fh:
        fh.write("=== untested-pin strap sweep %s pins=%s ===\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), pins))
    print("testing pins:", pins)
    main(pins)
