#!/usr/bin/env python3
"""Find the EC600U pin that holds the ESP's GPIO0 strap low.

The ESP prints `boot mode:(1,7)` — UART download mode — on every reset, which
means its GPIO0 is being held low. Flash boot needs `boot mode:(3,x)`.

This reads the real banner through the PL2303 tap at 74880 and checks the boot
mode the ROM reports directly, rather than inferring it.

Note: an earlier sweep scored printable ASCII at 115200 and found nothing, and
that result was dismissed here as meaningless on the grounds that the ESP
always talks 74880. **That dismissal was wrong.** The ROM emits 74880, but a
successful flash boot makes the application fix the divisor to a true 115200,
so readable text at 115200 is exactly the signal a strap change would produce.
That sweep covered all 47 GPIOs at both levels and its negative result
stands.

Requires the U0TXD tap wired to /dev/ttyUSB0 and the panel stopped, since only
one process can own the module's REPL.
"""

import time

import serial

import pinmap
from qpy import Qpy

TAP = "/dev/ttyUSB0"
TAP_BAUD = 74880

EXTERNALLY_DRIVEN = set(pinmap.EXTERNALLY_DRIVEN)
SKIP = EXTERNALLY_DRIVEN | {pinmap.ESP_EN}
CANDIDATES = [g for g in sorted(pinmap.PINS) if g not in SKIP]


def reset_and_read(q, tap, settle=0.35, listen=1.6):
    """Power-cycle the ESP and return whatever banner it prints."""
    q.exec("from machine import Pin\nimport utime\n"
           "Pin(Pin.GPIO{0}, Pin.OUT, Pin.PULL_DISABLE, 0)".format(pinmap.ESP_EN),
           read_for=8)
    time.sleep(settle)
    tap.reset_input_buffer()
    q.exec("Pin(Pin.GPIO{0}, Pin.OUT, Pin.PULL_DISABLE, 1)".format(pinmap.ESP_EN),
           read_for=8)
    buf = b""
    end = time.time() + listen
    while time.time() < end:
        c = tap.read(4096)
        if c:
            buf += c
    return buf.decode("latin1")


def boot_mode(text):
    if "boot mode:(" not in text:
        return None
    return text.split("boot mode:(")[1].split(",")[0].strip()


def main():
    tap = serial.Serial(TAP, TAP_BAUD, timeout=0.15)
    q = Qpy()
    hits = []
    try:
        base = reset_and_read(q, tap)
        print("baseline boot mode:", boot_mode(base), "|", base.strip()[:60])

        for gpio in CANDIDATES:
            for level in (1, 0):
                try:
                    q.exec("from machine import Pin\n"
                           "Pin(Pin.GPIO%d, Pin.OUT, Pin.PULL_DISABLE, %d)"
                           % (gpio, level), read_for=8)
                except Exception as exc:
                    print("GPIO%-3d error %s" % (gpio, exc))
                    continue
                text = reset_and_read(q, tap)
                mode = boot_mode(text)
                mark = ""
                if mode == "3":
                    mark = "   <<<< FLASH BOOT"
                    hits.append((gpio, level))
                print("GPIO%-3d lvl=%d  boot mode=%s%s"
                      % (gpio, level, mode or "?", mark))
                with open("logs/strap74880.log", "a") as fh:
                    fh.write("GPIO%d lvl=%d mode=%s %r\n"
                             % (gpio, level, mode, text[:120]))
            try:
                q.exec("from machine import Pin\n"
                       "Pin(Pin.GPIO%d, Pin.IN, Pin.PULL_DISABLE)" % gpio,
                       read_for=8)
            except Exception:
                pass
    finally:
        tap.close()
        q.close()

    print("\n" + "=" * 56)
    if hits:
        for gpio, level in hits:
            pin = pinmap.PINS[gpio][0]
            print("GPIO%d (module pin %d) at %s releases the strap -> flash boot"
                  % (gpio, pin, "HIGH" if level else "LOW"))
    else:
        print("no EC600U pin changed the boot mode; GPIO0 is most likely tied "
              "low by a resistor on the PCB rather than driven by the module")


if __name__ == "__main__":
    with open("logs/strap74880.log", "a") as fh:
        fh.write("=== strap sweep @74880 %s ===\n"
                 % time.strftime("%Y-%m-%d %H:%M:%S"))
    main()
