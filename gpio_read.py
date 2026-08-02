"""Read every EC600U GPIO as a high-impedance input.

Purely observational: no pin is driven, so this is safe to run against an
unknown board. The resulting level map narrows down which pin holds the ESP
in reset.
"""

import time

from qpy import Qpy

DEVICE_CODE = """
from machine import Pin
out = {}
for i in range(1, 48):
    name = 'GPIO%%d' %% i
    pid = getattr(Pin, name, None)
    if pid is None:
        continue
    try:
        p = Pin(pid, Pin.IN, %(pull)s)
        out[name] = p.read()
    except Exception as e:
        out[name] = 'ERR ' + repr(e)[:40]
for k in sorted(out, key=lambda x: int(x[4:])):
    print(k, out[k])
"""


def read_all(pull="Pin.PULL_DISABLE"):
    q = Qpy()
    out, err = q.exec(DEVICE_CODE % {"pull": pull}, read_for=25)
    q.close()
    return out, err


if __name__ == "__main__":
    results = {}
    for label, pull in (("float", "Pin.PULL_DISABLE"),
                        ("pullup", "Pin.PULL_PU"),
                        ("pulldown", "Pin.PULL_PD")):
        out, err = read_all(pull)
        results[label] = {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].startswith("GPIO"):
                results[label][parts[0]] = " ".join(parts[1:])
        if err:
            print(label, "err:", err[:200])

    pins = sorted(results["float"], key=lambda x: int(x[4:]))
    lines = ["pin      float  pullup  pulldown   verdict"]
    for p in pins:
        f = results["float"].get(p, "?")
        u = results["pullup"].get(p, "?")
        d = results["pulldown"].get(p, "?")
        if u == "1" and d == "0":
            verdict = "floating (no external driver)"
        elif u == d == "1":
            verdict = "DRIVEN HIGH externally"
        elif u == d == "0":
            verdict = "DRIVEN LOW externally"
        else:
            verdict = ""
        lines.append("%-8s %-6s %-7s %-10s %s" % (p, f, u, d, verdict))
    report = "=== GPIO level map (%s) ===\n%s\n" % (
        time.strftime("%Y-%m-%d %H:%M:%S"), "\n".join(lines))
    print(report)
    with open("logs/gpio_levels.log", "a") as fh:
        fh.write(report)
