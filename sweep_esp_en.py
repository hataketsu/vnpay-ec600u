"""Find the GPIO that enables the ESP by sweeping candidate pins.

For each candidate the pin is driven low, then high, and all four UARTs are
checked for traffic.  An ESP coming out of reset announces itself (boot
banner / "ready"), so any bytes at all identify both the enable pin and the
UART the ESP is wired to.

Safety rules applied to the candidate list:
  * pins that gpio_read.py showed as externally driven are never driven back
    into, to avoid output contention
  * pins belonging to the UARTs being listened on are left alone
"""

import time

from qpy import Qpy

# Externally driven on this board - do not drive.
EXTERNALLY_DRIVEN = {2, 23, 24, 35, 36, 40, 41}
# Module UART2 pins (123/124/121/122 -> GPIO7/19/21/20) and its flow control
# (GPIO3/18); driving them would break the ports being monitored.
UART_PINS = {3, 7, 18, 19, 20, 21}

CANDIDATES = [i for i in range(1, 48)
              if i not in EXTERNALLY_DRIVEN and i not in UART_PINS]

DEVICE_PROLOGUE = """
from machine import UART, Pin
import utime
_u = {}
for _n in ('UART1','UART2','UART4'):   # UART3 is the USB CDC port backing the REPL
    try:
        _u[_n] = UART(getattr(UART,_n), 115200, 8, 0, 1, 0)
    except Exception as _e:
        pass
def _drain():
    got = {}
    for k, v in _u.items():
        try:
            n = v.any()
            if n:
                got[k] = bytes(v.read(n))
        except Exception:
            pass
    return got
print('uarts', sorted(_u.keys()))
"""

DEVICE_SWEEP = """
for _pin in %(pins)s:
    _pid = getattr(Pin, 'GPIO%%d' %% _pin, None)
    if _pid is None:
        continue
    for _lvl in (0, 1):
        try:
            _p = Pin(_pid, Pin.OUT, Pin.PULL_DISABLE, _lvl)
        except Exception as _e:
            print('GPIO%%d ERR %%s' %% (_pin, repr(_e)[:40]))
            break
        utime.sleep_ms(%(settle)d)
        _g = _drain()
        if _g:
            print('HIT GPIO%%d level=%%d %%s' %% (_pin, _lvl, _g))
    try:
        Pin(_pid, Pin.IN, Pin.PULL_DISABLE)
    except Exception:
        pass
print('chunk done')
"""


def sweep(settle=1200, chunk=6):
    q = Qpy()
    out, err = q.exec(DEVICE_PROLOGUE, read_for=20)
    lines = [out]
    print(out)
    if err:
        print("prologue err:", err[:300])
    for i in range(0, len(CANDIDATES), chunk):
        pins = CANDIDATES[i:i + chunk]
        code = DEVICE_SWEEP % {"pins": repr(pins), "settle": settle}
        budget = len(pins) * 2 * (settle / 1000.0) + 25
        out, err = q.exec(code, read_for=budget)
        text = out + (("\nERR " + err) if err else "")
        print("pins %s -> %s" % (pins, text.replace("\n", " | ")))
        lines.append("pins %s -> %s" % (pins, text))
    # Always hand the ports back, otherwise a stuck UART wedges the REPL and
    # only a power cycle recovers it.
    q.exec("for _v in _u.values():\n    try:\n        _v.close()\n    except Exception:\n        pass\nprint('uarts closed')", read_for=15)
    q.close()
    return "\n".join(lines)


if __name__ == "__main__":
    report = "=== ESP enable sweep (%s) ===\n%s\n" % (
        time.strftime("%Y-%m-%d %H:%M:%S"), sweep())
    with open("logs/esp_en_sweep.log", "a") as fh:
        fh.write(report)
