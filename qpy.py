"""Raw-REPL driver for the VNPay EC600U board.

The module exposes a MicroPython REPL on interface 1.8 (/dev/ttyUSB7).
Raw REPL (ctrl-A) is used instead of the friendly REPL so that output is
framed and does not have to be scraped out of echoed input.
"""

import glob
import os

import serial

import time

BAUD = 115200

# The REPL lives on USB interface .8 of the Quectel device. Port numbering
# shifts every time the module re-enumerates, so resolve it through sysfs
# rather than hard-coding a /dev/ttyUSBn.
REPL_INTERFACE = 8
VID, PID = "2c7c", "0901"


def find_repl_port():
    for iface in glob.glob("/sys/bus/usb/devices/*:*.%d" % REPL_INTERFACE):
        dev = os.path.dirname(iface) + "/" + iface.split("/")[-1].split(":")[0]
        try:
            vid = open(os.path.join(dev, "idVendor")).read().strip()
            pid = open(os.path.join(dev, "idProduct")).read().strip()
        except Exception:
            continue
        if (vid, pid) != (VID, PID):
            continue
        for entry in os.listdir(iface):
            if entry.startswith("ttyUSB"):
                return "/dev/" + entry
    # Returning a guess here only produces a confusing "no such file" later.
    raise OSError("module %s:%s not found on USB - check it is plugged in"
                  % (VID, PID))


try:
    REPL_PORT = find_repl_port()
except OSError:
    REPL_PORT = None


class Qpy:
    def __init__(self, port=None, baud=BAUD, timeout=0.4):
        # Resolved per connection, not at import: the ttyUSB numbering shifts
        # whenever anything else is plugged in, and a module-level constant
        # goes stale the moment that happens.
        port = port or find_repl_port()
        self.s = serial.Serial(port, baud, timeout=timeout)
        self._enter_raw()

    def _enter_raw(self):
        self.s.write(b"\r\x03\x03")
        self.s.flush()
        time.sleep(0.3)
        self.s.reset_input_buffer()
        self.s.write(b"\r\x01")
        self.s.flush()
        time.sleep(0.3)
        self.s.read(4096)

    def exec(self, code, wait=0.0, read_for=None):
        """Run code in the raw REPL and return (stdout, stderr)."""
        self.s.reset_input_buffer()
        self.s.write(code.encode() + b"\x04")
        self.s.flush()
        deadline = time.time() + (read_for if read_for else 15)
        buf = b""
        while time.time() < deadline:
            chunk = self.s.read(4096)
            if chunk:
                buf += chunk
                if buf.count(b"\x04") >= 2:
                    break
            elif buf:
                time.sleep(0.05)
        if wait:
            time.sleep(wait)
        body = buf.split(b"OK", 1)[-1] if buf.startswith(b"OK") else buf
        parts = body.split(b"\x04")
        out = parts[0].decode(errors="replace") if parts else ""
        err = parts[1].decode(errors="replace") if len(parts) > 1 else ""
        return out.strip(), err.strip()

    def close(self):
        try:
            self.s.write(b"\x02")  # back to friendly REPL
            self.s.flush()
        except Exception:
            pass
        self.s.close()


if __name__ == "__main__":
    q = Qpy()
    print(q.exec("import uos; print(uos.uname())")[0])
    q.close()
