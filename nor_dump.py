#!/usr/bin/env python3
"""Dump the whole 16 MB SPI NOR to the laptop before anything erases it.

The chip came with a vendor filesystem on it (`FILETMCL` at offset 0, every
64 KB block non-blank) and no backup exists, so this has to run before
`nor_format.py`.

Chunk size matters a lot, because each chunk is one REPL round-trip:

    4 KB    8.9 KB/s
    16 KB  27.6 KB/s
    32 KB  42.0 KB/s
    64 KB  56.4 KB/s
    128 KB 70.1 KB/s   <- about 4 minutes for the full 16 MB

Resumable: it appends to the output file and restarts from whatever is already
there, so a broken run can just be re-run.

    python3 nor_dump.py                  # dump everything, resuming if partial
    python3 nor_dump.py --verify         # only re-check an existing dump
"""

import base64
import os
import sys
import time

from qpy import Qpy

SIZE = 16 * 1024 * 1024
CHUNK = 128 * 1024
OUT = "nor_backup.bin"

SETUP = """
import usys
if '/usr' not in usys.path: usys.path.append('/usr')
import nor, ubinascii, gc
d = nor.NorFlash()
print('jedec', ['0x%02x' % x for x in d.jedec()], 'blocks', d.blocks)
"""

READ = """
gc.collect()
print(ubinascii.b2a_base64(d.read(%d, %d)).decode().strip())
"""


def fetch(q, addr, n):
    out, err = q.exec(READ % (addr, n), read_for=90)
    if err:
        raise RuntimeError("device error at 0x%x: %s" % (addr, err[:120]))
    line = (out or "").strip().splitlines()[-1] if out else ""
    data = base64.b64decode(line)
    if len(data) != n:
        raise RuntimeError("short read at 0x%x: got %d of %d"
                           % (addr, len(data), n))
    return data


def dump(q):
    done = os.path.getsize(OUT) if os.path.exists(OUT) else 0
    if done:
        done -= done % CHUNK          # restart at a clean chunk boundary
        print("resuming at %d MB" % (done // 1048576))
    fh = open(OUT, "r+b" if done else "wb")
    fh.seek(done)
    t0 = time.time()
    try:
        addr = done
        while addr < SIZE:
            n = min(CHUNK, SIZE - addr)
            fh.write(fetch(q, addr, n))
            fh.flush()
            addr += n
            el = time.time() - t0
            rate = (addr - done) / 1024.0 / el if el else 0
            eta = (SIZE - addr) / 1024.0 / rate if rate else 0
            sys.stdout.write("\r  %5.1f/%d MB  %5.1f KB/s  eta %3.0fs"
                             % (addr / 1048576.0, SIZE // 1048576, rate, eta))
            sys.stdout.flush()
    finally:
        fh.close()
    print("\n  done: %s, %d bytes" % (OUT, os.path.getsize(OUT)))


def verify(q, samples=8):
    """Re-read a spread of offsets and compare against the saved file."""
    size = os.path.getsize(OUT)
    print("verifying %d spots against the device" % samples)
    data = open(OUT, "rb")
    bad = 0
    for i in range(samples):
        addr = (size // samples) * i
        addr -= addr % 4096
        want = fetch(q, addr, 4096)
        data.seek(addr)
        got = data.read(4096)
        ok = got == want
        if not ok:
            bad += 1
        print("  0x%07x %s" % (addr, "match" if ok else "MISMATCH"))
    data.close()
    print("  %d/%d matched" % (samples - bad, samples))
    return bad == 0


if __name__ == "__main__":
    q = Qpy()
    try:
        out, err = q.exec(SETUP, read_for=25)
        print("device:", (out or "").strip()[:120], (err or "")[:120])
        if err:
            raise SystemExit(1)
        if "--verify" not in sys.argv:
            dump(q)
        if os.path.exists(OUT):
            verify(q)
    finally:
        q.close()
