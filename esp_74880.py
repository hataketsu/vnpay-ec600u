"""Read the ESP at (near) 74880 baud.

An ESP8266/8285 with a 26 MHz crystal running firmware built for 40 MHz
transmits at nominal_baud * 26/40, so its "115200" is really 74880 - which is
also why the ROM banner is unreadable at every standard rate.

QuecPython rejects 74880 outright, but 76800 is a standard rate only 2.56 %
away, comfortably inside normal UART framing tolerance. This script finds
which non-standard rates the port accepts and reads the boot banner at each.

A successful decode shows the ESP8266 ROM banner, whose "boot mode:(N,M)"
field says whether the chip is flash-booting (N=3) or sitting in UART
download mode (N=1).
"""

import time

from qpy import Qpy

ESP_EN = 44
ESP_UART = "UART2"
CANDIDATES = (76800, 74880, 73728, 78125, 72000, 80000)

PROBE = """
from machine import UART, Pin
import utime
try:
    _u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)
except Exception as e:
    print('BAUD %(baud)d REJECT', repr(e)[:60])
else:
    try:
        Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)
        utime.sleep_ms(300)
        try:
            _u.read(_u.any())
        except Exception:
            pass
        Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)
        b = b''
        for _i in range(30):
            utime.sleep_ms(100)
            n = _u.any()
            if n:
                b += bytes(_u.read(n))
        ok = 0
        for c in b:
            if 32 <= c < 127 or c in (10, 13):
                ok += 1
        print('BAUD %(baud)d n=%%d ascii=%%d%%%%' %% (len(b), (ok * 100 // len(b)) if b else 0))
        print(b[:400])
    finally:
        try:
            _u.close()
        except Exception:
            pass
"""


if __name__ == "__main__":
    out_all = []
    for baud in CANDIDATES:
        q = Qpy()
        try:
            out, err = q.exec(PROBE % {"uart": ESP_UART, "baud": baud, "en": ESP_EN},
                              read_for=25)
        finally:
            q.close()
        print("--- %d ---" % baud)
        for line in out.splitlines():
            print("   ", line[:200])
        if err:
            print("    err:", err[:200])
        out_all.append("--- %d ---\n%s\n%s" % (baud, out, err))
    with open("logs/esp_74880.log", "a") as fh:
        fh.write("=== %s ===\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                       "\n".join(out_all)))
