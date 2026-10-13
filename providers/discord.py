"""Discord, from the Discord app on this PC: the call you are in, the chat you have open, and new DMs.

It talks to Discord's local RPC socket the way the StreamKit overlay does (StreamKit's client id and its
token exchange). The first time, Discord shows an "Authorize" window; the token is then kept in
data/discord_token.json.

GET /api/discord[?sound=1&expire=minutes]
  -> {"status": "ready" | "no_discord" | "authorizing" | "error", "message": str,
      "channel": {"id", "name", "guild"} | null,
      "members": [{"id", "name", "avatar", "speaking", "muted", "deafened", "me"}],
      "dms": [{"channel_id", "name", "avatar", "count", "time"}]}        unread DMs, newest first
  sound=1: play sounds/dm.wav when a DM arrives while you are in a call (asked for by the call widget).
  expire: forget an unread DM after this many minutes (default 180).
GET /api/discord?view=chat
  -> {"status": "ready" | "none" | "dm" | "not_found" | "loading" | <the connection statuses>, "message": str,
      "channel": {"id", "name", "guild", "topic"} | null,
      "messages": [{"id", "author_id", "name", "color", "avatar", "time", "text", "files", "edited", "bot",
                    "images": [{"key", "src", "w", "h", "full"}]}]}           src: a thumbnail at most 480 px wide
POST /api/discord {"open": channel_id}     opens that DM in Discord and marks it read
POST /api/discord {"dismiss": channel_id | "all"}
POST /api/discord {"view": url}            opens a picture from the chat (a Discord media link) in the browser

The open chat is found from the Discord window's title ("#channel | Server - Discord"), by name, so with two
servers of the same name and channel name it can pick the wrong one. A DM can't be shown: Discord's RPC can't
look one up by name. A DM counts as read when its conversation is open in Discord (the title shows it), when
you answer it, or when you open it from the hub. Reading it on another device can't be seen from here.
"""
import ctypes
import ctypes.wintypes as wt
import json
import logging
import os
import re
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import websocket

from hub_config import DATA

log = logging.getLogger("discord")

CLIENT_ID = "207646673902501888"                 # StreamKit
ORIGIN = "http://localhost:3000"            # an origin StreamKit's app accepts (as Discover overlay uses)
TOKEN_URL = "https://streamkit.discord.com/overlay/token"
TOKEN_FILE = DATA / "discord_token.json"
SOUND = Path(__file__).resolve().parent.parent / "sounds" / "dm.wav"
SCOPES = ["rpc", "messages.read", "rpc.notifications.read"]
CHANNEL_EVENTS = ["VOICE_STATE_CREATE", "VOICE_STATE_UPDATE", "VOICE_STATE_DELETE", "SPEAKING_START", "SPEAKING_STOP"]
MESSAGE_EVENTS = ["MESSAGE_CREATE", "MESSAGE_UPDATE", "MESSAGE_DELETE"]
TEXT_TYPES = (0, 5, 2, 13, 15)               # text, announcement, voice (has a text chat), stage, forum
KEEP_MESSAGES = 50

_lock = threading.Lock()
_state = {"status": "no_discord", "message": "Connecting to Discord...", "channel": None}
_members = {}                 # user id -> member dict
_me = {"id": None}
_conn = {"send": None}        # the live session's send(), once authenticated
_chat = {"status": "none", "message": "Open a server channel in Discord", "channel": None, "messages": []}
_title = {"value": None, "gen": 0}
_dms = {}                     # channel id -> unread DM (see get)
_dm_kind = {}                 # channel id -> True if it is a DM or group DM
_watched = set()              # channel ids with message events subscribed
_sound = {"t": 0.0}           # when a call widget last asked for the sound
_cache = {"guilds": (0.0, []), "channels": {}}


