"""Which monitor the overlay covers. The overlay asks every couple of seconds and moves itself when this changes.

GET  /api/display -> {"monitors": [{id, x, y, width, height, primary}], "selected": id or null}
                     id is the Windows device name ("\\\\.\\DISPLAY2"), null = the overlay's default (first non-primary)
POST /api/display {"monitor": id or null} -> {"ok": true}
"""
import ctypes
import json
from ctypes import wintypes

from hub_config import DATA

FILE = DATA / "display.json"


class _MonitorInfoEx(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


_ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

# The server process isn't DPI aware, so without this Windows reports scaled coordinates for high-DPI monitors.
ctypes.windll.user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
ctypes.windll.user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]


def monitors() -> list:
    out = []

    def each(handle, _hdc, _rect, _data):
        info = _MonitorInfoEx(cbSize=ctypes.sizeof(_MonitorInfoEx))
        ctypes.windll.user32.GetMonitorInfoW(handle, ctypes.byref(info))
        r = info.rcMonitor
        out.append({"id": info.szDevice, "x": r.left, "y": r.top, "width": r.right - r.left, "height": r.bottom - r.top,
                    "primary": bool(info.dwFlags & 1)})
        return True

    old = ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # per-monitor v2: real pixels
    try:
        ctypes.windll.user32.EnumDisplayMonitors(None, None, _ENUM(each), 0)
    finally:
        ctypes.windll.user32.SetThreadDpiAwarenessContext(old)
    return out


def selected():
    try:
        return json.loads(FILE.read_text(encoding="utf-8")).get("monitor")
    except (OSError, ValueError):
        return None


def get(params: dict) -> dict:
    return {"monitors": monitors(), "selected": selected()}


def post(body: dict) -> dict:
    mon = body.get("monitor")
    if mon is not None and mon not in {m["id"] for m in monitors()}:
        return {"error": "No such monitor"}
    FILE.write_text(json.dumps({"monitor": mon}), encoding="utf-8")
    return {"ok": True}
