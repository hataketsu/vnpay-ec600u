# VNPay notification box — EC600U + ESP8285

Separate board from the EC600M one documented in `../BAO_CAO_REVERSE.md`.
Findings here apply to **this** board only; the two differ in both the WiFi
chip and the ESP wiring.

## Module

| | |
|---|---|
| Module | Quectel EC600U-EUAB (UNISOC UIS8910 / `UIX8910_MODEM`) |
| Stock firmware | `EC600UEUABR03A02M08_OCPU_BETA0302` (vendor OpenCPU app, **overwritten**) |
| Now running | `EC600UEUABR03A21M08_OCPU_QPY` — QuecPython V0003, MicroPython v1.12 |
| IMEI | redacted (preserved through the reflash) |
| User filesystem | ~360 KB free of 380 KB on `/usr` |
| REPL | `/dev/ttyUSB7` (USB interface 1.8) @ 115200 |
| AT port | `/dev/ttyUSB1` (USB interface 1.2) |

No TTS in this firmware build: `audio.TTS` does not exist, only
`audio.Audio` / `audio.Record`.

## Flashing QuecPython

There is no software route into download mode on this board — `AT+QDOWNLOAD=1`
returns `+CME ERROR: 4`, and QPYcom's Unisoc branch never sends that command
anyway (it assigns it, then waits for the download-mode USB device).

1. Tie **pin 55 (USB_BOOT)** to **pin 76 (VDD_EXT, 1.8 V)** through 4.7 kΩ
   *before* applying power. Module then enumerates as `0525:a4a7`.
2. `sudo QDloader -f <firmware>.pac -x <nv-backup-dir>` (~19 s).
   QDloader speaks the UNISOC **BSL** protocol over raw USBDEVFS bulk
   endpoints, not over a ttyUSB.
3. Remove the USB_BOOT strap, power cycle.

NV/calibration is backed up and merged automatically, which is why the IMEI
survived. Backup lives in `../nvbackup/quectel_back_NV`.

## QuecPython UART mapping

| `machine.UART` | Physical port | Module pins |
|---|---|---|
| `UART1` | BT port | — |
| `UART2` | **MAIN UART** | 31 / 32 |
| `UART3` | **USB CDC — this is the REPL** | — |
| `UART4` | spare UART | 103 / 104 |
| not exposed | **DEBUG UART**, AP log output only | 71 / 72 |

**Never open or write `UART3`.** It is the same port the REPL runs on; a write
corrupts REPL output and a port left open wedges the REPL until a power cycle.
Quectel documents the debug UART as log-output-only and not usable as a
general purpose UART, so QuecPython cannot open pins 71/72 at all.

## ESP8285 side

ESP8285 is an ESP8266 core with 1 MB internal flash, so:

* **UART0** (ESP GPIO1 TX / GPIO3 RX) — bidirectional, carries AT commands.
* **UART1** (ESP GPIO2) — **TX only**, debug log output.

The board was described as having two UART links to the ESP - one for
commands, one for the log - and that assumption was carried through the early
work. **It was never confirmed.** See "How many UART links" below.

* Boot ROM prints its banner at **74880 baud**. QuecPython rejects that
  baudrate (`ValueError: invalid baudrate`), but the boot chatter still shows
  up as garbage bytes when sampled at 115200 — good enough to detect that the
  ESP has powered up.
* **CH_PD/EN is active-high**; RST is active-low. (The EC600M board's ESP32-C2
  used an inverted, active-low enable — do not carry that assumption over.)

## Pin roles, EC600M vs EC600U

Same LCC footprint, so module pin numbers match, but the GPIO indices differ.
This is the easiest thing to get wrong:

| Signal | Module pin | EC600M GPIO | EC600U GPIO |
|---|---|---|---|
| MAIN_DTR | 39 | — | GPIO23 |
| MAIN_RI | 40 | G9 | GPIO24 |
| MAIN_DCD | 48 | — | GPIO22 |
| WAKEUP_IN | 49 | G21 | GPIO25 |
| AP_READY | 50 | G22 | GPIO26 |

## Measured pin levels (ESP still off)

Read as high-impedance inputs with internal pull-up then pull-down, so no pin
was driven:

* **Externally driven HIGH:** GPIO2 (pin 58, i2s2_lrck), GPIO40 (pin 100),
  GPIO41 (pin 120)
* **Externally driven LOW:** GPIO23 (pin 39), GPIO24 (pin 40, MAIN_RI),
  GPIO35 (pin 137), GPIO36 (pin 62)
* Everything else floats.

GPIO7 (pin 123) and GPIO19 (pin 124) — the module's UART2 pair — both float,
so nothing is wired to that port.

## ESP behaviour: 2-second watchdog loop

With GPIO44 held high the ESP emits exactly 152 bytes, then repeats on a
**2000 ms period** (bursts at t = 60, 1160, 3160, 5160, 7160 ms). A precise
2 s cycle is the ESP8266 hardware watchdog, not a brownout - brownouts are
irregular. So the ROM runs and hands off to the application, which then dies
immediately and lets the watchdog fire.

That rules out both earlier theories:

* not a strap problem - all 47 EC600U GPIOs were driven to both levels and
  none changed the behaviour
* not the 1.8 V enable being marginal - that would give irregular resets

Remaining suspects are the ESP's own flash contents (blank, corrupt, or wrong
flash mode) or the application hanging on something it expects from the host.

The banner itself is unreadable from the module: it is sent at 74880 baud
(ESP8266 with a 26 MHz crystal) and QuecPython rejects every rate near it -
74880, 76800, 73728, 78125, 72000 and 80000 all raise
`ValueError: invalid baudrate`. Only 9600/19200/38400/57600/115200/230400/
460800/921600 are accepted.

A PL2303 USB-TTL adapter (already on `/dev/ttyUSB0`) *does* accept 74880, so
`esp_tap.py` reads the banner there while the EC600U only resets the ESP.