def get(params: dict) -> dict:
    if params.get("view") == "chat":
        with _lock:
            return {**_chat, "messages": list(_chat["messages"])}
    if params.get("sound") == "1":
        _sound["t"] = time.monotonic()
    expire = float(params.get("expire") or 180) * 60
    with _lock:
        for ch in [c for c, d in _dms.items() if time.time() - d["time"] > expire]:
            del _dms[ch]
        members = sorted(_members.values(), key=lambda m: (not m["me"], m["name"].lower()))
        dms = sorted(({k: v for k, v in d.items() if k != "names"} for d in _dms.values()), key=lambda d: -d["time"])
        return {**_state, "members": members, "dms": dms}


def post(body: dict) -> dict:
    if body.get("open"):
        ch = str(body["open"])
        if not ch.isdigit():
            return {"error": "bad channel id"}
        os.startfile(f"discord://-/channels/@me/{ch}")
        _read(ch)
    elif body.get("view"):
        url = str(body["view"])
        if not re.match(r"^https://(cdn\.discordapp\.com|media\.discordapp\.net|images-ext-\d\.discordapp\.net)/", url):
            return {"error": "only Discord's own media links"}
        os.startfile(url)
    elif body.get("dismiss") == "all":
        with _lock:
            _dms.clear()
    elif body.get("dismiss"):
        _read(str(body["dismiss"]))
    return {"ok": True}


def start():
    threading.Thread(target=_run, name="discord-rpc", daemon=True).start()
    threading.Thread(target=_watch_title, name="discord-title", daemon=True).start()


def _set(**kw):
    with _lock:
        _state.update(kw)


def _set_chat(**kw):
    with _lock:
        _chat.update(kw)


def _avatar(user: dict) -> str:
    uid = user.get("id") or "0"
    if user.get("avatar"):
        return f"https://cdn.discordapp.com/avatars/{uid}/{user['avatar']}.png?size=64"
    return f"https://cdn.discordapp.com/embed/avatars/{(int(uid) >> 22) % 6}.png"


def _name(user: dict) -> str:
    return user.get("global_name") or user.get("username") or "?"


# ------------------------------------------------------------------ token --
def _load_token():
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("access_token")
    except (FileNotFoundError, ValueError):
        return None


def _save_token(token):
    if token:
        TOKEN_FILE.write_text(json.dumps({"access_token": token}), encoding="utf-8")
    else:
        TOKEN_FILE.unlink(missing_ok=True)


