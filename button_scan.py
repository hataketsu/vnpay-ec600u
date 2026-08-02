#!/usr/bin/env python3
"""Find which GPIOs the three buttons (M, +, -) are wired to.

Every candidate pin is configured as an input with its pull-up on, so an
unconnected pin sits at 1. A button normally shorts its pin to ground, so
pressing one drops that pin to 0. The scan takes a baseline, then watches for
any pin that leaves it.

Pin objects are built once and only read inside the loop - constructing them
per sample is far too slow to catch a short press.

Skipped: GPIO44 (the ESP's 3V3 rail switch) and GPIO26 (its boot strap), since
reconfiguring those as inputs drops the ESP.

    python3 button_scan.py            # watch for 30 s
    python3 button_scan.py 60         # longer
    python3 button_scan.py 30 pd      # pull-down instead, for buttons to VCC
"""

import sys
import time

from qpy import Qpy

SKIP = {26, 44}
CANDIDATES = [g for g in range(1, 48) if g not in SKIP]

CODE = """
from machine import Pin
import utime
pull = Pin.%(pull)s
pins = {}
for g in %(pins)s:
    pid = getattr(Pin, 'GPIO%%d' %% g, None)
    if pid is None:
        continue
    try:
        pins[g] = Pin(pid, Pin.IN, pull)
    except Exception:
        pass
base = {}
for g in pins:
    try:
        base[g] = pins[g].read()
    except Exception:
        pass
print('watching %%d pins' %% len(base))
print('baseline zeros:', sorted([g for g in base if base[g] == 0]))
seen = {}
t0 = utime.ticks_ms()
while utime.ticks_diff(utime.ticks_ms(), t0) < %(ms)d:
    for g in pins:
        try:
            v = pins[g].read()
        except Exception:
            continue
        if v != base.get(g):
            n = seen.get(g, 0)
            seen[g] = n + 1
            if n == 0:
                print('CHANGE GPIO%%d  %%d -> %%d  at %%dms'
                      %% (g, base.get(g), v, utime.ticks_diff(utime.ticks_ms(), t0)))
    utime.sleep_ms(5)
print('summary:', [(g, seen[g]) for g in sorted(seen)])
"""


def main(seconds, pull):
    q = Qpy()
    try:
        out, err = q.exec(CODE % {"pins": repr(CANDIDATES),
                                  "ms": int(seconds * 1000),
                                  "pull": "PULL_PU" if pull == "pu" else "PULL_PD"},
                          read_for=seconds + 60)
        for line in (out or "").splitlines():
            print("  " + line[:150])
        if err:
            print("err:", err[:250])
    finally:
        q.close()


if __name__ == "__main__":
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 30
    pull = sys.argv[2] if len(sys.argv) > 2 else "pu"
    print("watching every GPIO for %g s with the %s pull on." % (secs, pull))
    print("press M, then +, then - , holding each about a second, "
          "leaving a gap between them.\n")
    main(secs, pull)
    with open("logs/button_scan.log", "a") as fh:
        fh.write("%s button scan %gs pull=%s\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), secs, pull))