## What did not work

The EC600M recipe (`WAKEUP_IN` high to bring up the VDD_EXT rail, then
`MAIN_RI` low for ESP EN) does **not** apply here. Driving GPIO25 high and
GPIO24 both ways, then re-reading all 47 GPIOs, produced **no change on any
pin** — the peripheral rail does not come up that way on this board.

## Tools in this directory

| File | Purpose |
|---|---|
| `qpy.py` | raw-REPL driver (`Qpy().exec(code)`) |
| `gpio_read.py` | read every GPIO hi-Z, classify floating / driven |
| `diff_levels.py` | same, but skips the enable pins so they stay asserted |
| `scan_uart.py` | passive listen + `AT` probe on each UART, closes ports |
| `esp_enable.py` | drive the candidate enable pins only |
| `sweep_esp_en.py` | drive each safe GPIO in turn, watch UART1/2/4 for life |

Logs land in `logs/`.

## ESP test pads

The board brings the ESP's **U0TXD and U0RXD** out to two test pads (found
while the original ROM was still running). That is ESP UART0 — the port the
ROM banner comes out of, the port ESP-AT listens on, and the port esptool
flashes through. It is 3.3 V, unlike the 1.8 V module side of the level
translator, so it is the right place to probe.

Because the ESP free-runs on a 2 s watchdog loop, no reset is needed to catch
a banner — connect and listen:

    PL2303 RX  <-  U0TXD pad
    PL2303 GND <-> board GND

`/dev/ttyUSB0` (PL2303) accepts 74880, which QuecPython cannot. `esp_listen.py`
reads there and decodes the `rst cause` / `boot mode` fields; it never touches
the REPL, so it can run while `gpio_panel.py` is up.

Do not wire PL2303 TX to U0RXD unless that adapter is confirmed 3.3 V — plenty
of PL2303 cables swing 5 V and would damage the ESP.

esptool 5.3.0 is installed, so reflashing the ESP through the same pads is
possible once GPIO0 can be held low at reset (the EC600U can supply the reset
itself by toggling GPIO44).

## Tools added later

| File | Purpose |
|---|---|
| `pinmap.py` | EC600U GPIO -> module pin / function / domain metadata |
| `gpio_panel.py` | local web panel on :8760 to drive any pin and sample UART2 |
| `boot_timing.py` | timestamp ESP bursts to tell a boot loop from a brownout |
| `esp_74880.py` | probe which non-standard bauds QuecPython accepts (none near 74880) |
| `esp_tap.py` | read the banner via PL2303 while the module resets the ESP |
| `esp_listen.py` | passive PL2303 listener, no REPL needed |

## Corrected: GPIO44 is a power switch, GPIO14 shares the rail

GPIO44 does not drive CH_PD — it switches the **3V3 rail feeding the ESP's
VDD3V3**, which is why every reset reports `rst cause:1` (power on).

GPIO14 sits on the same power path rather than being independent:

| GPIO14 | bytes seen in a 3 s window |
|---|---|
| before it was ever driven | 102–136 = 3–4 banners → boot loop |
| driven HIGH | **0** — ESP completely unpowered |
| driven LOW or released | **34 = exactly one banner**, and it stays that way |

Driving GPIO14 once permanently changed the ESP from boot-looping to booting
once and going quiet, so any sweep result recorded before and after it are not
comparable.

## The two crystal-related baud rates

One wire, two phases — not two links:

* The ROM computes its divisor assuming a 40 MHz crystal. This board has
  26 MHz, so the banner actually leaves at **74880** and reads as garbage when
  UART2 is opened at 115200.
* Once the application loads it fixes the divisor and UART0 becomes a true
  **115200**, and UART2 reads clean text.

`74880 × 40/26 = 115200` exactly. This gives a detector that needs no
74880-capable port: **clean text on UART2 @115200 means the firmware ran.**

## Ruled out

* **Off-time timing.** Cutting the rail for 150, 400, 800 or 2000 ms gives
  byte-for-byte identical results, so the earlier "the bulk cap has not
  drained" theory is wrong.
* **A strap pin among GPIO1–16.** Every one driven both ways, power-cycled,
  and watched — none reached firmware.

## ESP bootloader reachable over UART2

The ESP answers the ROM loader's SYNC over the module's own UART2 at 115200 —
11 replies out of 12 tries:

    sent  c0 00 08 24 00 00000000 07071220 55*32 c0
    got   c0 01 08 02 00 07071220 0000 c0

`0x01` marks a response, `0x08` echoes SYNC, trailing `00 00` is success. The
ROM measures the host rate from the 0x55 run, so 115200 works despite the
banner being at 74880.

This proves three things at once: the ESP is genuinely in UART download mode,
the module's UART2 **TX reaches the ESP's U0RXD** (the link is bidirectional),
and the ESP flash can be dumped or rewritten straight through the EC600U with
no extra wiring. `esp_sync.py` performs the handshake.

## ESP identity, read through the loader

`READ_REG` (0x0A) also works over UART2, so the loader is usable beyond SYNC.
Reading the eFuse block:

    0x3FF00050 = 0x61af0030
    0x3FF00054 = 0x0200b900
    0x3FF00058 = 0x2000b000
    0x3FF0005C = 0x04ec94cb

    -> MAC ec:94:cb:xx:xx:xx   (ec:94:cb is an Espressif OUI)

`esp_reg.py` does this.

## Dumping the flash

The bare ESP8266 ROM has **no read-flash command** — esptool implements
`read_flash` by first uploading a small stub into RAM
(`MEM_BEGIN`/`MEM_DATA`/`MEM_END`) and then talking to the stub. Two ways to
get a full 1 MB image:

1. **PL2303 straight to the pads** — wire `PL2303 TX -> U0RXD` in addition to
   the existing RX, then `esptool.py -p /dev/ttyUSB0 read_flash 0 0x100000
   esp_backup.bin`. Fast and uses the stock tool. Needs the adapter confirmed
   3.3 V first; many PL2303 cables swing 5 V and would damage the ESP.
