"""The voice assistant (Clanker) through its local API, for the assistant widget. The assistant runs as its own
service (voice_assistant/main.py, push-to-talk and tray); this only relays, so the widget shows the same
conversation whether you spoke or typed, and answers its approvals.

GET  /api/assistant?since=<seq>&wait=<s>  -> the assistant's state and new conversation items (see
                                             voice_assistant/assistant/engine.py), held up to `wait` seconds
                                             until something changes; {"online": false} if it isn't running
POST /api/assistant {"ask": "text", "speak": false} | {"approve": true|false} | {"backend": "local"|"cloud"|"auto"}
                    | {"stop": true} | {"preload": true} (the user started typing: load the local model now)
The editor's Assistant settings (kept by the assistant in its config/settings.json, never in layout.json):
GET  /api/assistant?settings=1          the model settings; the cloud key only as "...abcd"
GET  /api/assistant?models=cloud|local  models on offer
POST /api/assistant {"settings": {"cloud_api_key", "cloud_provider", "cloud_model", "cloud_url", "ollama_url",
                    "local_model"}} | {"test": "cloud"|"local"}

The assistant's API refuses requests from browsers; this server calls it without an Origin.
"""
import json
import urllib.error
import urllib.request
from urllib.parse import urlencode

from hub_config import CONFIG

URL = (CONFIG.get("assistant_url") or "http://127.0.0.1:8766").rstrip("/")
MAX_WAIT = 10        # under the overlay's 15 s request timeout


def _call(method: str, path: str, body=None, timeout: float = 5):
    req = urllib.request.Request(URL + path, method=method, headers={"Content-Type": "application/json"},
                                 data=json.dumps(body).encode("utf-8") if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:            # 400 with {"error": ...}
        try:
            return json.loads(e.read())
        except ValueError:
            return {"error": f"HTTP {e.code}"}


def _offline() -> dict:
    return {"error": "The assistant isn't running.", "online": False}


def get(params: dict) -> dict:
    if params.get("settings") or params.get("models"):      # the editor's Assistant settings
        path = "/settings" if params.get("settings") else "/models?" + urlencode({"target": params["models"]})
        try:
            return _call("GET", path, timeout=20)
        except (urllib.error.URLError, OSError, ValueError):
            return _offline()
    try:
        since = int(params.get("since", 0))
        wait = max(0.0, min(float(params.get("wait", 0)), MAX_WAIT))
    except ValueError:
        return {"error": "since and wait must be numbers"}
    try:
        d = _call("GET", "/state?" + urlencode({"since": since, "wait": wait}), timeout=wait + 5)
    except (urllib.error.URLError, OSError, ValueError):
        return {"online": False}
    d["online"] = True
    return d


def post(body: dict) -> dict:
    if "ask" in body:
        path, payload = "/ask", {"text": str(body["ask"]), "speak": bool(body.get("speak", False))}
    elif "approve" in body:
        path, payload = "/approve", {"approve": bool(body["approve"])}
    elif "backend" in body:
        path, payload = "/backend", {"mode": str(body["backend"])}
    elif "stop" in body:
        path, payload = "/stop", {}
    elif "preload" in body:
        path, payload = "/preload", {}
    elif isinstance(body.get("settings"), dict):
        path, payload = "/settings", body["settings"]
    elif "test" in body:
        path, payload = "/test", {"target": str(body["test"])}
    else:
        return {"error": "nothing to do"}
    try:
        # a local-model test loads the model, which takes a while on a cold start
        return _call("POST", path, payload, timeout=150 if path == "/test" else 10)
    except (urllib.error.URLError, OSError, ValueError):
        return _offline()
