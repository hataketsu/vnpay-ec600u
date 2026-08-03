#!/usr/bin/env python3
"""Local web panel for driving EC600U GPIOs one at a time.

Runs a small HTTP server on localhost that holds a single raw-REPL connection
to the module. The page lets you drive any pin high, low, or back to
high-impedance, and sample UART2 so you can see immediately whether a pin
change woke the ESP8285 up.

    python3 gpio_panel.py            # then open http://127.0.0.1:8760

Only one process can own the REPL, so stop other scripts first.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import pinmap
from qpy import Qpy

HOST, PORT = "127.0.0.1", 8760

_lock = threading.Lock()
_repl = None
_state = {}          # gpio -> "HIGH" / "LOW" / "HI-Z"


def repl():
    """Return the shared REPL, reconnecting if the module was power-cycled."""
    global _repl
    if _repl is None:
        _repl = Qpy()
    return _repl


def drop_repl():
    global _repl
    if _repl is not None:
        try:
            _repl.close()
        except Exception:
            pass
        _repl = None


def run(code, read_for=15):
    with _lock:
        for attempt in (1, 2):
            try:
                out, err = repl().exec(code, read_for=read_for)
                return {"out": out, "err": err}
            except Exception as exc:
                drop_repl()
                if attempt == 2:
                    return {"out": "", "err": "REPL error: %s" % exc}


def drive(gpio, mode):
    if mode == "hiz":
        code = ("from machine import Pin\n"
                "Pin(Pin.GPIO%d, Pin.IN, Pin.PULL_DISABLE)\n"
                "print('GPIO%d hi-z')" % (gpio, gpio))
        label = "HI-Z"
    else:
        level = 1 if mode == "high" else 0
        code = ("from machine import Pin\n"
                "Pin(Pin.GPIO%d, Pin.OUT, Pin.PULL_DISABLE, %d)\n"
                "print('GPIO%d = %d')" % (gpio, level, gpio, level))
        label = "HIGH" if level else "LOW"
    res = run(code)
    if not res["err"]:
        _state[gpio] = label
    res["state"] = _state.get(gpio, "?")
    return res


def read_all():
    code = ("from machine import Pin\n"
            "r={}\n"
            "for i in range(1,48):\n"
            "    p=getattr(Pin,'GPIO%d'%i,None)\n"
            "    if p is None: continue\n"
            "    try: r[i]=(Pin(p,Pin.IN,Pin.PULL_PU).read(),"
            "Pin(p,Pin.IN,Pin.PULL_PD).read())\n"
            "    except Exception: r[i]=('E','E')\n"
            "for k in sorted(r): print(k,r[k][0],r[k][1])")
    res = run(code, read_for=35)
    levels = {}
    for line in res["out"].splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0].isdigit():
            pu, pd = parts[1], parts[2]
            if pu == "1" and pd == "0":
                v = "floating"
            elif pu == pd == "1":
                v = "driven HIGH"
            elif pu == pd == "0":
                v = "driven LOW"
            else:
                v = "?"
            levels[int(parts[0])] = v
    # Reading reconfigures every pin as an input, so nothing is driven now.
    _state.clear()
    res["levels"] = levels
    return res


def esp_probe(ms=2000, baud=115200):
    code = ("from machine import UART\n"
            "import utime\n"
            "_u=UART(UART.%s,%d,8,0,1,0)\n"
            "try:\n"
            "    b=b''\n"
            "    for _i in range(%d):\n"
            "        utime.sleep_ms(50)\n"
            "        n=_u.any()\n"
            "        if n: b+=bytes(_u.read(n))\n"
            "    print('n',len(b))\n"
            "    print(b[:200])\n"
            "finally:\n"
            "    try: _u.close()\n"
            "    except Exception: pass\n" % (pinmap.ESP_UART, baud, ms // 50))
    return run(code, read_for=ms / 1000.0 + 20)


def esp_reset():
    code = ("from machine import Pin\n"
            "import utime\n"
            "Pin(Pin.GPIO{0}, Pin.OUT, Pin.PULL_DISABLE, 0)\n"
            "utime.sleep_ms(400)\n"
            "Pin(Pin.GPIO{0}, Pin.OUT, Pin.PULL_DISABLE, 1)\n"
            "print('esp reset, GPIO{0} high')").format(pinmap.ESP_EN)
    res = run(code)
    _state[pinmap.ESP_EN] = "HIGH"
    return res


# Pins with a known job, kept out of the bulk drive so a sweep cannot cut the
# ESP's power, fight a button, disturb the NOR bus, or contend with something
# already driving the line.
def unknown_pins():
    known = set(getattr(pinmap, "BUTTONS", {}))
    known |= set(getattr(pinmap, "NOR_SPI", ()))
    known |= set(pinmap.EXTERNALLY_DRIVEN)
    known |= set(getattr(pinmap, "LEDS", {}))
    known |= {pinmap.ESP_EN, getattr(pinmap, "ESP_STRAP", -1), 14, 7, 19}
    return [g for g in sorted(pinmap.PINS) if g not in known]


def drive_many(pins, mode):
    level = "" if mode == "hiz" else (1 if mode == "high" else 0)
    if mode == "hiz":
        body = ("    try: Pin(getattr(Pin,'GPIO%d'%g), Pin.IN, Pin.PULL_DISABLE)\n"
                "    except Exception: pass\n")
    else:
        body = ("    try: Pin(getattr(Pin,'GPIO%d'%g), Pin.OUT, Pin.PULL_DISABLE, "
                + str(level) + ")\n    except Exception: pass\n")
    # Built by concatenation: a trailing % here binds to the last literal
    # only, not to the whole expression.
    tail = "print('%d pins set to %s')" % (len(pins), mode)
    code = ("from machine import Pin\n"
            "for g in " + repr(pins) + ":\n" + body + tail)
    res = run(code, read_for=40)
    for g in pins:
        if mode == "hiz":
            _state.pop(g, None)
        else:
            _state[g] = "HIGH" if level else "LOW"
    return res


def pin_meta():
    out = []
    for gpio in sorted(pinmap.PINS):
        pin, func, domain, signal = pinmap.PINS[gpio]
        tag, note = pinmap.NOTES.get(gpio, ("", ""))
        out.append({
            "gpio": gpio, "pin": pin, "func": func, "domain": domain,
            "signal": signal, "tag": tag, "note": note,
            "driven": pinmap.EXTERNALLY_DRIVEN.get(gpio, ""),
            "conflict": pinmap.CONFLICTS.get(gpio, 0),
            "is_en": gpio == pinmap.ESP_EN,
            "button": getattr(pinmap, "BUTTONS", {}).get(gpio, ""),
            "strap": gpio == getattr(pinmap, "ESP_STRAP", -1),
            "nor": gpio in getattr(pinmap, "NOR_SPI", ()),
            "pa": gpio == getattr(pinmap, "AMP_CTRL", -1),
            "led": getattr(pinmap, "LEDS", {}).get(gpio, ""),
        })
    return out


PAGE = r"""<!-- served locally; talks to the module over the raw REPL -->
<title>EC600U GPIO panel — VNPay board</title>
<style>
:root{
  --bg:#f6f7f9; --card:#fff; --ink:#14161a; --mut:#6b7280; --line:#e3e6ea;
  --hi:#0a7d32; --lo:#1d4ed8; --hiz:#6b7280; --warn:#b45309; --en:#a21caf;
  --accent:#0f62fe;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0e1013; --card:#171a1f; --ink:#e8eaed; --mut:#9aa2ad; --line:#272b32;
  --hi:#4ade80; --lo:#93b4ff; --hiz:#9aa2ad; --warn:#fbbf24; --en:#e879f9;
  --accent:#7aa2ff;
}}
:root[data-theme=dark]{
  --bg:#0e1013; --card:#171a1f; --ink:#e8eaed; --mut:#9aa2ad; --line:#272b32;
  --hi:#4ade80; --lo:#93b4ff; --hiz:#9aa2ad; --warn:#fbbf24; --en:#e879f9;
  --accent:#7aa2ff;
}
:root[data-theme=light]{
  --bg:#f6f7f9; --card:#fff; --ink:#14161a; --mut:#6b7280; --line:#e3e6ea;
  --hi:#0a7d32; --lo:#1d4ed8; --hiz:#6b7280; --warn:#b45309; --en:#a21caf;
  --accent:#0f62fe;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);
 border-bottom:1px solid var(--line);padding:14px 18px}
