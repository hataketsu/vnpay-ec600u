"""Raw-REPL driver for the VNPay EC600U board.

The module exposes a MicroPython REPL on USB interface .8. Raw REPL (ctrl-A)
is used instead of the friendly REPL so that output is framed and does not
have to be scraped out of echoed input.

Two transports, picked by platform:

* Linux binds its `option` driver to the module's vendor-specific interfaces,
  so interface .8 shows up as a /dev/ttyUSBn and pyserial opens it.
* macOS has no driver for interface class 0xFF, so no /dev/cu.* is ever
  created. Those interfaces are left unclaimed, though, which means libusb
  can take interface .8 directly and speak the same protocol over its bulk
  endpoint pair. Needs pyusb; no kext and no SIP changes.
"""

import glob
import os
import sys

import time

BAUD = 115200

# The REPL lives on USB interface .8 of the Quectel device. Port numbering
# shifts every time the module re-enumerates, so resolve it through sysfs
# rather than hard-coding a /dev/ttyUSBn.
REPL_INTERFACE = 8
VID, PID = "2c7c", "0901"
VID_INT, PID_INT = int(VID, 16), int(PID, 16)

USE_LIBUSB = sys.platform == "darwin"


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


# Kept for the scripts that open a tty themselves. There is no device node
# under the libusb transport, so it stays None there.
try:
    REPL_PORT = None if USE_LIBUSB else find_repl_port()
except OSError:
    REPL_PORT = None


class UsbRawTransport:
    """pyserial-shaped wrapper around interface .8's bulk endpoints.

    Only the handful of methods Qpy uses are implemented. Unlike the ttyUSB
    numbering on Linux, the USB interface number is fixed, so there is
    nothing to re-resolve between connections.
    """

    def __init__(self, timeout=0.4, interface=REPL_INTERFACE):
        import usb.core
        import usb.util

        self._util = usb.util
        self._core = usb.core
        self.timeout = timeout
        self.interface = interface

        self.dev = usb.core.find(idVendor=VID_INT, idProduct=PID_INT)
        if self.dev is None:
            raise OSError("module %s:%s not found on USB - check it is "
                          "plugged in" % (VID, PID))

        intf = self.dev.get_active_configuration()[(interface, 0)]
        usb.util.claim_interface(self.dev, interface)

        def _dir(want):
            return usb.util.find_descriptor(
                intf, custom_match=lambda e: usb.util.endpoint_direction(
                    e.bEndpointAddress) == want)

        self.ep_out = _dir(usb.util.ENDPOINT_OUT)
        self.ep_in = _dir(usb.util.ENDPOINT_IN)
        if self.ep_out is None or self.ep_in is None:
            usb.util.release_interface(self.dev, interface)
            raise OSError("interface .%d has no bulk pair" % interface)

    def write(self, data):
        return self.ep_out.write(data, timeout=2000)

    def flush(self):
        pass                      # bulk writes are not buffered host-side

    def read(self, size=4096):
        try:
            return bytes(self.ep_in.read(size, timeout=int(self.timeout * 1000)))
        except self._core.USBTimeoutError:
            return b""

    def reset_input_buffer(self):
        # No host-side buffer to clear; drain whatever the module has queued
        # so a stale reply cannot be mistaken for the next one.
        while self.read(4096):
            pass

    def close(self):
        try:
            self._util.release_interface(self.dev, self.interface)
        finally:
            self._util.dispose_resources(self.dev)


class Qpy:
    def __init__(self, port=None, baud=BAUD, timeout=0.4):
        if USE_LIBUSB:
            self.s = UsbRawTransport(timeout=timeout)
        else:
            # Resolved per connection, not at import: the ttyUSB numbering
            # shifts whenever anything else is plugged in, and a module-level
            # constant goes stale the moment that happens.
            import serial
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
