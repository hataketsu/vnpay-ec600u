"""ESP8285 link and a tiny HTTP server, for code running on the EC600U.

Extracted from esp_web.py so more than one on-board app can use it. The module
has no network of its own here - no SIM, and no `usbnet` in this QuecPython
build - so the ESP is the network interface:

    browser --WiFi--> ESP8285 --UART2--> EC600U

Every quirk commented below was paid for once already; see NOTES.md.

Not importable until /usr is on the path, which it is not by default:

    import usys; usys.path.append('/usr')
    import espnet
"""

from machine import UART, Pin
import utime

ESP_EN = 44          # switches the ESP's 3V3 rail
ESP_RAIL = 14        # shares the rail; must stay low / released
ESP_STRAP = 26       # pin 50, AP_READY - LOW lets the ESP flash-boot
BAUD = 115200
CHUNK = 1400         # ESP-AT accepts up to 2048 bytes per CIPSEND

WIFI_FILE = "/usr/wifi.txt"
LOG = "/usr/weblog.txt"

uart = UART(UART.UART2, BAUD, 8, 0, 1, 0)


def credentials():
    """SSID and password from /usr/wifi.txt, so they stay out of git.

    `python3 upload.py wifi` writes that file. Importing wifi_config on the
    module would not work - /usr is not on usys.path.
    """
    try:
        lines = open(WIFI_FILE).read().split("\n")
        return lines[0].strip(), lines[1].strip()
    except Exception:
        return "", ""


def log(*parts):
    """Record progress to a file as well as stdout.

    Running as /usr/main.py there is no console attached, so print() alone
    leaves no trace of where a boot went wrong.
    """
    line = " ".join(str(p) for p in parts)
    print(line)
    try:
        f = open(LOG, "a")
        f.write("%d %s\n" % (utime.ticks_ms(), line))
        f.close()
    except Exception:
        pass


# ---------------------------------------------------------------- ROM loader

def _slip(packet):
    out = bytearray(b"\xc0")
    for b in packet:
        if b == 0xC0:
            out += b"\xdb\xdc"
        elif b == 0xDB:
            out += b"\xdb\xdd"
        else:
            out.append(b)
    out += b"\xc0"
    return bytes(out)


def _cmd(op, payload=b""):
    n = len(payload)
    header = bytes([0x00, op, n & 0xFF, (n >> 8) & 0xFF, 0, 0, 0, 0])
    return _slip(header + payload)


def _u32(v):
    return bytes([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF])


SYNC = _cmd(0x08, b"\x07\x07\x12\x20" + b"\x55" * 32)
FLASH_BEGIN = _cmd(0x02, _u32(0) + _u32(0) + _u32(1024) + _u32(0))
FLASH_END = _cmd(0x04, _u32(0))


# One shared receive buffer. Everything arriving on UART2 lands here and is
# only ever removed deliberately. Letting at() discard whatever it saw while
# waiting for "SEND OK" swallowed the +IPD belonging to the next request, and
# every second request came back empty.
# Plain bytes, not bytearray: this MicroPython's bytearray has no .find() and
# does not support slice deletion, so the buffer is rebuilt by slicing.
RX = b""


def pump():
    global RX
    try:
        n = uart.any()
        if n:
            RX += bytes(uart.read(n))
    except Exception:
        pass


def drain():
    """Take everything currently buffered. Only safe before the server runs."""
    global RX
    pump()
    out = RX
    RX = b""
    return out


def wait_for(markers, start, timeout):
    """Wait for one of markers to appear at or after start.

    Only the matched region is removed, so a +IPD that arrived before it - or
    lands while we wait - stays queued. Clearing the buffer instead, or
    searching from zero, made every second request come back empty.
    """
    global RX
    t0 = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), t0) < timeout:
        pump()
        tail = RX[start:]
        for m in markers:
            i = tail.find(m)
            if i >= 0:
                end = start + i + len(m)
                seen = RX[start:end]
                RX = RX[:start] + RX[end:]
                return seen
        utime.sleep_ms(20)
    return b""


def esp_boot():
    # GPIO26 (pin 50, AP_READY) is the boot-mode strap: held LOW the ESP
    # flash-boots by itself, high or floating it lands in UART download mode.
    # QuecPython leaves it floating, which is the only reason the ROM handover
    # below is needed at all.
    Pin(getattr(Pin, "GPIO%d" % ESP_STRAP), Pin.OUT, Pin.PULL_DISABLE, 0)
    Pin(getattr(Pin, "GPIO%d" % ESP_RAIL), Pin.IN, Pin.PULL_DISABLE)
    Pin(getattr(Pin, "GPIO%d" % ESP_EN), Pin.OUT, Pin.PULL_DISABLE, 0)
    utime.sleep_ms(700)
    drain()
    Pin(getattr(Pin, "GPIO%d" % ESP_EN), Pin.OUT, Pin.PULL_DISABLE, 1)
    buf = b""
    for _ in range(40):
        utime.sleep_ms(50)
        buf += drain()
        if b"ready" in buf:
            return True
    # Fall back to the ROM handover if the strap alone did not do it.
    utime.sleep_ms(300)
    drain()
    for _ in range(8):
        uart.write(SYNC)
        utime.sleep_ms(120)
        drain()
    uart.write(FLASH_BEGIN)
    utime.sleep_ms(300)
    drain()
    uart.write(FLASH_END)
    buf = b""
    for _ in range(30):
        utime.sleep_ms(100)
        buf += drain()
        if b"ready" in buf:
            return True
    return False