2. **Through UART2 via the REPL** — possible, since SYNC and READ_REG already
   work, but every block costs a REPL round-trip, so a 1 MB image means
   hundreds of them.

Option 1 is much better if the adapter's level is right.

## Getting the ESP to actually run — solved

The GPIO0 strap is held low by the board and no module pin overrides it, so
the ESP powers up in UART download mode every single time. Rather than fight
the strap, ask the ROM loader to hand over — the same thing esptool's `run`
does:

    power-cycle GPIO44   (switches the ESP's 3V3 rail)
    SYNC                 (x8; also sets the ROM's baud from the 0x55 run)
    FLASH_BEGIN 0,0      (erase_size 0 - nothing erased, only enters flash mode)
    FLASH_END 0          (reboot into the application)

`FLASH_END` on its own is refused with status `01 06` and the ROM then panics
with `ets_main.c`; esptool's source carries the same warning. With the no-op
`FLASH_BEGIN` first it works, and the app announces itself with `\r\nready\r\n`
at a true 115200.

`esp.py` implements this. Everything below was done through it, with no wiring
beyond what the board already has.

## ESP firmware and state

    AT version : 2.2.2.0-dev (ESP8266, Jun 29 2022)
    SDK        : v3.4-49-g696ef14c
    Bin        : 2.2.1(WROOM-02-N)  MFVER:V5.1.3
    MAC        : ec:94:cb:xx:xx:xx   (matches the eFuse-derived value exactly)
    free RAM   : 41828 of 47148

Verified working end to end:

* WiFi join, DHCP, and `AT+PING="8.8.8.8"` -> 23 ms
* MQTT to broker.emqx.io:1883 - connect, subscribe, publish, and the published
  message came back via `+MQTTSUBRECV`, so both directions work

## Flash layout — read this before reflashing anything

    factory_param        0xf1000   0x1000
    server_cert/key/ca   0xf2000 - 0xf7fff
    client_cert/key/ca   0xf8000 - 0xfdfff
    wpa2_cert/key/ca     0xfe000 - 0x103fff
    mqtt_cert/key/ca     0x104000 - 0x109fff

Partitions run past 0x100000, so the part has **2 MB** of flash, not the 1 MB
an ESP8285 usually carries.

Those partitions hold this unit's own TLS material for VNPay's backend plus
its factory parameters. They are per-device and cannot be regenerated. A stock
ESP-AT image would overwrite them, and no dump of this device exists.

## GPIO panel over WiFi, no serial

`onboard/esp_web.py` runs on the module and serves the panel through the ESP:

    browser --WiFi--> ESP8285 --UART2--> EC600U --> GPIO

Installed as `/usr/main.py`, so it starts with the module and needs no host
connection at all. Open **http://192.168.1.243/**.

    /                 the panel
    /set?g=N&m=1|0|2  drive GPIO N high / low / hi-Z
    /read?g=N         read it hi-Z and classify floating / driven

Guards: GPIO7 and GPIO19 are refused because they are UART2, the link the
request itself rides on; GPIO44 cannot be driven low or read, since either
cuts the ESP's 3V3 rail and takes the page down.

### Things that cost time here, worth remembering

* **`machine.reset()` does nothing on this build.** USB never drops. Every
  "reset" was a no-op, so `usys.modules` kept a stale `esp_web` and the old
  code kept running no matter what was uploaded. Use
  `misc.Power.powerRestart()`, which really does reboot (the REPL read fails
  mid-call, and that failure is the confirmation).
* **`/usr/main.py` does autorun**, verified with a marker file.
* **`_thread.start_new_thread` produced no output and no listener**, and
  handing the code to the raw REPL then closing the port kills it. Running as
  `main.py` is what works.
* **This MicroPython's `bytearray` has no `.find()` and no slice deletion.**
  The receive buffer is plain `bytes`, rebuilt by slicing.
* **`bytes.split("\r\n")` is a TypeError** - the separator must be bytes. This
  crashed the server on its first request, right after it logged "listening".
* **AT responses and `+IPD` share one stream.** Waiting for a marker from
  offset zero, or clearing the buffer between commands, ate the next request
  and made every second response empty. `wait_for()` searches only from the
  offset recorded at write time and removes just the matched region.
* Progress goes to `/usr/weblog.txt` as well as stdout; with no console
  attached to `main.py` a print alone leaves no trace.

**Opening the REPL stops the server.** `qpy.py` sends Ctrl-C on connect to get
into raw mode, and that interrupts `main.py`. Anything that constructs `Qpy()`
- including reading `/usr/weblog.txt` - takes the panel down until the next
`misc.Power.powerRestart()`. Read state over HTTP instead while it is serving.

### Behaviour and limits of the WiFi panel

Measured over 24 requests spaced ~1.2 s apart: **22 succeeded**. The two
failures were both GPIO25.

* **Space requests out.** Clicking at human speed is fine. Firing them
  back-to-back makes some come back empty - the ESP-AT server needs a moment
  between connections, and a reply that lands late goes to a reused link id.
* **GPIO25 (WAKEUP_IN, pin 49) breaks the ESP link when driven.** The panel
  notices, rebuilds the link, and drops whatever was queued, so it recovers on
  its own within about 10 s. Expect one or two dead requests around it.
* **GPIO22 (MAIN_DCD, pin 48) now reads driven HIGH**, which it did not in the
  original hi-Z survey taken while the ESP was unpowered.

### What the WiFi panel is good for, and what it is not

It works well for **deliberate, one-pin-at-a-time probing**: 22 of 24 spaced
requests succeeded, and reads/sets return correct values.

It is **not reliable as a bulk sweep tool**. Sweeping ~15 pins in a row landed
26 of 45 requests and then left the ESP unable to boot at all - repeated
`booting ESP, attempt 1..4` / `ESP never reached firmware` in `weblog.txt`,
with no recovery for over 75 s. `misc.Power.powerRestart()` brings it straight
back.

The reason is structural, not a bug that can be tidied away: the panel probes
GPIOs using a transport that runs *through* those same GPIOs. GPIO25
(WAKEUP_IN) and GPIO26 (AP_READY, the pin that reaches the ESP's straps on the
EC600M board) break the link when driven, and once the ESP will not boot the
panel has no way left to talk to anything.

Three recovery layers are in place and each helped, but none can cover that
last case:

1. release the pin just driven, and retry
2. an idle watchdog - if nothing arrives for 20 s, test the link and rebuild
3. release every held pin if the ESP fails to boot on the first attempt

**For sweeping many pins, use the USB-serial tools instead** (`gpio_panel.py`
on localhost, or `strap_find.py`), where the transport is independent of the
pins under test. Keep the WiFi panel for checking or toggling a pin once the
interesting ones are known.

---

# Consolidated pin map

Everything below was established in this session. The module is an
**EC600U-EUAB**: same LCC footprint as the EC600M board, so module pin numbers
match, but the GPIO indices differ — that mismatch is the easiest thing to get
wrong when carrying notes across.

## ESP8285 interface — confirmed by experiment

| EC600U | Module pin | Default function | Role on this board |
|---|---|---|---|
| **GPIO44** | 14 | spi_camera_si_0 | **Switches the ESP's 3V3 rail. Active HIGH.** |
| **GPIO14** | 54 | NET_STATUS | Also on the ESP power path. HIGH = ESP fully unpowered. |
| — | **31** | MAIN_RXD | **← ESP U0TXD** (pins 31/32 cannot be muxed as GPIO) |
| — | **32** | MAIN_TXD | **→ ESP U0RXD** |
| GPIO25 | 49 | WAKEUP_IN | Breaks the ESP link when driven high. |
| GPIO26 | 50 | AP_READY | Implicated in the ESP failing to boot after being driven. |

Evidence, in order of strength:

* GPIO44 was the **only** hit in a sweep of all 47 GPIOs at both levels; and it
  matches what was found on the board: it gates a 3V3 switch feeding the ESP's
  VDD3V3. That is why every ESP reset reports `rst cause:1` (power on).
* GPIO14: driven HIGH gives **0 bytes** from the ESP; LOW or released gives
  **34 bytes = exactly one banner**. Driving it once also changed the ESP from
  boot-looping to booting once and staying quiet.
* Pins 31/32 are `machine.UART.UART2`. Both directions proven: the ESP's boot
  banner and AT replies arrive here, and the ESP answers our ROM-loader SYNC
  and AT commands, so our TX genuinely reaches its U0RXD.
* GPIO25 and GPIO26 are weaker: both were observed to break things, but their
  exact function was never isolated.

## Externally driven pins

Measured as high-impedance inputs with the internal pull-up, then the
pull-down — nothing was driven, so these levels come from the board itself.
Taken while the **ESP was unpowered**:

| Level | Pins |
|---|---|
| Driven HIGH | GPIO2 (pin 58, i2s2_lrck), GPIO40 (pin 100), GPIO41 (pin 120) |
| Driven LOW | GPIO23 (pin 39, MAIN_DTR), GPIO24 (pin 40, MAIN_RI), GPIO35 (pin 137), GPIO36 (pin 62) |

With the **ESP running**, GPIO22 (pin 48, MAIN_DCD) additionally reads driven
HIGH. So this table is state-dependent and should be re-measured in whatever
state matters.

## Not connected

GPIO7 (pin 123) and GPIO19 (pin 124) — the module's *other* UART port, `uart_1`
in SoC naming, "UART2" in Quectel's pin naming — both float. Nothing is wired
to that port on this board.

## Module-level pins

| Pin | Signal | Note |
|---|---|---|
| 55 | USB_BOOT | Pull to VDD_EXT through 4.7 kΩ **before** power to force download mode. 1.8 V domain, active high. |
| 76 | VDD_EXT | 1.8 V output |

## ESP8285 side

* **U0TXD / U0RXD are brought out to test pads**, at 3.3 V — the right place to
  probe, unlike the 1.8 V module side of the level translator.
* **Boot mode is set by GPIO26 (module pin 50, AP_READY).** Held LOW the ESP
  flash-boots; high or floating it powers up in UART download mode
  (`boot mode:(1,7)`). QuecPython leaves it floating, which is why the ESP
  looked permanently stuck. See "SOLVED" below — the ROM-loader handover in
  `esp.py` is now only a fallback.
* MAC `ec:94:cb:xx:xx:xx`; **2 MB** flash (partitions extend past 0x100000).

## Still unknown

Nothing here identifies the audio path, the speaker amplifier enable, the
status LED, or any button. GPIO2 being driven high is `i2s2_lrck` by default,
which would fit an I2S codec on a speaker box, but that is a guess from the
pin's default function and was never tested. GPIO35/36 (V_LCD domain) and
GPIO40/41 are driven but their purpose was never established.

---

# How many UART links to the ESP?

**Only one link was ever demonstrated**, and the "two UARTs" in the original
description remains unverified.

## What is proven

A single bidirectional link: **EC600U pins 31/32 (`machine.UART.UART2`, the
MAIN UART) <-> ESP UART0 (U0TXD/U0RXD)**. Both directions were exercised — the
ESP's ROM banner and AT replies arrive on it, and the ESP answers our
ROM-loader SYNC and our AT commands over it.

## What argues against a second link

* `UART1` and `UART4` on the module were listened to and probed at 9600, 19200,
  38400, 57600, 115200, 230400, 460800 and 921600 — **silent at every rate**.
* GPIO7 (pin 123) and GPIO19 (pin 124), the module's only other GPIO-accessible
  UART port, both **read floating**, so nothing is wired to them.
* The **test pads are on ESP U0TXD/U0RXD** — the same UART0 that reaches pins
  31/32. Reading 74880 at the pad and 115200 at the module is not two links: it
  is one line before and after the application fixes the ROM's divisor
  (`74880 x 40/26 = 115200`). The pads look like probe points on the existing
  link, not a separate channel.

## What cannot be ruled out

The module's **DEBUG UART (pins 71/72)** was never tested. Quectel documents it
as log output that cannot be used as a general purpose UART, and QuecPython
cannot open it, so no software test was possible. If the ESP's UART1 (GPIO2,
TX-only) does feed a log line into the EC600U, pins 71/72 are where it would
land — and that would only ever be readable by tapping them physically.

Settling this needs continuity checks on the bare board: ESP GPIO2 against
module pin 71/72, and the U0 lines against pins 31/32.

## Bootlog and control share one wire

The natural reading of "one UART for the log, one for control" is that they are
separate lines. That is not what was measured: **both appeared on pins 31/32.**

* The ESP's ROM boot banner arrived on `UART2` — first as garbage at 115200
  (because the ROM emits it at 74880), and later decoded cleanly once the
  application had fixed the divisor.
* The `ets Jan 8 2013 / rst cause / boot mode / load 0x40100000 / csum` lines
  were read there too.
* AT commands and their replies use that same port.

This is simply how an ESP8266/8285 behaves: **UART0 carries the ROM bootlog and
the AT command channel** — the ROM prints to it, then ESP-AT listens on it. One
wire pair does both jobs, and the test pads sit on those same U0 lines.

So if the board really does have a second pair, it is not "the log" in the
bootlog sense. The candidate is the ESP's **UART1 (GPIO2, TX only)**, which is
where the ESP-AT *application* sends its own debug prints in some builds - a
different stream from the ROM bootlog, and one-way. On the module side that
would land on the DEBUG UART, pins 71/72, which QuecPython cannot open.

# Is there a pin that controls the ESP's boot mode?

**Superseded — a pin was found: GPIO26 (pin 50, AP_READY). See "SOLVED"
below.** The section is kept because the reasoning about how download mode is
reached is still correct, and because it records where the search went wrong.

## Download mode is the default here

The ESP's GPIO0 is held low by the board, so **every power cycle lands it in
UART download mode** (`boot mode:(1,7)`) on its own. Cutting and restoring the
3V3 rail with GPIO44 is all it takes to get there. The hard direction is the
opposite one — getting it *out* into the application — and that is what the
ROM handover in `esp.py` is for.

A useful consequence: **flashing the ESP through the EC600U needs no boot pin
at all.** The loader is reachable over UART2 the moment the ESP powers up.

## What was searched, and how

All 47 GPIOs, both levels, power-cycling the ESP each time and checking
whether the firmware started. Two independent detectors agreed:

* `strap_sweep.py` - readable ASCII on UART2 at 115200. This is a sound test:
  the ROM emits 74880, but once the application runs it reprograms the divisor
  to a true 115200, so readable text means, and only means, that flash boot
  happened. All 47 pins covered. **No hit.**
* `strap_find.py` - the same signal, re-run more carefully after the boot
  behaviour was better understood. Covered GPIO1-16. **No hit.**

`strap_sweep74880.py` was written to read the ROM's `boot mode:(N,M)` field
directly through the PL2303 tap, which would have been the most direct
evidence, but it never produced usable data - captures came back as runs of
`\x00`, a fault in how it reset the ESP that was not chased down.

## Conclusion

**This conclusion was wrong.** It was reached only because GPIO26 had been
excluded from every sweep — excluded, ironically, for reading as "driven",
which was the module driving it. GPIO26 (pin 50, AP_READY) controls the strap;
no PCB resistor is involved.

## Gap in the strap search: 13 pins were never driven

`strap_sweep.py` covered 33 of 47 GPIOs. The other **13 were skipped**, on two
assumptions that were both wrong:

    never driven: 2, 3, 7, 18, 19, 20, 21, 23, 24, 35, 36, 40, 41

* Skipped as "externally driven" (2, 23, 24, 35, 36, 40, 41) to avoid output
  contention. But a pin reading as driven does not prove an *external* circuit
  holds it — the module may be driving it itself. Quectel's GPIO sheet says
  pins 39, 40, 48, 49, 50 "have a 3 V output voltage and a level jump when the
  module is just turned on", and GPIO22-26 are the `sdmmc1_*` group, driven by
  the SD controller whenever that peripheral is enabled no matter how Pin() is
  configured.
* Skipped as "UART pins" (3, 7, 18, 19, 20, 21) to protect the link being read.
  The link is `UART2` on module pins **31/32**, which cannot be muxed as GPIO
  at all, so no GPIO can disturb it. Those six are pins 34/123/33/124/122/121
  on a different port, and GPIO7/GPIO19 read floating anyway.

This matches the idea that the default QuecPython firmware simply leaves a pin
in the wrong state: **GPIO24 (pin 40, MAIN_RI) and GPIO23 (pin 39, MAIN_DTR)
are both being held low right now**, and MAIN_RI is exactly the pin that drove
the ESP on the EC600M board.

`strap_untested.py` runs the proper test on those 13 - cut the ESP rail with
GPIO44, set the candidate, restore the rail, and check whether readable text
appears at 115200 (which only happens on a flash boot). Run it over USB serial
with the board reassembled; it does not depend on the ESP link staying up.

---

# SOLVED: GPIO26 (pin 50, AP_READY) controls the ESP boot mode

Driving it **LOW makes the ESP flash-boot**. High or floating forces UART
download mode. Confirmed with a clean, repeated contrast — each row is a full
power cycle of the ESP's rail via GPIO44, reading UART2 at 115200:

    GPIO26 = HIGH   194 -> 152 bytes   ready=False   ROM banner only
    GPIO26 = hi-Z          152 bytes   ready=False   same as HIGH
    GPIO26 = LOW           194 bytes   ready=True    'ready / WIFI CONNECTED'
    GPIO26 = HIGH          152 bytes   ready=False
    GPIO26 = LOW           194 bytes   ready=True

With it held low the ESP not only boots, it auto-joins the stored WiFi on its
own. No ROM handover needed.

This is exactly the "the default firmware just leaves a pin in the wrong
state" explanation: QuecPython leaves AP_READY floating, so the ESP never
flash-boots. It is **not** a hard-strapped resistor, and the earlier
conclusion in this file that said so was wrong.

## Why the sweeps missed it, twice

1. `strap_sweep.py` skipped GPIO26 - it was in the "externally driven / UART"
   exclusion set built from the hi-Z survey. Excluding a pin because it reads
   as driven was the mistake: the module itself was driving it.
2. When `strap_untested.py` finally did hit it, the first verification run
   scored the capture as "rom-only" and nearly threw the result away. That
   check demanded >=80% printable, but a successful boot capture contains the
   **ROM banner at 74880 (garbage at 115200) followed by the application's
   clean output**, which lands around 45%. Percent-printable is the wrong
   metric here - searching for the literal `ready` is the right one.

Note also GPIO22 (pin 48, MAIN_DCD) at LOW dropped the capture from 152 to 34
bytes - one banner instead of several. Not a boot-mode change, but it does
affect the ESP somehow, and was never followed up.

---

# Audio: SOLVED — the speaker plays out loud

Two conditions have to hold at the same time. Every earlier attempt in this
file satisfied at most one of them, which is why the box stayed silent through
months of pin sweeps.

```python
from machine import Pin
import audio

# 1. wake the amplifier - GPIO13 is the HT8313's CTRL line
Pin(Pin.GPIO13, Pin.OUT, Pin.PULL_DISABLE, 1)

# 2. route the codec at the loudspeaker
a = audio.Audio(2)
a.set_channel(2)
a.setVolume(1)          # 1 is already loud, see below
a.play(1, 0, 'U:/say.mp3')
```

`audio_play.py` is this, from the laptop.

**The routing is the part nobody had tried.** `set_channel` is never called
anywhere else in this file. Without it the codec biases SPK_P/SPK_N to 1.5 V
but puts no signal on them — measured as 0 mV AC across the pair while an MP3
was demonstrably decoding — so the amplifier has nothing to amplify no matter
what its enable pin is doing.

**The enable pin is GPIO13**, module pin 2, default function `spi_0_di`. That
is one of the four `spi_0` pins that every sweep in this repo skipped on
purpose — `speaker_test.py` lists "10, 11, 12, 13 spi_0" under "pins
deliberately left alone". Only SPI1 is wired here, to the NOR; spi_0 is free,
and the board uses one of its pins for the amplifier. The single blind spot.

**Volume 1 is already loud.** The HT8313 has a fixed 28 dB gain that
`setVolume` cannot reach, so the top of the 0-11 range overdrives the speaker
into what sounds like a continuous tone rather than audio. That tone was
briefly mistaken for success.

## Measured, with a meter on the HT8313

The chip is 10-pin, not the 8-pin part the EC600M notes describe:
**PVBAT, AVBAT, PVDD, IN+, IN−, OUT+, OUT−, CP, CN, CTRL**.

| Pin | At rest | Amplifier awake |
|---|---|---|
| PVBAT, AVBAT | 5 V | 5 V — always powered, not off the switched rail |
| **CTRL** | **0 V** | **1.8 V** |
| PVDD | 0 V | 5 V — the internal charge pump only runs once CTRL is high |
| CP, CN | 0 V | switching |
| IN+, IN− | 0 V | 1.3 V each — the input stage self-biases |
| OUT+, OUT− | 0 V | drives the speaker |

One cause, four consequences: CTRL low keeps the charge pump down, so PVDD is
absent, so the output bridge has no supply. Reading OUT+/OUT− at 0 V never
meant a missing signal; it meant the chip was asleep.

**1.8 V on CTRL is enough.** The module's GPIOs are a 1.8 V domain and the amp
runs on 5 V, so a level shifter looked likely — PVDD coming up to 5 V proves
it is not needed.

Two things that confirmed the analog path before any sound was heard: the
speaker measures **4 Ω** and is healthy, and once the amplifier was awake,
*touching a meter probe to IN+/IN−* injected enough hum to make the speaker
buzz audibly. Amplifier and speaker were fine all along.

## CTRL latches, and that cost hours

Once CTRL has been raised it **stays at 1.8 V until the board loses power**.
Driving GPIO13 low again does not clear it. Neither does driving all 39 safe
pins low and holding them there for five seconds. Whatever holds the node up
is not the pin, and nothing in software brings it down.

The practical damage: after one successful run, every later run appears to work
with no pins driven at all, so the pin looks unnecessary. This produced two
false "solved" conclusions before a full power cycle exposed it. **Any claim
about what audio needs has to be tested on a freshly powered board.**

It also shapes how the pin was found. Bisecting is asymmetric here: a negative
result leaves CTRL at 0 V and the next subset can be tried immediately, but a
positive result latches and the board has to be power-cycled before
subdividing. 39 pins came down to GPIO13 in three power cycles.

## Corrections to earlier work here

* **"Sound was heard while sweeping 5, 6, 8, 9, 15, 16, 17, 18" never
  happened.** No MP3 was ever audible before this. Everything built on that
  sentence — including narrowing the HT8313 shutdown pin to 5, 6, 8, 9, 17, 18,
  and `PA_CANDIDATES` in `pinmap.py` — was founded on nothing.
* **The enable pin is real and is called CTRL**, contradicting the guess that
  the PA is on by default and there was never a pin to find.
* **`set_pa` does not mute anything.** `a.set_pa(15)` returned 1, and the
  speaker worked later in the same session with no reboot in between. The
  EC600M warning does not carry over.
* **`aud_tone_play` still produces nothing** even with the amplifier awake and
  the channel routed. MP3 only.

## What is still open

* **What holds CTRL up after GPIO13 is released**, and why driving it low does
  not undo that. A diode or a transistor between pin and CTRL would explain a
  one-way path; so would a latch inside the amplifier. Not investigated.
* **Whether `audio.Audio(2)` or `set_channel(2)` is the operative half**, or
  both. Both were changed at once and neither was tested alone on a freshly
  powered board.
* **`setGainTabel`** takes an ID and a gain per volume step and would reach
  below what volume 0 gives, if the box is still too loud. Its call signature
  was never worked out — it rejects an empty call with `ValueError: Please
  enter complete parameters, including the gain corresponding to ID and volume
  (0-11)`.
## Resolved: long.mp3 "never ends"

It ends fine. The file is **75.1 s**, not the 30.0 s an early measurement here
claimed, so a 31 s window never reached it.

That number was wrong because the MP3 parser used MPEG1 constants on MPEG2
files. Both differ, and both matter:

| | MPEG1 layer III | MPEG2 / 2.5 layer III |
|---|---|---|
| Samples per frame | 1152 | **576** |
| Bitrate index 5 | 64 kbps | **40 kbps** |

These files are MPEG2, mono, 16 kHz — so a frame is 36 ms, not 72 ms. With the
right tables the frames tile the file exactly, last frame ending on the final
byte, and the durations match what the board reports:

| File | Parsed | Board's end event |
|---|---|---|
| `say.mp3` | 3.24 s | 3.43 s |
| `beep.mp3` | 3.13 s | — |
| `long.mp3` | 75.13 s | — |

The residual ~0.2 s is encoder padding and decoder delay. `trim_mp3.py` has
the corrected tables.

## Method note

Every attempt before this one asked a human whether they could hear anything,
and a silent result could mean the pin was wrong, the routing was wrong, the
amplifier was dead, or the speaker was unplugged. Four unknowns, one bit of
feedback per run, and no way to tell them apart.

A meter on the amplifier's own pins collapses that. PVBAT said it had power.
CTRL said it was asleep. PVDD following CTRL said the enable worked and 1.8 V
logic was sufficient. IN+/IN− biasing said the input stage was alive, and
buzzing under a probe said the speaker was too. Only then was silence
diagnostic: everything downstream was proven good, so the fault had to be
upstream, and 0 mV AC on SPK_P/SPK_N pointed at the codec.

The same instrument then replaced listening entirely for the pin hunt. Reading
CTRL is one unambiguous bit per run; hearing a tone is not.

## Earlier findings that still hold

MP3 playback runs correctly. The proof is the callback timing, not the return
value:

    a = audio.Audio(0); a.setCallback(cb); a.setVolume(11)
    a.play(1, 0, 'U:/say.mp3')
    -> events [(44, 0), (3300, 7)]      # start at 44 ms, end at 3.30 s

3.30 s is exactly the length of the file. Same on device 0, 1 and 2.

**Event 0 is start, event 7 is end.** An earlier note in this file called 7 an
error - that was wrong, and it sent the whole investigation sideways. With WAV
and with `aud_tone_play` the 7 arrives after ~270 ms because those finish
immediately, not because they fail.

* **WAV is not decoded** - it "plays" for 270 ms and stops. Only MP3 works.
  The EC600M notes already said this; it was not read carefully enough.
* `pa_sweep.py`, `speaker_test.py` and `audio_path.py` were built on the
  premise that an unfound enable pin was the whole problem. They sweep pins
  while playing `aud_tone_play`, which is silent regardless. Superseded by
  `audio_play.py` and `ctrl_probe.py`.

## What has been ruled out

* **All audio AT commands are stripped from this firmware.** Through
  `atcmd.sendSync`: `AT+CLVL?`, `AT+QAUDMOD?`, `AT+QTTS=?`, `AT+QAUDLOOP=?`
  all return `+CME ERROR: 58`, while `ATI` answers normally. So there is no
  mic-to-speaker loopback available to test the analog path with, and no TTS.
* **No I2C device on any bus.** I2C0-I2C3, addresses 0x08-0x77: nothing
  acknowledges.
* **Nothing on UART1 or UART4.** Probed at 9600/19200/38400/57600/115200 with
  JQ8400, DFPlayer and WT588 style command frames - silent everywhere.
* **Not I2S.** The EC600U's i2s2 lines are GPIO1/2/30/4, which are the SPI1
  pads the NOR flash uses.

Taken together the separate audio chip has no digital control interface the
module can reach, which is what a plain class-D amplifier looks like: analog
in, an enable pin, speaker out. That reading was correct — the enable pin is
CTRL, on GPIO13 — but the conclusion drawn from it, that finding the pin would
produce sound, was not. The pin was only half the problem.

---

# Buttons: M, +, − — identified

Found by scanning all 47 GPIOs with the internal pull-up and pull-down while
each button was held, and diffing against a released baseline.

| Button | EC600U GPIO | Module pin | Default function |
|---|---|---|---|
| **M** | **GPIO28** | 52 | `sim_2_dio` |
| **+** | **GPIO27** | 53 | `sim_2_clk` |
| **−** | **GPIO16** | 56 | `i2c_1_sda` |

**They are active HIGH**, not active low: pressing drives the pin high, and
releasing leaves it floating. So they must be read with the **pull-down** on —
released reads 0, pressed reads 1:

```python
from machine import Pin
m     = Pin(Pin.GPIO28, Pin.IN, Pin.PULL_PD)
plus  = Pin(Pin.GPIO27, Pin.IN, Pin.PULL_PD)
minus = Pin(Pin.GPIO16, Pin.IN, Pin.PULL_PD)
print(m.read(), plus.read(), minus.read())     # 1 while that button is held
```

Confirmation for M was 8 of 8 samples high while held and 8 of 8 floating once
released; + and − were 3 of 3 each.

## Two guesses that were wrong

* **The EC600M mapping does not carry over.** That board has M/+/− on module
  pins 69/70/57, **active low**. This board uses pins 52/53/56, active high —
  different pins *and* inverted sense. Suggesting `PULL_UP` and pins 5/6/15
  from those notes was wrong on both counts.
* **They are not all on the SIM2 cluster.** After M and + landed on pins 52 and
  53, − was predicted on pin 51 (`sim_2_rst`, GPIO29). It is actually GPIO16 on
  pin 56, an I2C pin.

That GPIO16 is a button also explains the empty I2C scan: `i2c_1_sda` has a
button on it, not a bus.

## A caution about the level map

GPIO41 read driven HIGH at the start of the session, driven LOW in a later
sweep, then HIGH again — it flips between captures and should not be trusted
as a fixed state. GPIO5 and GPIO6 likewise read low right after `pa_pin_hunt`
drove them, then floating once settled; a reading taken immediately after
driving a pin is not a reliable baseline.

## LED hunt: both polarities swept, nothing identified yet

Every GPIO except 44 (the ESP rail switch) was driven for 1.2 s and released,
once LOW and once HIGH - 46 pins each pass, no errors. Which pin lights an LED
is still unanswered, because that needs somebody watching.

Worth knowing before the next attempt:

* The EC600M board's LEDs are a common-anode RGB, **active low**, on module
  pins 58/60/61. Those pins are not free here - on this board they are SPI1,
  the NOR flash bus - so that mapping cannot transfer.
* `misc.net_light(1)/(0)` drove the green network LED on the EC600M board. It
  was attempted here but the module dropped off USB during that run, so **that
  result does not count** and needs redoing.
* A network-status LED may simply never light: there is **no SIM in the
  board**, so it has nothing to indicate.

## Tooling fixes made along the way

`qpy.py` resolved the REPL port once at import. The ttyUSB numbering shifts
whenever anything else is plugged or unplugged, so that constant went stale
repeatedly and cost several failed runs. It now resolves **per connection**.

It also returned a hardcoded `/dev/ttyUSB7` when it could not find the module,
which surfaced as a misleading "no such file: ttyUSB7" instead of the truth. It
now raises:

    OSError: module 2c7c:0901 not found on USB - check it is plugged in

## LED found: GPIO15 (module pin 57) is the red LED

Driving **GPIO15 HIGH lights the red LED**. Module pin 57, default function
`i2c_1_scl`. Active high, like the buttons and unlike the EC600M board, whose
LEDs are active-low on pins 58/60/61 - pins that are the NOR's SPI1 bus here.

A sweep of the remaining 28 unknown pins driven HIGH (3, 5, 6, 8, 9, 10, 11,
12, 13, 17, 18, 20, 21, 22, 25, 29, 31, 32, 33, 34, 37, 38, 39, 42, 43, 45, 46,
47) turned up no other colour. So either the indicator is single-colour, or the
other colours sit on one of the pins deliberately excluded from the sweep:
GPIO14 (pin 54, NET_STATUS - driving it high kills the ESP), or the
externally-driven group GPIO23/24/35/36/40/41.

This also **shrinks the amplifier hunt**. Sound was heard while sweeping
5, 6, 8, 9, 15, 16, 17, 18; GPIO15 is the LED and GPIO16 is button "-", so the
HT8313 shutdown pin is among **5, 6, 8, 9, 17, 18**.

---

# The box as an MQTT device

With audio working and the ESP already proven on MQTT, the box runs standalone:
red LED on at boot, battery and buttons published, volume driven from a laptop
page. Nothing goes over USB.

    browser --WSS--> broker.emqx.io <--TCP-- ESP8285 <--UART2--> EC600U

`onboard/box_mqtt.py`, uploaded as `/usr/main.py`, so it starts with the
module. `mqtt_panel.html` is the laptop side and needs no server - open the
file. `mqtt_probe.py` does the same from a terminal, which matters because
attaching the REPL sends ctrl-C and kills whatever `main.py` is doing.

State on `<prefix>/state` every second and on every change; commands on
`<prefix>/cmd` as one `key=value` per message — `vol=3`, `vol=+1`, `ping`,
`play=say.mp3`, `led=0`.

    {"mv":4180,"pct":97,"vol":1,"btn":"","led":1,"up":64}

## Things worth knowing before changing it

* **The broker is public and unauthenticated.** Anyone with the prefix can read
  the box and drive it. The random suffix is obscurity, not security. The box
  picks it at first boot and keeps it in `/usr/mqtt_id.txt`.
* **`AT+MQTTPUBRAW`, not `AT+MQTTPUB`.** The state payload is JSON, full of
  quotes and commas, which the quoted-string form mangles. PUBRAW takes a
  length and then the bytes, like CIPSEND.
* **`+MQTTSUBRECV:0,"topic",<len>,<data>` has to be parsed by length.** The
  payload can hold commas and newlines, so splitting on them loses messages.
* **Buttons need edge detection.** Polling level alone repeats the action for
  as long as a button is held; volume walked itself to 0 the first time.
* **Interrupt the previous beep.** `stopAll()` before playing the confirmation
  tone, or holding `+` queues one beep per step and they play long after the
  volume stopped moving.
* `espnet.py` has to be uploaded too - `box_mqtt.py` imports it, and `/usr` is
  not on `usys.path`, so the import only works after `usys.path.append('/usr')`.

## The confirmation beep

`beep.mp3` is 3.1 s of speech-like noise; cutting it short just gives a shorter
piece of the same thing. `make_tone.py` synthesises a clean one instead - a
sine with a 4 ms attack and an exponential decay, encoded to match what the
module decodes (MPEG2, mono, 16 kHz). Without the envelope both ends click.

There is no MP3 encoder in the standard library, so this needs `lame`
(`brew install lame`, 1.9 MB). Generating the WAV is pure Python.
