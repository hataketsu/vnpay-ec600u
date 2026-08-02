#!/usr/bin/env python3
"""Listen to the ESP8285 debug UART through the board's test pads.

The ESP re-boots every 2 s on its own (hardware watchdog), so nothing has to
be reset - just connect and a banner arrives within a couple of seconds.

Wiring, ESP side is 3.3 V:

    PL2303 RX  <-  U0TXD test pad
    PL2303 GND <-> board GND

The EC600U must be holding GPIO44 high so the ESP is powered; use the panel's
"Reset ESP" button, or run esp_at.py once, before listening.

This script deliberately does not touch the module's REPL, so it can run while
gpio_panel.py is up.

    python3 esp_listen.py              # 74880, the 26 MHz-crystal ROM rate
    python3 esp_listen.py 115200 20    # other baud, 20 seconds
"""

import sys
import time

import serial

PORT = "/dev/ttyUSB0"
BAUD = 74880

# What the ESP8266/8285 ROM tells you in its banner.
RST_CAUSE = {
    "0": "power-on",
    "1": "hardware watchdog",
    "2": "exception / soft restart",
    "3": "software watchdog",
    "4": "soft restart",
    "5": "deep-sleep wake",
    "6": "external reset",
}
BOOT_MODE = {
    "1": "UART download mode (bootloader waiting for a flash tool)",
    "3": "flash boot (normal)",
}


def explain(text):
    hits = []
    for line in text.splitlines():
        s = line.strip()
        if "rst cause" in s or "boot mode" in s:
            hits.append(s)
            if "rst cause:" in s:
                n = s.split("rst cause:")[1].split(",")[0].strip()
                hits.append("    rst cause %s = %s" % (n, RST_CAUSE.get(n, "?")))
            if "boot mode:(" in s:
                n = s.split("boot mode:(")[1].split(",")[0].strip()
                hits.append("    boot mode %s = %s" % (n, BOOT_MODE.get(n, "?")))
        elif any(k in s for k in ("csum err", "flash read err", "ets_main.c",
                                  "ready", "Fatal exception", "wdt reset")):
            hits.append(s)
    return hits


def listen(port=PORT, baud=BAUD, seconds=10):
    s = serial.Serial(port, baud, timeout=0.2)
    s.reset_input_buffer()
    buf = b""
    deadline = time.time() + seconds
    while time.time() < deadline:
        chunk = s.read(4096)
        if chunk:
            buf += chunk
    s.close()
    return buf


if __name__ == "__main__":
    baud = int(sys.argv[1]) if len(sys.argv) > 1 else BAUD
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 10
    print("listening on %s @ %d for %g s …" % (PORT, baud, secs))
    raw = listen(PORT, baud, secs)
    text = raw.decode("latin1")
    printable = sum(1 for c in raw if 32 <= c < 127 or c in (10, 13))
    pct = (printable * 100 // len(raw)) if raw else 0
    print("%d bytes, %d%% printable\n%s" % (len(raw), pct, "-" * 62))
    print(text)
    print("-" * 62)
    hits = explain(text)
    if hits:
        print("decoded:")
        for h in hits:
            print("  " + h)
    elif pct < 60:
        print("still garbage - wrong baud, or the pad is on the 1.8 V module "
              "side rather than the 3.3 V ESP side.")
    with open("logs/esp_listen.log", "a") as fh:
        fh.write("=== %s @%d (%d bytes, %d%% printable) ===\n%s\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), baud, len(raw), pct, text))
