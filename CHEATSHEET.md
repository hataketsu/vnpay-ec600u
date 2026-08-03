# Working the box by hand

Everything here was run against this board. Anything not verified is marked.

## Which USB port is which

### macOS

There are no device nodes at all — macOS binds no driver to interface class
0xFF, so `ls /dev/cu.*` shows nothing but Bluetooth. The interfaces are
unclaimed, though, so `qpy.py` opens interface .8 with libusb directly and
every tool here works unchanged. Needs `brew install libusb` and `pip install
pyusb`; no kext, no SIP changes. Interface numbers are fixed, so nothing has to
be re-resolved between runs.

Endpoints, if you need them by hand: interface .8 is bulk **out 0x08, in 0x8b**;
interface .2, the AT port, is **out 0x02, in 0x84**.

### Linux

The module presents 7 serial interfaces. **The ttyUSB numbers shift** whenever
anything else is plugged or unplugged, so identify by USB *interface number*,
not by the device name:

| Interface | Purpose |
|---|---|
| `.2` | AT command port |
| `.8` | **MicroPython REPL** |
| `.3` – `.7` | diagnostic / log streams, mostly binary noise |

Find them without guessing:

```bash
for i in /sys/bus/usb/devices/3-*:1.*; do
  d=$(dirname $i)/$(basename $i | cut -d: -f1)
  [ "$(cat $d/idVendor 2>/dev/null)" = "2c7c" ] || continue
  echo "interface .$(basename $i | cut -d. -f2) -> $(ls $i | grep -o 'ttyUSB[0-9]*' | head -1)"
done
```

At the time of writing: REPL = `/dev/ttyUSB6`, AT = `/dev/ttyUSB0`.

The helper does this automatically:

```bash
python3 -c "import qpy; print(qpy.REPL_PORT)"
```

## Connecting

```bash
picocom -b 115200 /dev/ttyUSB6        # REPL - Ctrl-A Ctrl-X to quit
picocom -b 115200 /dev/ttyUSB0        # AT port
```

`screen /dev/ttyUSB6 115200` works too. In minicom set **115200 8N1**, and turn
hardware flow control off.

> **Opening the REPL stops whatever `main.py` is running.** Getting a prompt
> sends Ctrl-C, which interrupts it. The web panel dies the moment you connect,
> and only comes back after `misc.Power.powerRestart()`.

## Rules that will bite you

* **`machine.reset()` does nothing on this firmware** — USB never even drops.
  The real restart is `misc.Power.powerRestart()`.
* **Editing a file on the module is not enough.** `usys.modules` keeps the old
  copy, and tracebacks keep showing the *old* line numbers. Restart properly
  after any upload.
* **`/usr` is not on the import path.** `usys.path.append('/usr')` first.
* This MicroPython's **`bytearray` has no `.find()`**, no slice deletion, and
  **no slice assignment** — item assignment works. Use `bytes` and rebuild by
  slicing, or assign one byte at a time.
* **`bytes.split("\r\n")` is a TypeError** — the separator must be bytes.
* `machine.SPI.write(buf)` needs a length: `write(buf, len(buf))`.

## MicroPython, straight into the REPL

### Basics

```python
import usys
usys.path.append('/usr')
import uos
uos.uname()
uos.listdir('/usr')
uos.statvfs('/usr')        # (blocksize, ..., total, free, ...)
import gc; gc.collect(); gc.mem_free()
import misc; misc.Power.powerRestart()
```

### GPIO

```python
from machine import Pin
Pin(Pin.GPIO9, Pin.OUT, Pin.PULL_DISABLE, 1)     # drive high
Pin(Pin.GPIO9, Pin.OUT, Pin.PULL_DISABLE, 0)     # drive low
Pin(Pin.GPIO9, Pin.IN, Pin.PULL_DISABLE)         # release (hi-Z)
Pin(Pin.GPIO9, Pin.IN, Pin.PULL_PU).read()       # read with pull-up
Pin(Pin.GPIO9, Pin.IN, Pin.PULL_PD).read()       # read with pull-down
```

Pull-up 1 / pull-down 0 means floating. Both 1 means something drives it high,
both 0 means something drives it low.

A fresh `Pin(...)` is what re-drives a level — `.value()` alone does not.

### Pins that matter on this board

| GPIO | Module pin | What it does |
|---|---|---|
| **26** | 50 | ESP boot strap. **LOW = ESP runs its firmware**, high/floating = download mode |
| **44** | 14 | Switches the ESP's 3V3 rail. HIGH = powered |
| **14** | 54 | Same rail. HIGH = ESP completely off |
| 2 | 58 | SPI1 chip select for the NOR — reads high because of its pull-up |
| 7, 19 | 123, 124 | A UART port with nothing wired to it |
| 25 | 49 | WAKEUP_IN — driving it disturbs the ESP link |

Do not drive 7/19 while using UART2, and leave 44 high and 26 low whenever the
ESP is meant to stay up.

### Talk to the ESP

