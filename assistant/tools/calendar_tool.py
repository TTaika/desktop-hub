"""Google Calendar tools: create_event (approval required) and list_events (read-only).

Setup (one-time, manual):
  1. Google Cloud Console -> new project -> enable "Google Calendar API"
  2. Credentials -> OAuth client ID -> Desktop app -> download JSON
  3. save it as config.GOOGLE_CREDENTIALS (in Desktop Hub: data/google_credentials.json)
  4. log in once: py -3.13 -m assistant.tools.calendar_tool --login (stores config.GOOGLE_TOKEN)

Read-only alternative without a Google Cloud project: set config.GOOGLE_CALENDAR_ICS_URL to the
calendar's "Secret address in iCal format". list_events then reads that feed (Google refreshes
it every few hours); create_event still needs the OAuth setup.
"""
import logging
import re
import time
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from .. import config
from .registry import Tool, ValidationError, ToolError, register

log = logging.getLogger("calendar")

# events: read/write events. calendarlist.readonly: find the other calendars shown in the user's Google
# Calendar (subscriptions, shared and linked calendars) so list_events covers all of them.
SCOPES = ["https://www.googleapis.com/auth/calendar.events",
          "https://www.googleapis.com/auth/calendar.calendarlist.readonly"]
TZ = ZoneInfo(config.TIMEZONE)
_service = None
_ics_cache = {"at": 0.0, "cal": None}


def backend() -> str:
    """'oauth' when the OAuth client file exists, 'ics' when only the secret iCal link is set, else ''."""
    if config.GOOGLE_CREDENTIALS.exists():
        return "oauth"
    if config.GOOGLE_CALENDAR_ICS_URL:
        return "ics"
    return ""


# ---------------------------------------------------------------- auth ----
def _get_service():
    global _service
    if _service is not None:
        return _service
    if not config.GOOGLE_CREDENTIALS.exists():
        raise ToolError(
            "Google Calendar is not set up yet. Put the OAuth client file at "
            f"{config.GOOGLE_CREDENTIALS}, or set GOOGLE_CALENDAR_ICS_URL in config for read-only access.")
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    import json
    creds = None
    if config.GOOGLE_TOKEN.exists():
        granted = json.loads(config.GOOGLE_TOKEN.read_text(encoding="utf-8")).get("scopes") or []
        if SCOPES[0] in granted:
            # An older token without the calendar-list scope still works (main calendar only); never open a
            # browser from the tray for it. `py -3.13 -m assistant.tools.calendar_tool --login` upgrades it.
            creds = Credentials.from_authorized_user_file(str(config.GOOGLE_TOKEN), granted)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(config.GOOGLE_CREDENTIALS), SCOPES)
            creds = flow.run_local_server(port=0)
        config.GOOGLE_TOKEN.write_text(creds.to_json(), encoding="utf-8")
    _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _service


# ------------------------------------------------------------ date parse --
def parse_when(s: str, default_time=None) -> datetime:
    """Accept ISO-8601 ('2026-09-23T15:00', '2026-09-23 15:00', '2026-09-23') -> aware datetime."""
    if s is None:
        raise ValidationError("datetime is missing.")
    s = str(s).strip().replace("T", " ")
    s = re.sub(r"[Zz]$", "", s)
    s = re.sub(r"([+-]\d\d:\d\d)$", "", s)
    fmts = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H", "%Y-%m-%d"]
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            if f == "%Y-%m-%d" and default_time is not None:
                dt = dt.replace(hour=default_time[0], minute=default_time[1])
            return dt.replace(tzinfo=TZ)
        except ValueError:
            continue
    raise ValidationError(f"Could not read the date/time '{s}'. Use ISO format like 2026-09-23T15:00.")


def _human(dt: datetime) -> str:
    return dt.strftime("%a %d %b %Y at %H:%M")


