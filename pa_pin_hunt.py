#!/usr/bin/env python3
"""Find the HT8313 shutdown pin by ear, with real audio playing.

The amplifier is an HT8313 - the same part as the EC600M board. It is a plain
class-D amp: analog in, speaker out, and an active-low SD pin. Nothing on I2C
or any UART answers, which fits: there is no digital interface to find, only
that one pin.

The module's side is proven good. MP3 plays for its full length (callback
gives event 0 at start and event 7 at the file's exact duration), and the
encoding matches the files that work on the EC600M board byte for byte in
parameters - mp3, 16 kHz, mono, 32 kbps. So the only thing left between the
codec and the speaker is SD being held low.

This plays a 75 s tone and walks each safe pin high while it runs, printing
which pin is being driven. Whoever is listening calls out the number that was
on screen when sound appeared.

Earlier attempts at this were built on `aud_tone_play`, which returns 0 but
never plays anything on this board, so they proved nothing.

Pins left alone:
    1, 2, 4, 30     SPI1 - the NOR bus, GPIO2 is its chip select
    10, 11, 12, 13  spi_0
    7, 19           UART pins
    26              ESP boot strap, must stay low
    44              ESP 3V3 rail switch
    14              shares that rail

    python3 pa_pin_hunt.py             # every candidate, ~2 s each
    python3 pa_pin_hunt.py 22,23,24    # just these
    python3 pa_pin_hunt.py --hold 25   # hold one pin high and keep playing
"""

import sys
import time

from qpy import Qpy

SKIP = {1, 2, 4, 7, 10, 11, 12, 13, 14, 19, 26, 30, 44}
CANDIDATES = [g for g in range(1, 48) if g not in SKIP]
DWELL_MS = 2000
TRACK = "U:/long.mp3"

PLAY = """
import audio, utime
from machine import Pin
EV = []
t0 = utime.ticks_ms()
def cb(e):
    EV.append((utime.ticks_diff(utime.ticks_ms(), t0), e))
a = audio.Audio(0)
a.setCallback(cb)
a.setVolume(11)
EV = []
t0 = utime.ticks_ms()
print('play ->', a.play(1, 0, '%(track)s'))
utime.sleep(1)
print('events after 1s', EV)
"""

SWEEP = """
for g in %(pins)s:
    pid = getattr(Pin, 'GPIO%%d' %% g, None)
    if pid is None:
        continue
    try:
        Pin(pid, Pin.OUT, Pin.PULL_DISABLE, 1)
    except Exception:
        print('GPIO%%d could not be driven' %% g)
        continue
    print('>>> GPIO%%d HIGH' %% g)
    utime.sleep_ms(%(dwell)d)
    try:
        Pin(pid, Pin.IN, Pin.PULL_DISABLE)
    except Exception:
        pass
print('sweep done, events', EV)
"""

HOLD = """
import audio, utime
from machine import Pin
Pin(Pin.GPIO%(pin)d, Pin.OUT, Pin.PULL_DISABLE, 1)
a = audio.Audio(0)
a.setVolume(11)
print('GPIO%(pin)d held high, playing')
print('play ->', a.play(1, 0, '%(track)s'))
utime.sleep(20)
print('still holding')
"""


def hold(pin):
    q = Qpy()
    try:
        out, err = q.exec(HOLD % {"pin": pin, "track": TRACK}, read_for=45)
        print((out or "").strip()[:300], (err or "")[:200])
    finally:
        q.close()


def hunt(pins):
    q = Qpy()
    try:
        out, err = q.exec(PLAY % {"track": TRACK}, read_for=30)
        print((out or "").strip()[:200], (err or "")[:150])
        if err:
            return
        print("\nlisten now - note the number showing when sound starts\n")
        chunk = 6
        for i in range(0, len(pins), chunk):
            part = pins[i:i + chunk]
            out, err = q.exec(SWEEP % {"pins": repr(part), "dwell": DWELL_MS},
                              read_for=len(part) * (DWELL_MS / 1000.0) + 30)
            for line in (out or "").splitlines():
                print("  " + line[:100])
            if err:
                print("   err:", err[:150])
    finally:
        q.close()


if __name__ == "__main__":
    if "--hold" in sys.argv:
        hold(int(sys.argv[sys.argv.index("--hold") + 1]))
    else:
        pins = ([int(x) for x in sys.argv[1].split(",")]
                if len(sys.argv) > 1 else CANDIDATES)
        print("candidates: %s\n" % pins)
        hunt(pins)
    with open("logs/pa_pin_hunt.log", "a") as fh:
        fh.write("%s ran pa pin hunt\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
