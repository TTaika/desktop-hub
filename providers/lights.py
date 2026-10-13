"""Airam / Tuya WiFi bulbs over the local network, through the lights tool in assistant/tools/ (bulbs in
data/devices.json), or the voice assistant's own copy when voice_assistant_dir is set, so both share the bulbs
and saved scenes.

GET  /api/lights  -> {"lights": [{name, on, brightness, mode}], "scenes": [...], "colours": {...}}  (cached 4 s)
POST /api/lights  {"name": "all", "state": "on"|"off"} or {"brightness": 1-100} or {"color_temp": "warm"}
                  or {"color": "red"} or {"scene": "normal"}  - the same arguments the voice tool's set_light takes
"""
import sys
import threading
import time

from hub_config import voice_assistant_dir

_lock = threading.Lock()
_cache = {"t": 0.0, "value": None}
_lt = None


def _tool():
    global _lt
    if _lt is None:
        va = voice_assistant_dir()             # its own copy and logins; else the copy in assistant/
        if va and va not in sys.path:
            sys.path.insert(0, va)
        from assistant.tools import lights_tool
        _lt = lights_tool
    return _lt


def _colours(lt) -> dict:
    """English colour names -> hex; the Finnish synonyms map to the same colours and are left out."""
    out = {}
    for name, rgb in lt.COLOURS.items():
        hexv = "#%02x%02x%02x" % rgb if rgb else None
        if hexv and hexv not in out.values():
            out[name] = hexv
    return out


def _status() -> dict:
    lt = _tool()
    devices = lt.load_devices()
    if not devices:
        return {"error": "No bulbs set up: run  py -3.13 tools/fetch_tuya_keys.py <Smart Life user code>  (see README)."}
    st = lt.h_light_status(devices)
    return {"lights": st["lights"], "scenes": st["saved_scenes"], "colours": _colours(lt),
            "temps": ["warm", "neutral", "cool"]}


def get(params: dict) -> dict:
    with _lock:
        if _cache["value"] is None or time.monotonic() - _cache["t"] > 4:
            _cache["value"] = _status()
            _cache["t"] = time.monotonic()
        return _cache["value"]


def post(body: dict) -> dict:
    lt = _tool()
    args = {k: body[k] for k in ("name", "state", "brightness", "color_temp", "color", "scene") if k in body}
    with _lock:
        try:
            resolved = lt.v_set_light(args)
            result = lt.h_set_light(**resolved)
        except (lt.ValidationError, lt.ToolError) as e:
            return {"error": str(e)}
        finally:
            _cache["value"] = None       # next GET reads the bulbs again
    return {"ok": True, "result": result}