h1{margin:0 0 2px;font-size:17px;letter-spacing:-.01em}
.sub{color:var(--mut);font-size:12.5px}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin-top:11px;align-items:center}
button{font:inherit;border:1px solid var(--line);background:var(--card);
 color:var(--ink);border-radius:7px;padding:6px 11px;cursor:pointer}
button:hover{border-color:var(--accent)}
button.p{background:var(--accent);color:#fff;border-color:transparent;font-weight:600}
main{padding:16px 18px 40px}
.grid{display:grid;gap:10px;
 grid-template-columns:repeat(auto-fill,minmax(215px,1fr))}
.c{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 11px}
.c.en{border-color:var(--en);box-shadow:0 0 0 1px var(--en) inset}
.c.warn{border-color:var(--warn)}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:6px}
.g{font-weight:700;font-size:15px;letter-spacing:-.01em}
.pin{color:var(--mut);font-size:12px;font-variant-numeric:tabular-nums}
.sig{margin-top:1px;font-size:12.5px;font-weight:600;color:var(--accent)}
.fn{color:var(--mut);font-size:11.5px;margin-top:1px;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.badges{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}
.b{font-size:10.5px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;
 padding:1.5px 6px;border-radius:999px;border:1px solid currentColor}
.b.en{color:var(--en)} .b.warn{color:var(--warn)} .b.mut{color:var(--mut)}
.b.btn{color:#0ea5e9} .b.amp{color:#16a34a} .b.led{color:#ef4444}
.btns{display:flex;gap:5px;margin-top:9px}
.btns button{flex:1;padding:5px 0;font-size:12.5px;font-weight:600}
.st{margin-top:7px;font-size:12px;font-variant-numeric:tabular-nums;color:var(--mut)}
.st b{color:var(--ink)}
.st.HIGH b{color:var(--hi)} .st.LOW b{color:var(--lo)}
.note{margin-top:6px;font-size:11.5px;color:var(--mut);border-top:1px dashed var(--line);padding-top:5px}
#log{margin-top:18px;background:var(--card);border:1px solid var(--line);
 border-radius:10px;padding:11px 13px;font:12px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;
 max-height:290px;overflow:auto;white-space:pre-wrap;word-break:break-word}
.filter{padding:6px 10px;border-radius:7px;border:1px solid var(--line);
 background:var(--card);color:var(--ink);font:inherit;min-width:150px}
</style>

<header>
  <h1>EC600U GPIO panel <span style="color:var(--mut);font-weight:400">— VNPay board</span></h1>
  <div class="sub">ESP8285 enable is <b style="color:var(--en)">GPIO44</b> (module pin 14), active HIGH.
    Driving <b style="color:var(--warn)">GPIO14</b> high silences the ESP.</div>
  <div class="bar">
    <button class="p" onclick="espReset()">Reset ESP (toggle GPIO44)</button>
    <button onclick="espProbe()">Probe UART2 (2 s)</button>
    <button onclick="readAll()">Read all levels</button>
    <button onclick="allHiZ()">All pins hi-Z</button>
    <button onclick="readButtons()">Read buttons</button>
    <button onclick="bulk('high')">Unknown pins HIGH</button>
    <button onclick="bulk('low')">Unknown pins LOW</button>
    <input class="filter" id="q" placeholder="filter: gpio, pin, signal…" oninput="render()">
    <button onclick="toggleTheme()" style="margin-left:auto">Theme</button>
  </div>
</header>

<main>
  <div class="grid" id="grid"></div>
  <div id="log">ready.</div>
</main>

<script>
let META=[], LEVELS={}, STATE={};

function log(s){const l=document.getElementById('log');
  l.textContent=new Date().toLocaleTimeString()+"  "+s+"\n"+l.textContent;}

async function api(p,q){
  const r=await fetch(p+(q?'?'+new URLSearchParams(q):''));
  return await r.json();
}

async function boot(){
  const d=await api('/api/meta'); META=d.pins; render();
  log('loaded '+META.length+' pins. ESP enable = GPIO'+d.esp_en+', UART '+d.esp_uart+'.');
}

function render(){
  const f=(document.getElementById('q').value||'').toLowerCase();
  const g=document.getElementById('grid'); g.innerHTML='';
  for(const p of META){
    const hay=('gpio'+p.gpio+' pin'+p.pin+' '+p.signal+' '+p.func+' '+p.tag).toLowerCase();
    if(f && !hay.includes(f)) continue;
    const st=STATE[p.gpio]||'—';
    const d=document.createElement('div');
    d.className='c'+(p.is_en?' en':'')+(p.tag==='KILLS ESP'?' warn':'');
    let badges='';
    if(p.is_en) badges+='<span class="b en">esp 3v3 switch</span>';
    if(p.button) badges+='<span class="b btn">button '+p.button+'</span>';
    if(p.led) badges+='<span class="b led">LED '+p.led+'</span>';
    if(p.strap) badges+='<span class="b en">esp boot strap</span>';
    if(p.nor) badges+='<span class="b warn">NOR spi</span>';
    if(p.pa) badges+='<span class="b amp">amp?</span>';
    if(p.tag==='KILLS ESP') badges+='<span class="b warn">kills esp</span>';
    if(p.driven) badges+='<span class="b warn">ext '+p.driven+'</span>';
    if(p.tag&&!p.is_en&&p.tag!=='KILLS ESP') badges+='<span class="b mut">'+p.tag+'</span>';
    badges+='<span class="b mut">'+p.domain+'</span>';
    if(p.conflict) badges+='<span class="b mut">vs GPIO'+p.conflict+'</span>';
    d.innerHTML=
      '<div class="top"><span class="g">GPIO'+p.gpio+'</span>'+
      '<span class="pin">pin '+p.pin+'</span></div>'+
      (p.signal?'<div class="sig">'+p.signal+'</div>':'')+
      '<div class="fn">'+p.func+'</div>'+
      '<div class="badges">'+badges+'</div>'+
      '<div class="btns">'+
        '<button onclick="drive('+p.gpio+',\'high\')">HIGH</button>'+
        '<button onclick="drive('+p.gpio+',\'low\')">LOW</button>'+
        '<button onclick="drive('+p.gpio+',\'hiz\')">HI-Z</button>'+
      '</div>'+
      '<div class="st '+st+'">driving <b>'+st+'</b>'+
        (LEVELS[p.gpio]?' · measured '+LEVELS[p.gpio]:'')+'</div>'+
      (p.note?'<div class="note">'+p.note+'</div>':'');
    g.appendChild(d);
  }
}

async function drive(gpio,mode){
  log('GPIO'+gpio+' -> '+mode.toUpperCase()+' …');
  const r=await api('/api/drive',{gpio:gpio,mode:mode});
  if(r.err) log('  error: '+r.err);
  else{STATE[gpio]=r.state; log('  '+(r.out||'ok')); }
  render();
}

async function readAll(){
  log('reading every pin hi-Z (this drops anything you were driving) …');
  const r=await api('/api/readall');
  LEVELS=r.levels||{}; STATE={};
  const drivenPins=Object.entries(LEVELS).filter(([k,v])=>v!=='floating');
  log('  driven: '+(drivenPins.map(([k,v])=>'GPIO'+k+'='+v).join(', ')||'none'));
  render();
}

async function espReset(){
  log('resetting ESP …');
  const r=await api('/api/esp_reset');
  log('  '+(r.out||r.err));
  STATE[44]='HIGH'; render();
}

async function espProbe(){
  log('sampling UART2 for 2 s …');
  const r=await api('/api/esp_probe');
  log('  '+(r.out||r.err).replace(/\n/g,'\n  '));
}

async function bulk(mode){
  log('driving every unknown pin '+mode.toUpperCase()+' ...');
  const r=await api(mode==='high'?'/api/allhigh':'/api/alllow');
  if(r.err){log('  error: '+r.err); return;}
  const ps=r.pins||[];
  ps.forEach(g=>STATE[g]=mode==='high'?'HIGH':'LOW');
  log('  '+ps.length+' pins: '+ps.join(','));
  render();
}

async function readButtons(){
  const r=await api('/api/buttons');
  log('buttons -> '+(r.out||r.err));
}

async function allHiZ(){
  log('returning every pin to hi-Z …');
  const r=await api('/api/allhiz');
  STATE={}; log('  '+(r.out||r.err)); render();
}

function toggleTheme(){
  const cur=document.documentElement.getAttribute('data-theme');
  const next=cur==='dark'?'light':(cur==='light'?'':'dark');
  if(next) document.documentElement.setAttribute('data-theme',next);
  else document.documentElement.removeAttribute('data-theme');
}

boot();
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype="application/json"):
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path

        if p in ("/", "/index.html"):
            return self._send(PAGE, "text/html; charset=utf-8")
        if p == "/api/meta":
            return self._send(json.dumps({
                "pins": pin_meta(), "esp_en": pinmap.ESP_EN,
                "esp_uart": pinmap.ESP_UART}))
        if p == "/api/drive":
            return self._send(json.dumps(
                drive(int(q["gpio"]), q.get("mode", "hiz"))))
        if p == "/api/readall":
            return self._send(json.dumps(read_all()))
        if p == "/api/esp_probe":
            return self._send(json.dumps(esp_probe()))
        if p == "/api/esp_reset":
            return self._send(json.dumps(esp_reset()))
        if p == "/api/allhigh":
            pins = unknown_pins()
            r = drive_many(pins, "high")
            r["pins"] = pins
            return self._send(json.dumps(r))
        if p == "/api/alllow":
            pins = unknown_pins()
            r = drive_many(pins, "low")
            r["pins"] = pins
            return self._send(json.dumps(r))
        if p == "/api/buttons":
            code = ("from machine import Pin\n"
                    "out=''\n"
                    "for g,n in ((28,'M'),(27,'+'),(16,'-')):\n"
                    "    v=Pin(getattr(Pin,'GPIO%d'%g),Pin.IN,Pin.PULL_PD).read()\n"
                    "    out+='%s(GPIO%d)=%d  '%(n,g,v)\n"
                    "print(out)")
            return self._send(json.dumps(run(code, read_for=15)))
        if p == "/api/allhiz":
            code = ("from machine import Pin\n"
                    "for i in range(1,48):\n"
                    "    p=getattr(Pin,'GPIO%d'%i,None)\n"
                    "    if p is None: continue\n"
                    "    try: Pin(p,Pin.IN,Pin.PULL_DISABLE)\n"
                    "    except Exception: pass\n"
                    "print('all hi-z')")
            _state.clear()
            return self._send(json.dumps(run(code, read_for=30)))
        self.send_error(404)


if __name__ == "__main__":
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print("EC600U GPIO panel  ->  http://%s:%d" % (HOST, PORT))
    print("ESP enable = GPIO%d (module pin %d), active HIGH"
          % (pinmap.ESP_EN, pinmap.PINS[pinmap.ESP_EN][0]))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        drop_repl()
        print("\nstopped, REPL released")
