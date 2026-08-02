"""GPIO control panel served over WiFi, running on the EC600U itself.

The module has no usable network of its own here - there is no SIM, and this
QuecPython build has no `usbnet` module - so the ESP8285 is used as the
network interface. It already joins WiFi, and ESP-AT can run a TCP server, so
the path is:

    browser --WiFi--> ESP8285 --UART2--> EC600U --> GPIO

Nothing goes over USB serial, which is the point.

The ESP's boot mode is set by **GPIO26 (module pin 50, AP_READY)**: held LOW it
flash-boots on its own, high or floating it lands in UART download mode.
QuecPython leaves that pin floating, which is why the ESP looked permanently
stuck. Holding it low and power-cycling the rail is all that is needed; the ROM
handover (SYNC, no-op FLASH_BEGIN, FLASH_END) is kept only as a fallback.

Run it from the REPL:

    exec(open('/usr/esp_web.py').read())

or upload it as /usr/main.py to have it start with the module.
"""

from machine import UART, Pin
import utime

PORT = 80

# Credentials live in /usr/wifi.txt, two lines, SSID then password, so they
# are not baked into a file that gets committed. `python3 upload.py wifi`
# writes it from wifi_config.py. Importing wifi_config here would not work:
# /usr is not on usys.path on the module.
WIFI_FILE = "/usr/wifi.txt"
SSID = PASSWORD = ""
try:
    _lines = open(WIFI_FILE).read().split("\n")
    SSID, PASSWORD = _lines[0].strip(), _lines[1].strip()
except Exception:
    pass

ESP_EN = 44          # switches the ESP's 3V3 rail
ESP_RAIL = 14        # shares the rail; must stay low / released
ESP_STRAP = 26       # pin 50, AP_READY - LOW lets the ESP flash-boot
BAUD = 115200
CHUNK = 1400         # ESP-AT accepts up to 2048 bytes per CIPSEND

LOG = "/usr/weblog.txt"

uart = UART(UART.UART2, BAUD, 8, 0, 1, 0)


def log(*parts):
    """Record progress to a file as well as stdout.

    When this runs as /usr/main.py there is no console attached, so print()
    alone leaves no trace of where a boot went wrong.
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


# One shared receive buffer. Everything that arrives on UART2 lands here and
# is only ever removed deliberately. An earlier version let at() read and
# discard whatever it saw while waiting for "SEND OK", which swallowed the
# +IPD belonging to the next request - every second request came back empty.
# Plain bytes, not bytearray: this MicroPython's bytearray has no .find() and
# does not support slice deletion, so the buffer is rebuilt by slicing instead.
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

    Only the matched response region is removed, so a +IPD that arrived
    before it - or lands while we wait - stays queued. Clearing the buffer
    instead, or searching from zero, made every second request come back
    empty: a stale reply matched immediately and each command then read the
    previous one's response.
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


# ------------------------------------------------------------------------ AT

def at(cmd, timeout=4000, want=b"OK"):
    pump()
    start = len(RX)          # ignore anything already buffered
    uart.write(cmd + b"\r\n")
    return wait_for((want, b"ERROR"), start, timeout)


# ---------------------------------------------------------------------- GPIO

PINS = {
    1: (61, "i2s2_bck"), 2: (58, "i2s2_lrck"), 3: (34, "uart_2_rts"),
    4: (60, "i2s2_sdat_o"), 5: (69, "gpio_5"), 6: (70, "gpio_6"),
    7: (123, "uart_1_rxd"), 8: (118, "sdmmc2_clk"), 9: (9, "gpio_9"),
    10: (1, "spi_0_clk"), 11: (4, "spi_0_cs"), 12: (3, "spi_0_dio"),
    13: (2, "spi_0_di"), 14: (54, "NET_STATUS"), 15: (57, "i2c_1_scl"),
    16: (56, "i2c_1_sda"), 17: (12, "i2c_0_sda"), 18: (33, "uart_2_cts"),
    19: (124, "uart_1_txd"), 20: (122, "uart_1_rts"), 21: (121, "uart_1_cts"),
    22: (48, "MAIN_DCD"), 23: (39, "MAIN_DTR"), 24: (40, "MAIN_RI"),
    25: (49, "WAKEUP_IN"), 26: (50, "AP_READY / ESP BOOT STRAP"), 27: (53, "sim_2_clk"),
    28: (52, "sim_2_dio"), 29: (51, "sim_2_rst"), 30: (59, "i2s2_sdat_i"),
    31: (66, "spi_lcd_sio"), 32: (63, "spi_lcd_sdc"), 33: (67, "spi_lcd_clk"),
    34: (65, "spi_lcd_cs"), 35: (137, "spi_lcd_select"), 36: (62, "lcd_fmark"),
    37: (98, "sdmmc2_data_0"), 38: (95, "sdmmc2_data_1"),
    39: (119, "sdmmc2_data_2"), 40: (100, "sdmmc2_data_3"),
    41: (120, "camera_rst_l"), 42: (16, "camera_pwdn"),
    43: (10, "camera_ref_clk"), 44: (14, "ESP 3V3 SWITCH"),
    45: (15, "spi_camera_si_1"), 46: (13, "spi_camera_sck"),
    47: (99, "sdmmc2_cmd"),
}
EXT_DRIVEN = {2: "HIGH", 23: "LOW", 24: "LOW", 35: "LOW",
              36: "LOW", 40: "HIGH", 41: "HIGH"}
state = {}
last_driven = [None]     # the pin most recently driven, for recovery


def release_all():
    """Return every pin we drove to high-impedance, except the ESP's rail."""
    for g in list(state.keys()):
        if g in (ESP_EN, ESP_STRAP):
            continue
        try:
            Pin(getattr(Pin, "GPIO%d" % g), Pin.IN, Pin.PULL_DISABLE)
        except Exception:
            pass
        state.pop(g, None)
    last_driven[0] = None


