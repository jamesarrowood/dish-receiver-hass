#!/usr/bin/env python3
"""A local web remote for a DISH Wally — click buttons, launch apps, see state.

Runs a stdlib HTTP server that serves a remote-control page and relays actions
to the receiver over three confirmed local interfaces (all discovered by live
testing — see tools/protocol-findings/):

  * SGS remote keys      — POST /www/sgs   (HTTP Digest + message-digest)
  * App launch (DIAL)    — POST /dial/<App>  (Netflix, YouTube), unauthenticated
  * Device state (UPnP)  — SOAP GetEchostarDevInfo, unauthenticated
                           → live power / standby status + firmware

    python3 tools/remote_server.py        # opens http://127.0.0.1:8765

Credentials/host come from tools/remote_creds.json (created by pairing).
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import re
import socket
import socketserver
import sys
import urllib.error
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
CREDS_PATH = os.path.join(HERE, "remote_creds.json")
REALM = "Please provide user name and password"
KEY_URI = "/www/sgs"
ECHO_SVC = "urn:schemas-echostar-com:service:EchostarService:1"
md5 = lambda s: hashlib.md5(s.encode()).hexdigest()  # noqa: E731

# Confirmed-working keys, grouped for the UI. (label, key_name)
LAYOUT = {
    "top": [("Home", "Home"), ("Guide", "Guide"), ("DVR", "DVR"), ("Search", "Search")],
    "sys": [("Info", "Info"), ("Menu", "Menu"), ("Options", "Options"), ("Live TV", "TV")],
    "pad": [("Up", "Up"), ("Down", "Down"), ("Left", "Left"), ("Right", "Right")],
    "transport": [("⏪ Rew", "Rewind"), ("▶ Play", "Play"), ("⏸ Pause", "Pause"),
                  ("⏹ Stop", "Stop"), ("⏩ Jump", "Jump"), ("● Rec", "Record")],
    "colors": [("Red", "Red"), ("Green", "Green"), ("Yellow", "Yellow"), ("Blue", "Blue")],
    "extra": [("🔇 Mute", "Mute"), ("Mode", "Mode"), ("Apps", "Applications"),
              ("⌫", "Backspace"), ("Format", "Format")],
    "apps": [("Netflix", "Netflix"), ("YouTube", "YouTube")],
}


def load_creds() -> dict:
    with open(CREDS_PATH) as fh:
        c = json.load(fh)
    c.setdefault("host", "192.168.1.50")
    c["mac"] = c["mac"].lower().replace(":", "")
    return c


# -- UPnP discovery (find the EchoStar control URL + DIAL base) --------------

def discover_urls(host: str, timeout: float = 3.0) -> dict:
    """SSDP-discover the receiver's UPnP device.xml, then read its control URL
    and DIAL Application-URL. Falls back to conventional ports on failure."""
    urls = {
        "control": f"http://{host}:49316/upnp/control/EchostarService",
        "dial": f"http://{host}/dial/",
    }
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    msg = (
        "M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n'
    ).encode()
    location = None
    try:
        sock.sendto(msg, ("239.255.255.250", 1900))
        import time as _t

        end = _t.monotonic() + timeout
        while _t.monotonic() < end:
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                break
            if addr[0] == host and b"echostar" in data.lower():
                m = re.search(rb"LOCATION:\s*(\S+)", data, re.I)
                if m:
                    location = m.group(1).decode()
                    break
    except OSError:
        pass
    finally:
        sock.close()
    if not location:
        return urls
    try:
        with urllib.request.urlopen(location, timeout=4) as r:
            xml = r.read().decode("utf-8", "replace")
            app_url = r.headers.get("Application-URL")
    except OSError:
        return urls
    base = location.rsplit("/", 1)[0]  # http://host:port
    for svc in re.findall(r"<service>(.*?)</service>", xml, re.S):
        if "EchostarService" in svc:
            cu = re.search(r"<controlURL>(.*?)</controlURL>", svc)
            if cu:
                urls["control"] = base + cu.group(1)
    if app_url:
        urls["dial"] = app_url if app_url.endswith("/") else app_url + "/"
    return urls


def device_info(control_url: str) -> dict:
    """SOAP GetEchostarDevInfo → dict of the receiver's live state."""
    action = "GetEchostarDevInfo"
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{ECHO_SVC}"></u:{action}></s:Body></s:Envelope>'
    )
    req = urllib.request.Request(
        control_url, data=body.encode(),
        headers={"Content-Type": 'text/xml; charset="utf-8"',
                 "SOAPAction": f'"{ECHO_SVC}#{action}"'},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            xml = r.read().decode("utf-8", "replace")
    except OSError:
        return {}
    out = {}
    for k, v in re.findall(r"<(\w+)>([^<]*)</\1>", xml):
        if k not in ("s:Body",) and v.strip():
            out[k] = v.strip()
    return out


# -- SGS remote keys (Digest) -----------------------------------------------

def _post(host, path, body, headers, port=80):
    req = urllib.request.Request(
        f"http://{host}:{port}{path}", data=body.encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


def send_key(c: dict, key_name: str) -> dict:
    body = (
        f'{{"receiver": "XT1{c["mac"]}","key_name": "{key_name}","tv_id": "0",'
        f'"stb": "{c["serial"]}","command": "remote_key"}}'
    )
    host = c["host"]
    st, hd, _ = _post(host, KEY_URI, body, {"Content-Type": "application/json"})
    if st != 401:
        return {"ok": False, "error": f"no auth challenge (HTTP {st})"}
    m = re.search(r'nonce="([^"]+)"', hd.get("WWW-Authenticate", ""))
    if not m:
        return {"ok": False, "error": "no nonce"}
    nonce = m.group(1)
    ha1 = md5(f'{c["user"]}:{REALM}:{c["pw"]}')
    ha2 = md5(f"POST:{KEY_URI}")
    cnonce = os.urandom(4).hex()
    response = md5(f"{ha1}:{nonce}:00000001:{cnonce}:auth:{ha2}")
    mdg = md5(f"{ha1}:{nonce}:{md5(body)}")
    auth = (
        f'Digest username={c["user"]}, realm="{REALM}", nonce="{nonce}", '
        f'uri="{KEY_URI}", algorithm="MD5", qop=auth, nc=00000001, '
        f'cnonce="{cnonce}", response="{response}", message-digest="{mdg}"'
    )
    st, _, text = _post(host, KEY_URI, body,
                        {"Content-Type": "application/json", "Authorization": auth})
    try:
        result = json.loads(text.strip()).get("result")
    except ValueError:
        return {"ok": st < 400}
    if result == 1:
        return {"ok": True}
    if result == 20:
        return {"ok": False, "error": f"'{key_name}' not supported over IP"}
    return {"ok": False, "error": f"result {result}"}


def send_channel(c: dict, channel: str) -> dict:
    for ch in channel.strip():
        if ch.isdigit():
            r = send_key(c, ch)
            if not r.get("ok"):
                return r
    return send_key(c, "Enter")


# -- DIAL app launch --------------------------------------------------------

def launch_app(dial_base: str, app: str) -> dict:
    url = dial_base + app
    req = urllib.request.Request(url, data=b"", headers={"Content-Type": "text/plain"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return {"ok": r.status in (200, 201), "status": r.status}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}"}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def stop_app(dial_base: str, app: str) -> dict:
    req = urllib.request.Request(dial_base + app + "/run", method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return {"ok": r.status == 200, "status": r.status}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}"}
    except OSError as e:
        return {"ok": False, "error": str(e)}


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DISH Wally Remote</title>
<style>
  :root { --bg:#0e1116; --panel:#171b22; --btn:#232a34; --btn2:#2d3644;
          --accent:#e11d2a; --text:#e8edf2; --muted:#8b95a3; --ok:#69db7c; }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body { margin:0; background:var(--bg); color:var(--text);
         font-family:-apple-system,Segoe UI,Roboto,sans-serif;
         display:flex; flex-direction:column; align-items:center; padding:18px; }
  .hdr { display:flex; align-items:center; gap:8px; margin:2px 0 12px; }
  .dot { width:9px; height:9px; border-radius:50%; background:var(--muted); }
  .dot.live { background:var(--ok); box-shadow:0 0 8px var(--ok); }
  h1 { font-size:14px; font-weight:600; color:var(--muted); letter-spacing:.5px; margin:0; }
  .remote { width:330px; background:var(--panel); border-radius:24px; padding:18px;
            box-shadow:0 12px 40px rgba(0,0,0,.5); }
  .row { display:flex; gap:8px; margin-bottom:8px; justify-content:center; }
  button { flex:1; border:0; border-radius:12px; background:var(--btn);
           color:var(--text); font-size:13px; padding:12px 6px; cursor:pointer;
           transition:transform .05s, background .1s; user-select:none; }
  button:hover { background:var(--btn2); }
  button:active { transform:scale(.93); background:var(--accent); }
  .app { background:#1a2030; border:1px solid #2d3644; font-weight:600; padding:13px; }
  .app.netflix:active { background:#e50914; } .app.youtube:active { background:#ff0000; }
  .dpad { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin:10px 0; }
  .dpad .ok { background:var(--accent); font-weight:700; }
  .dpad .sp { visibility:hidden; }
  .grid4 { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }
  .grid5 { display:grid; grid-template-columns:repeat(5,1fr); gap:8px; }
  .num { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-top:8px; }
  .num button { font-size:18px; padding:14px 0; font-weight:600; }
  .tune { display:flex; gap:8px; margin-top:10px; }
  .tune input { flex:2; border-radius:12px; border:1px solid #333c48; background:#0c0f14;
                color:var(--text); text-align:center; font-size:18px; padding:10px; }
  .tune button { flex:1; background:var(--accent); font-weight:700; }
  .color-r{color:#ff6b6b}.color-g{color:#69db7c}.color-y{color:#ffd43b}.color-b{color:#74c0fc}
  .sect { color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:1px;
          margin:14px 0 6px; text-align:center; }
  #toast { position:fixed; bottom:20px; left:50%; transform:translateX(-50%);
           background:#0c0f14; border:1px solid #2d3644; padding:9px 16px; border-radius:10px;
           font-size:13px; opacity:0; transition:opacity .2s; pointer-events:none; }
  #toast.show { opacity:1; } #toast.err { border-color:var(--accent); color:#ff9ba1; }
</style></head><body>
<div class="hdr"><span class="dot" id="dot"></span><h1 id="status">DISH WALLY</h1></div>
<div class="remote">
  <div class="sect">Apps</div>
  <div class="row">__APPS__</div>

  <div class="row">__TOP__</div>
  <div class="row">__SYS__</div>

  <div class="dpad">
    <span class="sp"></span><button data-k="Up">▲</button><span class="sp"></span>
    <button data-k="Left">◀</button><button class="ok" data-k="Enter">OK</button><button data-k="Right">▶</button>
    <span class="sp"></span><button data-k="Down">▼</button><span class="sp"></span>
  </div>
  <div class="row"><button data-k="Back">Back</button><button data-k="Cancel">Cancel</button></div>

  <div class="sect">Playback</div>
  <div class="grid4">__TRANSPORT__</div>

  <div class="sect">Channel</div>
  <div class="num">__NUM__</div>
  <div class="tune"><input id="ch" placeholder="e.g. 140" inputmode="numeric">
    <button onclick="tune()">Tune</button></div>

  <div class="sect">Color / Extra</div>
  <div class="row">__COLORS__</div>
  <div class="grid5" style="margin-top:8px">__EXTRA__</div>
</div>
<div id="toast"></div>
<script>
  const toast=(m,e)=>{const t=document.getElementById('toast');t.textContent=m;
    t.className='show'+(e?' err':'');clearTimeout(t._h);t._h=setTimeout(()=>t.className='',1400);};
  async function key(name){try{const d=await(await fetch('/api/key?name='+encodeURIComponent(name))).json();
    d.ok?toast(name+' ✓'):toast(d.error||'failed',true);}catch(e){toast('server offline',true);}}
  async function app(name){toast('Launching '+name+'…');
    const d=await(await fetch('/api/launch?app='+encodeURIComponent(name))).json();
    toast(d.ok?(name+' launched ✓'):(d.error||'failed'),!d.ok);}
  async function tune(){const v=document.getElementById('ch').value.trim();if(!v)return;
    toast('Tuning '+v+'…');const d=await(await fetch('/api/tune?ch='+encodeURIComponent(v))).json();
    toast(d.ok?('Tuned '+v+' ✓'):(d.error||'failed'),!d.ok);document.getElementById('ch').value='';}
  async function poll(){try{const d=await(await fetch('/api/state')).json();
    const dot=document.getElementById('dot'),s=document.getElementById('status');
    if(d.name){s.textContent=d.name+(d.standby?(' · '+d.standby):'');
      dot.className='dot'+(d.standby==='LIVE'?' live':'');}
  }catch(e){}}
  document.addEventListener('click',e=>{const b=e.target.closest('[data-k]');if(b)key(b.getAttribute('data-k'));
    const a=e.target.closest('[data-app]');if(a)app(a.getAttribute('data-app'));});
  document.getElementById('ch').addEventListener('keydown',e=>{if(e.key==='Enter')tune();});
  poll(); setInterval(poll, 5000);
</script></body></html>"""


def _btns(items, cls=""):
    out = []
    for label, key in items:
        c = ""
        if cls == "colors":
            c = ' class="color-' + key[0].lower() + '"'
        out.append(f'<button{c} data-k="{key}">{label}</button>')
    return "".join(out)


def _appbtns(items):
    return "".join(
        f'<button class="app {key.lower()}" data-app="{key}">{label}</button>'
        for label, key in items
    )


def render_page() -> str:
    return (
        PAGE.replace("__APPS__", _appbtns(LAYOUT["apps"]))
        .replace("__TOP__", _btns(LAYOUT["top"]))
        .replace("__SYS__", _btns(LAYOUT["sys"]))
        .replace("__TRANSPORT__", _btns(LAYOUT["transport"]))
        .replace("__COLORS__", _btns(LAYOUT["colors"], "colors"))
        .replace("__EXTRA__", _btns(LAYOUT["extra"]))
        .replace("__NUM__", _btns([(str(n), str(n)) for n in
                                   [1, 2, 3, 4, 5, 6, 7, 8, 9]] + [("0", "0")]))
    )


class Handler(http.server.BaseHTTPRequestHandler):
    creds: dict = {}
    urls: dict = {}

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            body = render_page().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        q = parse_qs(parsed.query)
        if parsed.path == "/api/key":
            name = (q.get("name") or [""])[0]
            self._json(send_key(self.creds, name) if name else {"ok": False, "error": "no key"})
        elif parsed.path == "/api/tune":
            ch = (q.get("ch") or [""])[0]
            self._json(send_channel(self.creds, ch) if ch else {"ok": False, "error": "no channel"})
        elif parsed.path == "/api/launch":
            app = (q.get("app") or [""])[0]
            self._json(launch_app(self.urls["dial"], app) if app else {"ok": False, "error": "no app"})
        elif parsed.path == "/api/stop":
            app = (q.get("app") or [""])[0]
            self._json(stop_app(self.urls["dial"], app) if app else {"ok": False, "error": "no app"})
        elif parsed.path == "/api/state":
            info = device_info(self.urls["control"])
            self._json({
                "name": info.get("Name"),
                "standby": info.get("Standby_Status"),
                "version": info.get("Version"),
                "type": info.get("Type"),
            })
        else:
            self._json({"ok": False, "error": "not found"}, 404)


def main() -> int:
    if not os.path.exists(CREDS_PATH):
        print(f"No credentials at {CREDS_PATH}.", file=sys.stderr)
        print("Pair first: python3 tools/verify_control.py <ip> --pair", file=sys.stderr)
        return 2
    Handler.creds = load_creds()
    print("Discovering UPnP/DIAL endpoints…")
    Handler.urls = discover_urls(Handler.creds["host"])
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    url = f"http://127.0.0.1:{port}"
    print(f"DISH Wally remote → {url}")
    print(f"  receiver {Handler.creds['host']}  serial {Handler.creds['serial']}")
    print(f"  control  {Handler.urls['control']}")
    print(f"  dial     {Handler.urls['dial']}")
    print("  Ctrl-C to stop.")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
