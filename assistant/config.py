"""Settings for the lights and calendar tools in assistant/tools/, which come from a voice assistant project and
run here on their own. Values come from the "calendar" and "lights" sections of the hub's config.json; logins and
bulb keys live in data/ (git-ignored).

config.json:
  "timezone": "Europe/Helsinki",
  "calendar": {"ids": [], "ics_url": "", "event_calendar": "primary"},
  "lights": {"groups": {"bedroom": ["Bulb 1"]}}

With voice_assistant_dir set in config.json, the hub uses that project's own copy of these tools (and its
logins) instead of this one.
"""
from hub_config import CONFIG, DATA

_cal = CONFIG.get("calendar") or {}
_lights = CONFIG.get("lights") or {}

# -------------------------------------------------------------- calendar ---
TIMEZONE = CONFIG.get("timezone") or "UTC"
GOOGLE_CREDENTIALS = DATA / "google_credentials.json"   # the OAuth client from Google Cloud Console (see README)
GOOGLE_TOKEN = DATA / "google_token.json"               # written by: py -3.13 -m assistant.tools.calendar_tool --login
GOOGLE_CALENDAR_ID = _cal.get("event_calendar") or "primary"   # where create_event puts events (unused by the hub)
GOOGLE_CALENDAR_IDS = _cal.get("ids") or []             # calendars to read; empty = every calendar ticked in Google Calendar
GOOGLE_CALENDAR_ICS_URL = _cal.get("ics_url") or ""     # read-only alternative: the calendar's secret iCal address
DEFAULT_EVENT_MINUTES = 60
FREE_DAY_HOURS = (8, 22)
FREE_MIN_MINUTES = 30
ICS_CACHE_S = 300

# ---------------------------------------------------------------- lights ---
TUYA_DEVICES_FILE = DATA / "devices.json"               # written by tools/fetch_tuya_keys.py
LIGHT_SCENES_FILE = DATA / "light_scenes.json"
LIGHT_TIMEOUT = 5
LIGHT_GROUPS = _lights.get("groups") or {}
