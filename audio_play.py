#!/usr/bin/env python3
"""Play an MP3 through the board's speaker, out loud.

The whole fix is one line: **`audio.Audio(2)` with `set_channel(2)`**. Left on
its default the codec biases SPK_P/SPK_N to 1.5 V and puts no signal on them -
0 mV AC, measured, while an MP3 was demonstrably decoding - so the amplifier
has nothing to amplify and `play()` still reports success. `set_channel` is
never called anywhere else in this repo, which is why the box was silent for
so long.

The routing is only half of it. The HT8313's CTRL pin has to be driven high
too, or the amplifier stays in shutdown and its charge pump never starts. That
pin is **GPIO13** (module pin 2, `spi_0_di`) - one of the four spi_0 pins every
earlier sweep in this repo deliberately skipped. On a freshly powered board,
routing alone is silent; `--pins 13` plays.

**CTRL keeps its level once it has been raised**, and stays high until the
board loses power. Driving GPIO13 - or every safe pin - low again for five
seconds does not clear it, so whatever holds it is not simply the pin. The
practical consequence: after one successful run, everything appears to work
with no pins at all, which is why this looked solved twice before it was. Only
a power cycle resets it.

**Volume 1 is already loud.** The HT8313 adds a fixed 28 dB that `setVolume`
cannot reach, so the top of the 0-11 range overdrives the speaker badly enough
to sound like a continuous tone rather than audio.

Only MP3 decodes - WAV plays for 270 ms and stops, and `aud_tone_play` returns
0 without producing anything.

    python3 audio_play.py                    # long.mp3, device 2, channel 2
    python3 audio_play.py say.mp3
    python3 audio_play.py long.mp3 --rounds 4
    python3 audio_play.py say.mp3 --volume 4          # louder
    python3 audio_play.py long.mp3 --channel -        # leave set_channel alone
    python3 audio_play.py long.mp3 --pins ''          # do not touch CTRL
"""

import argparse

from qpy import Qpy

CTRL_PIN = 13        # module pin 2, spi_0_di - the HT8313's CTRL line

# --pins all, kept for re-testing. 23/24/35/36/40/41 are driven by the board,
# so driving them back is contention; 14/44 gate the ESP's 3V3 rail.
SKIP = {14, 23, 24, 35, 36, 40, 41, 44}
ALL_PINS = [g for g in range(1, 48) if g not in SKIP]

CODE = """
import audio, utime
from machine import Pin
if %(reset)s:
    # CTRL keeps its level after the pins are released, so a subset that does
    # not include it still plays once anything has driven it high. Force every
    # safe pin low first, or a bisect can only ever answer "yes".
    for g in %(allpins)s:
        pid = getattr(Pin, 'GPIO%%d' %% g, None)
        if pid is not None:
            try:
                Pin(pid, Pin.OUT, Pin.PULL_DISABLE, 0)
            except Exception:
                pass
    utime.sleep_ms(%(reset_ms)d)
    print('reset: all safe pins low for %(reset_ms)d ms')
held = []
for g in %(pins)s:
    pid = getattr(Pin, 'GPIO%%d' %% g, None)
    if pid is None:
        continue
    try:
        held.append((g, Pin(pid, Pin.OUT, Pin.PULL_DISABLE, 1)))
    except Exception:
        print('GPIO%%d ERR' %% g)
if held:
    print('forcing CTRL high with', len(held), 'pins')
a = audio.Audio(%(dev)d)
%(chan)s
a.setVolume(%(vol)d)
print('device %(dev)d volume', a.getVolume())
t0 = utime.ticks_ms()
ev = []
def cb(args):
    ev.append((utime.ticks_diff(utime.ticks_ms(), t0), args))
a.setCallback(cb)
for i in range(%(rounds)d):
    a.play(1, 0, %(path)r)
    utime.sleep(%(secs)d)
print('events', ev)
a.stopAll()
for g, _ in held:
    Pin(getattr(Pin, 'GPIO%%d' %% g), Pin.IN, Pin.PULL_DISABLE)
print('done')
"""

CHAN = """
try:
    print('set_channel(%(ch)d) ->', a.set_channel(%(ch)d))
except Exception as e:
    print('set_channel ERR', repr(e)[:120])
"""


def play(path, dev=2, ch=2, rounds=1, secs=31, vol=1, pins=(CTRL_PIN,),
         reset=0):
    q = Qpy()
    try:
        out, err = q.exec(CODE % {"pins": repr(list(pins)), "dev": dev,
                                  "reset": bool(reset), "reset_ms": reset or 0,
                                  "allpins": repr(ALL_PINS),
                                  "chan": "" if ch is None else CHAN % {"ch": ch},
                                  "vol": vol, "rounds": rounds, "secs": secs,
                                  "path": path},
                          read_for=rounds * (secs + 1) + 40)
        print((out or "").strip())
        if err:
            print("err:", err[:300])
    finally:
        q.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("file", nargs="?", default="long.mp3",
                   help="file under /usr on the module")
    p.add_argument("--device", type=int, default=2,
                   help="audio.Audio() device; 2 is the loudspeaker path")
    p.add_argument("--channel", default="2",
                   help="set_channel() argument, or - to skip the call")
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--seconds", type=int, default=31,
                   help="how long each round is held; long.mp3 runs 30 s")
    p.add_argument("--volume", type=int, default=1,
                   help="0-11. 1 is already loud - the HT8313 adds a fixed "
                        "28 dB that setVolume cannot touch")
    p.add_argument("--pins", default=str(CTRL_PIN),
                   help="GPIOs to drive high; %d is CTRL. 'all' for the whole "
                        "safe set, empty to drive nothing" % CTRL_PIN)
    p.add_argument("--reset", nargs="?", type=int, const=400, default=0,
                   metavar="MS",
                   help="drive every safe pin low for MS first. Does not "
                        "actually clear CTRL - only a power cycle does")
    a = p.parse_args()

    pins = (ALL_PINS if a.pins == "all"
            else [int(x) for x in a.pins.split(",") if x])

    play("U:/" + a.file.lstrip("/"),
         dev=a.device,
         ch=None if a.channel == "-" else int(a.channel),
         rounds=a.rounds, secs=a.seconds, vol=a.volume,
         pins=pins, reset=a.reset)
