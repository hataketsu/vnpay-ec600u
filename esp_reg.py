#!/usr/bin/env python3
"""Read ESP registers through the ROM loader over the module's UART2.

SYNC already works, so the loader is reachable. READ_REG (0x0A) is the other
command the bare ROM supports without uploading a stub, and it reads any
memory-mapped address — enough to pull the eFuse block and derive the MAC,
which confirms the part and gives a value that can be checked against the
sticker or a WiFi scan.

    eFuse block: 0x3FF00050, 0x3FF00054, 0x3FF00058, 0x3FF0005C

Note the bare ESP8266 ROM has no read-flash command; dumping the flash needs
esptool's RAM stub, which is why a full dump is better done with a USB-TTL
adapter wired straight to the test pads.
"""

import time

from qpy import Qpy
import pinmap

BAUD = 115200
EFUSE = (0x3FF00050, 0x3FF00054, 0x3FF00058, 0x3FF0005C)


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


def slip_frames(raw):
    """Yield the payload of each complete SLIP frame in raw."""
    frames, cur, inside = [], bytearray(), False
    i = 0
    while i < len(raw):
        b = raw[i]
        if b == 0xC0:
            if inside and cur:
                frames.append(bytes(cur))
            cur, inside = bytearray(), True
        elif inside:
            if b == 0xDB and i + 1 < len(raw):
                nxt = raw[i + 1]
                cur.append(0xC0 if nxt == 0xDC else 0xDB if nxt == 0xDD else nxt)
                i += 1
            else:
                cur.append(b)
        i += 1
    return frames


def command(op, payload=b""):
    header = bytes([0x00, op]) + len(payload).to_bytes(2, "little") + \
        (0).to_bytes(4, "little")
    return slip_encode(header + payload)


SYNC = command(0x08, bytes([0x07, 0x07, 0x12, 0x20]) + b"\x55" * 32)


CODE = """
from machine import UART, Pin
import utime
_u = UART(UART.%(uart)s, %(baud)d, 8, 0, 1, 0)
try:
    Pin(Pin.GPIO14, Pin.IN, Pin.PULL_DISABLE)
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)
    utime.sleep_ms(500)
    try:
        _u.read(_u.any())
    except Exception:
        pass
    Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)
    utime.sleep_ms(300)
    try:
        _u.read(_u.any())
    except Exception:
        pass
    for _i in range(6):                 # sync also sets the ROM's baud
        _u.write(%(sync)r)
        utime.sleep_ms(100)
    try:
        _u.read(_u.any())
    except Exception:
        pass
    for _name, _cmd in %(cmds)r:
        _u.write(_cmd)
        utime.sleep_ms(250)
        n = _u.any()
        print(_name, bytes(_u.read(n)) if n else b'')
finally:
    try:
        _u.close()
    except Exception:
        pass
"""


def decode_reg(raw):
    """Pull the 4-byte value field out of a READ_REG response."""
    for f in slip_frames(raw):
        if len(f) >= 8 and f[0] == 0x01 and f[1] == 0x0A:
            return int.from_bytes(f[4:8], "little")
    return None


def mac_from_efuse(e):
    """ESP8266 MAC derivation, as esptool does it."""
    mac0, mac1, mac2, mac3 = e
    if mac3 != 0:
        oui = ((mac3 >> 16) & 0xFF, (mac3 >> 8) & 0xFF, mac3 & 0xFF)
    elif ((mac1 >> 16) & 0xFF) == 0:
        oui = (0x18, 0xFE, 0x34)
    elif ((mac1 >> 16) & 0xFF) == 1:
        oui = (0xAC, 0xD0, 0x74)
    else:
        return None
    return oui + ((mac1 >> 8) & 0xFF, mac1 & 0xFF, (mac0 >> 24) & 0xFF)


def main():
    cmds = [("EFUSE%d" % i, command(0x0A, a.to_bytes(4, "little")))
            for i, a in enumerate(EFUSE)]
    q = Qpy()
    try:
        out, err = q.exec(CODE % {
            "uart": pinmap.ESP_UART, "baud": BAUD, "en": pinmap.ESP_EN,
            "sync": SYNC, "cmds": cmds}, read_for=45)
    finally:
        q.close()
    return out, err


if __name__ == "__main__":
    out, err = main()
    values = []
    for line in (out or "").splitlines():
        if not line.startswith("EFUSE"):
            continue
        name, _, rest = line.partition(" ")
        try:
            raw = eval(rest, {"__builtins__": {}})
        except Exception:
            raw = b""
        val = decode_reg(raw) if isinstance(raw, bytes) else None
        values.append(val)
        print("%s = %s" % (name, "0x%08x" % val if val is not None else "no reply"))
    if err:
        print("err:", err[:250])

    if len(values) == 4 and all(v is not None for v in values):
        mac = mac_from_efuse(values)
        if mac:
            print("\nESP MAC: " + ":".join("%02x" % b for b in mac))
        print("READ_REG works, so the loader is usable beyond SYNC.")
    else:
        print("\nREAD_REG did not return all four registers.")
    with open("logs/esp_reg.log", "a") as fh:
        fh.write("=== %s ===\n%s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                           out, err))
