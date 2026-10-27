"""Your Google Calendar, through the calendar tool in assistant/tools/ (login in data/google_token.json), or the
voice assistant's own copy when voice_assistant_dir is set, so both share one login and the same calendars.

GET /api/calendar?view=day|week|month[&offset=N]   (offset: months from this one, month view only)
  -> {"view", "start", "end", "today": "YYYY-MM-DD",
      "events": [{"title", "start", "end", "all_day", "calendar", "color", "busy",
                  "location", "description"}]}   (ISO times, local zone)
     or {"error": str}
GET  /api/calendar?status=1   -> {"state": "ok"|"ics"|"no_client"|"missing"|"expired"|"logging_in", "message",
                                  "credentials": path of the OAuth client file}   (the editor's ⚙ panel)
POST /api/calendar {"login": true}          opens Google's consent in this PC's browser (in a background thread)
POST /api/calendar {"credentials": "{...}"} saves the OAuth client JSON downloaded from Google Cloud Console
day = today, week = this Monday to Sunday, month = the Monday-to-Sunday weeks that cover this month.
Cached for 5 minutes per view and month.
"""
import json
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from hub_config import voice_assistant_dir

CACHE_S = 300
_lock = threading.Lock()
_cache = {}                  # (view, month offset) -> (monotonic time, value)
_colors = {"t": 0.0, "map": {}}
_ct = None
_login = {"running": False, "error": None}    # the login started from the editor
LOGIN_TIMEOUT_S = 300


def _tool():
    global _ct
    if _ct is None:
        va = voice_assistant_dir()             # its own copy and logins; else the copy in assistant/
        if va and va not in sys.path:
            sys.path.insert(0, va)
        from assistant.tools import calendar_tool
        _ct = calendar_tool
    return _ct


