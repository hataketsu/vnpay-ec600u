"""Find the baud the ESP-AT firmware actually runs at.

The ESP is reset for every candidate baud so its boot banner is captured
fresh. The 74880-baud ROM banner is unreadable (QuecPython cannot select that
rate) but the AT firmware prints "ready" at its own configured baud, so the
right baud is the one that yields printable ASCII.
"""

import time

from qpy import Qpy

ESP_EN = 44
ESP_UART = "UART2"
BAUDS = (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600)

DEVICE_CODE = """
from machine import UART, Pin
import utime
_en = Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)
utime.sleep_ms(400)
_u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)
try:
    _en = Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)
    boot = b''
    for _i in range(30):
        utime.sleep_ms(100)
        n = _u.any()
        if n:
            boot += bytes(_u.read(n))
    _u.write(b'AT\\r\\n')
    utime.sleep_ms(1500)
    n = _u.any()
    resp = bytes(_u.read(n)) if n else b''
    print('BAUD %(baud)d boot=%%d %%s' %% (len(boot), boot[:100]))
    print('BAUD %(baud)d at=%%s' %% resp[:100])
finally:
    try:
        _u.close()
    except Exception:
        pass
"""


def printable_ratio(raw):
    if not raw:
        return 0.0
    ok = sum(1 for b in raw if 32 <= b < 127 or b in (10, 13))
    return ok / len(raw)


if __name__ == "__main__":
    lines = []
    for baud in BAUDS:
        q = Qpy()
        try:
            out, err = q.exec(DEVICE_CODE % {
                "en": ESP_EN, "uart": ESP_UART, "baud": baud}, read_for=25)
        finally:
            q.close()
        lines.append("--- %d ---\n%s" % (baud, out))
        flag = ""
        if "ready" in out or "OK" in out.split("at=")[-1]:
            flag = "   <<< READABLE"
        print("--- %-7d ---%s" % (baud, flag))
        for l in out.splitlines():
            print("   ", l[:160])
    report = "=== ESP baud scan (%s) ===\n%s\n" % (
        time.strftime("%Y-%m-%d %H:%M:%S"), "\n".join(lines))
    with open("logs/esp_baud_scan.log", "a") as fh:
        fh.write(report)
