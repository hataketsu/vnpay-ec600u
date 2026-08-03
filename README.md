# VNPay notification speaker box — EC600U + ESP8285

Reverse engineering of a VNPay payment-notification speaker box, and running
[QuecPython](https://python.quectel.com/) on it.

The box is a Quectel **EC600U-EUAB** (UNISOC UIS8910) with an **ESP8285**
running ESP-AT as its WiFi front end, an HT8313 class-D amplifier, a 16 MB SPI
NOR flash, three buttons and an LED. The stock vendor firmware has been
replaced with QuecPython, so the whole board is now scriptable from a
MicroPython REPL — including the ESP, which the module drives over UART2.

`NOTES.md` is the working log: how download mode was reached, how the ESP boot
strap was found, every pin that was probed and what it turned out to be.
`CHEATSHEET.md` is the short version.

## What works

* QuecPython V0003 flashed over USB_BOOT / BSL, IMEI and RF calibration intact
* Full control of the ESP8285 — power rail, boot mode, ESP-AT command channel
* WiFi join and an MQTT publish/subscribe round trip, driven from the module
* A GPIO control panel served **over WiFi by the board itself**, no USB in the
  path: `browser → ESP8285 → UART2 → EC600U → GPIO`
* **Sound out of the speaker**, loud — `python3 audio_play.py`
* **The box as a standalone MQTT device**: red LED on at boot, battery and
  buttons published, volume driven from a laptop page, no USB in the path
* Buttons, LED, and the SPI NOR identified
* Driven from Linux or macOS; on macOS the REPL is reached over libusb

## Pin map

| Function | GPIO | Module pin | Notes |
|---|---|---|---|
| LED, red | 15 | 57 | HIGH = lit |
| Button M | 28 | 52 | HIGH = pressed |
| Button + | 27 | 53 | HIGH = pressed |
| Button − | 16 | 56 | HIGH = pressed |
| ESP 3V3 rail switch | 44 | 14 | HIGH = powered |
| ESP boot strap | 26 | 50 | LOW = flash boot, floating = UART download |
| Shares the ESP rail | 14 | 54 | driving it HIGH drops the ESP |
| SPI1 → 16 MB NOR | 1, 2, 4, 30 | 61/58/60/59 | GPIO2 is chip select |
| UART2 ↔ ESP UART0 | — | 31/32 | not GPIO-muxable |

Note this board is **active high** for both the buttons and the LED, the
opposite of the related EC600M box.

## Getting sound

Two conditions, and both are needed:

1. **GPIO13 high.** That is the HT8313's CTRL pin (module pin 2, `spi_0_di`).
   Low, and the amplifier stays in shutdown: its charge pump never starts, so
   PVDD, CP, CN and OUT± all sit at 0 V. Driving it puts CTRL at 1.8 V and
   PVDD at 5 V — the module's 1.8 V domain clears the threshold, no level
   shifter needed.
2. **Codec routed to the loudspeaker**: `audio.Audio(2)` with `set_channel(2)`.
   Left alone it biases SPK_P/SPK_N to 1.5 V and puts no signal on them, so the
   amplifier has nothing to work with even when awake.

```sh
python3 audio_play.py say.mp3
```

Volume 1 of 11 is already loud — the HT8313 adds a fixed 28 dB that
`setVolume` cannot reach. Only MP3 decodes; WAV stops after 270 ms and
`aud_tone_play` is silent.

**CTRL latches.** Once raised it stays at 1.8 V until the board loses power,
and driving GPIO13 low does not clear it. So any run after the first appears to
work with no pins at all. Test audio claims on a freshly powered board or they
mean nothing.

Still open: what holds CTRL up after the pin is released, whether `Audio(2)` or
`set_channel(2)` is the operative half, and what GPIO 23, 24, 35, 36, 40, 41
are for.

## Layout

```
qpy.py               raw-REPL driver; everything else builds on it
pinmap.py            pin metadata, one place
audio_play.py        play an MP3 out loud
battery.py           read the cell voltage, estimate a percentage
ctrl_probe.py        hold pins high so the HT8313's CTRL can be metered
make_tone.py         synthesise a confirmation blip (needs lame)
trim_mp3.py          cut an MP3 at a frame boundary, no re-encode
mqtt_panel.html      laptop UI for the box, over MQTT; just open it
mqtt_probe.py        the same over the terminal, for when main.py is running
gpio_panel.py        GPIO panel on http://localhost:8760 (over USB)
onboard/box_mqtt.py  the box as an MQTT device - upload as main.py
onboard/espnet.py    ESP boot, WiFi, HTTP; shared by the on-board apps
onboard/esp_web.py   GPIO panel served by the board itself over WiFi
onboard/nor.py       SPI NOR block device
esp.py               ESP power, boot strap, ESP-AT channel
upload.py            push a file to the module's /usr
*_scan.py            the probes: buttons, LEDs, SPI, I2C, UARTs, boot straps
```

`pa_sweep.py`, `speaker_test.py` and `audio_path.py` predate the audio fix and
hunt an enable pin while playing a tone that never made a sound. Kept for the
record; use `audio_play.py`.

## Running the box on its own

```sh
cp wifi_config.example.py wifi_config.py     # then edit it
python3 upload.py wifi
python3 upload.py onboard/espnet.py
python3 upload.py onboard/box_mqtt.py main.py
python3 -c "from qpy import Qpy; Qpy().exec('import misc; misc.Power.powerRestart()')"
open mqtt_panel.html
```

The box lights the red LED, joins WiFi through the ESP, and publishes battery,
button and volume state once a second. The panel connects to the same public
broker over a WebSocket and can set the volume, play a file, or toggle the LED.
The + and − buttons on the box do the same thing, each confirmed by a short
beep at the new level.

The topic prefix is `vnpay-ec600u/<id>`, where the box picks `<id>` at first
boot and keeps it in `/usr/mqtt_id.txt`. It also logs it at startup.

**The broker is public and unauthenticated.** Anyone who knows the prefix can
read the box's state and drive it. That is fine for a demo and not fine for
anything else — point `BROKER` at your own broker with credentials first.

Attaching the REPL sends ctrl-C and kills `main.py`, so use `mqtt_probe.py`
rather than `qpy.py` while the box is meant to stay up.

## Setup

```sh
pip install pyserial          # Linux
pip install pyusb             # macOS, plus: brew install libusb
cp wifi_config.example.py wifi_config.py   # then edit it
python3 qpy.py                             # should print uos.uname()
```

On Linux the module's interface .8 appears as a `/dev/ttyUSBn` because the
`option` driver binds it. macOS has no driver for interface class 0xFF, so no
device node is ever created — but nothing has claimed those interfaces either,
so `qpy.py` takes interface .8 with libusb and speaks the same raw REPL over
its bulk pair. No kext, no SIP changes. The interface number is fixed there,
unlike the ttyUSB numbering.

For the on-board WiFi panel:

```sh
python3 upload.py wifi                        # credentials -> /usr/wifi.txt
python3 upload.py onboard/esp_web.py main.py  # -> /usr/main.py, autostarts
```

Connecting with `qpy.py` sends Ctrl-C, which kills whatever `main.py` is
running. That is deliberate, but it means the WiFi panel stops the moment you
open a serial session.

## Not in this repo

The SPI NOR dump (`nor_backup.bin`), the NV/calibration backup, and the session
logs are gitignored. The dump is VNPay's stock firmware and the NV backup
carries the module's IMEI; neither is mine to publish. If you are doing this on
your own box, take your own backup before touching the flash — mine did not
survive an interrupted chip erase.

This is a teardown of hardware I own, for my own use. Do not use anything here
to impersonate payment notifications.
