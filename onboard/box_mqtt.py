"""Run the box as an MQTT device: publish state, take commands.

    laptop browser --WSS--> broker.emqx.io <--TCP-- ESP8285 <--UART2--> EC600U

The module has no network of its own, so the ESP does the talking. ESP-AT has
an MQTT client built in and it was already proven on this board - connect,
subscribe, publish, and a published message came back via +MQTTSUBRECV.

Published on `<prefix>/state`, once a second and immediately after any change:

    {"mv":4162,"pct":95,"vol":1,"btn":"M+-","up":123456}

Accepted on `<prefix>/cmd`, one `key=value` per message:

    vol=3           set volume, 0-11
    vol=+1          relative, also vol=-1
    ping            play the beep at the current volume
    play=say.mp3    play a file from /usr
    led=1           red LED on, led=0 off

**The broker is public and unauthenticated.** Anyone who knows the prefix can
read the state and drive the box. The random suffix in TOPIC is obscurity, not
security. Point this at your own broker with credentials before it matters.

Upload as /usr/main.py to have it start with the module:

    python3 upload.py onboard/espnet.py
    python3 upload.py onboard/box_mqtt.py main.py
"""

import usys
if "/usr" not in usys.path:
    usys.path.append("/usr")

import audio
import misc
import utime
from machine import Pin

import espnet
from espnet import at, log, pump, RX

BROKER = "broker.emqx.io"
PORT = 1883

# Written by box_mqtt at first boot so the laptop panel and the box agree on a
# topic without either being edited. Deleting the file picks a new one.
ID_FILE = "/usr/mqtt_id.txt"

LED_RED = 15         # module pin 57, active high
AMP_CTRL = 13        # module pin 2, the HT8313's CTRL line
BUTTONS = ((28, "M"), (27, "+"), (16, "-"))   # active HIGH, read with PULL_PD

AUDIO_DEV = 2        # loudspeaker path
AUDIO_CHAN = 2
# 0.5 s, cut from beep.mp3 by trim_mp3.py. beep.mp3 itself runs 1.58 s, which
# is far too long to confirm a volume step - holding + would queue a backlog.
PING_FILE = "U:/ping.mp3"

# Resting-voltage curve for one Li-ion cell, mV to percent. Rough by nature,
# and meaningless while USB is charging - see battery.py.
CURVE = ((4200, 100), (4160, 95), (4060, 85), (3950, 70), (3850, 50),
         (3750, 30), (3700, 20), (3600, 10), (3400, 0))

STATE_MS = 1000
POLL_MS = 120


def device_id():
    try:
        return open(ID_FILE).read().strip()
    except Exception:
        pass
    # No Math.random here; the module's uptime in ms at first boot is enough
    # entropy to keep two boxes off each other's topic.
    new = "%x" % (utime.ticks_ms() & 0xFFFFFF)
    try:
        f = open(ID_FILE, "w")
        f.write(new)
        f.close()
    except Exception:
        pass
    return new


DEV = device_id()
TOPIC = "vnpay-ec600u/" + DEV
T_STATE = TOPIC + "/state"
T_CMD = TOPIC + "/cmd"


def percent(mv):
    if mv >= CURVE[0][0]:
        return 100
    if mv <= CURVE[-1][0]:
        return 0
    for i in range(len(CURVE) - 1):
        hi_mv, hi_pc = CURVE[i]
        lo_mv, lo_pc = CURVE[i + 1]
        if lo_mv <= mv <= hi_mv:
            return int(lo_pc + (mv - lo_mv) * (hi_pc - lo_pc) / (hi_mv - lo_mv))
    return 0


# --------------------------------------------------------------------- board

