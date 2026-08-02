"""Talk to the board's ESP8285 over the EC600U MAIN UART.

Wiring established by sweeping every safe GPIO and watching for life:

    EC600U GPIO44 (module pin 14)  ->  ESP CH_PD/EN, active HIGH
    EC600U UART2  (module pins 31/32) <-> ESP UART0, the AT command port

The ESP8285 boot ROM banner comes out at 74880 baud, which QuecPython cannot
select, so the first burst after enable is unreadable garbage at 115200. That
garbage is still the signal that the ESP powered up; the AT firmware itself
speaks at whatever baud is passed here.

GPIO44 is left driven high on exit so the ESP stays powered, but UART2 is
always closed - a UART left open wedges the REPL.

Usage:
    python3 esp_at.py                     # enable + AT + AT+GMR at 115200
    python3 esp_at.py 9600                # same at another baud
    python3 esp_at.py 115200 "AT+CWLAP"   # arbitrary command
"""

import sys
import time

from qpy import Qpy

ESP_EN = 44          # module pin 14, active high
ESP_UART = "UART2"   # module pins 31/32

DEVICE_CODE = """
from machine import UART, Pin
import utime

_en = Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)
utime.sleep_ms(300)
_en = Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)

_u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)
try:
    boot = b''
    for _i in range(25):
        utime.sleep_ms(100)
        n = _u.any()
        if n:
            boot += bytes(_u.read(n))
    print('BOOT', len(boot), boot[:120])

    for _c in %(cmds)s:
        _u.write(_c + b'\\r\\n')
        utime.sleep_ms(2000)
        n = _u.any()
        print('CMD', _c, bytes(_u.read(n)) if n else b'')
finally:
    try:
        _u.close()
    except Exception:
        pass
    print('uart closed')
"""


def talk(baud=115200, cmds=(b"AT", b"AT+GMR")):
    q = Qpy()
    try:
        out, err = q.exec(DEVICE_CODE % {
            "en": ESP_EN,
            "uart": ESP_UART,
            "baud": baud,
            "cmds": repr(list(cmds)),
        }, read_for=15 + 3 * len(cmds))
    finally:
        q.close()
    return out, err


if __name__ == "__main__":
    baud = int(sys.argv[1]) if len(sys.argv) > 1 else 115200
    cmds = [c.encode() for c in sys.argv[2:]] or [b"AT", b"AT+GMR"]
    out, err = talk(baud, cmds)
    report = "=== ESP@%d (%s) ===\n%s\n%s\n" % (
        baud, time.strftime("%Y-%m-%d %H:%M:%S"), out, err)
    print(report)
    with open("logs/esp_at.log", "a") as fh:
        fh.write(report)
