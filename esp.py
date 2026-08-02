#!/usr/bin/env python3
"""Driver for the board's ESP8285, over the EC600U's UART2. No extra wiring.

The ESP powers up into UART download mode every time — the GPIO0 strap is held
low by the board and no module pin overrides it. Rather than fight that, this
asks the ROM loader to hand over to the application, which is exactly what
esptool's `run` does:

    power-cycle via GPIO44  (it switches the ESP's 3V3 rail)
    SYNC                    (also sets the ROM's baud from the 0x55 run)
    FLASH_BEGIN 0,0         (no erase, no write - only enters flash mode;
                             FLASH_END alone is refused 01/06 and panics)
    FLASH_END 0             (reboot into the application)

After that the app prints `ready` and answers AT at a true 115200. The ROM's
own output is 74880, because its divisor assumes a 40 MHz crystal while this
board has 26 MHz.

    python3 esp.py                       # boot, then report firmware + state
    python3 esp.py "AT+CWLAP"            # boot, then run one command
    python3 esp.py "AT+CWMODE=1" "AT+CWJAP=\\"ssid\\",\\"pass\\""
"""

import sys
import time

from qpy import Qpy
import pinmap

BAUD = 115200
DEFAULT_CMDS = ("AT+GMR", "AT+CWMODE?", "AT+CIPSTAMAC?", "AT+CWSTATE?")


def slip_encode(packet):
    out = bytearray([0xC0])
    for b in packet:
        if b == 0xC0:
            out += b"\xdb\xdc"
        elif b == 0xDB:
            out += b"\xdb\xdd"
        else:
            out.append(b)
    out.append(0xC0)
    return bytes(out)


def command(op, payload=b""):
    header = bytes([0x00, op]) + len(payload).to_bytes(2, "little") + \
        (0).to_bytes(4, "little")
    return slip_encode(header + payload)


SYNC = command(0x08, bytes([0x07, 0x07, 0x12, 0x20]) + b"\x55" * 32)
FLASH_BEGIN_NOOP = command(0x02, b"".join(
    x.to_bytes(4, "little") for x in (0, 0, 1024, 0)))
FLASH_END_REBOOT = command(0x04, (0).to_bytes(4, "little"))

BOOT = """
from machine import UART, Pin
import utime
_u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)

def _drain():
    try:
        n = _u.any()
        return bytes(_u.read(n)) if n else b''
    except Exception:
        return b''

def _power_cycle():
    Pin(Pin.GPIO14, Pin.IN, Pin.PULL_DISABLE)
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)
    utime.sleep_ms(700)
    _drain()
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)

def esp_boot():
    # GPIO26 (pin 50, AP_READY) is the ESP's boot-mode strap on this board.
    # Held LOW the ESP flash-boots on its own; high or floating it lands in
    # UART download mode. QuecPython leaves it floating, which is the only
    # reason the ROM handover below was ever needed.
    Pin(Pin.GPIO26, Pin.OUT, Pin.PULL_DISABLE, 0)
    _power_cycle()
    out = b''
    for _i in range(40):
        utime.sleep_ms(50)
        out += _drain()
        if b'ready' in out:
            return out

    # Fallback: ask the ROM loader to hand over, the way esptool's run() does.
    # flash_begin with erase_size 0 erases nothing; it only enters flash mode,
    # without which flash_end is refused 01/06 and the ROM panics.
    _power_cycle()
    utime.sleep_ms(300)
    _drain()
    for _i in range(8):
        _u.write(%(sync)r)
        utime.sleep_ms(120)
        _drain()
    _u.write(%(fbegin)r)
    utime.sleep_ms(300)
    _drain()
    _u.write(%(fend)r)
    for _i in range(30):
        utime.sleep_ms(100)
        out += _drain()
        if b'ready' in out:
            break
    return out

def esp_cmd(c, wait=1500):
    _drain()
    _u.write(c + b'\\r\\n')
    utime.sleep_ms(wait)
    return _drain()

print('READY' if b'ready' in esp_boot() else 'NO-READY')
"""

RUN = """
for _c in %(cmds)r:
    print('>', _c)
    print('<', esp_cmd(_c, %(wait)d))
"""

CLOSE = """
try:
    _u.close()
except Exception:
    pass
print('closed')
"""


def run(cmds, wait=1500):
    q = Qpy()
    try:
        out, err = q.exec(BOOT % {
            "uart": pinmap.ESP_UART, "baud": BAUD, "en": pinmap.ESP_EN,
            "sync": SYNC, "fbegin": FLASH_BEGIN_NOOP, "fend": FLASH_END_REBOOT,
        }, read_for=40)
        booted = "READY" in (out or "")
        print("boot:", "firmware up" if booted else "did not reach firmware",
              (err[:150] if err else ""))
        if not booted:
            return booted, ""
        out, err = q.exec(RUN % {"cmds": [c.encode() for c in cmds],
                                 "wait": wait},
                          read_for=len(cmds) * (wait / 1000.0) + 30)
        return booted, out + (("\n" + err) if err else "")
    finally:
        try:
            q.exec(CLOSE, read_for=10)
        except Exception:
            pass
        q.close()


if __name__ == "__main__":
    cmds = sys.argv[1:] or list(DEFAULT_CMDS)
    booted, out = run(cmds)
    for line in (out or "").splitlines():
        print("  " + line[:220])
    with open("logs/esp.log", "a") as fh:
        fh.write("=== %s booted=%s ===\n%s\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), booted, out))
