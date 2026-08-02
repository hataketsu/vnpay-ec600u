"""Find the EC600U pin that holds the ESP's boot strap.

The ESP powers up (GPIO44 high produces a boot burst) but never speaks AT at
any baud - only the unreadable 74880 ROM banner, then silence. That is what a
ESP8266/8285 does when strapped into UART download mode instead of flash boot:
ROM prints its banner and then waits for a flash tool.

Flash boot needs GPIO0=1, GPIO2=1, GPIO15=0 at reset. So this sweep holds the
ESP enable high, drives each candidate EC600U pin to each level, resets the
ESP, and looks for printable ASCII at 115200 - the AT firmware's "ready"
banner is the success signal.
"""

import time

from qpy import Qpy

ESP_EN = 44
ESP_UART = "UART2"
BAUD = 115200

EXTERNALLY_DRIVEN = {2, 23, 24, 35, 36, 40, 41}
UART_PINS = {3, 7, 18, 19, 20, 21}
CANDIDATES = [i for i in range(1, 48)
              if i not in EXTERNALLY_DRIVEN and i not in UART_PINS and i != ESP_EN]

PROLOGUE = """
from machine import UART, Pin
import utime
_u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)
def _boot():
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)
    utime.sleep_ms(250)
    try:
        _u.read(_u.any())
    except Exception:
        pass
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)
    b = b''
    for _i in range(20):
        utime.sleep_ms(100)
        n = _u.any()
        if n:
            b += bytes(_u.read(n))
    return b
def _score(b):
    if not b:
        return 0
    ok = 0
    for c in b:
        if 32 <= c < 127 or c in (10, 13):
            ok += 1
    return ok * 100 // len(b)
print('ready', _score(_boot()))
"""

SWEEP = """
for _pin in %(pins)s:
    _pid = getattr(Pin, 'GPIO%%d' %% _pin, None)
    if _pid is None:
        continue
    for _lvl in (1, 0):
        try:
            Pin(_pid, Pin.OUT, Pin.PULL_DISABLE, _lvl)
        except Exception as _e:
            print('GPIO%%d ERR' %% _pin)
            break
        _b = _boot()
        _s = _score(_b)
        if _s > 60 and len(_b) > 8:
            print('READABLE GPIO%%d lvl=%%d score=%%d %%s' %% (_pin, _lvl, _s, _b[:120]))
        else:
            print('.GPIO%%d lvl=%%d n=%%d s=%%d' %% (_pin, _lvl, len(_b), _s))
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


def sweep(chunk=4):
    q = Qpy()
    try:
        out, _ = q.exec(PROLOGUE % {"uart": ESP_UART, "baud": BAUD, "en": ESP_EN},
                        read_for=20)
        print("baseline:", out)
        for i in range(0, len(CANDIDATES), chunk):
            pins = CANDIDATES[i:i + chunk]
            out, err = q.exec(SWEEP % {"pins": repr(pins)},
                              read_for=len(pins) * 2 * 3.0 + 25)
            for line in out.splitlines():
                if line.startswith("READABLE") or line.startswith("GPIO"):
                    print("  ", line[:170])
            print("chunk %s ok" % pins)
            if err:
                print("   err:", err[:200])
            with open("logs/strap_sweep.log", "a") as fh:
                fh.write(out + "\n")
        q.exec(EPILOGUE, read_for=15)
    finally:
        q.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        CANDIDATES = [int(x) for x in sys.argv[1].split(",")]
    with open("logs/strap_sweep.log", "a") as fh:
        fh.write("=== strap sweep %s pins=%s ===\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), CANDIDATES))
    sweep()