class Box:
    def __init__(self):
        Pin(getattr(Pin, "GPIO%d" % LED_RED), Pin.OUT, Pin.PULL_DISABLE, 1)
        self.led = 1
        # CTRL high or the amplifier stays in shutdown and nothing is audible.
        # It latches once raised, but drive it anyway so a cold boot works.
        Pin(getattr(Pin, "GPIO%d" % AMP_CTRL), Pin.OUT, Pin.PULL_DISABLE, 1)
        self.audio = audio.Audio(AUDIO_DEV)
        try:
            self.audio.set_channel(AUDIO_CHAN)
        except Exception as e:
            log("set_channel failed", repr(e)[:60])
        self.vol = 1
        self.audio.setVolume(self.vol)
        self.pressed = {}
        self.dirty = True

    def set_led(self, on):
        self.led = 1 if on else 0
        Pin(getattr(Pin, "GPIO%d" % LED_RED), Pin.OUT, Pin.PULL_DISABLE,
            self.led)
        self.dirty = True

    def set_volume(self, v, ping=True):
        v = 0 if v < 0 else (11 if v > 11 else v)
        self.vol = v
        self.audio.setVolume(v)
        self.dirty = True
        if ping:
            # The point of the ping is to hear where the level landed, so cut
            # off the previous one rather than letting steps queue up.
            self.play(PING_FILE, interrupt=True)
        return v

    def play(self, path, interrupt=False):
        try:
            if interrupt:
                self.audio.stopAll()
            return self.audio.play(1, 0, path)
        except Exception as e:
            log("play failed", repr(e)[:60])
            return -1

    def buttons(self):
        """Which buttons are held. Active HIGH, so read with the pull-down."""
        out = ""
        for g, name in BUTTONS:
            try:
                if Pin(getattr(Pin, "GPIO%d" % g), Pin.IN, Pin.PULL_PD).read():
                    out += name
            except Exception:
                pass
        return out

    def poll_buttons(self):
        """Act on presses, not on being held. Returns the current set."""
        held = self.buttons()
        for _, name in BUTTONS:
            was = self.pressed.get(name, False)
            now = name in held
            self.pressed[name] = now
            if now and not was:
                if name == "+":
                    self.set_volume(self.vol + 1)
                elif name == "-":
                    self.set_volume(self.vol - 1)
                else:
                    self.dirty = True
        return held

    def state_json(self, held):
        mv = misc.Power.getVbatt()
        return ('{"mv":%d,"pct":%d,"vol":%d,"btn":"%s","led":%d,"up":%d}'
                % (mv, percent(mv), self.vol, held, self.led,
                   utime.ticks_ms() // 1000))


# ---------------------------------------------------------------------- MQTT

def mqtt_connect():
    at(b'AT+MQTTUSERCFG=0,1,"ec600u-%s","","",0,0,""' % DEV.encode())
    r = at(b'AT+MQTTCONN=0,"%s",%d,1' % (BROKER.encode(), PORT), 12000)
    if b"OK" not in r:
        log("mqtt connect failed", r[-60:])
        return False
    s = at(b'AT+MQTTSUB=0,"%s",1' % T_CMD.encode(), 6000)
    log("subscribed", T_CMD, s[-20:])
    return True


def publish(topic, payload):
    """MQTTPUBRAW, not MQTTPUB: the payload is JSON and full of quotes and
    commas, which the quoted-string form of MQTTPUB would mangle."""
    body = payload.encode()
    r = at(b'AT+MQTTPUBRAW=0,"%s",%d,0,0' % (topic.encode(), len(body)),
           4000, b">")
    if b">" not in r:
        return False
    espnet.pump()
    start = len(espnet.RX)
    espnet.uart.write(body)
    return bool(espnet.wait_for((b"OK", b"ERROR"), start, 4000))


def take_command(box, text):
    text = text.strip()
    log("cmd", text[:40])
    if text == "ping":
        box.play(PING_FILE)
        return
    if "=" not in text:
        return
    key, val = text.split("=", 1)
    if key == "vol":
        if val.startswith("+") or val.startswith("-"):
            box.set_volume(box.vol + int(val))
        else:
            box.set_volume(int(val))
    elif key == "play":
        box.play("U:/" + val.lstrip("/"))
    elif key == "led":
        box.set_led(val not in ("0", "off", "false"))


def pop_message():
    """Pull one +MQTTSUBRECV out of the shared buffer, if a whole one is there.

    Format: +MQTTSUBRECV:0,"topic",<len>,<data>. The length is authoritative -
    the payload can contain commas and newlines, so it cannot be split on.
    """
    idx = espnet.RX.find(b"+MQTTSUBRECV:")
    if idx < 0:
        return None
    head_end = espnet.RX.find(b",", espnet.RX.find(b'"', idx + 13) + 1)
    if head_end < 0:
        return None
    # ...,<len>,<data> - the length runs from head_end+1 to the next comma.
    len_end = espnet.RX.find(b",", head_end + 1)
    if len_end < 0:
        return None
    try:
        ln = int(espnet.RX[head_end + 1:len_end])
    except Exception:
        espnet.RX = espnet.RX[idx + 13:]
        return None
    start = len_end + 1
    if len(espnet.RX) < start + ln:
        return None                      # rest of it has not arrived yet
    data = espnet.RX[start:start + ln]
    espnet.RX = espnet.RX[:idx] + espnet.RX[start + ln:]
    return data.decode("latin1")


def run():
    box = Box()
    log("box up, led on, topic", TOPIC)
    if not espnet.join_wifi():
        log("no wifi - staying offline, buttons still work")
    elif not mqtt_connect():
        log("no broker")

    last_state = utime.ticks_ms()
    last_poll = utime.ticks_ms()
    held = ""
    while True:
        utime.sleep_ms(30)
        espnet.pump()

        msg = pop_message()
        while msg is not None:
            try:
                take_command(box, msg)
            except Exception as e:
                log("bad command", repr(e)[:60])
            msg = pop_message()

        if utime.ticks_diff(utime.ticks_ms(), last_poll) >= POLL_MS:
            last_poll = utime.ticks_ms()
            new_held = box.poll_buttons()
            if new_held != held:
                held = new_held
                box.dirty = True

        if box.dirty or \
                utime.ticks_diff(utime.ticks_ms(), last_state) >= STATE_MS:
            last_state = utime.ticks_ms()
            box.dirty = False
            if not publish(T_STATE, box.state_json(held)):
                log("publish failed, reconnecting")
                if espnet.at(b"AT", 1500):
                    mqtt_connect()
                else:
                    espnet.join_wifi() and mqtt_connect()


if __name__ == "__main__":
    try:
        run()
    except Exception as _e:
        log("box_mqtt crashed:", repr(_e)[:120])
        raise
