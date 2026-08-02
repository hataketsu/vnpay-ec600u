#!/usr/bin/env python3
"""Find which GPIOs drive the LEDs.

The EC600M board has a common-anode RGB LED that is **active low** - driving a
pin HIGH does nothing, LOW turns a colour on - on module pins 58/60/61. Those
pins are not available here: on this board they are SPI1, the NOR flash bus.
So the LEDs are somewhere else and have to be found.

`misc.net_light()` is tried first, since on the EC600M board that drove the
green network LED directly.

Then each safe pin is driven LOW for a moment, then released, in numeric
order, printing as it goes - watch the LED and call out the number on screen
when it lights. Both polarities are offered because the wiring here has
already proved different from the EC600M board once: its buttons are active
high where the EC600M's are active low.

GPIO44 is skipped - it switches the ESP's 3V3 rail.

    python3 led_scan.py              # active-low sweep, the likely one
    python3 led_scan.py high         # drive HIGH instead
    python3 led_scan.py netlight     # just toggle misc.net_light
"""

import sys
import time

from qpy import Qpy

SKIP = {44}
CANDIDATES = [g for g in range(1, 48) if g not in SKIP]
DWELL_MS = 1200

NETLIGHT = """
import misc, utime
try:
    for i in range(4):
        print('net_light on')
        misc.net_light(1)
        utime.sleep(1)
        print('net_light off')
        misc.net_light(0)
        utime.sleep(1)
except Exception as e:
    print('net_light not available:', repr(e)[:60])
"""

SWEEP = """
from machine import Pin
import utime
for g in %(pins)s:
    pid = getattr(Pin, 'GPIO%%d' %% g, None)
    if pid is None:
        continue
    try:
        Pin(pid, Pin.OUT, Pin.PULL_DISABLE, %(level)d)
    except Exception:
        print('GPIO%%d cannot be driven' %% g)
        continue
    print('>>> GPIO%%d = %(level)d' %% g)
    utime.sleep_ms(%(dwell)d)
    try:
        Pin(pid, Pin.IN, Pin.PULL_DISABLE)
    except Exception:
        pass
    utime.sleep_ms(400)
print('sweep done')
"""


def netlight():
    q = Qpy()
    try:
        out, err = q.exec(NETLIGHT, read_for=30)
        print((out or "").strip()[:300], (err or "")[:200])
    finally:
        q.close()


def sweep(pins, level):
    q = Qpy()
    try:
        chunk = 6
        for i in range(0, len(pins), chunk):
            part = pins[i:i + chunk]
            out, err = q.exec(SWEEP % {"pins": repr(part), "level": level,
                                       "dwell": DWELL_MS},
                              read_for=len(part) * (DWELL_MS + 400) / 1000.0 + 30)
            for line in (out or "").splitlines():
                print("  " + line[:100])
            if err:
                print("   err:", err[:150])
    finally:
        q.close()


if __name__ == "__main__":
    if "netlight" in sys.argv:
        print("toggling misc.net_light four times - watch the LEDs")
        netlight()
    else:
        level = 1 if "high" in sys.argv else 0
        rest = [a for a in sys.argv[1:] if a not in ("high", "low")]
        pins = [int(x) for x in rest[0].split(",")] if rest else CANDIDATES
        print("driving each pin %s for %.1fs - watch the LEDs and note the "
              "number on screen when one lights\n"
              % ("HIGH" if level else "LOW", DWELL_MS / 1000.0))
        sweep(pins, level)
    with open("logs/led_scan.log", "a") as fh:
        fh.write("%s led scan %s\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(sys.argv[1:])))
