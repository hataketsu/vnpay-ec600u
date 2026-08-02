"""Power the ESP up.

This script only drives the enable pins and leaves them driven; probing the
UARTs is left to scan_uart.py, which opens and *closes* each port.  Keeping
the two jobs apart matters: one of the QuecPython UARTs is backed by the same
port as the REPL, so a UART left open silently hijacks the REPL and the only
way back is a power cycle.

Pin roles come from the EC600M board notes, re-mapped to EC600U GPIO numbers
(same LCC footprint, different GPIO indices):

    module pin 40  MAIN_RI     EC600M G9   -> EC600U GPIO24   ESP EN
    module pin 49  WAKEUP_IN   EC600M G21  -> EC600U GPIO25   VDD_EXT rail enable
    module pin 50  AP_READY    EC600M G22  -> EC600U GPIO26

A fresh Pin object has to be constructed to actually re-drive a level on this
QuecPython build; .value() alone does not.
"""

import sys
import time

from qpy import Qpy

WAKEUP = 25
ESP_EN = 24
AP_READY = 26

DEVICE_CODE = """
from machine import Pin
import utime
_wk = Pin(Pin.GPIO%(wakeup)d, Pin.OUT, Pin.PULL_DISABLE, 1)
utime.sleep_ms(200)
_en = Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, %(en_off)d)
utime.sleep_ms(300)
_en = Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, %(en_on)d)
utime.sleep_ms(%(settle)d)
print('wakeup=1 en=%(en_on)d done')
"""


def enable(en_active_low=True, settle=1500):
    q = Qpy()
    try:
        out, err = q.exec(DEVICE_CODE % {
            "wakeup": WAKEUP,
            "en": ESP_EN,
            "en_off": 1 if en_active_low else 0,
            "en_on": 0 if en_active_low else 1,
            "settle": settle,
        }, read_for=20)
    finally:
        q.close()
    return out, err


if __name__ == "__main__":
    active_low = "high" not in sys.argv
    out, err = enable(active_low)
    label = "EN active-low" if active_low else "EN active-high"
    report = "=== ESP enable %s (%s) ===\n%s\n%s\n" % (
        label, time.strftime("%Y-%m-%d %H:%M:%S"), out, err)
    print(report)
    with open("logs/esp_enable.log", "a") as fh:
        fh.write(report)
    print("now run:  python3 scan_uart.py 115200")
