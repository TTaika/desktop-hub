"""Airam SmartHome bulbs (Tuya WiFi) over the local network, no cloud:
  set_light           (no approval)  on/off, brightness, colour temperature, colour, or a saved scene
  light_status        (read-only)    what is on, how bright, which scenes are saved
  save_light_scene    (approval only when replacing)  current state, or spoken settings, under a name
  delete_light_scene  (approval)     forget a saved scene

Bulbs are read from config.TUYA_DEVICES_FILE, written by tools/fetch_tuya_keys.py
(name, id, key, ip, version). Names are the ones the bulbs have in the app.
Optional config.LIGHT_GROUPS maps a spoken room name to several bulb names.
Scenes are kept in config.LIGHT_SCENES_FILE.
"""
import colorsys
import json
import logging
import re
import threading

from .. import config
from .registry import Tool, ValidationError, ToolError, register

log = logging.getLogger("lights")

STATES = ["on", "off"]
TEMPS = {"warm": 0, "neutral": 50, "cool": 100, "cold": 100, "white": 50, "daylight": 100,
         "lämmin": 0, "neutraali": 50, "kylmä": 100, "viileä": 100}
COLOURS = {
    "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "yellow": (255, 200, 0), "orange": (255, 120, 0),
    "purple": (150, 0, 255), "pink": (255, 80, 180), "cyan": (0, 255, 255), "white": None,
    "punainen": (255, 0, 0), "vihreä": (0, 255, 0), "sininen": (0, 0, 255), "keltainen": (255, 200, 0),
    "oranssi": (255, 120, 0), "violetti": (150, 0, 255), "pinkki": (255, 80, 180), "valkoinen": None,
}
ALL_WORDS = {"all", "all lights", "light", "everything", "every light", "lights", "the lights", "kaikki", "kaikki valot", "valot"}

_devices = None
_lock = threading.Lock()
_handles = {}


