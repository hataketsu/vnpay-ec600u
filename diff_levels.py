"""Compare GPIO levels before and after the ESP enable pins are asserted.

Reading a pin reconfigures it as an input, which would drop whatever level
esp_enable.py is holding, so the enable pins themselves are skipped.  If the
peripheral rail really comes up, pins wired to the now-powered ESP change from
floating to externally driven.
"""

import time

from qpy import Qpy

SKIP = {24, 25, 26}

DEVICE_CODE = """
from machine import Pin
skip = %(skip)s
out = {}
for i in range(1, 48):
    if i in skip:
        continue
    pid = getattr(Pin, 'GPIO%%d' %% i, None)
    if pid is None:
        continue
    try:
        out[i] = (Pin(pid, Pin.IN, Pin.PULL_PU).read(),
                  Pin(pid, Pin.IN, Pin.PULL_PD).read())
    except Exception:
        out[i] = ('E', 'E')
for k in sorted(out):
    print('GPIO%%d %%s %%s' %% (k, out[k][0], out[k][1]))
"""


def read(skip=SKIP):
    q = Qpy()
    try:
        out, err = q.exec(DEVICE_CODE % {"skip": repr(set(skip))}, read_for=30)
    finally:
        q.close()
    levels = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) == 3 and p[0].startswith("GPIO"):
            levels[p[0]] = (p[1], p[2])
    return levels, err


def verdict(pu, pd):
    if pu == "1" and pd == "0":
        return "floating"
    if pu == pd == "1":
        return "DRIVEN HIGH"
    if pu == pd == "0":
        return "DRIVEN LOW"
    return "?"


BASELINE = {
    "GPIO2": "DRIVEN HIGH", "GPIO40": "DRIVEN HIGH", "GPIO41": "DRIVEN HIGH",
    "GPIO23": "DRIVEN LOW", "GPIO35": "DRIVEN LOW", "GPIO36": "DRIVEN LOW",
}

if __name__ == "__main__":
    levels, err = read()
    lines = []
    for pin, (pu, pd) in sorted(levels.items(), key=lambda x: int(x[0][4:])):
        v = verdict(pu, pd)
        was = BASELINE.get(pin, "floating")
        if v != was:
            lines.append("%-8s %-12s (was %s)   <-- CHANGED" % (pin, v, was))
        elif v != "floating":
            lines.append("%-8s %-12s (unchanged)" % (pin, v))
    report = "=== levels with ESP enable asserted (%s) ===\n%s\n" % (
        time.strftime("%Y-%m-%d %H:%M:%S"),
        "\n".join(lines) if lines else "no pin differs from baseline")
    print(report)
    if err:
        print("err:", err[:300])
    with open("logs/gpio_levels.log", "a") as fh:
        fh.write(report)
