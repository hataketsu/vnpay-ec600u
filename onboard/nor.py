"""Block device for the board's 16 MB SPI NOR, so LittleFS can live on it.

The chip answers on SPI1 with JEDEC `5e 50 18` - Zbit, 2^24 = 16 MB. SPI1 is
module pins 61/58/59/60 (GPIO1 clk, GPIO2 cs, GPIO30 dio, GPIO4 di), which is
also why GPIO2 reads driven high: it is the chip select, with a pull-up.

QuecPython here has `uos.VfsLfs1` and `uos.mount` but no VfsFat and no Lfs2, so
LittleFS v1 is the filesystem to use. It needs the extended block protocol:
readblocks/writeblocks with an offset, and ioctl 6 to erase a block.

Block size is the flash's 4 KB sector, since that is the smallest erase unit.

    import nor
    d = nor.NorFlash()
    print(d.jedec())          # (0x5e, 0x50, 0x18)

    # destructive from here - erases everything already on the chip
    import uos
    uos.VfsLfs1.mkfs(d)
    uos.mount(uos.VfsLfs1(d), '/nor')
"""

from machine import SPI
import utime

CMD_READ = 0x03
CMD_PAGE_PROGRAM = 0x02
CMD_SECTOR_ERASE = 0x20      # 4 KB
CMD_WREN = 0x06
CMD_RDSR = 0x05
CMD_JEDEC = 0x9F

SECTOR = 4096
PAGE = 256


class NorFlash:
    def __init__(self, port=1, mode=0, clk=1, size=16 * 1024 * 1024):
        self.spi = SPI(port, mode, clk)
        self.size = size
        self.blocks = size // SECTOR

    # ------------------------------------------------------------ raw access

    def _xfer(self, tx, rxlen):
        """One CS-framed transaction: QuecPython drives CS per call, so the
        command and its data have to go out together.

        Built by concatenation because this MicroPython's bytearray supports
        item assignment but **not** slice assignment.
        """
        buf = bytearray(tx) + bytearray(rxlen)
        out = bytearray(len(buf))
        self.spi.write_read(out, buf, len(buf))
        return bytes(out[len(tx):])

    def jedec(self):
        r = self._xfer(b"\x9f", 3)
        return (r[0], r[1], r[2])

    def _busy(self):
        return self._xfer(b"\x05", 1)[0] & 0x01

    def _wait(self, timeout_ms=3000):
        t0 = utime.ticks_ms()
        while self._busy():
            if utime.ticks_diff(utime.ticks_ms(), t0) > timeout_ms:
                return False
            utime.sleep_ms(1)
        return True

    def _wren(self):
        # QuecPython's SPI.write requires the length as a second argument.
        self.spi.write(bytearray([CMD_WREN]), 1)

    def read(self, addr, n):
        cmd = bytearray([CMD_READ, (addr >> 16) & 0xFF,
                         (addr >> 8) & 0xFF, addr & 0xFF])
        return self._xfer(cmd, n)

    def erase_sector(self, addr):
        self._wren()
        buf = bytearray([CMD_SECTOR_ERASE, (addr >> 16) & 0xFF,
                         (addr >> 8) & 0xFF, addr & 0xFF])
        self.spi.write(buf, len(buf))
        return self._wait()

    def write(self, addr, data):
        """Program, splitting at page boundaries - a page program that crosses
        one wraps within the page instead of continuing."""
        i = 0
        while i < len(data):
            room = PAGE - ((addr + i) % PAGE)
            chunk = data[i:i + room]
            a = addr + i
            self._wren()
            buf = bytearray([CMD_PAGE_PROGRAM, (a >> 16) & 0xFF,
                             (a >> 8) & 0xFF, a & 0xFF]) + bytearray(chunk)
            self.spi.write(buf, len(buf))
            if not self._wait():
                return False
            i += len(chunk)
        return True

    # -------------------------------------------------- block device protocol

    def readblocks(self, block, buf, offset=0):
        data = self.read(block * SECTOR + offset, len(buf))
        # Element-wise: slice assignment on a bytearray raises TypeError here.
        for i in range(len(buf)):
            buf[i] = data[i]
        return 0

    def writeblocks(self, block, buf, offset=None):
        if offset is None:
            # Short form implies erase-then-write of the whole block.
            self.erase_sector(block * SECTOR)
            offset = 0
        self.write(block * SECTOR + offset, buf)
        return 0

    def ioctl(self, op, arg):
        if op == 3:              # sync
            return 0
        if op == 4:              # block count
            return self.blocks
        if op == 5:              # block size
            return SECTOR
        if op == 6:              # erase one block
            self.erase_sector(arg * SECTOR)
            return 0
        return None

    def chip_erase(self, timeout_ms=180000):
        """Erase the whole chip. Much faster than 4096 sector erases."""
        self._wren()
        self.spi.write(bytearray([0xC7]), 1)
        return self._wait(timeout_ms)