def load_devices() -> list:
    """[{name, id, key, ip, version}, ...] from config.TUYA_DEVICES_FILE; [] if missing."""
    global _devices
    if _devices is None:
        try:
            raw = json.loads(config.TUYA_DEVICES_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = []
        except Exception as e:
            log.warning("devices file unreadable: %s", e)
            raw = []
        _devices = [d for d in raw if d.get("id") and d.get("key")]
    return _devices


def reload_devices():
    global _devices
    _devices = None
    _handles.clear()


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", str(s or "").lower()).split())


def match_lights(name: str) -> list:
    """Bulbs whose name (or group name) matches the spoken name. 'all' / '' -> every bulb.
    Several names may be joined with a comma or 'and' ("bedroom and kitchen")."""
    parts = [p for p in re.split(r",|\band\b|\bja\b|&", str(name or ""), flags=re.I) if p.strip()]
    if len(parts) > 1:
        seen, out = set(), []
        for p in parts:
            for d in _match_one(p):
                if d["id"] not in seen:
                    seen.add(d["id"])
                    out.append(d)
        return out
    return _match_one(name)


def _match_one(name: str) -> list:
    devs = load_devices()
    key = _norm(name)
    for prefix in ("the ", "my "):
        if key.startswith(prefix):
            key = key[len(prefix):]
    if not key or key in ALL_WORDS:
        return list(devs)
    key = re.sub(r" (light|lights|lamp)$", "", key)   # "bedroom light" -> "bedroom"
    if key in ALL_WORDS:
        return list(devs)
    groups = {_norm(k): v for k, v in getattr(config, "LIGHT_GROUPS", {}).items()}
    if key in groups:
        wanted = {_norm(n) for n in groups[key]}
        return [d for d in devs if _norm(d["name"]) in wanted]
    exact = [d for d in devs if _norm(d["name"]) == key]
    if exact:
        return exact
    partial = [d for d in devs if key in _norm(d["name"]) or _norm(d["name"]) in key]
    if partial:
        return partial
    toks = set(key.split())
    return [d for d in devs if toks & set(_norm(d["name"]).split())]


def _bulb(dev: dict):
    """A tinytuya.BulbDevice for one entry of devices.json. persist=False: a fresh connection per command
    (~0.1 s). On a kept-open connection the bulb's change reports queue up and every later reply is
    one command behind, so status reads and tinytuya's own mode checks saw stale values."""
    if dev["id"] in _handles:
        return _handles[dev["id"]]
    import tinytuya
    b = tinytuya.BulbDevice(dev["id"], dev.get("ip") or "Auto", dev["key"],
                            version=float(dev.get("version") or 3.3), persist=False)
    b.set_socketTimeout(config.LIGHT_TIMEOUT)
    _handles[dev["id"]] = b
    return b


def _check(resp, what: str, name: str):
    if isinstance(resp, dict) and resp.get("Error"):
        _handles.pop(name, None)
        raise ToolError(f"{name}: {resp.get('Error')} ({what}). Is the bulb powered and on the WiFi?")


def _full_status(b, tries: int = 4):
    """status() of a bulb, skipping a partial change report ({"protocol": 4, "dps": {"21": "colour"}})
    if one still arrives before the full status."""
    st = None
    for _ in range(tries):
        st = b.status()
        if not isinstance(st, dict) or st.get("Error"):
            return st
        dps = st.get("dps") or {}
        if "protocol" not in st and ("20" in dps or "1" in dps):
            return st
    return st



def _look(b, n: str, brightness=None, temp=None, hsv=None):
    """Turn on and set colour (hsv 0-1) or white (brightness/temp in %) in ONE raw command with switch,
    mode and values together. tinytuya's set_colour/set_brightness/set_white pick what to send from its
    cached or freshly queried state, which right after another command is a stale queued report:
    "red at 10%" came out white, and a switch back to white was skipped. Brightness alone keeps colour
    mode if the bulb is in it (it becomes the colour's V)."""
    if not b.bulb_configured:
        _full_status(b)                   # detects the bulb type and fills b.dpset
    d = b.dpset
    if hsv is None and temp is None and brightness is not None:
        dps = (_full_status(b) or {}).get("dps") or {}
        hexv = dps.get(d["colour"]) if d["colour"] else None
        if dps.get(d["mode"]) == "colour" and hexv:
            import tinytuya
            h, s, _ = tinytuya.BulbDevice.hexvalue_to_hsv(hexv)
            hsv = (h, s, brightness / 100)
    data = {d["switch"]: True}
    if hsv is not None:
        import tinytuya
        data[d["mode"]] = "colour"
        data[d["colour"]] = tinytuya.BulbDevice.hsv_to_hexvalue(*hsv, d["value_hexformat"])
    else:
        data[d["mode"]] = "white"
        if brightness is not None:
            data[d["brightness"]] = round(d["value_min"] + (d["value_max"] - d["value_min"]) * brightness / 100)
        if temp is not None and d["colourtemp"]:
            data[d["colourtemp"]] = round(d["value_max"] * temp / 100)
    _check(b.set_multiple_values(data), "set light", n)

# --------------------------------------------------------------- set_light --
def _need_devices():
    if not load_devices():
        raise ValidationError("No smart bulbs are set up yet (config/devices.json is missing). "
                              "Run tools/fetch_tuya_keys.py first.", kind="unavailable")


def v_set_light(args: dict, scope=None) -> dict:
    _need_devices()
    name = str(args.get("name") or "all").strip()
    if str(args.get("scene") or "").strip():
        return _scene_args(str(args["scene"]), name)
    try:
        settings = _parse_settings(args)
    except ValidationError:
        # "lights to normal" may arrive as color_temp/color "normal": a saved scene, not a bad value
        scene = _first_scene(args.get("color_temp"), args.get("color"))
        if scene:
            return _scene_args(scene, name)
        raise
    if not any(settings.values()):
        if _first_scene(name):
            return _scene_args(name, "all")
        raise ValidationError("Say what to change: on/off, brightness, color_temp, color or a saved scene.")
    targets = match_lights(name)
    if not targets:
        if _first_scene(name):
            return _scene_args(name, "all")
        raise ValidationError(f"No light called '{name}'. Lights: {', '.join(d['name'] for d in load_devices())}.",
                              kind="not_found")
    if settings["state"] is None:
        settings["state"] = "on"          # setting brightness/colour implies on
    return {"targets": targets, **settings}


def _parse_settings(args: dict) -> dict:
    """state/brightness/color_temp/color from the model's args, checked; None for each one not given."""
    state = (args.get("state") or "").strip().lower() or None
    if state and state not in STATES:
        raise ValidationError("state must be on or off.")
    brightness = args.get("brightness")
    if brightness not in (None, ""):
        try:
            brightness = int(brightness)
        except (TypeError, ValueError):
            raise ValidationError("brightness must be a whole number from 1 to 100.")
        if not 1 <= brightness <= 100:
            raise ValidationError("brightness must be between 1 and 100.")
    else:
        brightness = None
    temp = (args.get("color_temp") or "").strip().lower() or None
    if temp and temp not in TEMPS:
        raise ValidationError(f"color_temp must be one of: {', '.join(k for k in TEMPS if k.isascii())}.")
    colour = (args.get("color") or "").strip().lower() or None
    if colour and colour not in COLOURS:
        raise ValidationError(f"color must be one of: {', '.join(k for k in COLOURS if k.isascii())}.")
    return {"state": state, "brightness": brightness, "color_temp": temp, "color": colour}


def h_set_light(targets: list, state=None, brightness=None, color_temp=None, color=None, scene=None,
                scope=None) -> dict:
    if scene:
        return _apply_scene(scene, targets)
    done, failed = [], []
    for dev in targets:
        n = dev["name"]
        try:
            b = _bulb(dev)
            if state == "off":
                _check(b.turn_off(), "turn off", n)
            elif color and COLOURS[color] is not None:
                h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in COLOURS[color]))
                _look(b, n, hsv=(h, s, brightness / 100 if brightness else v))
            elif color_temp is not None or color == "white":
                _look(b, n, brightness=brightness, temp=TEMPS.get(color_temp, 50))
            elif brightness is not None:
                _look(b, n, brightness=brightness)
            else:
                _check(b.turn_on(), "turn on", n)
            done.append(n)
        except ToolError as e:
            failed.append(str(e))
        except Exception as e:
            _handles.pop(dev["id"], None)
            failed.append(f"{n}: {type(e).__name__}: {e}")
    if not done:
        raise ToolError("; ".join(failed)[:300])
    change = {k: v for k, v in {"state": state, "brightness": brightness, "color_temp": color_temp, "color": color}.items()
              if v is not None}
    return {"changed": done, "set": change, "failed": failed}