# ----------------------------------------------------------- create_event --
def v_create_event(args: dict, scope=None) -> dict:
    title = str(args.get("title", "")).strip()
    if not title:
        raise ValidationError("title is missing.")
    start = parse_when(args.get("datetime"), default_time=(9, 0))
    minutes = args.get("duration_minutes")
    try:
        minutes = int(minutes) if minutes not in (None, "", 0) else config.DEFAULT_EVENT_MINUTES
    except (TypeError, ValueError):
        raise ValidationError("duration_minutes must be a whole number of minutes.")
    if not (1 <= minutes <= 24 * 60):
        raise ValidationError("duration_minutes must be between 1 and 1440.")
    if start < datetime.now(TZ) - timedelta(minutes=5):
        raise ValidationError(
            f"{_human(start)} is in the past (now is {_human(datetime.now(TZ))}). Re-check the date.")
    return {"title": title, "start": start, "end": start + timedelta(minutes=minutes), "duration_minutes": minutes}


def h_create_event(title: str, start: datetime, end: datetime, duration_minutes: int, scope=None) -> dict:
    if backend() == "ics":
        raise ToolError("Creating events needs the Google OAuth setup (config/google_credentials.json); "
                        "the iCal link is read-only.")
    svc = _get_service()
    body = {"summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": config.TIMEZONE},
            "end": {"dateTime": end.isoformat(), "timeZone": config.TIMEZONE}}
    ev = svc.events().insert(calendarId=config.GOOGLE_CALENDAR_ID, body=body).execute()
    return {"created": title, "start": _human(start), "duration_minutes": duration_minutes,
            "link": ev.get("htmlLink", "")}


def target_calendar_name() -> str:
    """The name of the calendar new events go to ('Assistant'), not its long id; the id if the lookup fails."""
    if config.GOOGLE_CALENDAR_ID == "primary":
        return "main calendar"
    try:
        return _get_service().calendarList().get(calendarId=config.GOOGLE_CALENDAR_ID).execute().get("summary") \
            or config.GOOGLE_CALENDAR_ID
    except Exception:
        return config.GOOGLE_CALENDAR_ID


def d_create_event(a: dict) -> str:
    return (f"CREATE EVENT  '{a['title']}'\n  {_human(a['start'])}  for {a['duration_minutes']} min  "
            f"(Google Calendar: {target_calendar_name()})")


register(Tool(
    name="create_event",
    description="Create a Google Calendar event. datetime is ISO 8601 local time, duration_minutes defaults to 60.",
    params={"title": {"type": "string"}, "datetime": {"type": "string"}, "duration_minutes": {"type": "integer"}},
    required=["title", "datetime"],
    handler=h_create_event, validate=v_create_event, describe=d_create_event, confirm=True, read_only=False,
))


# ------------------------------------------------------------ list_events --
RANGES = ["today", "tomorrow", "this_week", "next_week", "this_weekend", "next_7_days", "custom"]


def _named_range(name: str):
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    table = {
        "today": (today, today + timedelta(days=1)),
        "tomorrow": (today + timedelta(days=1), today + timedelta(days=2)),
        "this_week": (monday, monday + timedelta(days=7)),
        "next_week": (monday + timedelta(days=7), monday + timedelta(days=14)),
        "this_weekend": (monday + timedelta(days=5), monday + timedelta(days=7)),
        "next_7_days": (today, today + timedelta(days=7)),
    }
    return table.get(name)


def v_list_events(args: dict, scope=None) -> dict:
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    rng = (args.get("range") or "").strip().lower()
    if rng and rng != "custom" and not args.get("start"):
        if rng not in RANGES:
            raise ValidationError(f"range must be one of: {', '.join(RANGES)}.")
        start, end = _named_range(rng)
        return {"start": start, "end": end}
    start = parse_when(args.get("start"), default_time=(0, 0)) if args.get("start") else today
    if args.get("end"):
        end = parse_when(args.get("end"), default_time=(23, 59))
    else:
        end = start + timedelta(days=1)
    if end <= start:
        raise ValidationError("end must be after start.")
    if end - start > timedelta(days=62):
        raise ValidationError("Date range too large (max 62 days).")
    return {"start": start, "end": end}


