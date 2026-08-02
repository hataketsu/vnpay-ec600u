#!/usr/bin/env python3
"""Identify the SPI NOR flash on this board.

The EC600U's `spi_0` sits on module pins 1/4/3/2 = GPIO10 (clk), GPIO11 (cs),
GPIO12 (dio), GPIO13 (di). Those are the same module pins the EC600M board used
for its 25LQ128 NOR flash, so that is where this one should be too. All four
read floating in the hi-Z survey, which is what an idle SPI bus looks like.

Reads the JEDEC ID (command 0x9F): the reply is manufacturer, memory type, and
capacity, where capacity is a power-of-two exponent — 0x18 means 2^24 = 16 MB.
All 0x00 or all 0xFF means nothing answered.

    python3 spi_scan.py
"""

import time

from qpy import Qpy

# JEDEC manufacturer IDs likely on a board like this.
VENDORS = {
    0xEF: "Winbond", 0xC8: "GigaDevice", 0x1C: "Eon", 0x20: "Micron/XMC",
    0xC2: "Macronix", 0x9D: "ISSI", 0x01: "Spansion", 0xBF: "SST",
    0x0B: "XTX", 0x68: "Boya", 0x5E: "Zbit", 0xA1: "Fudan",
}

PROBE = """
from machine import SPI
import utime
res = []
for port in (0, 1):
    for mode in (0, 3):
        for clk in range(0, 6):
            try:
                s = SPI(port, mode, clk)
            except Exception as e:
                res.append((port, mode, clk, 'open:' + repr(e)[:26]))
                continue
            try:
                r = bytearray(4)
                s.write_read(r, bytearray(b'\\x9f\\x00\\x00\\x00'), 4)
                res.append((port, mode, clk, bytes(r)))
            except Exception as e:
                res.append((port, mode, clk, 'io:' + repr(e)[:26]))
            try:
                s.close()
            except Exception:
                pass
            utime.sleep_ms(30)
for r in res:
    print(r)
"""


def decode(raw):
    """JEDEC reply is echoed one byte late: [junk, mfr, type, capacity]."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 4:
        return None
    mfr, typ, cap = raw[1], raw[2], raw[3]
    if mfr in (0x00, 0xFF) or cap in (0x00, 0xFF):
        return None
    size = 1 << cap if 16 <= cap <= 27 else None
    return (VENDORS.get(mfr, "unknown 0x%02x" % mfr), typ, cap, size)


if __name__ == "__main__":
    q = Qpy()
    try:
        out, err = q.exec(PROBE, read_for=60)
    finally:
        q.close()

    found = []
    for line in (out or "").splitlines():
        line = line.strip()
        if not line.startswith("("):
            continue
        try:
            port, mode, clk, raw = eval(line, {"__builtins__": {}})
        except Exception:
            print("  ?", line[:120])
            continue
        d = decode(raw) if not isinstance(raw, str) else None
        mark = ""
        if d:
            vendor, typ, cap, size = d
            mark = "   <<< %s, type 0x%02x, capacity 0x%02x%s" % (
                vendor, typ, cap,
                (" = %d MB" % (size // 1048576)) if size else "")
            found.append((port, mode, clk, raw, d))
        print("  SPI%d mode%d clk%d -> %s%s"
              % (port, mode, clk,
                 raw if isinstance(raw, str) else raw.hex(), mark))
    if err:
        print("err:", err[:200])

    print("\n" + "=" * 58)
    if found:
        port, mode, clk, raw, (vendor, typ, cap, size) = found[0]
        print("NOR flash answers on SPI%d, mode %d, clk %d" % (port, mode, clk))
        print("  JEDEC %s -> %s, %s" % (
            raw.hex(), vendor,
            ("%d MB" % (size // 1048576)) if size else "size 0x%02x" % cap))
    else:
        print("nothing answered - either the flash is on the other SPI port, "
              "needs a different mode/clock, or its CS is not the one SPI0 "
              "drives")
    with open("logs/spi_scan.log", "a") as fh:
        fh.write("=== %s ===\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), out))
