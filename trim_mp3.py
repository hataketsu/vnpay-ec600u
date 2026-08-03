#!/usr/bin/env python3
"""Cut an MP3 short at a frame boundary, without re-encoding.

There is no ffmpeg or lame on the machine this was written on, and none is
needed: MPEG layer III frames carry their own header, so keeping the first N
of them is a valid file. Each frame is 1152 samples, which at this board's
16 kHz files is 72 ms - so the result lands on a 72 ms grid rather than
exactly on the requested length.

Truncation can clip the tail of the last frame, because layer III lets a frame
borrow bytes from earlier ones through the bit reservoir. For a beep that is
inaudible.

    python3 trim_mp3.py audio/beep.mp3 audio/ping.mp3 0.5
"""

import sys

# Layer III bitrate tables, in kbps by index. MPEG1 and MPEG2/2.5 do not share
# one - this board's files are MPEG2, where index 5 is 40 kbps, not 64. Using
# the MPEG1 table computes the wrong frame length and truncation lands inside a
# frame instead of between two.
BITRATES_MPEG1 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256,
                  320, 0)
BITRATES_MPEG2 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144,
                  160, 0)
RATES = {0: 44100, 1: 48000, 2: 32000}
# MPEG1 layer III carries two granules per frame, MPEG2/2.5 only one.
SAMPLES_MPEG1 = 1152
SAMPLES_MPEG2 = 576


def frames(data):
    """Yield (offset, length, seconds) for each layer III frame."""
    i = 0
    if data[:3] == b"ID3":
        i = 10 + (((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) |
                  ((data[8] & 0x7F) << 7) | (data[9] & 0x7F))
    while i < len(data) - 4:
        if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
            version = (data[i + 1] >> 3) & 3
            layer = (data[i + 1] >> 1) & 3
            table = BITRATES_MPEG1 if version == 3 else BITRATES_MPEG2
            bitrate = table[(data[i + 2] >> 4) & 0xF]
            rate = RATES.get((data[i + 2] >> 2) & 3)
            padding = (data[i + 2] >> 1) & 1
            if bitrate and rate and layer == 1:
                if version == 3:        # MPEG1
                    hz, samples = rate, SAMPLES_MPEG1
                elif version == 2:      # MPEG2
                    hz, samples = rate // 2, SAMPLES_MPEG2
                else:                   # MPEG2.5
                    hz, samples = rate // 4, SAMPLES_MPEG2
                length = samples // 8 * bitrate * 1000 // hz + padding
                yield i, length, samples / float(hz)
                i += length
                continue
        i += 1


def trim(src, dst, seconds):
    data = open(src, "rb").read()
    kept, total = 0, 0.0
    end = 0
    for offset, length, dur in frames(data):
        if kept == 0:
            start = offset
        if total >= seconds:
            break
        kept += 1
        total += dur
        end = offset + length
    if not kept:
        raise SystemExit("%s: no MPEG layer III frames found" % src)
    out = data[start:end]
    open(dst, "wb").write(out)
    return kept, total, len(out)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        raise SystemExit(1)
    n, secs, size = trim(sys.argv[1], sys.argv[2], float(sys.argv[3]))
    print("%s -> %s: %d frames, %.3f s, %d bytes"
          % (sys.argv[1], sys.argv[2], n, secs, size))
