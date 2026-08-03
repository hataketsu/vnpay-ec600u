#!/usr/bin/env python3
"""Read the board's battery voltage, and guess a percentage from it.

`misc.Power.getVbatt()` returns millivolts and is the only battery reading the
firmware exposes - there is no state-of-charge API, and none of the ADC
channels carry a battery divider (ADC0-3 sit at 642-782 mV, nowhere near the
~2 V a 2:1 divider off a Li-ion cell would give).

**The percentage is an estimate, and it is only meaningful on a resting cell.**
While USB is connected the reading tracks the charger rather than the cell, so
a full-looking 4.16 V says nothing about how much charge is actually in there.
For a real figure: unplug USB, leave the board alone for a few minutes, then
read - which of course means reading it some other way than over USB.

    python3 battery.py
    python3 battery.py --samples 20 --interval 500
"""

import argparse

from qpy import Qpy

# Resting-voltage curve for a single Li-ion cell, millivolts to percent.
# Rough by nature: cell chemistry, temperature and load all move it.
CURVE = [(4200, 100), (4160, 95), (4060, 85), (3950, 70), (3850, 50),
         (3750, 30), (3700, 20), (3600, 10), (3400, 0)]

CODE = """
import misc, utime
out = []
for i in range(%(n)d):
    out.append(misc.Power.getVbatt())
    utime.sleep_ms(%(ms)d)
print('mv', out)
print('reason', misc.Power.powerOnReason())
"""


def percent(mv):
    if mv >= CURVE[0][0]:
        return 100
    if mv <= CURVE[-1][0]:
        return 0
    for (hi_mv, hi_pc), (lo_mv, lo_pc) in zip(CURVE, CURVE[1:]):
        if lo_mv <= mv <= hi_mv:
            span = hi_mv - lo_mv
            return round(lo_pc + (mv - lo_mv) * (hi_pc - lo_pc) / span)
    return 0


def read(samples=5, interval=300):
    q = Qpy()
    try:
        out, err = q.exec(CODE % {"n": samples, "ms": interval},
                          read_for=samples * (interval / 1000.0) + 20)
        if err:
            print("err:", err[:200])
        return out
    finally:
        q.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--samples", type=int, default=5)
    p.add_argument("--interval", type=int, default=300, help="ms")
    a = p.parse_args()

    out = read(a.samples, a.interval)
    mv = []
    for line in (out or "").splitlines():
        if line.startswith("mv "):
            mv = [int(x) for x in line[3:].strip("[]").split(",") if x.strip()]
    if not mv:
        raise SystemExit(out or "no reading")

    avg = sum(mv) / len(mv)
    print("%d mV  (%d samples, spread %d mV)"
          % (avg, len(mv), max(mv) - min(mv)))
    print("~%d%% if the cell is resting - see the caveat in this file's "
          "docstring" % percent(avg))
