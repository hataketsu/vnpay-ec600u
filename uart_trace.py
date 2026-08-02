#!/usr/bin/env python3
"""Trace which EC600U UART is wired to the ESP's U0.

The ESP now flash-boots (`boot mode:(3,7)`, checksums good), so its firmware
is running and should answer AT. This walks every UART the module exposes at
every baud QuecPython accepts, listens passively, then sends `AT`.

UART3 is skipped throughout: it is the USB CDC port the REPL runs on, and
writing to it corrupts the REPL.

Nothing here resets the ESP - it is left running so its firmware keeps
whatever state it reached.
"""

import time

from qpy import Qpy

UARTS = ("UART1", "UART2", "UART4")
BAUDS = (115200, 9600, 57600, 38400, 19200, 230400, 460800, 921600)

CODE = """
from machine import UART
import utime
try:
    _u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)
except Exception as e:
    print('%(uart)s %(baud)d OPEN-FAIL', repr(e)[:50])
else:
    try:
        utime.sleep_ms(600)
        n = _u.any()
        passive = bytes(_u.read(n)) if n else b''
        _u.write(b'AT\\r\\n')
        utime.sleep_ms(1200)
        n = _u.any()
        active = bytes(_u.read(n)) if n else b''
        def sc(b):
            if not b:
                return 0
            k = 0
            for c in b:
                if 32 <= c < 127 or c in (10, 13):
                    k += 1
            return k * 100 // len(b)
        print('%(uart)s %(baud)d passive=%%d/%%d%%%% active=%%d/%%d%%%%'
              %% (len(passive), sc(passive), len(active), sc(active)))
        if passive:
            print('  P', passive[:110])
        if active:
            print('  A', active[:110])
    finally:
        try:
            _u.close()
        except Exception:
            pass
"""


def main():
    q = Qpy()
    best = []
    try:
        for uart in UARTS:
            for baud in BAUDS:
                out, err = q.exec(CODE % {"uart": uart, "baud": baud},
                                  read_for=20)
                text = (out or "") + (err or "")
                for line in text.splitlines():
                    print("  " + line[:170])
                if "OPEN-FAIL" in text:
                    break
                # Flag anything that decoded as mostly text.
                for line in text.splitlines():
                    if "active=" in line:
                        try:
                            a = line.split("active=")[1]
                            n, pct = a.split("/")[0], a.split("/")[1].rstrip("%")
                            if int(n) > 0 and int(pct) >= 70:
                                best.append((uart, baud, int(n), int(pct)))
                        except Exception:
                            pass
                with open("logs/uart_trace.log", "a") as fh:
                    fh.write(text + "\n")
    finally:
        q.close()

    print("\n" + "=" * 60)
    if best:
        for uart, baud, n, pct in best:
            print("%s @ %d answered with %d bytes, %d%% printable" %
                  (uart, baud, n, pct))
    else:
        print("no UART returned readable text; the ESP link is most likely at "
              "74880, which QuecPython cannot select")


if __name__ == "__main__":
    with open("logs/uart_trace.log", "a") as fh:
        fh.write("=== uart trace %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
    main()
