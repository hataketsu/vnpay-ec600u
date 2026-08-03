#!/usr/bin/env python3
"""Watch the box's MQTT state, and optionally send it a command.

The same wire the browser panel uses, from a terminal - handy when the box is
running /usr/main.py and the REPL is out of reach, because opening the REPL
sends ctrl-C and kills whatever is running.

    python3 mqtt_probe.py                        # watch state
    python3 mqtt_probe.py --send vol=3
    python3 mqtt_probe.py --send ping --watch 6

The broker is public and unauthenticated; the prefix is obscurity, not
security.
"""

import argparse
import json
import time

import paho.mqtt.client as mqtt

BROKER = "broker.emqx.io"
PORT = 1883


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--prefix", default="vnpay-ec600u/c55fa",
                   help="topic prefix the box printed at startup")
    p.add_argument("--send", help="command, e.g. vol=3 / ping / led=0")
    p.add_argument("--watch", type=float, default=10.0, help="seconds")
    a = p.parse_args()

    seen = []

    def on_connect(client, *_):
        client.subscribe(a.prefix + "/state")
        if a.send:
            client.publish(a.prefix + "/cmd", a.send)
            print("sent %r to %s/cmd" % (a.send, a.prefix))

    def on_message(_c, _u, msg):
        try:
            s = json.loads(msg.payload.decode())
        except Exception:
            print("raw:", msg.payload[:120])
            return
        seen.append(s)
        # "none" rather than a dash: a dash is also the name of a button.
        print("battery %d%% (%d mV)  vol %2d  buttons %-4s  led %d  up %ds"
              % (s.get("pct", -1), s.get("mv", 0), s.get("vol", -1),
                 s.get("btn") or "none", s.get("led", -1), s.get("up", 0)))

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(BROKER, PORT, 30)
    c.loop_start()
    time.sleep(a.watch)
    c.loop_stop()

    if not seen:
        print("nothing published on %s/state - is the box up and on WiFi?"
              % a.prefix)


if __name__ == "__main__":
    main()