register(Tool(
    name="set_light",
    description="Control the Airam smart bulbs: state on/off, brightness 1-100, color_temp warm/neutral/cool, "
                "color (red, blue, ...), or scene = a saved light scene. name = a bulb or room as named in "
                "the Airam app, or 'all'.",
    # scene before the settings: the constrained decode emits keys in schema order, so a scene save
    # ("reading = 40 percent warm") could not add brightness/color_temp after a trailing scene key
    params={"name": {"type": "string"}, "scene": {"type": "string"}, "state": {"type": "string", "enum": STATES},
            "brightness": {"type": "integer"}, "color_temp": {"type": "string"}, "color": {"type": "string"}},
    required=[],
    handler=h_set_light, validate=v_set_light, confirm=False, read_only=False,
))


# ------------------------------------------------------------ light_status --
def v_light_status(args: dict, scope=None) -> dict:
    if not load_devices():
        raise ValidationError("No smart bulbs are set up yet (config/devices.json is missing).", kind="unavailable")
    name = str(args.get("name") or "all").strip()
    targets = match_lights(name)
    if not targets:
        raise ValidationError(f"No light called '{name}'.", kind="not_found")
    return {"targets": targets}


def _decode_status(dps: dict) -> dict:
    """Tuya bulb datapoints (type A: 1/2/3/4, type B: 20/21/22/23) -> plain words."""
    on = dps.get("20", dps.get("1"))
    mode = dps.get("21", dps.get("2"))
    bright = dps.get("22", dps.get("3"))
    out = {"on": bool(on)} if on is not None else {}
    if bright is not None:
        scale = 1000 if "22" in dps else 255
        out["brightness"] = round(int(bright) * 100 / scale)
    if mode:
        out["mode"] = {"white": "white", "colour": "colour"}.get(str(mode), str(mode))
    hexv = dps.get("24", dps.get("5"))
    if mode == "colour" and hexv:         # in colour mode the brightness is the colour's V, not dps 22/3
        import tinytuya
        out["brightness"] = round(tinytuya.BulbDevice.hexvalue_to_hsv(hexv)[2] * 100)
    return out


