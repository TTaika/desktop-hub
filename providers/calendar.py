"""Your Google Calendar, through the voice assistant's calendar tool, so both use the same login
(voice_assistant/config/google_token.json) and read the same calendars.

GET /api/calendar?view=day|week|month
  -> {"view", "start", "end", "today": "YYYY-MM-DD",
      "events": [{"title", "start", "end", "all_day", "calendar", "color", "busy",
                  "location", "description"}]}   (ISO times, local zone)
     or {"error": str}
day = today, week = this Monday to Sunday, month = the Monday-to-Sunday weeks that cover this month.
Cached for 5 minutes per view.
"""
import sys
import threading
import time
from datetime import datetime, timedelta

from hub_config import NO_VOICE_ASSISTANT, voice_assistant_dir

CACHE_S = 300
_lock = threading.Lock()
_cache = {}                  # view -> (monotonic time, value)
_colors = {"t": 0.0, "map": {}}
_ct = None


def _tool():
    global _ct
    if _ct is None:
        va = voice_assistant_dir()
        if va not in sys.path:
            sys.path.append(va)
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
        return "The calendar isn't set up in the voice assistant."
    import json
    try:
        token = json.loads(cfg.GOOGLE_TOKEN.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        token = {}
    if not token.get("refresh_token"):
        return "Calendar login missing: run  py -3.13 -m assistant.tools.calendar_tool --login  in voice_assistant."
    return None


def _range(view: str, now: datetime):
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if view == "day":
        return day, day + timedelta(days=1)
    monday = day - timedelta(days=day.weekday())
    if view == "week":
        return monday, monday + timedelta(days=7)
    first = day.replace(day=1)
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


def _load(view: str) -> dict:
    ct = _tool()
    problem = _check_login(ct)
    if problem:
        return {"error": problem}
    now = datetime.now(ct.TZ)
    start, end = _range(view, now)
    try:
        events, failed = ct.fetch_events(start, end)
    except Exception as e:
        if "invalid_grant" in str(e):            # Google expires logins of apps in "testing" mode after 7 days
            return {"error": "The calendar login has expired. Log in again: in voice_assistant run  "
                             "py -3.13 -m assistant.tools.calendar_tool --login"}
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


def get(params: dict) -> dict:
    if not voice_assistant_dir():
        return {"error": NO_VOICE_ASSISTANT}
    view = params.get("view", "week")
    if view not in ("day", "week", "month"):
        return {"error": "view must be day, week or month"}
    with _lock:
        hit = _cache.get(view)
        if hit is None or time.monotonic() - hit[0] > CACHE_S or hit[1].get("today") != datetime.now().date().isoformat():
            _cache[view] = (time.monotonic(), _load(view))
        return _cache[view][1]
