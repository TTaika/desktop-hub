"""Desktop Hub backend: serves the widget page (web/) and a small JSON API, on 127.0.0.1 only.

Every module in providers/ is one data source, reachable at /api/<module name>:
  get(params: dict) -> dict     answers GET  /api/<name>?a=b
  post(body: dict) -> dict      answers POST /api/<name> with a JSON body
  start()                       optional, called once at startup (e.g. to start a background thread)
A module whose name starts with "_" is skipped.

Run:  pyw -3.13 server.py   (no console)   or   py -3.13 server.py   (logs to the console too)
"""
import importlib
import json
import logging
import pkgutil
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from hub_config import DATA, PORT, WEB

log = logging.getLogger("hub")
PROVIDERS = {}

# Windows' registry can map .js to text/plain, which browsers refuse for ES modules
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
         ".woff2": "font/woff2", ".mp4": "video/mp4", ".webm": "video/webm"}
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
ALLOWED_ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}

_rev = {"t": 0.0, "value": 0}
LAYOUT_FILES = {WEB / "layout.json", WEB / "layout.tmp"}


def web_rev() -> int:
    """Newest modification time under web/, so open pages reload themselves after an edit. Cached 2 s.
    layout.json is left out: it has layout_rev, and pages swap a new layout in place without reloading."""
    now = time.monotonic()
    if now - _rev["t"] > 2:
        _rev["value"] = int(max((p.stat().st_mtime for p in WEB.rglob("*") if p.is_file() and p not in LAYOUT_FILES),
                                default=0))
        _rev["t"] = now
    return _rev["value"]


def layout_rev() -> int:
    """layout.json's modification time; it changes on a save in the editor or a preset hotkey. Not cached."""
    try:
        return (WEB / "layout.json").stat().st_mtime_ns
    except OSError:
        return 0


def load_providers():
    import providers
    for m in pkgutil.iter_modules(providers.__path__):
        if m.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"providers.{m.name}")
            if hasattr(mod, "start"):
                mod.start()
            PROVIDERS[m.name] = mod
            log.info("provider %s loaded", m.name)
        except Exception:
            log.exception("provider %s failed to load", m.name)


class Handler(BaseHTTPRequestHandler):
    server_version = "DesktopHub"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str, cors=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj, cors=False):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), TYPES[".json"], cors)

    def _trusted(self) -> bool:
        """Only this machine, by name (no DNS rebinding) and, if the browser says, from our own page."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        origin = self.headers.get("Origin")
        return host in ALLOWED_HOSTS and (origin is None or origin in ALLOWED_ORIGINS)

    def _call(self, fn, arg):
        try:
            self._json(200, fn(arg))
        except Exception as e:
            log.exception("%s %s failed", self.command, self.path)
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/health":     # read by the Wallpaper Engine loader page, which has a file:// origin
            return self._json(200, {"ok": True, "web_rev": web_rev(), "layout_rev": layout_rev()}, cors=True)
        if not self._trusted():
            return self._json(403, {"error": "forbidden"})
        if url.path.startswith("/api/"):
            mod = PROVIDERS.get(url.path[5:].strip("/"))
            if not mod or not hasattr(mod, "get"):
                return self._json(404, {"error": "no such provider"})
            return self._call(mod.get, dict(parse_qsl(url.query)))
        if url.path == "/media/background":
            return self._background()
        if url.path.startswith("/media/preview/"):
            return self._preview(url.path.rsplit("/", 1)[1])
        self._static(url.path)

    def do_POST(self):
        url = urlparse(self.path)
        if not self._trusted() or not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(403, {"error": "forbidden"})
        mod = PROVIDERS.get(url.path[5:].strip("/")) if url.path.startswith("/api/") else None
        if not mod or not hasattr(mod, "post"):
            return self._json(404, {"error": "no such provider"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._json(400, {"error": "body is not JSON"})
        self._call(mod.post, body)

    def _static(self, path: str):
        target = (WEB / path.lstrip("/")).resolve()
        if target.is_dir():
            target = target / "index.html"
        if not target.is_relative_to(WEB) or not target.is_file():
            return self._json(404, {"error": "not found"})
        self._file(target)

    def _background(self):
        """The background file named in layout.json by an absolute path, e.g. a video in Wallpaper Engine's
        workshop folder, served from where it is instead of being copied into web/. Only that one file."""
        bg = json.loads((WEB / "layout.json").read_text(encoding="utf-8")).get("background")
        src = Path(bg.get("src") if isinstance(bg, dict) else bg or "")
        if not src.is_absolute() or not src.is_file():
            return self._json(404, {"error": "no background file"})
        self._file(src)

    def _preview(self, wallpaper_id: str):
        """Thumbnail of an installed Wallpaper Engine video wallpaper, for the editor's background picker."""
        from providers._shared import video_wallpapers
        hit = next((b for b in video_wallpapers() if b["id"] == wallpaper_id and b["preview"]), None)
        if not hit:
            return self._json(404, {"error": "no preview"})
        self._file(hit["preview"])

    def _file(self, target: Path):
        """A file in chunks, honouring Range requests so videos can seek without loading the whole file."""
        size = target.stat().st_size
        start, end, code = 0, size - 1, 200
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if m and (m[1] or m[2]):
            if m[1]:
                start, end = int(m[1]), min(int(m[2]) if m[2] else size - 1, size - 1)
            else:
                start = max(0, size - int(m[2]))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", TYPES.get(target.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with open(target, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(left, 256 * 1024))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, OSError):
            pass                         # the browser stopped reading, e.g. after seeking


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second hub bind the same port and run alongside the first (two Discord
    # connections, two of everything), so "port in use" below never fired.
    allow_reuse_address = sys.platform != "win32"


def main():
    handlers =[logging.FileHandler(DATA / "hub.log", encoding="utf-8")]
    if sys.stdout:                       # None under pythonw
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        server = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        log.error("port %d is in use - is the hub already running?", PORT)
        return
    server.daemon_threads = True
    threading.Thread(target=load_providers, daemon=True).start()   # a slow provider must not delay the page
    log.info("Desktop Hub on http://127.0.0.1:%d/", PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