def gpio_set(g, mode):
    pid = getattr(Pin, "GPIO%d" % g, None)
    if pid is None:
        return "no such pin"
    # Never drive UART2 - it is the link carrying this very request.
    if g in (7, 19):
        return "refused: UART2 pin"
    if g == ESP_EN and mode != "high":
        return "refused: that would cut the ESP's power and drop this page"
    if g == ESP_STRAP and mode != "low":
        return "refused: GPIO26 must stay low or the ESP stops flash-booting"
    try:
        if mode == "hiz":
            Pin(pid, Pin.IN, Pin.PULL_DISABLE)
            state.pop(g, None)
            return "HI-Z"
        lvl = 1 if mode == "high" else 0
        last_driven[0] = g
        Pin(pid, Pin.OUT, Pin.PULL_DISABLE, lvl)
        state[g] = "HIGH" if lvl else "LOW"
        return state[g]
    except Exception as e:
        return "error " + repr(e)[:40]


def gpio_read(g):
    pid = getattr(Pin, "GPIO%d" % g, None)
    if pid is None:
        return "no such pin"
    if g in (7, 19):
        return "refused: UART2 pin"
    # Reading reconfigures the pin as an input, which on the rail switch would
    # cut the ESP's power and take this page down with it.
    if g == ESP_EN:
        return "refused: reading this would cut the ESP's power"
    if g == ESP_STRAP:
        return "refused: releasing GPIO26 would drop the ESP into download mode"
    try:
        pu = Pin(pid, Pin.IN, Pin.PULL_PU).read()
        pd = Pin(pid, Pin.IN, Pin.PULL_PD).read()
    except Exception:
        return "?"
    state.pop(g, None)
    if pu == 1 and pd == 0:
        return "floating"
    if pu == pd == 1:
        return "driven HIGH"
    if pu == pd == 0:
        return "driven LOW"
    return "?"


# ---------------------------------------------------------------------- HTTP

