#!/usr/bin/env python3
"""Try each audio output path, since nothing came out of the default one.

`audio.Audio(device)` picks the route, and the firmware image carries
`ql_set_audio_path_speaker`, `ql_set_audio_path_earphone` and
`ql_set_audio_path_receiver` - so device 0 is the receiver, not the
loudspeaker. Every earlier test used device 0, which is the likely reason the
tone was silent.

Plays a tone on each device index in turn, announcing it first, so whoever is
listening can say which one produced sound.

    python3 audio_path.py           # 4 seconds per path
    python3 audio_path.py 8         # longer
"""

import sys
import time

from qpy import Qpy

CODE = """
import audio
import utime
for dev in (0, 1, 2, 3):
    try:
        a = audio.Audio(dev)
    except Exception as e:
        print('device %%d  open failed %%s' %% (dev, repr(e)[:50]))
        continue
    try:
        a.setVolume(11)
    except Exception:
        pass
    try:
        r = a.aud_tone_play(1, %(sec)d)
    except Exception as e:
        print('device %%d  tone failed %%s' %% (dev, repr(e)[:50]))
        continue
    print('device %%d  playing now, returned %%s, state %%s'
          %% (dev, r, a.getState()))
    utime.sleep(%(sec)d + 1)
    try:
        a.stopAll()
    except Exception:
        pass
print('done')
"""


if __name__ == "__main__":
    sec = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    print("playing %ds on each audio device - listen and note which one "
          "makes sound\n" % sec)
    q = Qpy()
    try:
        out, err = q.exec(CODE % {"sec": sec}, read_for=4 * (sec + 3) + 40)
        for line in (out or "").splitlines():
            print("  " + line[:120])
        if err:
            print("err:", err[:200])
    finally:
        q.close()
    with open("logs/audio_path.log", "a") as fh:
        fh.write("%s tried audio devices 0-3\n"
                 % time.strftime("%Y-%m-%d %H:%M:%S"))
