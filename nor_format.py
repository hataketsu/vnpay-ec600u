#!/usr/bin/env python3
"""Save the head of the NOR, then format it as a LittleFS volume for Python.

The chip arrived with a vendor filesystem on it - `FILETMCL` at offset 0, and
every one of the 256 64 KB blocks non-blank - and there is no backup of it.
Formatting destroys that permanently, so the first 256 KB is pulled off first:
enough to keep the header and index for later identification, at about 40
seconds, where a full 16 MB dump over a 115200 REPL would take well over an
hour.

    python3 nor_format.py --dump-only    # just save the head, change nothing
    python3 nor_format.py                # save the head, then format and mount
"""

import base64
import sys
import time

from qpy import Qpy

DUMP_BYTES = 256 * 1024
BLOCK = 4096
OUT = "nor_head.bin"

SETUP = """
import usys
if '/usr' not in usys.path: usys.path.append('/usr')
import nor, ubinascii
d = nor.NorFlash()
print('jedec', ['0x%02x' % x for x in d.jedec()], 'blocks', d.blocks)
"""

READ = """
import ubinascii
print(ubinascii.b2a_base64(d.read(%d, %d)).decode().strip())
"""

FORMAT = """
import uos
uos.VfsLfs1.mkfs(d)
print('mkfs done')
try:
    uos.umount('/nor')
except Exception:
    pass
uos.mount(uos.VfsLfs1(d), '/nor')
print('mounted', uos.listdir('/nor'))
s = uos.statvfs('/nor')
print('block size', s[0], 'total blocks', s[2], 'free blocks', s[3])
print('capacity MB %.1f free MB %.1f' % (s[0]*s[2]/1048576.0, s[0]*s[3]/1048576.0))
"""

VERIFY = """
f = open('/nor/hello.txt', 'w')
f.write('written to the external NOR from QuecPython')
f.close()
print('read back:', open('/nor/hello.txt').read())
print('listdir:', uos.listdir('/nor'))
import uos as _u
s = _u.statvfs('/nor')
print('free MB %.1f' % (s[0]*s[3]/1048576.0))
"""


def main(dump_only):
    q = Qpy()
    try:
        out, err = q.exec(SETUP, read_for=25)
        print("device:", (out or "").strip()[:150], (err or "")[:150])
        if err:
            return

        print("saving first %d KB to %s" % (DUMP_BYTES // 1024, OUT))
        data = bytearray()
        t0 = time.time()
        for addr in range(0, DUMP_BYTES, BLOCK):
            out, err = q.exec(READ % (addr, BLOCK), read_for=25)
            line = (out or "").strip().splitlines()[-1] if out else ""
            try:
                data += base64.b64decode(line)
            except Exception:
                print("\n  chunk at 0x%x failed: %s" % (addr, (err or line)[:80]))
                break
            done = addr + BLOCK
            sys.stdout.write("\r  %d/%d KB  %.0fs"
                             % (done // 1024, DUMP_BYTES // 1024,
                                time.time() - t0))
            sys.stdout.flush()
        print()
        open(OUT, "wb").write(bytes(data))
        print("  wrote %s, %d bytes" % (OUT, len(data)))

        if dump_only:
            print("\n--dump-only: nothing was erased")
            return

        print("\nformatting - this erases the vendor filesystem")
        out, err = q.exec(FORMAT, read_for=180)
        print((out or "").strip()[:400], (err or "")[:250])
        if err:
            return
        out, err = q.exec(VERIFY, read_for=60)
        print((out or "").strip()[:400], (err or "")[:250])
    finally:
        q.close()


if __name__ == "__main__":
    main("--dump-only" in sys.argv)
