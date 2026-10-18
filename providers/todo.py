"""A todo.txt file (http://todotxt.org): one task per line, `+tag` / `@context` to group, `due:YYYY-MM-DD` deadlines.
The file is shared with other devices by Syncthing (or any synced folder), so the same list is edited in sleek,
Markor etc. config.json: {"todo": {"file": "C:/Users/me/Sync/todo.txt"}}; without it, data/todo.txt.

GET  /api/todo  -> {"file", "exists", "tasks": [{id, raw, done, priority, due, created, completed, text, tags,
                    contexts}], "conflicts": [names of Syncthing conflict copies next to the file]}
POST /api/todo  {"action": "add", "text": "Call dentist +health due:fri"}   (today/tomorrow/weekday names become dates)
                {"action": "toggle", "id": 3, "raw": "<the line as GET gave it>"}   done <-> not done
                {"action": "delete", "id": 3, "raw": "..."}
A task is found by its line number and checked against its text, so an edit that synced in meanwhile is never
overwritten by mistake: the request fails with "changed" and the widget reloads.
"""
import datetime as dt
import os
import re
import threading
import time
from pathlib import Path

from hub_config import CONFIG, DATA

_lock = threading.Lock()
_cache = {"key": None, "value": None}

TASK = re.compile(r"^(?:(x) (?:(\d{4}-\d\d-\d\d) )?)?(?:\(([A-Z])\) )?(?:(\d{4}-\d\d-\d\d) )?(.*)$")
DATE = re.compile(r"^\d{4}-\d\d-\d\d$")
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _path() -> Path:
    f = (CONFIG.get("todo") or {}).get("file")
    return Path(os.path.expandvars(os.path.expanduser(f))) if f else DATA / "todo.txt"


def parse(line: str, i: int) -> dict:
    done, completed, prio, created, rest = TASK.match(line).groups()
    words, tags, contexts, extra = [], [], [], {}
    for w in rest.split(" "):
        if len(w) > 1 and w[0] == "+":
            tags.append(w[1:])
        elif len(w) > 1 and w[0] == "@":
            contexts.append(w[1:])
        elif re.match(r"^[^\s:/]+:[^\s:/]+$", w):     # key:value, but not a link like https://...
            k, v = w.split(":", 1)
            extra[k] = v
        else:
            words.append(w)
    due = extra.get("due") if DATE.match(extra.get("due", "")) else None
    return {"id": i, "raw": line, "done": bool(done), "priority": prio or extra.get("pri"), "due": due,
            "created": created, "completed": completed, "text": " ".join(w for w in words if w),
            "tags": tags, "contexts": contexts}


def _conflicts(p: Path) -> list:
    """Syncthing keeps both versions when two devices changed the file while apart: todo.sync-conflict-*.txt."""
    try:
        return sorted(f.name for f in p.parent.glob(f"{p.stem}.sync-conflict-*{p.suffix}"))
    except OSError:
        return []


def _read(p: Path):
    """(lines, newline). Blank lines are kept so line numbers match what other apps see."""
    data = p.read_bytes()
    text = data.decode("utf-8-sig")
    return text.splitlines(), "\r\n" if b"\r\n" in data else "\n"


def _write(p: Path, lines: list, nl: str):
    """Write a temp file and swap it in, so Syncthing never picks up a half-written list. The "~syncthing~" prefix
    is one Syncthing itself ignores. Another program may hold the file open for a moment on Windows: retry."""
    tmp = p.with_name(f"~syncthing~{p.name}.hub.tmp")
    tmp.write_bytes((nl.join(lines) + nl if lines else "").encode("utf-8"))
    for attempt in range(10):
        try:
            os.replace(tmp, p)
            break
        except PermissionError:
            if attempt == 9:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.1)
    _cache["key"] = None


def get(params: dict) -> dict:
    p = _path()
    with _lock:
        try:
            st = p.stat()
        except OSError:
            return {"file": str(p), "exists": False, "tasks": [], "conflicts": []}
        key = (st.st_mtime_ns, st.st_size)
        if _cache["key"] != key:
            lines, _ = _read(p)
            _cache["value"] = [parse(l, i) for i, l in enumerate(lines) if l.strip()]
            _cache["key"] = key
        return {"file": str(p), "exists": True, "tasks": _cache["value"], "conflicts": _conflicts(p)}


def _dates(text: str, today: dt.date) -> str:
    """due:today, due:tomorrow, due:fri ... -> due:YYYY-MM-DD (the next such day, not today)."""
    def repl(m):
        w = m.group(1).lower()
        if w in ("today", "tod"):
            d = today
        elif w in ("tomorrow", "tom"):
            d = today + dt.timedelta(days=1)
        elif w[:3] in WEEKDAYS:
            d = today + dt.timedelta(days=(WEEKDAYS.index(w[:3]) - today.weekday() - 1) % 7 + 1)
        else:
            return m.group(0)
        return f"due:{d.isoformat()}"
    return re.sub(r"\bdue:([A-Za-z]+)\b", repl, text)


def _find(lines: list, body: dict) -> int:
    i, raw = int(body.get("id", -1)), body.get("raw")
    if not (0 <= i < len(lines) and lines[i] == raw):
        raise LookupError
    return i


def toggle(line: str, today: dt.date) -> str:
    """Done the way todo.txt says: "x <completion date> ", and the priority kept as pri:A so undo can put it back."""
    t = parse(line, 0)
    if t["done"]:
        rest = re.sub(r"^x (\d{4}-\d\d-\d\d )?", "", line)
        m = re.search(r"(?:^| )pri:([A-Z])(?= |$)", rest)
        if m:
            rest = f"({m.group(1)}) " + (rest[:m.start()] + rest[m.end():]).strip()
        return rest
    m = re.match(r"^\(([A-Z])\) ", line)
    if m:
        line = line[m.end():] + f" pri:{m.group(1)}"
    return f"x {today.isoformat()} {line}"


def post(body: dict) -> dict:
    p = _path()
    today = dt.date.today()
    action = body.get("action")
    with _lock:
        lines, nl = _read(p) if p.exists() else ([], os.linesep)
        try:
            if action == "add":
                text = " ".join(str(body.get("text", "")).split())
                if not text:
                    return {"error": "Empty task"}
                text = _dates(text, today)
                m = re.match(r"^\(([A-Z])\) ", text)        # keep a typed priority in front of the date
                lines.append(f"{m.group(0) if m else ''}{today.isoformat()} {text[m.end():] if m else text}")
            elif action == "toggle":
                i = _find(lines, body)
                lines[i] = toggle(lines[i], today)
            elif action == "delete":
                lines.pop(_find(lines, body))
            else:
                return {"error": f"Unknown action {action!r}"}
        except LookupError:
            return {"error": "changed"}       # the file changed under us (a sync): reload and try again
        p.parent.mkdir(parents=True, exist_ok=True)
        _write(p, lines, nl)
    return {"ok": True}
