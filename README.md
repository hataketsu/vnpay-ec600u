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
* MP3 playback through `audio.Audio`
* Buttons, LED, and the SPI NOR identified

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

Still open: which pin holds the HT8313's shutdown line (narrowed to GPIO 5, 6,
8, 9, 17, 18), and what GPIO 23, 24, 35, 36, 40, 41 are for.

## Layout

```
qpy.py              raw-REPL driver over USB serial; everything else builds on it
pinmap.py           pin metadata, one place
gpio_panel.py       GPIO panel on http://localhost:8760 (drives the board over USB)
onboard/esp_web.py  the same panel, but served by the board over WiFi
onboard/nor.py      SPI NOR block device
esp.py              ESP power, boot strap, ESP-AT channel
upload.py           push a file to the module's /usr
*_scan.py           the probes: buttons, LEDs, SPI, I2C, UARTs, boot straps
```

## Setup

```sh
pip install pyserial
cp wifi_config.example.py wifi_config.py   # then edit it
python3 qpy.py                             # should print uos.uname()
```

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