def h_light_status(targets: list, scope=None) -> dict:
    lights = []
    for dev in targets:
        n = dev["name"]
        try:
            st = _full_status(_bulb(dev))
            if isinstance(st, dict) and st.get("Error"):
                lights.append({"name": n, "error": st["Error"]})
                _handles.pop(dev["id"], None)
            else:
                lights.append({"name": n, **_decode_status(st.get("dps", {}) if isinstance(st, dict) else {})})
        except Exception as e:
            _handles.pop(dev["id"], None)
            lights.append({"name": n, "error": f"{type(e).__name__}: {e}"})
    on = [l["name"] for l in lights if l.get("on")]
    return {"lights": lights, "on": on, "count": len(lights), "saved_scenes": scene_names()}


register(Tool(
    name="light_status",
    description="Which Airam smart bulbs are on and how bright, and which light scenes are saved. "
                "name = bulb, room or 'all'.",
    params={"name": {"type": "string"}},
    required=[],
    handler=h_light_status, validate=v_light_status, confirm=False, read_only=True,
))


# ----------------------------------------------------------------- scenes --
# config.LIGHT_SCENES_FILE: {"normal": {"<bulb id>": {"name": "Bulb 1", "on": true, "mode": "white",
# "brightness": 74, "temp": 51}}}. A bulb entry holds only what is known: a snapshot of the current state
# has everything, a scene saved from spoken settings ("reading = 40 percent warm") only those settings.
# Scene names are stored normalised ("Movie mode" -> "movie").

