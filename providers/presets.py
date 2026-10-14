"""Saved hub layouts (presets), switched from the editor or with a global hotkey + number key.

data/presets.json: {"hotkey": "ctrl+shift", "active": "1", "presets": {"1": {"name": "Gaming", "layout": {...}}}}
Slots are "1"-"9" and "0", one per number key (the top row and the numpad both work).

GET  /api/presets -> {"hotkey", "active", "presets": {slot: {"name", "widgets"}}, "taken": [slots whose hotkey failed]}
POST /api/presets {"action": "save", "slot": "1", "name": "Gaming", "layout": {...}}   (no layout: the current layout.json)
                  {"action": "load", "slot": "1"}       writes it to layout.json; open pages switch to it in about a second
                  {"action": "rename", "slot": "1", "name": "..."}
                  {"action": "delete", "slot": "1"}
                  {"action": "hotkey", "hotkey": "ctrl+alt"}    modifiers only, the number is the slot

The hotkeys are registered with Windows (RegisterHotKey) on a thread of their own, so they work whatever window
has the focus, and Windows hands the keypress to the hub instead of that window. Many games switch registered
hotkeys off while they have the focus, so a second thread also watches the keyboard state (_poll_loop); in such a
game the hotkey still works, but the game sees the keypress too. Only slots with a preset are registered, so
the other number keys stay free.
"""
import ctypes
import json
import logging
import threading
import time
from ctypes import wintypes

from hub_config import DATA

from ._shared import load_layout, save_layout
from .layout import check

log = logging.getLogger("hub.presets")

FILE = DATA / "presets.json"
SLOTS = "1234567890"
MODS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4}
MOD_NOREPEAT = 0x4000
WM_HOTKEY, WM_REREGISTER = 0x0312, 0x8001
DEFAULT_HOTKEY = "ctrl+shift"   # not ctrl+alt: that is AltGr, which types @, {, [ ... on many keyboard layouts

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
_user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
_user32.PeekMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT)
_user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

_user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
_user32.GetAsyncKeyState.restype = ctypes.c_short
MOD_VKS = {"alt": 0x12, "ctrl": 0x11, "shift": 0x10}

_lock = threading.RLock()
_thread = {"id": 0}
_taken = []                   # slots whose hotkey another program already has
_watch = {"mods": 0, "keys": {}}          # what the key poll looks for: modifiers, and {virtual key: slot}
_fire_lock = threading.Lock()
_fired = {"slot": None, "t": 0.0}


def _load() -> dict:
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("hotkey", DEFAULT_HOTKEY)
    data.setdefault("active", None)
    data.setdefault("presets", {})
    return data


def _save(data: dict):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(FILE)


def _modifiers(hotkey: str) -> int:
    """'ctrl+shift' -> MOD_CONTROL | MOD_SHIFT. Needs Ctrl or Alt: Shift + a number alone types !, " and so on."""
    keys = [k for k in str(hotkey).lower().split("+") if k]
    if not keys or any(k not in MODS for k in keys) or not {"ctrl", "alt"} & set(keys):
        raise ValueError("hotkey must be Ctrl and/or Alt, optionally with Shift")
    mods = 0
    for k in keys:
        mods |= MODS[k]
    return mods


def _hotkey_name(mods: int) -> str:
    return "+".join(k for k in ("ctrl", "alt", "shift") if mods & MODS[k])


def apply(slot: str) -> dict:
    """Writes preset `slot` to layout.json. Called from the editor and from the hotkey thread."""
    with _lock:
        data = _load()
        preset = data["presets"].get(slot)
        if not preset:
            return {"error": f"no preset in slot {slot}"}
        try:
            layout = check(preset["layout"])
        except ValueError as e:
            return {"error": f"{preset['name']}: {e}"}
        save_layout(layout)
        data["active"] = slot
        _save(data)
    log.info("preset %s (%s) loaded", slot, preset["name"])
    return {"ok": True}


# ----------------------------------------------------------------- hotkeys --
def _register(registered: dict):
    """(Re)registers hotkey + number for each slot with a preset. Runs on the hotkey thread, which owns them."""
    for hid in registered:
        _user32.UnregisterHotKey(None, hid)
    registered.clear()
    data = _load()
    try:
        mods = _modifiers(data["hotkey"])
    except ValueError:
        mods = _modifiers(DEFAULT_HOTKEY)
    taken = []
    for slot in data["presets"]:
        d = int(slot)
        # ids: 1-10 for the number row (VK '0'-'9'), 101-110 for the numpad (VK_NUMPAD0-9)
        for hid, vk in ((d + 1, 0x30 + d), (d + 101, 0x60 + d)):
            if _user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
                registered[hid] = slot
            elif hid <= 10:
                taken.append(slot)
                log.warning("hotkey %s+%s is taken by another program (error %d)",
                            _hotkey_name(mods), slot, ctypes.get_last_error())
    _taken[:] = sorted(taken, key=SLOTS.index)
    _watch.update(mods=mods, keys={vk: slot for slot in data["presets"]
                                   for vk in (0x30 + int(slot), 0x60 + int(slot))})