def _ics_calendar():
    """Download (and cache) the secret iCal feed."""
    import requests
    import icalendar
    now = time.time()
    if _ics_cache["cal"] is not None and now - _ics_cache["at"] < config.ICS_CACHE_S:
        return _ics_cache["cal"]
    try:
        r = requests.get(config.GOOGLE_CALENDAR_ICS_URL, timeout=20)
        r.raise_for_status()
        cal = icalendar.Calendar.from_ical(r.content)
    except Exception as e:
        raise ToolError(f"Could not read the calendar feed: {e}")
    _ics_cache.update(at=now, cal=cal)
    return cal


def _raw(title, start, end, all_day, calendar, busy=True) -> dict:
    return {"title": title, "start": start, "end": end, "all_day": all_day, "calendar": calendar, "busy": busy}


def ics_events(cal, start: datetime, end: datetime) -> list:
    """Events (recurrences expanded) between start and end from an icalendar.Calendar, as raw events."""
    import recurring_ical_events
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        st, en = ev.get("DTSTART").dt, (ev.get("DTEND").dt if ev.get("DTEND") else None)
        title = str(ev.get("SUMMARY", "(no title)"))
        busy = str(ev.get("TRANSP", "OPAQUE")).upper() != "TRANSPARENT"
        if isinstance(st, datetime):
            sdt = st.astimezone(TZ) if st.tzinfo else st.replace(tzinfo=TZ)
            edt = ((en.astimezone(TZ) if en.tzinfo else en.replace(tzinfo=TZ)) if isinstance(en, datetime)
                   else sdt + timedelta(hours=1))
            out.append(_raw(title, sdt, edt, False, None, busy))
        else:
            sdt = datetime.combine(st, datetime.min.time(), TZ)
            edt = datetime.combine(en, datetime.min.time(), TZ) if isinstance(en, date) else sdt + timedelta(days=1)
            out.append(_raw(title, sdt, edt, True, None, busy))
        out[-1]["location"] = str(ev["LOCATION"]) if ev.get("LOCATION") else None
        out[-1]["description"] = str(ev["DESCRIPTION"]) if ev.get("DESCRIPTION") else None
    out.sort(key=lambda e: e["start"])
    return out


def _google_raw(ev: dict, cal_name) -> dict:
    title = ev.get("summary", "(no title)")
    declined = any(a.get("self") and a.get("responseStatus") == "declined" for a in ev.get("attendees", []))
    busy = ev.get("transparency") != "transparent" and not declined
    if "dateTime" not in ev["start"]:
        st, en = date.fromisoformat(ev["start"]["date"]), date.fromisoformat(ev["end"]["date"])
        out = _raw(title, datetime.combine(st, datetime.min.time(), TZ), datetime.combine(en, datetime.min.time(), TZ),
                   True, cal_name, busy)
    else:
        out = _raw(title, datetime.fromisoformat(ev["start"]["dateTime"]).astimezone(TZ),
                   datetime.fromisoformat(ev["end"]["dateTime"]).astimezone(TZ), False, cal_name, busy)
    out["location"], out["description"] = ev.get("location"), ev.get("description")   # for the desktop hub's details
    return out