# ---------------------------------------------------------------- data store
#
# QuecPython's `uos.mount` only accepts objects that already implement a VFS
# (they must have a .mount method), and `uos.VfsLfs1` takes ints - it is bound
# to the internal flash, not to a block device supplied from Python. So no
# filesystem can be mounted on this chip from here, and the usable answer is a
# small store of our own.
#
# Shaped for NOR: erasing is per 4 KB sector and writing can only clear bits,
# so the directory is append-only. A new entry goes in the next free slot; an
# entry is deleted by clearing its flag byte (1 -> 0 needs no erase); rewriting
# a name just appends a new entry and retires the old one.

DIR_START = 0
DIR_SECTORS = 4                  # 16 KB of directory
DATA_START = DIR_SECTORS * SECTOR
ENTRY = 32                       # name[20] + off[4] + len[4] + flag[4]
MAX_ENTRIES = DIR_SECTORS * SECTOR // ENTRY


class NorStore:
    def __init__(self, dev=None):
        self.d = dev or NorFlash()

    def format(self):
        """Erase everything. The vendor filesystem that shipped on the chip is
        destroyed by this - back it up with nor_dump.py first."""
        return self.d.chip_erase()

    def _entries(self):
        out = []
        for i in range(MAX_ENTRIES):
            raw = self.d.read(DIR_START + i * ENTRY, ENTRY)
            if raw[0] == 0xFF:
                break
            name = raw[0:20]
            j = 0
            while j < 20 and name[j] not in (0, 0xFF):
                j += 1
            off = raw[20] | (raw[21] << 8) | (raw[22] << 16) | (raw[23] << 24)
            ln = raw[24] | (raw[25] << 8) | (raw[26] << 16) | (raw[27] << 24)
            alive = raw[28] != 0x00
            out.append((i, bytes(name[:j]).decode(), off, ln, alive))
        return out

    def _next_free_data(self, entries):
        top = DATA_START
        for _, _, off, ln, _ in entries:
            end = off + ln
            if end > top:
                top = end
        return (top + SECTOR - 1) // SECTOR * SECTOR   # align to a sector

    def list(self):
        return [(n, ln) for _, n, _, ln, alive in self._entries() if alive]

    def put(self, name, data):
        if isinstance(data, str):
            data = data.encode()
        name_b = name.encode()[:20]
        entries = self._entries()
        if len(entries) >= MAX_ENTRIES:
            return False
        addr = self._next_free_data(entries)
        if addr + len(data) > self.d.size:
            return False
        for a in range(addr, addr + len(data), SECTOR):
            self.d.erase_sector(a)
        if not self.d.write(addr, data):
            return False
        # retire any live entry with the same name
        for i, n, _, _, alive in entries:
            if n == name and alive:
                self.d.write(DIR_START + i * ENTRY + 28, b"\x00")
        rec = bytearray(name_b) + bytearray(20 - len(name_b))
        for v in (addr, len(data)):
            rec += bytearray([v & 0xFF, (v >> 8) & 0xFF,
                              (v >> 16) & 0xFF, (v >> 24) & 0xFF])
        rec += bytearray([0x01, 0xFE, 0xFE, 0xFE])
        return self.d.write(DIR_START + len(entries) * ENTRY, rec)

    def get(self, name):
        for _, n, off, ln, alive in self._entries():
            if n == name and alive:
                return self.d.read(off, ln)
        return None

    def remove(self, name):
        for i, n, _, _, alive in self._entries():
            if n == name and alive:
                self.d.write(DIR_START + i * ENTRY + 28, b"\x00")
                return True
        return False

    def usage(self):
        entries = self._entries()
        used = self._next_free_data(entries)
        return used, self.d.size - used