def load_scenes() -> dict:
    try:
        return json.loads(config.LIGHT_SCENES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning("light scenes file unreadable: %s", e)
        return {}


def _save_scenes(scenes: dict):
    config.LIGHT_SCENES_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.LIGHT_SCENES_FILE.write_text(json.dumps(scenes, indent=1, ensure_ascii=False), encoding="utf-8")


def scene_names() -> list:
    return list(load_scenes())


def _scene_key(name: str) -> str:
    key = re.sub(r"^(the|my|to) ", "", _norm(name))
    return re.sub(r" (scene|mode|lighting|preset|lights|light)$", "", key).strip()


def find_scene(name: str):
    """Saved scene name matching the spoken name, or None. 'back to normal' finds 'normal'."""
    key = _scene_key(name)
    scenes = load_scenes()
    if not key or not scenes:
        return None
    if key in scenes:
        return key
    near = [s for s in scenes if re.search(rf"\b{re.escape(s)}\b", key) or re.search(rf"\b{re.escape(key)}\b", s)]
    return near[0] if len(near) == 1 else None


def _first_scene(*words):
    for w in words:
        if w and find_scene(str(w)):
            return str(w)
    return None


def _scene_args(spoken: str, name: str) -> dict:
    """set_light args for applying a scene; name narrows it to some of the scene's bulbs."""
    scene = find_scene(spoken)
    if not scene:
        saved = ", ".join(scene_names()) or "none"
        raise ValidationError(f"No saved light scene called '{spoken}'. Saved scenes: {saved}.", kind="not_found")
    entries = load_scenes()[scene]
    in_scene = [d for d in load_devices() if d["id"] in entries]
    wanted = match_lights(name) if name and _norm(name) not in ALL_WORDS else in_scene
    targets = [d for d in in_scene if d in wanted]
    if not targets:
        raise ValidationError(f"Scene '{scene}' has no saved settings for '{name}'. "
                              f"It covers: {', '.join(d['name'] for d in in_scene) or 'no current bulbs'}.",
                              kind="not_found")
    return {"targets": targets, "scene": scene}


def _apply_scene(scene: str, targets: list) -> dict:
    entries = load_scenes().get(scene, {})
    done, failed = [], []
    for dev in targets:
        n, rec = dev["name"], entries.get(dev["id"], {})
        try:
            b = _bulb(dev)
            if rec.get("on") is False:
                _check(b.turn_off(), "turn off", n)
            elif rec.get("hsv"):
                _look(b, n, hsv=rec["hsv"])
            elif rec.get("temp") is not None or rec.get("brightness") is not None:
                _look(b, n, brightness=rec.get("brightness"), temp=rec.get("temp"))
            else:
                _check(b.turn_on(), "turn on", n)
            done.append(n)
        except ToolError as e:
            failed.append(str(e))
        except Exception as e:
            _handles.pop(dev["id"], None)
            failed.append(f"{n}: {type(e).__name__}: {e}")
    if not done:
        raise ToolError("; ".join(failed)[:300])
    spoken = f"Switched to {scene}." + (f" {len(failed)} light{'s' if len(failed) > 1 else ''} did not answer." if failed else "")
    return {"scene": scene, "changed": done, "failed": failed, "spoken": spoken, "accomplished": "partial" if failed else "yes"}


def _from_settings(state=None, brightness=None, color_temp=None, color=None) -> dict:
    """A scene entry from spoken settings."""
    if state == "off":
        return {"on": False}
    rec = {"on": True}
    if color and COLOURS[color] is not None:
        h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in COLOURS[color]))
        rec.update(mode="colour", hsv=[round(h, 4), round(s, 4), brightness / 100 if brightness else round(v, 4)])
        return rec
    if color_temp is not None or color == "white":
        rec.update(mode="white", temp=TEMPS.get(color_temp, 50))
    if brightness is not None:
        rec["brightness"] = brightness
    return rec


def _snapshot(dps: dict) -> dict:
    """A scene entry from a bulb's current datapoints (type A: 1-5, type B: 20-24)."""
    st = _decode_status(dps)
    if "on" not in st:
        raise ToolError("the bulb did not report its state")
    rec = {"on": st["on"]}
    hexv = dps.get("24", dps.get("5"))
    if st.get("mode") == "colour" and hexv:
        import tinytuya
        rec.update(mode="colour", hsv=[round(x, 4) for x in tinytuya.BulbDevice.hexvalue_to_hsv(hexv)])
        return rec
    temp = dps.get("23", dps.get("4"))
    if temp is not None:
        rec.update(mode="white", temp=round(int(temp) * 100 / (1000 if "23" in dps else 255)))
    if "brightness" in st:
        rec["brightness"] = max(1, st["brightness"])
    return rec


def _summary(rec: dict) -> str:
    """Short words for one scene entry, for the reply."""
    if rec.get("on") is False:
        return "off"
    if rec.get("hsv"):
        return f"colour at {round(rec['hsv'][2] * 100)}%"
    parts = ["on"]
    if rec.get("temp") is not None:
        parts.append("warm white" if rec["temp"] <= 30 else "cool white" if rec["temp"] >= 70 else "neutral white")
    if rec.get("brightness") is not None:
        parts.append(f"{rec['brightness']}%")
    return " ".join(parts)


