#!/usr/bin/env python3
"""Find the amplifier enable pin by watching audio events, not by listening.

The audio engine currently fails outright: `aud_tone_play(1, 6)` returns 0 but
fires a single callback event **7** at ~270 ms and never runs the six seconds.
Playing a WAV gives `0, 7, 8` - start, error, end - in under 300 ms. So event 7
is the failure, and nothing ever reaches the speaker regardless of which of the
three device indices is used.

The firmware carries `helios_open_pa`, `asynch_open_pa_init` and
`user_audio_speakerpa_callback`, so the amplifier is meant to be enabled
through `Audio.set_pa(gpio)`. This walks that call across every safe pin and
plays a short tone each time, looking for the event pattern of a real playback
(a start, then an end after roughly the requested duration) instead of the
lone 7.

Being event-driven, it needs nobody listening.

Pins left alone:
    1, 2, 4, 30     SPI1 - the NOR bus, GPIO2 is its chip select
    10, 11, 12, 13  spi_0
    7, 19           UART pins
    26              ESP boot strap, must stay low
    44              ESP 3V3 rail switch
    14              shares that rail
"""

import sys
import time

from qpy import Qpy

SKIP = {1, 2, 4, 7, 10, 11, 12, 13, 14, 19, 26, 30, 44}
CANDIDATES = [g for g in range(1, 48) if g not in SKIP]
TONE_S = 2

PROLOGUE = """
import audio, utime
from machine import Pin
EV = []
def cb(evt):
    EV.append((utime.ticks_ms(), evt))
a = audio.Audio(2)
a.setCallback(cb)
a.setVolume(11)
def trial(g):
    global EV
    EV = []
    if g is not None:
        try:
            a.set_pa(g)
        except Exception as e:
            return 'set_pa err ' + repr(e)[:30]
    t0 = utime.ticks_ms()
    a.aud_tone_play(1, %(sec)d)
    for _ in range(%(sec)d * 4 + 6):
        utime.sleep_ms(250)
    out = []
    for t, e in EV:
        out.append((utime.ticks_diff(t, t0), e))
    try:
        a.stopAll()
    except Exception:
        pass
    return out
print('baseline (no set_pa):', trial(None))
"""

STEP = """
for g in %(pins)s:
    r = trial(g)
    ok = isinstance(r, list) and any(e != 7 for _, e in r) and len(r) > 1
    print(('HIT  ' if ok else '.    ') + 'GPIO%%d %%s' %% (g, r))
print('chunk done')
"""


def main(pins, chunk=4):
    q = Qpy()
    hits = []
    try:
        out, err = q.exec(PROLOGUE % {"sec": TONE_S}, read_for=40)
        print("prologue:", (out or "").strip()[:200], (err or "")[:150])
        for i in range(0, len(pins), chunk):
            part = pins[i:i + chunk]
            out, err = q.exec(STEP % {"pins": repr(part)},
                              read_for=len(part) * (TONE_S + 3) + 40)
            for line in (out or "").splitlines():
                print("  " + line[:150])
                if line.startswith("HIT"):
                    hits.append(line)
            if err:
                print("   err:", err[:150])
            with open("logs/pa_sweep.log", "a") as fh:
                fh.write((out or "") + "\n")
    finally:
        q.close()

    print("\n" + "=" * 56)
    if hits:
        for h in hits:
            print(h[:180])
    else:
        print("no pin changed the outcome - every trial still ended in the "
              "lone event 7, so the engine is failing before the amplifier "
              "matters")
    return hits


if __name__ == "__main__":
    pins = ([int(x) for x in sys.argv[1].split(",")]
            if len(sys.argv) > 1 else CANDIDATES)
    with open("logs/pa_sweep.log", "a") as fh:
        fh.write("=== pa sweep %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
    main(pins)