def page():
    rows = []
    for g in sorted(PINS):
        pin, fn = PINS[g]
        rows.append("%d,%d,%s,%s" % (g, pin, fn, EXT_DRIVEN.get(g, "")))
    data = ";".join(rows)
    return (
        "<title>EC600U GPIO over WiFi</title>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<style>"
        "body{font:14px system-ui;margin:0;background:#0e1013;color:#e8eaed}"
        "@media(prefers-color-scheme:light){body{background:#f6f7f9;color:#14161a}}"
        "h1{font-size:16px;margin:14px}"
        "#g{display:grid;gap:8px;padding:0 14px 30px;"
        "grid-template-columns:repeat(auto-fill,minmax(180px,1fr))}"
        ".c{border:1px solid #3a3f47;border-radius:9px;padding:8px 10px}"
        ".c.w{border-color:#c2410c}.c.e{border-color:#a21caf}"
        ".t{font-weight:700}.s{color:#9aa2ad;font-size:12px}"
        "b{display:flex;gap:4px;margin-top:6px}"
        "button{flex:1;font:600 12px system-ui;padding:4px 0;border-radius:6px;"
        "border:1px solid #3a3f47;background:transparent;color:inherit}"
        "#l{margin:10px 14px;color:#9aa2ad;font:12px ui-monospace}"
        "</style>"
        "<h1>EC600U GPIO <span class=s>over WiFi, no serial</span></h1>"
        "<div id=l>ready</div><div id=g></div>"
        "<script>"
        "var D='" + data + "'.split(';');"
        "function log(s){document.getElementById('l').textContent=s}"
        "function mk(){var h='';for(var i=0;i<D.length;i++){var p=D[i].split(',');"
        "var cls='c';if(p[3])cls+=' w';if(p[0]=='44')cls+=' e';"
        "h+='<div class=\"'+cls+'\"><div class=t>GPIO'+p[0]+"
        "'<span class=s> pin '+p[1]+'</span></div><div class=s>'+p[2]+"
        "(p[3]?' - ext '+p[3]:'')+'</div><b>'+"
        "'<button onclick=\"s('+p[0]+',1)\">H</button>'+"
        "'<button onclick=\"s('+p[0]+',0)\">L</button>'+"
        "'<button onclick=\"s('+p[0]+',2)\">Z</button>'+"
        "'<button onclick=\"r('+p[0]+')\">?</button>'+"
        "'</b><div class=s id=\"v'+p[0]+'\"></div></div>'}"
        "document.getElementById('g').innerHTML=h}"
        "function s(g,m){log('GPIO'+g+' ...');"
        "fetch('/set?g='+g+'&m='+m).then(r=>r.text()).then(t=>{"
        "document.getElementById('v'+g).textContent=t;log('GPIO'+g+': '+t)})}"
        "function r(g){fetch('/read?g='+g).then(r=>r.text()).then(t=>{"
        "document.getElementById('v'+g).textContent=t;log('GPIO'+g+': '+t)})}"
        "mk()</script>")


def respond(link, body, ctype="text/html"):
    head = ("HTTP/1.1 200 OK\r\nContent-Type: %s\r\n"
            "Content-Length: %d\r\nConnection: close\r\n\r\n"
            % (ctype, len(body)))
    payload = head + body
    raw = payload.encode()
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


def handle(link, request):
    line = request.split("\r\n", 1)[0]
    parts = line.split(" ")
    path = parts[1] if len(parts) > 1 else "/"

    if path.startswith("/set"):
        g = qs(path, "g")
        m = qs(path, "m")
        mode = {"1": "high", "0": "low", "2": "hiz"}.get(m, "hiz")
        return respond(link, gpio_set(int(g), mode), "text/plain")
    if path.startswith("/read"):
        g = qs(path, "g")
        return respond(link, gpio_read(int(g)), "text/plain")
    return respond(link, page())


# ---------------------------------------------------------------------- main