def fetch_events(start: datetime, end: datetime):
    """-> (raw events sorted by start, names of calendars that could not be read). The same event in two
    linked calendars is kept once."""
    failed = []
    if backend() == "ics":
        events = ics_events(_ics_calendar(), start, end)
    else:
        svc = _get_service()
        events = []
        for cal_id, cal_name in calendars(svc):
            try:
                res = svc.events().list(calendarId=cal_id, timeMin=start.isoformat(), timeMax=end.isoformat(),
                                        singleEvents=True, orderBy="startTime", maxResults=100).execute()
            except Exception as e:                      # one broken subscription must not hide the rest
                log.warning("calendar %r not read: %s", cal_name, e)
                failed.append(cal_name)
                continue
            events += [_google_raw(ev, cal_name) for ev in res.get("items", []) if ev.get("status") != "cancelled"]
    seen, unique = set(), []
    for e in sorted(events, key=lambda e: (e["start"], e["title"])):
        key = (e["title"].strip().lower(), e["start"], e["end"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique, failed


def _item(e: dict) -> dict:
    when = (f"{e['start'].date().isoformat()} (all day)" if e["all_day"] else
            f"{e['start'].strftime('%a %d %b %H:%M')}-{e['end'].strftime('%H:%M')}")
    item = {"title": e["title"], "when": when}
    if e["calendar"]:
        item["calendar"] = e["calendar"]
    return item


def _days(start: datetime, end: datetime) -> list:
    d, out = start.date(), []
    while datetime.combine(d, datetime.min.time(), TZ) < end:
        out.append(d)
        d += timedelta(days=1)
    return out


def _day_name(d: date) -> str:
    today = datetime.now(TZ).date()
    if d == today:
        return "Today"
    if d == today + timedelta(days=1):
        return "Tomorrow"
    if today < d < today + timedelta(days=7):
        return d.strftime("%A")
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B')}"


def _join(parts: list) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


_COURSE_CODE = re.compile(r"^[A-Z]{2,5}-[A-Z]?\d{3,5}\b")


def short_title(title: str) -> str:
    """University timetables name events like 'ABC-1234, Course name, Teaching 1.9.–1.12.2026 - Lecture - L01 - Hall A';
    say 'Course name, Lecture'. Other long titles are cut at their first ' - '."""
    parts = [p.strip() for p in title.split(" - ")]
    head = [h.strip() for h in parts[0].split(",")]
    if _COURSE_CODE.match(head[0]) and len(head) > 1:
        return head[1] + (f", {parts[1]}" if len(parts) > 1 else "")
    return parts[0] if len(title) > 60 else title


def spoken_events(events: list, start: datetime, end: datetime) -> str:
    """Just each event's name and time, grouped by day; days without events are skipped."""
    days = _days(start, end)
    by_day = {d: [] for d in days}
    for e in events:
        d = max(e["start"].date(), days[0])           # an all-day event that began before the range
        if d in by_day:
            by_day[d].append(short_title(e["title"]) + (", all day" if e["all_day"] else
                                           f" from {e['start'].strftime('%H:%M')} to {e['end'].strftime('%H:%M')}"))
    said = [f"{_day_name(d)}: {'; '.join(v)}." for d, v in by_day.items() if v]
    if said:
        return " ".join(said)
    if len(days) == 1:
        return f"You have nothing on your calendar {_day_name(days[0]).lower() if _day_name(days[0]) in ('Today', 'Tomorrow') else 'on ' + _day_name(days[0])}."
    return f"You have nothing on your calendar between {_day_name(days[0])} and {_day_name(days[-1])}."


def h_list_events(start: datetime, end: datetime, scope=None) -> dict:
    rng = f"{start.strftime('%a %d %b')} - {(end - timedelta(seconds=1)).strftime('%a %d %b')}"
    events, failed = fetch_events(start, end)
    out = {"range": rng, "count": len(events), "events": [_item(e) for e in events[:30]]}
    if backend() == "ics":
        out["source"] = "iCal link (read-only)"
    # Fixed reply with only names and times; the model padded it and dropped events past the third.
    out["spoken"] = spoken_events(events, start, end)
    if failed:
        out["calendars_not_read"] = failed
        out["spoken"] += f" I could not read {_join(failed)}."
    out["accomplished"], out["assessment"] = "yes", f"{len(events)} events read from the calendar."
    return out


def calendars(svc) -> list:
    """(id, name) of the calendars to read: config.GOOGLE_CALENDAR_IDS when set, otherwise every calendar
    ticked in the user's Google Calendar list. The main calendar's name is None (events need no label)."""
    if config.GOOGLE_CALENDAR_IDS:
        return [(c, None if c == "primary" else c) for c in config.GOOGLE_CALENDAR_IDS]
    try:
        entries, token = [], None
        while True:
            res = svc.calendarList().list(pageToken=token, minAccessRole="freeBusyReader").execute()
            entries += res.get("items", [])
            token = res.get("nextPageToken")
            if not token:
                break
    except Exception as e:
        log.warning("calendar list not read, using the main calendar only: %s", e)
        return [(config.GOOGLE_CALENDAR_ID, None)]
    cals = [(c["id"], None if c.get("primary") else _label(c.get("summaryOverride") or c.get("summary") or c["id"]))
            for c in entries if c.get("selected") or c.get("primary")]
    return cals or [(config.GOOGLE_CALENDAR_ID, None)]


def _label(name: str) -> str:
    """A calendar subscribed by URL is named after the URL; say its host instead ("timetable.example.edu").
    Renaming the calendar in Google Calendar overrides this."""
    if name.startswith(("http://", "https://", "webcal://")):
        from urllib.parse import urlparse
        return urlparse(name).hostname or name
    return name


register(Tool(
    name="list_events",
    description="List Google Calendar events. Prefer range (today, tomorrow, this_week, next_week, this_weekend, next_7_days); "
                "use range=custom with start/end ISO dates for a specific day or span.",
    params={"range": {"type": "string", "enum": RANGES}, "start": {"type": "string"}, "end": {"type": "string"}},
    required=[],
    handler=h_list_events, validate=v_list_events, confirm=False, read_only=True,
))


# -------------------------------------------------------------- free_time --
def free_slots(events: list, start: datetime, end: datetime, now: datetime = None) -> dict:
    """{day: [(from, to), ...]}: gaps of at least FREE_MIN_MINUTES between busy timed events, inside the daytime
    window FREE_DAY_HOURS and the asked range, from now on. All-day events and events marked free don't block."""
    now = now or datetime.now(TZ)
    h0, h1 = config.FREE_DAY_HOURS
    busy = sorted((e["start"], e["end"]) for e in events if e["busy"] and not e["all_day"])
    out = {}
    for d in _days(start, end):
        day0 = datetime.combine(d, datetime.min.time(), TZ)
        lo, hi = max(day0 + timedelta(hours=h0), start, now), min(day0 + timedelta(hours=h1), end)
        if hi <= lo:
            continue
        slots, t = [], lo
        for b0, b1 in busy:
            if b1 <= t or b0 >= hi:
                continue
            if b0 > t:
                slots.append((t, b0))
            t = max(t, b1)
        if t < hi:
            slots.append((t, hi))
        out[d] = [(a, b) for a, b in slots if b - a >= timedelta(minutes=config.FREE_MIN_MINUTES)]
    return out


def spoken_free(slots: dict) -> str:
    if not slots:
        return "That time is already over."
    h0, h1 = config.FREE_DAY_HOURS
    said = []
    for d, v in slots.items():
        name = _day_name(d)
        if not v:
            said.append(f"{name} you have no free time.")
        elif len(v) == 1 and (v[0][0].hour, v[0][0].minute, v[0][1].hour, v[0][1].minute) == (h0, 0, h1, 0):
            said.append(f"{name} you are free all day.")
        else:
            said.append(f"{name} you are free " +
                        _join([f"from {a.strftime('%H:%M')} to {b.strftime('%H:%M')}" for a, b in v]) + ".")
    return " ".join(said)


def h_free_time(start: datetime, end: datetime, scope=None) -> dict:
    events, failed = fetch_events(start, end)
    slots = free_slots(events, start, end)
    out = {"free": {d.isoformat(): [f"{a.strftime('%H:%M')}-{b.strftime('%H:%M')}" for a, b in v]
                    for d, v in slots.items()},
           "spoken": spoken_free(slots)}
    if failed:
        out["calendars_not_read"] = failed
        out["spoken"] += f" I could not read {_join(failed)}, so events from it are missing."
    out["accomplished"], out["assessment"] = "yes", "Free time worked out from the calendar."
    return out


register(Tool(
    name="free_time",
    description="When is the user free: the free time between calendar events. Same range/start/end as list_events; "
                "for part of a day (afternoon, morning, evening) give start and end with times, e.g. 12:00 to 18:00.",
    params={"range": {"type": "string", "enum": RANGES}, "start": {"type": "string"}, "end": {"type": "string"}},
    required=[],
    handler=h_free_time, validate=v_list_events, confirm=False, read_only=True,
))


# ---------------------------------------------------- plain calendar reads --
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
PARTS_OF_DAY = {"morning": (8, 12), "afternoon": (12, 18), "evening": (17, 22), "night": (18, 24)}
_FREE = re.compile(r"\b(when am i free|am i free|free time|free slots?|when do i have time|do i have time|"
                   r"am i available|when am i available|any time)\b")
_EVENTS = re.compile(r"\b(what'?s on|what is on|what do i have|do i have anything|anything on|what'?s happening|"
                     r"what is happening|what have i got|my (calendar|schedule|agenda))\b")
_NOT_CALENDAR = re.compile(r"\b(folder|files?|downloads?|documents?|desktop|ram|memory|lights?|bus|train|route)\b")


def _day_span(t: str, now: datetime):
    """Days named in the sentence -> (start, end, label) or None. 'next monday' is next week's Monday,
    'monday' / 'on monday' / 'this monday' the coming one (the same rule as the model's date table)."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    one = lambda d, label: (d, d + timedelta(days=1), label)
    if "day after tomorrow" in t:
        return one(today + timedelta(days=2), "the day after tomorrow")
    if re.search(r"\btomorrow\b", t):
        return one(today + timedelta(days=1), "tomorrow")
    if re.search(r"\b(today|tonight)\b", t):
        return one(today, "today")
    m = re.search(r"\b(next\s+)?(" + "|".join(_WEEKDAYS) + r")\b", t)
    if m:
        i = _WEEKDAYS.index(m.group(2))
        if m.group(1):
            return one(monday + timedelta(days=7 + i), "next " + m.group(2))
        ahead = (i - today.weekday()) % 7 or 7
        return one(today + timedelta(days=ahead), m.group(2))
    for words, rng in (("next weekend", None), ("this weekend", "this_weekend"), ("weekend", "this_weekend"),
                       ("next week", "next_week"), ("this week", "this_week")):
        if words in t:
            if rng is None:
                return monday + timedelta(days=12), monday + timedelta(days=14), words
            start, end = _named_range(rng)
            return start, end, words
    return None


def calendar_request(transcript: str, now: datetime = None):
    """'what's on my calendar next monday' / 'when am I free on friday afternoon' -> a list_events / free_time
    decision with the dates worked out here, or None to leave the sentence to the model. The 3B model
    picked wrong weekdays, dropped 'afternoon', and answered free-time questions from memory."""
    t = transcript.lower().replace("’", "'")
    if _NOT_CALENDAR.search(t) or re.search(r"\b(add|schedule a|book|create|put|remind)\b", t):
        return None
    tool = "free_time" if _FREE.search(t) else "list_events" if _EVENTS.search(t) else None
    now = now or datetime.now(TZ)
    span = _day_span(t, now) if tool else None
    if span is None and tool and not re.search(r"\d|january|february|march|april|may|june|july|august|september|"
                                               r"october|november|december|month", t):
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        span = (today, today + timedelta(days=1), "today")          # "when am I free" = today
    if span is None:
        return None
    start, end, label = span
    part = next((p for p in PARTS_OF_DAY if re.search(r"\b" + p + r"\b", t)), None)
    if part and end - start == timedelta(days=1):
        h0, h1 = PARTS_OF_DAY[part]
        start, end = start + timedelta(hours=h0), start + timedelta(hours=h1)
        label += " " + part
    fmt = "%Y-%m-%dT%H:%M"
    return {"action": "tool", "tool": tool,
            "args": {"range": "custom", "start": start.strftime(fmt), "end": end.strftime(fmt)},
            "text": ("Free time " if tool == "free_time" else "Events ") + label}


def login():
    """Run the Google consent in the browser now and save a token with every scope in SCOPES."""
    global _service
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(config.GOOGLE_CREDENTIALS), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    config.GOOGLE_TOKEN.write_text(creds.to_json(), encoding="utf-8")
    _service = None
    return creds


if __name__ == "__main__":
    import sys
    if "--login" in sys.argv:
        login()
        svc = _get_service()
        print("Logged in. Calendars read by list_events:")
        for _, name in calendars(svc):
            print("  -", name or "(main calendar)")