def at(cmd, timeout=4000, want=b"OK"):
    pump()
    start = len(RX)          # ignore anything already buffered
    uart.write(cmd + b"\r\n")
    return wait_for((want, b"ERROR"), start, timeout)


# ---------------------------------------------------------------------- HTTP

def respond(link, body, ctype="text/html"):
    head = ("HTTP/1.1 200 OK\r\nContent-Type: %s\r\n"
            "Content-Length: %d\r\nConnection: close\r\n\r\n"
            % (ctype, len(body)))
    raw = (head + body).encode()
    for i in range(0, len(raw), CHUNK):
        part = raw[i:i + CHUNK]
        r = at(b"AT+CIPSEND=%d,%d" % (link, len(part)), 3000, b">")
        if b">" not in r:
            log("cipsend refused", link, r[-40:])
            return False
        pump()
        start = len(RX)
        uart.write(part)
        if not wait_for((b"SEND OK", b"ERROR"), start, 4000):
            log("no SEND OK", link)
            return False
    at(b"AT+CIPCLOSE=%d" % link, 2000)
    return True


def qs(path, key):
    if "?" not in path:
        return None
    for kv in path.split("?", 1)[1].split("&"):
        if kv.startswith(key + "="):
            return kv[len(key) + 1:]
    return None


def join_wifi():
    """Boot the ESP and get it onto WiFi. Returns the IP, or ''.

    Everything network-shaped starts here - HTTP server, MQTT client, both.
    """
    for attempt in range(1, 5):
        log("booting ESP, attempt", attempt)
        if esp_boot():
            break
        utime.sleep_ms(800)
    else:
        log("ESP never reached firmware")
        return ""

    ssid, password = credentials()
    if not ssid:
        log("no credentials in %s - run: python3 upload.py wifi" % WIFI_FILE)
        return ""

    at(b"AT+SYSSTORE=0")
    at(b"AT+CWMODE=1")
    log("join:", at(b'AT+CWJAP="%s","%s"'
                    % (ssid.encode(), password.encode()), 20000)[-50:])
    ip = at(b"AT+CIPSTA?", 4000)

    addr = ""
    marker = b'+CIPSTA:ip:"'
    k = ip.find(marker)
    if k >= 0:
        addr = ip[k + len(marker):ip.find(b'"', k + len(marker))].decode()
    log("wifi ip", addr or "(none)")
    return addr


def setup_link(port=80):
    """Join WiFi and start the ESP's TCP server. Returns the IP, or ''."""
    addr = join_wifi()
    if not addr:
        return ""
    log("mux:", at(b"AT+CIPMUX=1")[-20:])
    log("server:", at(b"AT+CIPSERVER=1,%d" % port)[-20:])
    log("listening on http://%s:%d/" % (addr, port))
    return addr


def ensure_link(port=80):
    if at(b"AT", 1500):
        return True
    log("rebuilding link")
    return bool(setup_link(port))


def serve(handler, port=80, tick=None, tick_ms=120):
    """Answer requests forever, calling tick() between them.

    handler(link, request) -> truthy if it answered. tick() is where an app
    puts anything that has to keep running while nobody is asking - polling
    buttons, for instance.
    """
    ip = setup_link(port)
    if not ip:
        return ""

    global RX
    last_seen = utime.ticks_ms()
    last_tick = utime.ticks_ms()
    while True:
        utime.sleep_ms(30)
        pump()
        if tick is not None and \
                utime.ticks_diff(utime.ticks_ms(), last_tick) >= tick_ms:
            last_tick = utime.ticks_ms()
            try:
                tick()
            except Exception as e:
                log("tick error", repr(e)[:60])
        idx = RX.find(b"+IPD,")
        if idx < 0:
            # Drop stale chatter, but only when no request is pending.
            if len(RX) > 4096:
                RX = RX[-1024:]
            # The link can die *after* a response went out, and then nothing
            # ever arrives again - the loop would wait forever.
            if utime.ticks_diff(utime.ticks_ms(), last_seen) > 20000:
                last_seen = utime.ticks_ms()
                if not ensure_link(port):
                    utime.sleep_ms(2000)
                RX = b""
            continue
        last_seen = utime.ticks_ms()
        colon = RX.find(b":", idx)
        if colon < 0:
            continue
        try:
            hdr = RX[idx + 5:colon].split(b",")
            link = int(hdr[0])
            ln = int(hdr[1])
        except Exception:
            RX = RX[colon + 1:]
            continue
        t0 = utime.ticks_ms()
        while len(RX) - (colon + 1) < ln and \
                utime.ticks_diff(utime.ticks_ms(), t0) < 2000:
            utime.sleep_ms(20)
            pump()
        req = RX[colon + 1:colon + 1 + ln]
        RX = RX[colon + 1 + ln:]
        # req is bytes, so the separator has to be bytes too - splitting it
        # with a str raises TypeError on this MicroPython.
        try:
            ok = handler(link, req.decode("latin1"))
        except Exception as e:
            log("handler error", repr(e)[:60])
            ok = False
        if not ok:
            try:
                at(b"AT+CIPCLOSE=%d" % link, 1500)
            except Exception:
                pass
            ensure_link(port)
            # Rebuilding takes seconds, during which requests pile up.
            # Answering them afterwards is worse than dropping them: the ESP
            # reuses link ids, so a late reply lands on somebody else's
            # connection and the browser shows the previous answer.
            RX = b""
