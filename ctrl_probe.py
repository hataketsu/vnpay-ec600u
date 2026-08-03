#!/usr/bin/env python3
"""Drive a set of GPIOs high and hold, so the HT8313 CTRL pin can be metered.

This is how **GPIO13** was found. At rest CTRL sits at 0 V and holds the
amplifier in shutdown, which is why PVDD, CP, CN and OUT+/- all read 0 V too.
Driving GPIO13 pulls CTRL to 1.8 V and PVDD comes up to 5 V. A meter on CTRL
answers in one run what listening for a tone could not answer in dozens.

Kept for re-testing; `audio_play.py` drives GPIO13 on its own.

The bisect that found it relies on one asymmetry: **a negative result is
free** - CTRL stays at 0 V, so the next subset can be tried immediately. A
positive result latches CTRL high and nothing in software brings it back, so
the board has to be power-cycled before subdividing.

    python3 ctrl_probe.py            # every pin that is safe to drive
    python3 ctrl_probe.py 5,6,8,9    # bisect down to one
    python3 ctrl_probe.py 5,6,8,9 30 # ...and hold for 30 s instead of 90
"""

import sys

from qpy import Qpy

# 23/24/35/36/40/41 are driven by the board - driving them back is contention.
# 14/44 gate the ESP rail and are handled separately.
SKIP = {14, 23, 24, 35, 36, 40, 41, 44}
DEFAULT = [g for g in range(1, 48) if g not in SKIP]

CODE = """
import utime
from machine import Pin
Pin(Pin.GPIO14, Pin.OUT, Pin.PULL_DISABLE, 0)
Pin(Pin.GPIO44, Pin.OUT, Pin.PULL_DISABLE, 1)
held = []
for g in %(pins)s:
    pid = getattr(Pin, 'GPIO%%d' %% g, None)
    if pid is None:
        continue
    try:
        held.append((g, Pin(pid, Pin.OUT, Pin.PULL_DISABLE, 1)))
    except Exception:
        print('GPIO%%d ERR' %% g)
print('HIGH on', [g for g, _ in held])
utime.sleep(%(hold)d)
for g, _ in held:
    Pin(getattr(Pin, 'GPIO%%d' %% g), Pin.IN, Pin.PULL_DISABLE)
print('released')
"""


def main(pins, hold):
    q = Qpy()
    try:
        out, err = q.exec(CODE % {"pins": repr(pins), "hold": hold},
                          read_for=hold + 30)
        print((out or "").strip())
        if err:
            print("err:", err[:200])
    finally:
        q.close()


if __name__ == "__main__":
    # "-" keeps the default set, so a hold time can be given on its own.
    arg = sys.argv[1] if len(sys.argv) > 1 else "-"
    pins = DEFAULT if arg == "-" else [int(x) for x in arg.split(",") if x]
    hold = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    print("driving %d pins high for %d s - meter CTRL now" % (len(pins), hold))
    main(pins, hold)
