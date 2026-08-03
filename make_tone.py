#!/usr/bin/env python3
"""Synthesise a short confirmation blip and encode it as MP3.

The board's own beep.mp3 is 1.58 s of speech-like noise, far too long and too
ugly to confirm a volume step. Cutting it short with trim_mp3.py leaves a
fragment of the same ugly sound, so this generates a clean one instead: a sine
with a fast attack and an exponential decay, which is what a blip wants to be.
Without an envelope the abrupt start and stop click audibly.

Everything matches the files the module already decodes - MPEG2, mono, 16 kHz,
64 kbps. MP3 frames hold 1152 samples, so 72 ms at 16 kHz; the encoder rounds
up to a whole number of them.

Needs lame (`brew install lame`); the standard library has no MP3 encoder.

    python3 make_tone.py audio/ping.mp3
    python3 make_tone.py audio/ping.mp3 --ms 150 --hz 1320
"""

import argparse
import math
import struct
import subprocess
import tempfile
import wave

RATE = 16000


def synth(path, ms, hz, attack_ms=4.0, amplitude=0.5):
    n = int(RATE * ms / 1000.0)
    attack = max(1, int(RATE * attack_ms / 1000.0))
    # Decay to about -40 dB by the end, so the tail is inaudible rather than
    # chopped - a hard stop mid-cycle clicks.
    decay = 4.6 / n
    frames = bytearray()
    for i in range(n):
        env = min(1.0, i / float(attack)) * math.exp(-decay * i)
        s = amplitude * env * math.sin(2 * math.pi * hz * i / RATE)
        frames += struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767))

    w = wave.open(path, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(RATE)
    w.writeframes(bytes(frames))
    w.close()


def encode(wav_path, mp3_path, kbps):
    subprocess.run(
        ["lame", "--quiet", "-m", "m", "-b", str(kbps), "--cbr",
         wav_path, mp3_path],
        check=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("out")
    p.add_argument("--ms", type=float, default=100.0)
    p.add_argument("--hz", type=float, default=1000.0)
    p.add_argument("--kbps", type=int, default=64)
    a = p.parse_args()

    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        synth(tmp.name, a.ms, a.hz)
        encode(tmp.name, a.out, a.kbps)

    import os
    print("%s: %.0f ms at %.0f Hz, %d bytes"
          % (a.out, a.ms, a.hz, os.path.getsize(a.out)))