```python
from machine import UART, Pin
import utime
u = UART(UART.UART2, 115200, 8, 0, 1, 0)         # module pins 31/32

Pin(Pin.GPIO26, Pin.OUT, Pin.PULL_DISABLE, 0)    # strap: let it flash-boot
Pin(Pin.GPIO44, Pin.OUT, Pin.PULL_DISABLE, 0)    # rail off
utime.sleep_ms(700)
Pin(Pin.GPIO44, Pin.OUT, Pin.PULL_DISABLE, 1)    # rail on
utime.sleep(3)
u.read(u.any())                                   # boot chatter, ends in 'ready'

def at(c, w=2000):
    u.read(u.any())
    u.write(c + b'\r\n')
    utime.sleep_ms(w)
    n = u.any()
    return bytes(u.read(n)) if n else b''

at(b'AT')
at(b'AT+GMR')
at(b'AT+CWJAP="SSID","PASSWORD"', 15000)
at(b'AT+CIPSTA?')
at(b'AT+PING="8.8.8.8"', 5000)
u.close()                                         # always close it
```

The ROM banner before `ready` is garbage at 115200 — the ROM emits at 74880
because its divisor assumes a 40 MHz crystal and this board has 26 MHz. The
application fixes it, which is why `ready` onward is readable.

**Never touch `UART.UART3`** — it is the USB CDC port the REPL runs on.

### MQTT through the ESP

```python
at(b'AT+MQTTUSERCFG=0,1,"clientid","","",0,0,""')
at(b'AT+MQTTCONN=0,"broker.emqx.io",1883,1', 8000)
at(b'AT+MQTTSUB=0,"my/topic",1')
at(b'AT+MQTTPUB=0,"my/topic","hello",1,0', 4000)
```

### Audio — works, loud

Two conditions, both required. Miss either and the box is silent.

```python
from machine import Pin
import audio

# 1. GPIO13 is the HT8313's CTRL pin. Low = shutdown, charge pump never starts
Pin(Pin.GPIO13, Pin.OUT, Pin.PULL_DISABLE, 1)

# 2. route the codec at the loudspeaker - this is the part that was missing
a = audio.Audio(2)
a.set_channel(2)
a.setVolume(1)           # 0-11, and 1 is already loud
a.play(1, 0, 'U:/say.mp3')
```

From the laptop: `python3 audio_play.py say.mp3`.

* **MP3 only.** WAV stops after 270 ms, and `aud_tone_play` returns 0 while
  producing nothing — even with the amplifier awake.
* **Volume 1 is loud.** The HT8313 adds a fixed 28 dB that `setVolume` cannot
  reach; at 11 the speaker is overdriven into a continuous tone.
* **CTRL latches.** Once raised it holds 1.8 V until the board loses power, and
  driving GPIO13 low does not clear it. Every run after the first plays with no
  pin driven at all, so test on a freshly powered board or you will fool
  yourself.
* `getState()` returns 0 throughout. Use `setCallback`: event 0 is start,
  event 7 is end, and the end timestamp matches the file length exactly.
* Without `set_channel(2)` the codec biases SPK_P/SPK_N to 1.5 V and puts
  **0 mV AC** on them. Playback still reports success; nothing comes out.
* There is **no TTS** in this firmware: `audio.TTS` does not exist. Anything
  the box "says" has to be an MP3 already on `/usr`.

### Battery

```python
import misc
misc.Power.getVbatt()    # millivolts, e.g. 4162
```

No percentage API, and no ADC channel carries a battery divider. `battery.py`
maps the voltage onto a Li-ion curve, but while USB is plugged in the reading
follows the charger, not the cell.

Handy meter readings on the HT8313, for when it goes quiet again:

| Pin | Asleep | Awake |
|---|---|---|
| PVBAT / AVBAT | 5 V | 5 V |
| CTRL | 0 V | 1.8 V |
| PVDD | 0 V | 5 V |
| IN+ / IN− | 0 V | 1.3 V each |

### SPI NOR — currently not responding

```python
import nor
d = nor.NorFlash()
d.jedec()                # was (0x5e, 0x50, 0x18) = Zbit 16 MB
d.read(0, 64)
```

The chip stopped answering after a chip-erase was interrupted by a module
restart; a full power cycle of the board is the thing to try. A verified 16 MB
image of its original contents is in `nor_backup.bin`.

Once it answers again:

```python
s = nor.NorStore()
s.put('app.py', 'print("hi")')
s.get('app.py')
s.list()
s.usage()
```

It is a plain store, not a mountable filesystem: this firmware's `uos.mount`
only accepts objects that already implement a VFS, and `uos.VfsLfs1` takes ints
and is bound to the internal flash. So code kept there has to be run with
`exec(s.get('app.py'))` rather than imported.

## From the laptop instead of the REPL

```bash
cd ~/Projects/sound/vnpay_ec600u

python3 esp.py                      # boot the ESP, report firmware and WiFi
python3 esp.py "AT+CWLAP"           # any AT command
python3 beep.py 10                  # play a tone
python3 speaker_test.py             # hunt the amplifier enable pin
python3 spi_scan.py                 # look for the NOR on both SPI ports
python3 nor_dump.py                 # back the NOR up (resumable, ~4 min)
python3 gpio_read.py                # classify every pin floating/driven
python3 gpio_panel.py               # local web panel on :8760
python3 upload.py <file> [dest]     # copy a file to /usr
```

Each of these grabs the REPL, so run one at a time, and none of them can run
while the on-module web panel is meant to stay up.