def setup_link():
    """Bring the ESP up, onto WiFi, and listening. Returns the IP, or ''."""
    for attempt in range(1, 5):
        log("booting ESP, attempt", attempt)
        if esp_boot():
            break
        # Any pin still held can be what is blocking the boot - GPIO26
        # (AP_READY) reaches the ESP's straps on the related EC600M board - so
        # let go of everything before trying again, not just the last one.
        if attempt == 1 and state:
            log("releasing held pins:", sorted(state.keys()))
            release_all()
        utime.sleep_ms(800)
    else:
        log("ESP never reached firmware")
        return ""

    if not SSID:
        log("no credentials in %s - run: python3 upload.py wifi" % WIFI_FILE)
        return ""

    at(b"AT+SYSSTORE=0")
    at(b"AT+CWMODE=1")
    log("join:", at(b'AT+CWJAP="%s","%s"'
                    % (SSID.encode(), PASSWORD.encode()), 20000)[-50:])
    ip = at(b"AT+CIPSTA?", 4000)
    log("mux:", at(b"AT+CIPMUX=1")[-20:])
    log("server:", at(b"AT+CIPSERVER=1,%d" % PORT)[-20:])

    addr = ""
    marker = b'+CIPSTA:ip:"'
    k = ip.find(marker)
    if k >= 0:
        addr = ip[k + len(marker):ip.find(b'"', k + len(marker))].decode()
    log("listening on http://%s:%d/" % (addr, PORT))
    return addr


def ensure_link():
    """Rebuild everything if the ESP stopped answering.

    Driving some pins - GPIO25/WAKEUP_IN did it - disturbs the link enough
    that CIPSEND gets no prompt back. Since probing pins is the whole point of
    this panel, recover instead of wedging.
    """
    if at(b"AT", 1500):
        return True
    # Release whatever was just driven first. GPIO25 held high keeps the link
    # broken, so rebuilding without letting go of it never succeeds.
    g = last_driven[0]
    if g is not None:
        log("ESP unresponsive after GPIO%d - releasing it" % g)
        try:
            Pin(getattr(Pin, "GPIO%d" % g), Pin.IN, Pin.PULL_DISABLE)
            state.pop(g, None)
        except Exception:
            pass
        last_driven[0] = None
        utime.sleep_ms(300)
        if at(b"AT", 1500):
            log("link came back once the pin was released")
            return True
    log("rebuilding link")
    return bool(setup_link())


def serve():
    if not setup_link():
        return

    global RX
    last_seen = utime.ticks_ms()
    while True:
        utime.sleep_ms(30)
        pump()
        idx = RX.find(b"+IPD,")
        if idx < 0:
            # Drop stale chatter, but only when no request is pending.
            if len(RX) > 4096:
                RX = RX[-1024:]
            # A pin can break the link *after* its response went out, and then
            # nothing arrives ever again - the loop would wait forever. Check
            # the link whenever it has been quiet for a while.
            if utime.ticks_diff(utime.ticks_ms(), last_seen) > 20000:
                last_seen = utime.ticks_ms()
                if not ensure_link():
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
        # Wait for the whole request body to arrive.
        t0 = utime.ticks_ms()
        while len(RX) - (colon + 1) < ln and \
                utime.ticks_diff(utime.ticks_ms(), t0) < 2000:
            utime.sleep_ms(20)
            pump()
        req = RX[colon + 1:colon + 1 + ln]
        RX = RX[colon + 1 + ln:]
        # req is bytes, so the separator has to be bytes too - splitting it
        # with a str raises TypeError on this MicroPython.
        log("req", link, req.split(b"\r\n", 1)[0][:60])
        try:
            ok = handle(link, req.decode("latin1"))
        except Exception as e:
            log("handler error", repr(e)[:60])
            ok = False
        if not ok:
            try:
                at(b"AT+CIPCLOSE=%d" % link, 1500)
            except Exception:
                pass
            ensure_link()
            # Rebuilding takes seconds, during which requests pile up. Answering
            # them afterwards is worse than dropping them: the ESP reuses link
            # ids, so a late reply lands on somebody else's connection and the
            # browser shows the previous request's answer.
            RX = b""


if __name__ == "__main__":
    try:
        serve()
    except Exception as _e:
        log("serve crashed:", repr(_e)[:120])
        raise
