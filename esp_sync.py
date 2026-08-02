#!/usr/bin/env python3
"""Speak the ESP8266 ROM loader protocol over the module's UART2.

Evidence says the ESP sits in UART download mode: one banner per power cycle
and then silence, no watchdog loop, regardless of how long the rail is cut.
A bootloader waiting for a flash tool behaves exactly like that.

If so it will answer a SYNC frame. The ROM measures the host's rate from the
0x55 run inside that frame, so 115200 works even though the banner leaves at
74880.

Frame layout (SLIP framed with 0xC0, escaping 0xC0 -> DB DC and 0xDB -> DB DD):

    dir=0x00  cmd=0x08 (SYNC)  size=0x0024  checksum=0
    payload   07 07 12 20  then 32 x 0x55

A reply starts with 0xC0 0x01 0x08, and proves the ESP is reachable for
dumping or reflashing straight through the EC600U - no extra wiring.
"""

import time

from qpy import Qpy
import pinmap

BAUD = 115200


def slip(packet):
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


def sync_frame():
    payload = bytes([0x07, 0x07, 0x12, 0x20]) + b"\x55" * 32
    header = bytes([0x00, 0x08]) + len(payload).to_bytes(2, "little") + \
        (0).to_bytes(4, "little")
    return slip(header + payload)


CODE = """
from machine import UART, Pin
import utime
FRAME = %(frame)r
_u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)
try:
    Pin(Pin.GPIO14, Pin.IN, Pin.PULL_DISABLE)          # keep the rail alive
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)  # power off
    utime.sleep_ms(500)
    try:
        _u.read(_u.any())
    except Exception:
        pass
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)  # power on
    utime.sleep_ms(300)                                # let the ROM settle
    try:
        _u.read(_u.any())                              # drop the 74880 banner
    except Exception:
        pass
    hits = 0
    for _try in range(%(tries)d):
        _u.write(FRAME)
        utime.sleep_ms(120)
        n = _u.any()
        if n:
            r = bytes(_u.read(n))
            if 0xC0 in r:
                hits += 1
                print('REPLY try', _try, r[:80])
            else:
                print('noise  try', _try, r[:40])
    print('slip replies', hits)
finally:
    try:
        _u.close()
    except Exception:
        pass
"""


def main(tries=12):
    q = Qpy()
    try:
        out, err = q.exec(CODE % {
            "frame": sync_frame(), "uart": pinmap.ESP_UART,
            "baud": BAUD, "en": pinmap.ESP_EN, "tries": tries},
            read_for=tries * 0.5 + 30)
    finally:
        q.close()
    return out, err


if __name__ == "__main__":
    frame = sync_frame()
    print("SYNC frame (%d bytes): %s…" % (len(frame), frame[:16].hex()))
    out, err = main()
    for line in (out or "").splitlines():
        print("  " + line[:190])
    if err:
        print("err:", err[:300])
    verdict = ("ESP answered the loader — it is in download mode and can be "
               "dumped or reflashed through UART2"
               if "REPLY" in (out or "") else
               "no SLIP reply; either not in download mode, or the module's TX "
               "does not reach the ESP's U0RXD")
    print("\n" + verdict)
    with open("logs/esp_sync.log", "a") as fh:
        fh.write("=== %s ===\n%s\n%s\n%s\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), out, err, verdict))
