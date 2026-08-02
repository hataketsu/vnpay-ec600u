#!/usr/bin/env python3
"""Get sound out of the board's speaker, and find the amplifier enable pin.

`aud_tone_play(mode, seconds)` is accepted and returns 0, but a class-D amp
needs its enable line asserted before anything reaches the speaker. The
firmware image contains `helios_open_pa`, `asynch_open_pa_init` and
`user_audio_speakerpa_callback`, so there is a PA concept - it just has to be
pointed at the right pin.

Pass 1 plays a tone with no pin driven, to see whether the amp is already on.
Pass 2 keeps a long tone playing and walks candidate pins high one at a time,
printing each as it goes, so whoever is listening can call out which one makes
the sound appear.

Pins deliberately left alone:
    2, 1, 4, 30   SPI1 - the NOR flash bus (GPIO2 is its chip select)
    10, 11, 12, 13  spi_0
    7, 19         UART pins
    44            switches the ESP's 3V3 rail
    14            shares that rail; high silences the ESP

    python3 speaker_test.py           # pass 1 then pass 2
    python3 speaker_test.py 22,23,24  # only these candidates
"""

import sys
import time

from qpy import Qpy

SKIP = {1, 2, 4, 7, 10, 11, 12, 13, 14, 19, 30, 44}
CANDIDATES = [g for g in range(1, 48) if g not in SKIP]

PLAIN = """
import audio
from machine import Pin
import utime
a = audio.Audio(0)
a.setVolume(11)
print('volume', a.getVolume())
print('tone ->', a.aud_tone_play(1, 5))
utime.sleep(6)
print('state after', a.getState())
"""

SWEEP = """
import audio
from machine import Pin
import utime
a = audio.Audio(0)
a.setVolume(11)
a.aud_tone_play(1, %(total)d)
for g in %(pins)s:
    pid = getattr(Pin, 'GPIO%%d' %% g, None)
    if pid is None:
        continue
    try:
        Pin(pid, Pin.OUT, Pin.PULL_DISABLE, 1)
    except Exception as e:
        print('GPIO%%d ERR' %% g)
        continue
    print('now driving GPIO%%d high' %% g)
    utime.sleep_ms(%(dwell)d)
    try:
        Pin(pid, Pin.IN, Pin.PULL_DISABLE)
    except Exception:
        pass
print('sweep done')
"""


def main(pins, dwell_ms=1800):
    q = Qpy()
    try:
        print("=== pass 1: tone with nothing driven - listen ===")
        out, err = q.exec(PLAIN, read_for=25)
        print((out or "").strip()[:300], (err or "")[:200])

        total = int(len(pins) * dwell_ms / 1000) + 6
        print("\n=== pass 2: %d candidates, %.1fs each, %ds of tone ==="
              % (len(pins), dwell_ms / 1000.0, total))
        print("say which GPIO number was on screen when sound started\n")
        out, err = q.exec(SWEEP % {"pins": repr(pins), "dwell": dwell_ms,
                                   "total": total},
                          read_for=total + 40)
        for line in (out or "").splitlines():
            print("  " + line[:120])
        if err:
            print("err:", err[:200])
    finally:
        q.close()


if __name__ == "__main__":
    pins = ([int(x) for x in sys.argv[1].split(",")]
            if len(sys.argv) > 1 else CANDIDATES)
    main(pins)
    with open("logs/speaker_test.log", "a") as fh:
        fh.write("%s ran speaker sweep over %s\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), pins))
