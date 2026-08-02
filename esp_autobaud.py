#!/usr/bin/env python3
"""Work out what baud the ESP is actually talking at.

Two independent methods, because either one alone can mislead:

1. Sweep every plausible rate and score how much of the capture is printable
   ASCII, plus look for strings the ESP8266 ROM is known to emit.

2. Estimate the rate from the signal itself. Capturing at a much higher baud
   than the source turns each received byte into a coarse sample of the line,
   so expanding those bytes back into bits and measuring the *shortest* run of
   identical bits gives the source's bit period:

       source_baud ~= capture_baud / shortest_run

   This does not care whether the framing decodes, so it works even when every
   standard rate produces garbage.

The ESP free-runs on a 2 s watchdog loop, so each pass catches at least one
full banner without anything having to reset it.

    python3 esp_autobaud.py
"""

import time

import serial

PORT = "/dev/ttyUSB0"

SWEEP = (4800, 9600, 14400, 19200, 28800, 38400, 57600, 62500, 74880, 76800,
         115200, 230400, 250000, 460800, 921600)

MARKERS = ("ets ", "rst cause", "boot mode", "load 0x", "csum", "tail",
           "chksum", "ready", "wdt reset", "ets_main", "Fatal", "SPIWP",
           "flash", "AT+", "OK", "WIFI", "user code")


def grab(baud, seconds=2.6):
    try:
        s = serial.Serial(PORT, baud, timeout=0.15)
    except Exception as exc:
        return None, str(exc)
    try:
        s.reset_input_buffer()
        buf = b""
        end = time.time() + seconds
        while time.time() < end:
            try:
                c = s.read(8192)
            except serial.SerialException as exc:
                # Another program holding the port (minicom, screen, …) makes
                # reads fail this way rather than failing the open.
                return buf, "read failed - port shared with another program? (%s)" % exc
            if c:
                buf += c
        return buf, None
    finally:
        try:
            s.close()
        except Exception:
            pass


def score(raw):
    if not raw:
        return 0, []
    ok = sum(1 for b in raw if 32 <= b < 127 or b in (9, 10, 13))
    text = raw.decode("latin1")
    found = [m for m in MARKERS if m in text]
    return ok * 100 // len(raw), found


def bits_of(raw):
    """Expand received bytes into the bit pattern that produced them."""
    out = []
    for b in raw:
        out.append(0)                      # start bit
        for i in range(8):                 # data, LSB first
            out.append((b >> i) & 1)
        out.append(1)                      # stop bit
    return out


def estimate_baud(capture_baud, raw):
    bits = bits_of(raw)
    if len(bits) < 64:
        return None, None
    runs = []
    cur = bits[0]
    n = 1
    for b in bits[1:]:
        if b == cur:
            n += 1
        else:
            runs.append(n)
            cur = b
            n = 1
    runs.append(n)
    # Ignore 1-bit runs: at these oversampling ratios they are mostly framing
    # artefacts rather than real one-bit-wide pulses.
    real = [r for r in runs if r >= 2]
    if not real:
        return None, None
    shortest = min(real)
    return capture_baud / float(shortest), shortest


def busy_holder():
    """Name the process holding the port, if any - minicom/screen block us."""
    import glob
    import os
    for fd in glob.glob("/proc/[0-9]*/fd/*"):
        try:
            if os.path.realpath(fd) == PORT:
                pid = fd.split("/")[2]
                with open("/proc/%s/comm" % pid) as fh:
                    return pid, fh.read().strip()
        except Exception:
            continue
    return None, None


if __name__ == "__main__":
    pid, name = busy_holder()
    if pid:
        print("%s is held by %s (pid %s).\nClose it first — in minicom that is "
              "Ctrl-A then X.\n" % (PORT, name, pid))
        raise SystemExit(1)
    print("port %s — ESP re-boots every ~2 s, so each pass sees a banner\n" % PORT)
    results = []
    for baud in SWEEP:
        raw, err = grab(baud)
        if err:
            print("%-8d rejected: %s" % (baud, err))
            continue
        pct, found = score(raw)
        results.append((pct, len(found), baud, raw, found))
        flag = ""
        if found:
            flag = "   <<< " + ", ".join(repr(f) for f in found[:4])
        elif pct >= 85:
            flag = "   <<< looks like text"
        print("%-8d %5d bytes  %3d%% printable%s" % (baud, len(raw), pct, flag))

    results.sort(key=lambda r: (r[1], r[0]), reverse=True)
    print("\n" + "=" * 62)
    if results:
        pct, nfound, baud, raw, found = results[0]
        print("best candidate: %d baud (%d%% printable, markers: %s)"
              % (baud, pct, found or "none"))
        print("-" * 62)
        print(raw.decode("latin1")[:1200])
        print("-" * 62)

    # Independent estimate from the waveform itself.
    print("\nwaveform-based estimate (captured at the highest rate):")
    raw, err = grab(921600, 3.0)
    if err or not raw:
        print("  no data at 921600 (%s)" % (err or "empty"))
    else:
        est, shortest = estimate_baud(921600, raw)
        if est:
            print("  %d bytes, shortest pulse = %d sample-bits -> ~%d baud"
                  % (len(raw), shortest, int(est)))
            near = min(SWEEP, key=lambda b: abs(b - est))
            print("  nearest standard rate: %d" % near)
        else:
            print("  not enough signal to estimate")

    with open("logs/esp_autobaud.log", "a") as fh:
        fh.write("=== %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        for pct, nfound, baud, raw, found in results:
            fh.write("%d: %d%% printable, %d bytes, markers=%s\n%r\n"
                     % (baud, pct, len(raw), found, raw[:300]))
