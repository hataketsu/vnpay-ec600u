"""Scan the EC600U UARTs to find which one talks to the ESP.

Two passes per UART:
  passive - open the port and listen without sending, which reveals a log
            stream that the peer emits on its own
  active  - send "AT\r\n" and listen, which reveals an ESP-AT command port

Results are appended to logs/.
"""

import sys
import time

from qpy import Qpy

DEVICE_CODE = """
from machine import UART
import utime
res = []
for name in ('UART1', 'UART2', 'UART3', 'UART4'):
    uid = getattr(UART, name)
    entry = {'uart': name}
    u = None
    try:
        u = UART(uid, %(baud)d, 8, 0, 1, 0)
    except Exception as e:
        entry['open_error'] = repr(e)
        res.append(entry)
        continue
    try:
        # passive listen
        utime.sleep_ms(%(passive_ms)d)
        n = u.any()
        entry['passive_len'] = n
        entry['passive'] = bytes(u.read(n)) if n else b''
        # active probe
        u.write(b'AT\\r\\n')
        utime.sleep_ms(%(active_ms)d)
        n = u.any()
        entry['active_len'] = n
        entry['active'] = bytes(u.read(n)) if n else b''
    except Exception as e:
        entry['probe_error'] = repr(e)
    finally:
        try:
            u.close()
        except Exception:
            pass
    res.append(entry)
for e in res:
    print(e)
"""


def scan(baud=115200, passive_ms=2500, active_ms=1200):
    q = Qpy()
    code = DEVICE_CODE % {
        "baud": baud,
        "passive_ms": passive_ms,
        "active_ms": active_ms,
    }
    out, err = q.exec(code, read_for=(passive_ms + active_ms) * 4 / 1000 + 12)
    q.close()
    return out, err


if __name__ == "__main__":
    baud = int(sys.argv[1]) if len(sys.argv) > 1 else 115200
    out, err = scan(baud)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    report = "=== UART scan @ %d baud  (%s) ===\n%s\n%s\n" % (baud, stamp, out, err)
    print(report)
    with open("logs/uart_scan_%d.log" % baud, "a") as f:
        f.write(report)