# ------------------------------------------------------- save_light_scene --
def v_save_light_scene(args: dict, scope=None) -> dict:
    _need_devices()
    scene = _scene_key(args.get("scene") or "")
    if not scene or scene in ALL_WORDS:
        raise ValidationError("Give the scene a name, e.g. scene 'normal' or 'movie'.")
    if len(scene) > 40:
        raise ValidationError("Scene name is too long; use one or two words.")
    name = str(args.get("name") or "all").strip()
    targets = match_lights(name)
    if not targets:
        raise ValidationError(f"No light called '{name}'. Lights: {', '.join(d['name'] for d in load_devices())}.",
                              kind="not_found")
    settings = _parse_settings(args)
    return {"scene": scene, "targets": targets,
            "settings": settings if any(settings.values()) else None,   # None = save the current state
            "overwrite": scene in load_scenes()}


def h_save_light_scene(scene: str, targets: list, settings=None, overwrite=False, scope=None) -> dict:
    entries, failed = {}, []
    for dev in targets:
        n = dev["name"]
        if settings:
            entries[dev["id"]] = {"name": n, **_from_settings(**settings)}
            continue
        try:
            st = _full_status(_bulb(dev))
            if not isinstance(st, dict) or st.get("Error"):
                raise ToolError(f"{n}: {(st or {}).get('Error', 'no answer')}")
            entries[dev["id"]] = {"name": n, **_snapshot(st.get("dps", {}))}
        except ToolError as e:
            failed.append(str(e))
        except Exception as e:
            _handles.pop(dev["id"], None)
            failed.append(f"{n}: {type(e).__name__}: {e}")
    if not entries:
        raise ToolError("Could not read any light, nothing saved. " + "; ".join(failed)[:250])
    scenes = load_scenes()
    scenes[scene] = entries
    _save_scenes(scenes)
    spoken = (f"{'Replaced' if overwrite else 'Saved'} the light scene {scene}."
              + (f" {len(failed)} light{'s' if len(failed) > 1 else ''} did not answer and {'are' if len(failed) > 1 else 'is'} not in it." if failed else ""))
    return {"saved": scene, "replaced": overwrite, "from": "spoken settings" if settings else "current state",
            "lights": {e["name"]: _summary(e) for e in entries.values()}, "failed": failed,
            "spoken": spoken, "accomplished": "partial" if failed else "yes"}


register(Tool(
    name="save_light_scene",
    description="Save a named light scene to call later with set_light scene. Without settings it saves the "
                "lights as they are now; with state/brightness/color_temp/color it saves those instead. "
                "name = bulb, room or 'all'.",
    params={"name": {"type": "string"}, "scene": {"type": "string"}, "state": {"type": "string", "enum": STATES},
            "brightness": {"type": "integer"}, "color_temp": {"type": "string"}, "color": {"type": "string"}},
    required=["scene"],
    handler=h_save_light_scene, validate=v_save_light_scene,
    describe=lambda a: f"Replace the saved light scene '{a['scene']}'", confirm=False, read_only=False,
))


# ----------------------------------------------------- delete_light_scene --
def v_delete_light_scene(args: dict, scope=None) -> dict:
    spoken = str(args.get("scene") or "").strip()
    scene = find_scene(spoken)
    if not scene:
        raise ValidationError(f"No saved light scene called '{spoken}'. "
                              f"Saved scenes: {', '.join(scene_names()) or 'none'}.", kind="not_found")
    return {"scene": scene}


def h_delete_light_scene(scene: str, scope=None) -> dict:
    scenes = load_scenes()
    if scenes.pop(scene, None) is None:
        raise ToolError(f"The scene '{scene}' is already gone.")
    _save_scenes(scenes)
    return {"deleted": scene, "remaining": list(scenes), "spoken": f"Deleted the light scene {scene}.",
            "accomplished": "yes"}


register(Tool(
    name="delete_light_scene",
    description="Delete a saved light scene (not a file).",
    params={"scene": {"type": "string"}},
    required=["scene"],
    handler=h_delete_light_scene, validate=v_delete_light_scene,
    describe=lambda a: f"Delete the light scene '{a['scene']}'", confirm=True, read_only=False,
))
