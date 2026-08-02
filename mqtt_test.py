#!/usr/bin/env python3
"""End-to-end MQTT test over the ESP, driven entirely from the EC600U.

Joins WiFi, connects to a public broker over plain TCP, subscribes to a topic
and publishes to that same topic, so the message comes back to us — that
proves both directions in one shot.

Plain TCP (scheme 1) is used deliberately. The device has mqtt_cert/key/ca
partitions holding VNPay's own credentials; touching those is not needed to
prove the transport works, and they are per-device and irreplaceable.

`AT+SYSSTORE=1` is set first so the WiFi credentials persist, which is what
replaces the previously stored "Bun Doc Mung" entry.
"""

import sys
import time

import esp

try:
    from wifi_config import SSID, PASSWORD
except ImportError:
    raise SystemExit("copy wifi_config.example.py to wifi_config.py and put "
                     "your network in it")

BROKER = "broker.emqx.io"
PORT = 1883
TOPIC = "vnpay/ec600u/selftest"
CLIENT_ID = "ec600u_vnpay_%d" % (int(time.time()) % 100000)


def build(store=True):
    return [
        # store=1 persists the join, overwriting the stored "Bun Doc Mung"
        "AT+SYSSTORE=%d" % (1 if store else 0),
        "AT+CWMODE=1",
        'AT+CWJAP="%s","%s"' % (SSID, PASSWORD),
        'AT+MQTTUSERCFG=0,1,"%s","","",0,0,""' % CLIENT_ID,
        'AT+MQTTCONN=0,"%s",%d,1' % (BROKER, PORT),
        'AT+MQTTSUB=0,"%s",1' % TOPIC,
        'AT+MQTTPUB=0,"%s","hello-from-ec600u",1,0' % TOPIC,
        "AT+MQTTCONN?",
    ]


if __name__ == "__main__":
    store = "nostore" not in sys.argv
    cmds = build(store)
    print("broker %s:%d topic %s client %s" % (BROKER, PORT, TOPIC, CLIENT_ID))
    print("wifi credentials will %s be stored\n"
          % ("" if store else "NOT"))
    booted, out = esp.run(cmds, wait=8000)

    got_echo = False
    for line in (out or "").splitlines():
        if line.startswith("<"):
            try:
                raw = eval(line[2:], {"__builtins__": {}})
            except Exception:
                print(line[:200])
                continue
            for l in raw.decode("latin1").splitlines():
                if l.strip():
                    print("    " + l.strip()[:200])
                    if "MQTTSUBRECV" in l:
                        got_echo = True
        else:
            print(line[:200])

    print("\n" + ("round trip confirmed - the published message came back "
                 "through the subscription"
                 if got_echo else
                 "no +MQTTSUBRECV seen; check the lines above for where it "
                 "stopped"))
    with open("logs/mqtt_test.log", "a") as fh:
        fh.write("=== %s echo=%s ===\n%s\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), got_echo, out))
