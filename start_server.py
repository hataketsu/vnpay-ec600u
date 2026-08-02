#!/usr/bin/env python3
"""Start the on-module web server and let go of the serial line.

`serve()` never returns, so it cannot be run through the usual exec-and-wait
helper. `_thread.start_new_thread` was tried first and produced no output and
no listener, and this firmware does not autorun `/usr/main.py`, so the working
approach is to hand the code to the raw REPL and simply close the port - the
module keeps executing on its own.

    python3 start_server.py
"""

import time

import serial

import qpy

CODE = (
    "import usys\n"
    "if '/usr' not in usys.path: usys.path.append('/usr')\n"
    "import esp_web\n"
    "esp_web.serve()\n"
)


def start(port=None):
    port = port or qpy.REPL_PORT
    s = serial.Serial(port, qpy.BAUD, timeout=0.4)
    try:
        s.write(b"\r\x03\x03")          # interrupt anything running
        s.flush()
        time.sleep(0.4)
        s.reset_input_buffer()
        s.write(b"\r\x01")              # raw REPL
        s.flush()
        time.sleep(0.4)
        s.read(4096)
        s.write(CODE.encode() + b"\x04")
        s.flush()
        time.sleep(1.0)
        print("handed off to", port, "- closing the port, the module keeps running")
    finally:
        s.close()


if __name__ == "__main__":
    start()