def _exchange(code: str) -> str:
    req = urllib.request.Request(TOKEN_URL, data=json.dumps({"code": code}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["access_token"]


# ------------------------------------------------------------- connection --
def _run():
    while True:
        delay = 10
        try:
            delay = _session()
        except Exception as e:
            log.warning("discord session ended: %s: %s", type(e).__name__, e)
            _set(status="error", message="Lost the connection to Discord", channel=None)
        _conn["send"] = None
        _watched.clear()
        with _lock:
            _members.clear()
            _chat.update(status=_state["status"], message=_state["message"], channel=None, messages=[])
        time.sleep(delay)


def _connect():
    for port in range(6463, 6473):
        try:
            return websocket.create_connection(f"ws://127.0.0.1:{port}/?v=1&client_id={CLIENT_ID}",
                                               origin=ORIGIN, timeout=5)
        except (OSError, websocket.WebSocketException):
            continue
    return None


def _session() -> int:
    """One connection to the Discord app, until it closes. Returns seconds to wait before reconnecting."""
    ws = _connect()
    if ws is None:
        _set(status="no_discord", message="Discord is not running", channel=None)
        return 15
    ws.settimeout(None)
    channel = {"id": None}
    pending = {}                              # nonce -> callback(reply), for the commands that want the answer

    def send(cmd, args=None, evt=None, then=None):
        nonce = str(uuid.uuid4())
        msg = {"cmd": cmd, "args": args or {}, "nonce": nonce}
        if evt:
            msg["evt"] = evt
        if then:
            pending[nonce] = then
        ws.send(json.dumps(msg))              # websocket-client locks around send: the title thread sends too

    def watch(channel_id):
        if channel["id"] == channel_id:
            return
        if channel["id"]:
            for e in CHANNEL_EVENTS:
                send("UNSUBSCRIBE", {"channel_id": channel["id"]}, e)
        channel["id"] = channel_id
        if channel_id:
            for e in CHANNEL_EVENTS:
                send("SUBSCRIBE", {"channel_id": channel_id}, e)

    def authorize():
        _set(status="authorizing", message="Click Authorize in the Discord window", channel=None)
        send("AUTHORIZE", {"client_id": CLIENT_ID, "scopes": SCOPES, "prompt": "none"})

    try:
        while True:
            msg = json.loads(ws.recv())
            cmd, evt, data = msg.get("cmd"), msg.get("evt"), msg.get("data") or {}

            then = pending.pop(msg.get("nonce"), None)
            if then:
                try:
                    then(msg)
                except Exception:
                    log.exception("handling %s failed", cmd)

            elif cmd == "DISPATCH" and evt == "READY":
                _me["id"] = (data.get("user") or {}).get("id")
                token = _load_token()
                if token:
                    send("AUTHENTICATE", {"access_token": token})
                else:
                    authorize()

            elif cmd == "AUTHORIZE":
                if evt == "ERROR":
                    log.info("authorization refused: %s", data.get("message"))
                    _set(status="error", message="Discord access was not authorized - retrying in a minute")
                    return 60
                token = _exchange(data["code"])
                _save_token(token)
                send("AUTHENTICATE", {"access_token": token})

            elif cmd == "AUTHENTICATE":
                if evt == "ERROR":
                    log.info("stored token rejected: %s", data.get("message"))
                    _save_token(None)
                    authorize()
                else:
                    _set(status="ready", message="Not in a call")
                    send("SUBSCRIBE", evt="VOICE_CHANNEL_SELECT")
                    send("SUBSCRIBE", evt="NOTIFICATION_CREATE")
                    send("GET_SELECTED_VOICE_CHANNEL")
                    _conn["send"] = send
                    _title["value"] = None        # the title thread then finds the open chat again

            elif cmd == "GET_SELECTED_VOICE_CHANNEL":
                _on_channel(msg.get("data"), watch, send)

            elif cmd == "GET_GUILD" and evt != "ERROR":
                with _lock:
                    if _state["channel"] and _state["channel"].get("guild_id") == data.get("id"):
                        _state["channel"] = {**_state["channel"], "guild": data.get("name")}

            elif cmd == "DISPATCH":
                _on_event(evt, data, watch, send)
    finally:
        ws.close()


def _member(vs: dict, speaking=False) -> dict:
    user = vs.get("user") or {}
    v = vs.get("voice_state") or {}
    uid = user.get("id", "")
    return {"id": uid, "name": vs.get("nick") or _name(user),
            "avatar": _avatar(user), "speaking": speaking, "me": uid == _me["id"],
            "muted": bool(v.get("self_mute") or v.get("mute") or vs.get("mute")),
            "deafened": bool(v.get("self_deaf") or v.get("deaf"))}


def _on_channel(data, watch, send):
    if not data or not data.get("id"):
        watch(None)
        with _lock:
            _members.clear()
        _set(channel=None, message="Not in a call")
        return
    watch(data["id"])
    guild_id = data.get("guild_id")
    with _lock:
        _members.clear()
        for vs in data.get("voice_states") or []:
            m = _member(vs)
            _members[m["id"]] = m
        _state["channel"] = {"id": data["id"], "name": data.get("name") or "Call",
                             "guild_id": guild_id, "guild": None if guild_id else "Direct call"}
    if guild_id:
        send("GET_GUILD", {"guild_id": guild_id})


def _on_event(evt, data, watch, send):
    if evt == "VOICE_CHANNEL_SELECT":
        if data.get("channel_id"):
            send("GET_SELECTED_VOICE_CHANNEL")
        else:
            _on_channel(None, watch, send)
    elif evt in ("VOICE_STATE_CREATE", "VOICE_STATE_UPDATE"):
        with _lock:
            uid = (data.get("user") or {}).get("id")
            speaking = _members.get(uid, {}).get("speaking", False)
            m = _member(data, speaking)
            _members[m["id"]] = m
    elif evt == "VOICE_STATE_DELETE":
        with _lock:
            _members.pop((data.get("user") or {}).get("id"), None)
    elif evt in ("SPEAKING_START", "SPEAKING_STOP"):
        with _lock:
            m = _members.get(str(data.get("user_id")))
            if m:
                m["speaking"] = evt == "SPEAKING_START"
    elif evt == "NOTIFICATION_CREATE":
        _on_notification(data, send)
    elif evt in MESSAGE_EVENTS:
        _on_message(evt, data)


# ------------------------------------------------------------ unread DMs --
def _on_notification(data: dict, send):
    """Discord shows a desktop notification: keep it if it is from a DM or group DM."""
    ch = str(data.get("channel_id") or "")
    msg = data.get("message") or {}
    author = msg.get("author") or {}
    if not ch or author.get("id") == _me["id"]:
        return

    def decide(is_dm):
        if not is_dm:
            return
        with _lock:
            d = _dms.get(ch)
            names = {s.lower() for s in (data.get("title"), msg.get("nick"), author.get("global_name"),
                                         author.get("username")) if s}
            _dms[ch] = {"channel_id": ch, "name": data.get("title") or _name(author), "avatar": _avatar(author),
                        "count": (d["count"] if d else 0) + 1, "time": time.time(),
                        "names": (d["names"] if d else set()) | names}
            in_call = _state["channel"] is not None
        _subscribe_messages(ch)                # to see your answer, which marks it read
        if in_call and time.monotonic() - _sound["t"] < 30 and SOUND.is_file():
            import winsound
            winsound.PlaySound(str(SOUND), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)

    if ch in _dm_kind:
        return decide(_dm_kind[ch])

    def got(reply):
        info = reply.get("data") or {}
        if reply.get("evt") == "ERROR":       # can't look it up: server notifications are titled "name (#channel, server)"
            is_dm = "(#" not in (data.get("title") or "")
        else:
            is_dm = info.get("type") in (1, 3)
        _dm_kind[ch] = is_dm
        decide(is_dm)
    send("GET_CHANNEL", {"channel_id": ch}, then=got)


def _read(channel_id: str):
    with _lock:
        _dms.pop(channel_id, None)


def _read_by_title(name: str):
    name = name.lower()
    with _lock:
        for ch in [c for c, d in _dms.items() if name in d["names"]]:
            del _dms[ch]


# -------------------------------------------------------------- open chat --
def _discord_title():
    """The title of Discord's main window, or None when it has none (closed to the tray, not running)."""
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        n = u32.GetWindowTextLengthW(hwnd)
        if n and u32.IsWindowVisible(hwnd):
            pid = wt.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = k32.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
            if proc:
                exe, size = ctypes.create_unicode_buffer(260), wt.DWORD(260)
                k32.QueryFullProcessImageNameW(proc, 0, exe, ctypes.byref(size))
                k32.CloseHandle(proc)
                if exe.value.lower().endswith("\\discord.exe"):
                    buf = ctypes.create_unicode_buffer(n + 1)
                    u32.GetWindowTextW(hwnd, buf, n + 1)
                    found.append(buf.value)
        return True
    u32.EnumWindows(each, 0)
    return next((t for t in found if t.endswith("Discord")), None)


def _watch_title():
    while True:
        time.sleep(1)
        try:
            title = _discord_title()
            if title is None or title == _title["value"] or not _conn["send"]:
                continue
            _title["value"] = title
            _title["gen"] += 1
            _on_title(title, _title["gen"])
        except Exception:
            log.exception("reading the Discord window failed")


def _on_title(title: str, gen: int):
    core = re.sub(r"\s+-\s+Discord$", "", re.sub(r"^\(\d+\)\s*", "", title)).strip()
    if core.startswith("@"):
        _read_by_title(core[1:])
        return _show_none("dm", "A direct message is open. Open a server channel in Discord to see it here.")
    _read_by_title(core)                         # group DMs are titled by their name
    if " | " not in core:
        return _show_none("none", "Open a server channel in Discord")
    channel, guild = core.rsplit(" | ", 1)
    channel = channel.split(" | ")[-1].lstrip("#").strip()
    _set_chat(status="loading", message=f"Opening #{channel}...")
    _find_channel(channel, guild, gen)


def _show_none(status, message):
    _unwatch_chat()
    _set_chat(status=status, message=message, channel=None, messages=[])


def _find_channel(name: str, guild_name: str, gen: int):
    send = _conn["send"]

    def with_guilds(guilds):
        candidates = [g for g in guilds if g.get("name") == guild_name]
        if not candidates:
            return _show_none("not_found", f"Couldn't find the server {guild_name}")
        try_guild(candidates, 0)

    def try_guild(candidates, i):
        if gen != _title["gen"]:
            return
        if i == len(candidates):
            return _show_none("not_found", f"Couldn't find #{name} in {guild_name}")
        g = candidates[i]

        def with_channels(channels):
            hit = next((c for c in channels if c.get("name") == name and c.get("type") in TEXT_TYPES), None)
            if hit:
                _open_channel(hit["id"], g["name"], gen)
            else:
                try_guild(candidates, i + 1)
        t, channels = _cache["channels"].get(g["id"], (0.0, None))
        if channels is not None and time.monotonic() - t < 600:
            return with_channels(channels)

        def got(reply):
            channels = (reply.get("data") or {}).get("channels") or []
            _cache["channels"][g["id"]] = (time.monotonic(), channels)
            with_channels(channels)
        send("GET_CHANNELS", {"guild_id": g["id"]}, then=got)

    t, guilds = _cache["guilds"]
    if guilds and time.monotonic() - t < 600:
        return with_guilds(guilds)

    def got(reply):
        guilds = (reply.get("data") or {}).get("guilds") or []
        _cache["guilds"] = (time.monotonic(), guilds)
        with_guilds(guilds)
    send("GET_GUILDS", then=got)


def _open_channel(channel_id: str, guild_name: str, gen: int):
    def got(reply):
        if gen != _title["gen"]:
            return
        if reply.get("evt") == "ERROR":
            return _show_none("not_found", (reply.get("data") or {}).get("message") or "Couldn't read the channel")
        d = reply.get("data") or {}
        _unwatch_chat(keep=channel_id)
        for m in d.get("messages") or []:
            a = m.get("author") or {}
            if a.get("id"):
                _names[a["id"]] = m.get("nick") or _name(a)
        msgs = [_message(m) for m in (d.get("messages") or [])]
        msgs.sort(key=lambda m: m["time"])
        _set_chat(status="ready", message="", messages=msgs[-KEEP_MESSAGES:],
                  channel={"id": channel_id, "name": d.get("name") or "", "guild": guild_name, "topic": d.get("topic") or ""})
        _subscribe_messages(channel_id)
    _conn["send"]("GET_CHANNEL", {"channel_id": channel_id}, then=got)


def _subscribe_messages(channel_id: str):
    send = _conn["send"]
    if send and channel_id not in _watched:
        _watched.add(channel_id)
        for e in MESSAGE_EVENTS:
            send("SUBSCRIBE", {"channel_id": channel_id}, e)


def _unwatch_chat(keep=None):
    """Stops the message events of the chat shown so far (not of a DM still waiting to be read)."""
    with _lock:
        old = _chat["channel"]["id"] if _chat["channel"] else None
        if old in _dms:
            old = None
    send = _conn["send"]
    if old and old != keep and old in _watched and send:
        _watched.discard(old)
        for e in MESSAGE_EVENTS:
            send("UNSUBSCRIBE", {"channel_id": old}, e)


def _on_message(evt: str, data: dict):
    ch = str(data.get("channel_id") or "")
    m = data.get("message") or {}
    if evt == "MESSAGE_CREATE" and ch in _dms and (m.get("author") or {}).get("id") == _me["id"]:
        _read(ch)                                # you answered it
    with _lock:
        if not _chat["channel"] or _chat["channel"]["id"] != ch:
            return
        msgs = _chat["messages"]
        if evt == "MESSAGE_DELETE":
            _chat["messages"] = [x for x in msgs if x["id"] != m.get("id")]
        elif evt == "MESSAGE_UPDATE":
            _chat["messages"] = [_message(m) if x["id"] == m.get("id") else x for x in msgs]
        elif not any(x["id"] == m.get("id") for x in msgs):
            _chat["messages"] = (msgs + [_message(m)])[-KEEP_MESSAGES:]


_names = {}                   # user id -> display name, from the messages seen


def _message(m: dict) -> dict:
    author = m.get("author") or {}
    if author.get("id"):
        _names[author["id"]] = m.get("nick") or _name(author)
    text = m.get("content") or ""
    def mention(x):                              # mentions come as user ids; name the ones seen in this chat
        return "@" + _names.get(x[1], "someone")
    text = re.sub(r"<@!?(\d+)>", mention, text)
    text = re.sub(r"<a?:(\w+):\d+>", r":\1:", text)                  # custom emoji
    text = re.sub(r"<@&\d+>", "@role", text)
    text = re.sub(r"<#\d+>", "#channel", text)
    text = re.sub(r"<t:(\d+)(?::\w)?>", lambda x: time.strftime("%d.%m. %H:%M", time.localtime(int(x[1]))), text)
    if not text and m.get("embeds"):
        e = m["embeds"][0]
        text = e.get("title") or e.get("description") or "(embed)"
    images, files = [], []
    for a in m.get("attachments") or []:
        if (a.get("content_type") or "").startswith("image/") and a.get("width"):
            images.append(_image(a.get("id"), a.get("proxy_url") or a.get("url"), a["width"], a["height"], a.get("url")))
        else:
            files.append(a.get("filename"))
    for i, e in enumerate(m.get("embeds") or []):     # link previews, gifs (their still frame); keys come in two spellings
        pic = e.get("image") or e.get("thumbnail") or {}
        src = pic.get("proxyURL") or pic.get("proxy_url") or pic.get("url")
        if src and pic.get("width"):
            images.append(_image(f"{m.get('id')}-e{i}", src, pic["width"], pic["height"], e.get("url") or pic.get("url")))
            if text.strip() == (e.get("url") or "").strip() and e.get("type") in ("image", "gifv"):
                text = ""                              # a bare link to a picture: the picture says it
    return {"id": m.get("id"), "author_id": author.get("id"), "name": m.get("nick") or _name(author),
            "color": m.get("author_color"), "avatar": _avatar(author), "time": m.get("timestamp") or "",
            "text": text, "files": files, "images": images[:4],
            "edited": bool(m.get("edited_timestamp")), "bot": bool(author.get("bot"))}


THUMB_W = 480


def _image(key, src, width, height, full):
    """A picture as a thumbnail from Discord's media proxy, at most THUMB_W wide and as PNG/JPEG (the overlay
    engine can't decode WebP)."""
    scale = min(1.0, THUMB_W / width)
    w, h = max(1, round(width * scale)), max(1, round(height * scale))
    if "media.discordapp.net" in src or "images-ext" in src:
        src += ("&" if "?" in src else "?") + f"width={w}&height={h}&format=png"
    return {"key": key, "src": src, "w": w, "h": h, "full": full}
