#!/usr/bin/env python3
"""Play a tone through the board so you can listen for it.

`aud_tone_play(mode, seconds)` is accepted and returns 0, but nothing has yet
confirmed that sound actually reaches the speaker - a class-D amp usually needs
its enable line asserted first, and that pin has not been identified.

    python3 beep.py          # 10 second tone at full volume
    python3 beep.py 3        # shorter
"""

import sys

from qpy import Qpy

CODE = """
import audio
a = audio.Audio(0)
a.setVolume(11)
print('volume', a.getVolume())
print('tone   ', a.aud_tone_play(1, %(sec)d))
print('state  ', a.getState())
"""


def beep(seconds=10):
    q = Qpy()
    try:
        out, err = q.exec(CODE % {"sec": seconds}, read_for=seconds + 25)
        print((out or "").strip())
        if err:
            print("err:", err[:200])
    finally:
        q.close()


if __name__ == "__main__":
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print("playing a %d second tone - listen to the speaker now" % secs)
    beep(secs)
