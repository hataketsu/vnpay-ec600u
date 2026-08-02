"""Characterise what the ESP does after enable: one boot, or a reset loop.

GPIO44 sits in the V_PAD_1V8 domain, so it only ever reaches 1.8 V. An
ESP8285 running at 3.3 V wants roughly 0.75*VDD (~2.5 V) for a reliable logic
high on CH_PD/EN, so 1.8 V is marginal - which would show up as the chip
repeatedly browning out and re-running its ROM banner.

Capturing with timestamps separates the two cases: a single burst means one
clean boot, evenly spaced repeats mean a reset loop, and the spacing gives the
loop period.
"""

import time

from qpy import Qpy

ESP_EN = 44
ESP_UART = "UART2"
BAUD = 115200

CODE = """
from machine import UART, Pin
import utime
_u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)
try:
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)
    utime.sleep_ms(400)
    try:
        _u.read(_u.any())
    except Exception:
        pass
    t0 = utime.ticks_ms()
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)
    bursts = []
    total = 0
    for _i in range(%(ticks)d):
        utime.sleep_ms(20)
        n = _u.any()
        if n:
            d = _u.read(n)
            total += n
            bursts.append((utime.ticks_diff(utime.ticks_ms(), t0), n))
    print('total', total, 'bursts', len(bursts))
    print(bursts[:40])
finally:
    try:
        _u.close()
    except Exception:
        pass
"""


def run(seconds=8):
    q = Qpy()
    try:
        out, err = q.exec(CODE % {"uart": ESP_UART, "baud": BAUD, "en": ESP_EN,
                                  "ticks": int(seconds * 50)},
                          read_for=seconds + 25)
    finally:
        q.close()
    return out, err


if __name__ == "__main__":
    out, err = run()
    report = "=== boot timing (%s) ===\n%s\n%s\n" % (
        time.strftime("%Y-%m-%d %H:%M:%S"), out, err)
    print(report)
    with open("logs/boot_timing.log", "a") as fh:
        fh.write(report)
