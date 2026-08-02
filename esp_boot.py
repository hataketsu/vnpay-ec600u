#!/usr/bin/env python3
"""Make the ESP leave download mode and run its firmware, via UART2 only.

The ESP powers up into UART download mode every time and sits there. Rather
than fighting the GPIO0 strap, ask the ROM loader to leave: `FLASH_END` (0x04)
with parameter 0 means "finish and reboot into the application" — this is what
esptool sends after a successful flash.

Nothing here erases or writes. `FLASH_BEGIN` is the command that erases, and
it is deliberately never sent; only SYNC and FLASH_END are used.

Success shows up as clean text on UART2 at 115200: the ROM's divisor assumes a
40 MHz crystal against this board's 26 MHz, so ROM output is garbage at that
rate, while the application fixes the divisor and becomes readable.

    python3 esp_boot.py          # boot it, then listen
    python3 esp_boot.py at       # also poke AT once it is up
"""

import sys
import time

from qpy import Qpy
import pinmap

BAUD = 115200


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

# FLASH_END on its own is refused with status 01/06 and the ROM then panics
# with "ets_main.c". esptool's own run() hits the same thing and works around
# it the same way: flash_begin(0, 0) first, purely to put the ROM into flash
# mode. erase_size 0 and num_blocks 0 mean nothing is erased or written.
FLASH_BEGIN_NOOP = command(0x02, b"".join(x.to_bytes(4, "little") for x in (
    0,      # erase_size - zero, so no sector is touched
    0,      # num_blocks
    1024,   # block_size
    0,      # offset
)))
# parameter 0 == reboot into the application (esptool: int(not reboot))
FLASH_END_REBOOT = command(0x04, (0).to_bytes(4, "little"))


CODE = """
from machine import UART, Pin
import utime
_u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)

def drain():
    try:
        n = _u.any()
        return bytes(_u.read(n)) if n else b''
    except Exception:
        return b''

def clean(b):
    if not b or len(b) < 8:
        return 0
    k = 0
    for c in b:
        if 32 <= c < 127 or c in (10, 13):
            k += 1
    return k * 100 // len(b)

try:
    Pin(Pin.GPIO14, Pin.IN, Pin.PULL_DISABLE)
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)
    utime.sleep_ms(500)
    drain()
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)
    utime.sleep_ms(300)
    print('banner', drain()[:40])

    synced = 0
    for _i in range(8):
        _u.write(%(sync)r)
        utime.sleep_ms(120)
        r = drain()
        if 0xC0 in r:
            synced += 1
    print('synced', synced)

    _u.write(%(flash_begin)r)
    utime.sleep_ms(300)
    print('flash_begin reply', drain()[:60])

    _u.write(%(flash_end)r)
    utime.sleep_ms(200)
    print('flash_end reply', drain()[:60])

    good = 0
    for _i in range(%(ticks)d):
        utime.sleep_ms(100)
        b = drain()
        if b:
            c = clean(b)
            if c >= 85:
                good += len(b)
                print('CLEAN', utime.ticks_ms() %% 100000, b[:130])
            else:
                print('raw  ', len(b), c)
    print('clean total', good)

    if %(poke)s and good:
        for _i in range(4):
            _u.write(b'AT\\r\\n')
            utime.sleep_ms(600)
            b = drain()
            if b:
                print('AT ->', b[:120])
finally:
    try:
        _u.close()
    except Exception:
        pass
"""


def main(seconds=6.0, poke=False):
    q = Qpy()
    try:
        out, err = q.exec(CODE % {
            "uart": pinmap.ESP_UART, "baud": BAUD, "en": pinmap.ESP_EN,
            "sync": SYNC, "flash_begin": FLASH_BEGIN_NOOP,
            "flash_end": FLASH_END_REBOOT,
            "ticks": int(seconds * 10), "poke": "True" if poke else "False",
        }, read_for=seconds + 45)
    finally:
        q.close()
    return out, err


if __name__ == "__main__":
    poke = len(sys.argv) > 1
    out, err = main(poke=poke)
    for line in (out or "").splitlines():
        print("  " + line[:190])
    if err:
        print("err:", err[:300])
    ok = "CLEAN" in (out or "")
    print("\n" + ("firmware is running — UART2 now reads clean text"
                  if ok else
                  "still no firmware output; FLASH_END did not hand over"))
    with open("logs/esp_boot.log", "a") as fh:
        fh.write("=== %s poke=%s ok=%s ===\n%s\n%s\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), poke, ok, out, err))
