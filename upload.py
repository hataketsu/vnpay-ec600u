#!/usr/bin/env python3
"""Push a file to the module's filesystem through the raw REPL.

The REPL is a text channel, so the payload is sent as base64 in modest chunks
and reassembled on the device. Chunks are kept small because each one is a
separate REPL round-trip and the module's line buffer is not large.

    python3 upload.py onboard/esp_web.py            # -> /usr/esp_web.py
    python3 upload.py onboard/esp_web.py main.py    # -> /usr/main.py (autostart)
    python3 upload.py wifi                          # -> /usr/wifi.txt
"""

import base64
import os
import sys

from qpy import Qpy

CHUNK = 480          # base64 characters per REPL round-trip
DEST_DIR = "/usr/"


def upload(local, remote=None, chunk=CHUNK):
    remote = remote or os.path.basename(local)
    path = DEST_DIR + remote
    data = open(local, "rb").read()
    b64 = base64.b64encode(data).decode()

    q = Qpy()
    try:
        out, err = q.exec(
            "import ubinascii\n"
            "_f = open(%r, 'wb')\n"
            "print('open ok')" % path, read_for=15)
        if err:
            raise RuntimeError("could not open %s: %s" % (path, err[:200]))

        sent = 0
        for i in range(0, len(b64), chunk):
            part = b64[i:i + chunk]
            out, err = q.exec(
                "_f.write(ubinascii.a2b_base64(%r))\n"
                "print(%d)" % (part, i + len(part)), read_for=20)
            if err:
                raise RuntimeError("chunk at %d failed: %s" % (i, err[:200]))
            sent = i + len(part)
            pct = sent * 100 // len(b64)
            sys.stdout.write("\r  %s  %d%%  (%d/%d b64 chars)"
                             % (remote, pct, sent, len(b64)))
            sys.stdout.flush()
        print()

        out, err = q.exec(
            "_f.close()\n"
            "import uos\n"
            "print('size', uos.stat(%r)[6])" % path, read_for=15)
        print("  device says:", (out or err).strip()[:120])
        return path
    finally:
        q.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    if sys.argv[1] == "wifi":
        # Credentials are pushed as a file rather than compiled into
        # esp_web.py, which is committed.
        try:
            from wifi_config import SSID, PASSWORD
        except ImportError:
            raise SystemExit("copy wifi_config.example.py to wifi_config.py "
                             "and put your network in it")
        tmp = "/tmp/wifi.txt"
        open(tmp, "w").write("%s\n%s\n" % (SSID, PASSWORD))
        print("writing /usr/wifi.txt for SSID %r" % SSID)
        print("done ->", upload(tmp, "wifi.txt"))
        raise SystemExit(0)

    local = sys.argv[1]
    remote = sys.argv[2] if len(sys.argv) > 2 else None
    print("uploading %s (%d bytes)" % (local, os.path.getsize(local)))
    path = upload(local, remote)
    print("done ->", path)
