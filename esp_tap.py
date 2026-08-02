"""Read the ESP boot banner through a USB-TTL tap at 74880 baud.

QuecPython's UART only accepts a fixed set of standard baud rates and 74880 is
not among them, so the ESP8285 ROM banner can never be decoded from the
module side. A PL2303 (already present as /dev/ttyUSB0) does accept 74880, so
the banner is read there instead while the EC600U is used only to reset the
ESP via GPIO44.

The banner's "rst cause:N" and "boot mode:(N,M)" fields are what matter:

    rst cause  1 power-on   2 external reset   4 hardware watchdog
    boot mode  (3,x) flash boot   (1,x) UART download mode

Wiring (ESP side is 3.3 V, the module side of the level translator is 1.8 V,
so tap the ESP side):

    PL2303 RX  <-  ESP U0TXD        (or EC600U pin 31, MAIN_RXD)
    PL2303 GND <-> board GND

Do not connect PL2303 TX unless the adapter is confirmed 3.3 V - a 5 V TTL
adapter will damage the ESP.
"""

import sys
import time

import serial

from qpy import Qpy

TAP = "/dev/ttyUSB0"
TAP_BAUD = 74880
ESP_EN = 44

RESET_CODE = """
from machine import Pin
import utime
Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 0)
utime.sleep_ms(400)
Pin(Pin.GPIO%(en)d, Pin.OUT, Pin.PULL_DISABLE, 1)
print('esp reset')
"""


def capture(seconds=8, tap=TAP, baud=TAP_BAUD):
    s = serial.Serial(tap, baud, timeout=0.2)
    s.reset_input_buffer()

    q = Qpy()
    try:
        out, _ = q.exec(RESET_CODE % {"en": ESP_EN}, read_for=15)
        print("module:", out.strip())
    finally:
        q.close()

    buf = b""
    deadline = time.time() + seconds
    while time.time() < deadline:
        chunk = s.read(4096)
        if chunk:
            buf += chunk
    s.close()
    return buf


if __name__ == "__main__":
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 8
    raw = capture(secs)
    text = raw.decode("latin1")
    printable = sum(1 for c in raw if 32 <= c < 127 or c in (10, 13))
    print("captured %d bytes, %d%% printable" % (
        len(raw), (printable * 100 // len(raw)) if raw else 0))
    print("-" * 60)
    print(text)
    print("-" * 60)
    for marker in ("rst cause", "boot mode", "ready", "csum", "flash"):
        if marker in text:
            for line in text.splitlines():
                if marker in line:
                    print("  >>", line.strip())
    with open("logs/esp_tap.log", "a") as fh:
        fh.write("=== %s (%d bytes) ===\n%s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), len(raw), text))