def _trigger(slot: str, source: str):
    """One keypress can arrive both as WM_HOTKEY and through the key poll; only the first one counts."""
    now = time.monotonic()
    with _fire_lock:
        if _fired["slot"] == slot and now - _fired["t"] < 0.5:
            return
        _fired.update(slot=slot, t=now)
    log.info("preset %s from %s", slot, source)
    # off the key threads, so a slow disk never delays the next keypress
    threading.Thread(target=apply, args=(slot,), daemon=True).start()


def _hotkey_loop():
    msg = wintypes.MSG()
    _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)    # makes this thread's message queue
    _thread["id"] = ctypes.windll.kernel32.GetCurrentThreadId()
    registered = {}
    _register(registered)
    while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY and msg.wParam in registered:
            _trigger(registered[msg.wParam], "hotkey")
        elif msg.message == WM_REREGISTER:
            _register(registered)


def _poll_loop():
    """Games often turn off RegisterHotKey while they have the focus (raw input with RIDEV_NOHOTKEYS; League of
    Legends does). Windows still keeps track of which keys are held, so this reads that state every 25 ms and
    catches the hotkey there. It only reads the state and never hooks into or touches the game. Exactly the
    chosen modifiers count, like RegisterHotKey."""
    down = set()
    pressed = lambda vk: _user32.GetAsyncKeyState(vk) & 0x8000
    while True:
        time.sleep(0.025)
        mods, keys = _watch["mods"], _watch["keys"]
        if not keys or not all(pressed(vk) for name, vk in MOD_VKS.items() if mods & MODS[name]) \
                or any(pressed(vk) for name, vk in MOD_VKS.items() if not mods & MODS[name]) \
                or pressed(0x5B) or pressed(0x5C):                       # Win keys
            down.clear()
            continue
        now = {vk for vk in keys if pressed(vk)}
        for vk in now - down:
            _trigger(keys[vk], "key poll")
        down = now


def _reregister():
    if _thread["id"]:
        _user32.PostThreadMessageW(_thread["id"], WM_REREGISTER, 0, 0)


def start():
    threading.Thread(target=_hotkey_loop, name="preset-hotkeys", daemon=True).start()
    threading.Thread(target=_poll_loop, name="preset-key-poll", daemon=True).start()


# --------------------------------------------------------------------- API --
def get(params: dict) -> dict:
    data = _load()
    return {"hotkey": data["hotkey"], "active": data["active"], "taken": list(_taken),
            "presets": {s: {"name": p["name"], "widgets": len(p["layout"].get("widgets", []))}
                        for s, p in data["presets"].items()}}


def post(body: dict) -> dict:
    action, slot = body.get("action"), str(body.get("slot", ""))
    if action == "hotkey":
        try:
            hotkey = _hotkey_name(_modifiers(body.get("hotkey", "")))
        except ValueError as e:
            return {"error": str(e)}
        with _lock:
            data = _load()
            data["hotkey"] = hotkey
            _save(data)
        _reregister()
        return {"ok": True}
    if len(slot) != 1 or slot not in SLOTS:
        return {"error": "slot must be 0-9"}
    if action == "load":
        return apply(slot)
    with _lock:
        data = _load()
        if action == "save":
            try:
                layout = check(body["layout"] if "layout" in body else load_layout())
            except ValueError as e:
                return {"error": str(e)}
            name = str(body.get("name") or "").strip()[:40] or f"Preset {slot}"
            data["presets"][slot] = {"name": name, "layout": layout}
            data["active"] = slot
        elif action == "rename":
            if slot not in data["presets"]:
                return {"error": f"no preset in slot {slot}"}
            data["presets"][slot]["name"] = str(body.get("name") or "").strip()[:40] or f"Preset {slot}"
        elif action == "delete":
            data["presets"].pop(slot, None)
            if data["active"] == slot:
                data["active"] = None
        else:
            return {"error": "unknown action"}
        data["presets"] = dict(sorted(data["presets"].items(), key=lambda kv: SLOTS.index(kv[0])))
        _save(data)
    if action in ("save", "delete"):
        _reregister()
    return {"ok": True}
