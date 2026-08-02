#!/usr/bin/env python3
"""Power-cycle the ESP and talk to it during the window before the watchdog.

GPIO44 switches the 3V3 rail feeding the ESP's VDD3V3 - it is a power switch,
not CH_PD - so toggling it is a real power cycle, which is why the ROM reports
`rst cause:1` (power on).

The ESP now flash-boots (`boot mode:(3,7)`, checksums good) but then takes a
watchdog reset. This captures the whole window at 115200 on UART2 with
timestamps, optionally poking `AT` at it, so the sequence is visible: ROM
banner, loader lines, whatever the firmware prints, then the reset.

    python3 esp_talk.py            # listen only, 6 s
    python3 esp_talk.py 6 AT       # same, but send AT once per 500 ms
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
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)   # rail off
    utime.sleep_ms(600)
    try:
        _u.read(_u.any())
    except Exception:
        pass
    t0 = utime.ticks_ms()
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)   # rail on
    poke = %(poke)s
    for _i in range(%(ticks)d):
        utime.sleep_ms(50)
        if poke and _i %% 10 == 9:
            try:
                _u.write(b'AT\\r\\n')
            except Exception:
                pass
        n = _u.any()
        if n:
            print(utime.ticks_diff(utime.ticks_ms(), t0), bytes(_u.read(n)))
finally:
    try:
        _u.close()
    except Exception:
        pass
print('--end--')
"""


def main(seconds=6.0, poke=False):
    q = Qpy()
    try:
        out, err = q.exec(CODE % {
            "uart": pinmap.ESP_UART, "baud": BAUD, "en": pinmap.ESP_EN,
            "ticks": int(seconds * 20), "poke": "True" if poke else "False",
        }, read_for=seconds + 30)
    finally:
        q.close()
    return out, err


if __name__ == "__main__":
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
    poke = len(sys.argv) > 2
    out, err = main(secs, poke)
    print("=== ESP power-cycle, UART2 @%d%s ===" %
          (BAUD, ", poking AT" if poke else ""))
    for line in out.splitlines():
        print(" ", line[:200])
    if err:
        print("err:", err[:300])
    with open("logs/esp_talk.log", "a") as fh:
        fh.write("=== %s poke=%s ===\n%s\n%s\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), poke, out, err))