def _check_login(ct):
    """The calendar tool opens a browser to log in when it has no usable token. A background server must
    never do that, so say what to run instead."""
    cfg = ct.config
    if ct.backend() == "ics":
        return None
    if ct.backend() != "oauth":
        return f"The calendar isn't set up: save your Google OAuth client as {cfg.GOOGLE_CREDENTIALS} (see README)."
    try:
        token = json.loads(cfg.GOOGLE_TOKEN.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        token = {}
    if not token.get("refresh_token"):
        return f"Calendar login missing. Log in from the tile's ⚙ in the editor, or {_login_hint(cfg)}"
    return None


def _login_hint(cfg) -> str:
    folder = Path(cfg.__file__).resolve().parent.parent          # the project whose copy of the tool is in use
    return f"in {folder} run  py -3.13 -m assistant.tools.calendar_tool --login"


def _range(view: str, now: datetime, offset: int = 0):
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if view == "day":
        return day, day + timedelta(days=1)
    monday = day - timedelta(days=day.weekday())
    if view == "week":
        return monday, monday + timedelta(days=7)
    y, m = divmod(day.year * 12 + day.month - 1 + offset, 12)
    first = day.replace(year=y, month=m + 1, day=1)
    start = first - timedelta(days=first.weekday())
    next_month = (first + timedelta(days=32)).replace(day=1)
    end = next_month + timedelta(days=(7 - next_month.weekday()) % 7)
    return start, end


def _calendar_colors(ct) -> dict:
    """calendar label (as the tool names events' calendars) -> its colour in Google Calendar; None = main."""
    if time.monotonic() - _colors["t"] < 3600 and _colors["map"]:
        return _colors["map"]
    out = {}
    try:
        svc = ct._get_service()
        for c in svc.calendarList().list(minAccessRole="freeBusyReader").execute().get("items", []):
            label = None if c.get("primary") else ct._label(c.get("summaryOverride") or c.get("summary") or c["id"])
            out[label] = c.get("backgroundColor")
    except Exception:
        pass                                     # colours are a nicety; events still come without them
    _colors.update(t=time.monotonic(), map=out)
    return out


def _load(view: str, offset: int = 0) -> dict:
    ct = _tool()
    problem = _check_login(ct)
    if problem:
        return {"error": problem}
    now = datetime.now(ct.TZ)
    start, end = _range(view, now, offset)
    try:
        events, failed = ct.fetch_events(start, end)
    except Exception as e:
        if "invalid_grant" in str(e):            # Google expires logins of apps in "testing" mode after 7 days
            return {"error": f"The calendar login has expired. Log in again from the tile's ⚙ in the editor, or {_login_hint(ct.config)}"}
        return {"error": f"Could not read the calendar: {e}"}
    colors = _calendar_colors(ct) if ct.backend() == "oauth" else {}
    return {
        "view": view, "start": start.isoformat(), "end": end.isoformat(), "today": now.date().isoformat(),
        "failed": failed,
        "events": [{"title": e["title"], "start": e["start"].isoformat(), "end": e["end"].isoformat(),
                    "all_day": e["all_day"], "calendar": e["calendar"], "color": colors.get(e["calendar"]),
                    "busy": e["busy"], "location": e.get("location"),
                    "description": (e.get("description") or "")[:400] or None} for e in events],
    }


def _status() -> dict:
    ct = _tool()
    cfg = ct.config
    out = {"credentials": str(cfg.GOOGLE_CREDENTIALS)}
    if _login["running"]:
        return {**out, "state": "logging_in", "message": "Waiting for you to finish the login in the browser..."}
    if ct.backend() == "ics":
        return {**out, "state": "ics", "message": "Reading the calendar's secret iCal address (read-only)."}
    if ct.backend() != "oauth":
        return {**out, "state": "no_client", "message": "Not set up: add the OAuth client file from Google Cloud Console."}
    if _check_login(ct):
        return {**out, "state": "missing", "message": _login["error"] or "Not logged in."}
    get({"view": "day"})                        # an expired login only shows when reading (cached 5 minutes)
    with _lock:
        expired = any("expired" in (v.get("error") or "") for _, v in _cache.values())
    if expired:
        return {**out, "state": "expired", "message": "The login has expired (Google does that after 7 days while the app is in testing mode)."}
    return {**out, "state": "ok", "message": _login["error"] or "Logged in."}


def _run_login(ct):
    """Google's consent in this PC's default browser; the token lands where the calendar tool reads it."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(ct.config.GOOGLE_CREDENTIALS), ct.SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True, timeout_seconds=LOGIN_TIMEOUT_S,
                                      authorization_prompt_message=None,   # it prints; pythonw has no stdout
                                      success_message="Logged in. You can close this tab and go back to the hub.",
                                      access_type="offline", prompt="consent")   # always hand out a refresh token
        ct.config.GOOGLE_TOKEN.write_text(creds.to_json(), encoding="utf-8")
        ct._service = None                      # build a new client with the new token
        _login["error"] = None
    except Exception as e:
        _login["error"] = f"The login failed: {e}"
    finally:
        with _lock:
            _cache.clear()
        _colors.update(t=0.0, map={})
        _login["running"] = False


def post(body: dict) -> dict:
    ct = _tool()
    if isinstance(body.get("credentials"), str):
        try:
            client = json.loads(body["credentials"])
        except ValueError:
            return {"error": "That file isn't JSON. Download the OAuth client's JSON from Google Cloud Console."}
        if not isinstance(client, dict) or not ("installed" in client or "web" in client):
            return {"error": "That isn't an OAuth client file. Create one of type \"Desktop app\" and download its JSON."}
        ct.config.GOOGLE_CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
        ct.config.GOOGLE_CREDENTIALS.write_text(json.dumps(client, indent=2), encoding="utf-8")
        with _lock:
            _cache.clear()
        return _status()
    if body.get("login"):
        if ct.backend() != "oauth":
            return {"error": "Add the OAuth client file first."}
        if not _login["running"]:
            _login.update(running=True, error=None)
            threading.Thread(target=_run_login, args=(ct,), name="calendar-login", daemon=True).start()
        return _status()
    return {"error": "nothing to do"}


def get(params: dict) -> dict:
    if params.get("status"):
        return _status()
    view = params.get("view", "week")
    if view not in ("day", "week", "month"):
        return {"error": "view must be day, week or month"}
    try:
        offset = max(-120, min(120, int(params.get("offset") or 0))) if view == "month" else 0
    except ValueError:
        return {"error": "offset must be a whole number of months"}
    key = (view, offset)
    with _lock:
        hit = _cache.get(key)
        if hit is None or time.monotonic() - hit[0] > CACHE_S or hit[1].get("today") != datetime.now().date().isoformat():
            _cache[key] = (time.monotonic(), _load(view, offset))
        return _cache[key][1]
