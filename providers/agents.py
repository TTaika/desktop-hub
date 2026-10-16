"""Claude Code agents on this PC: background jobs and open terminal sessions, for the agents widget.

GET /api/agents?hours=<h>  -> {"agents": [...], "now": <ms>}, newest activity first. Finished agents are kept for
                              `hours` (default 12). Cached 1 s.

Each agent: {id, name, cwd ("~\\aikansio\\desktop_hub"), kind ("job" | "terminal"), status, detail, result,
             started (ms, when the current task began), finished (ms, when it ended or started waiting; else null)}
status: "working", "idle", "input" (needs input), "done", "failed" or "stopped" (the process is gone mid-task).

Read straight from Claude Code's own files, nothing is written:
  ~/.claude/jobs/<id>/state.json      a background job: state working | blocked | done | failed, tempo active | idle.
                                      After you reply, state stays "blocked" (or "done") while it works on it; tempo
                                      is "active" then, so that is what says it's working.
  ~/.claude/jobs/<id>/timeline.jsonl  its state changes. A line with "text" in a finished state is where it ended a
                                      turn; a line with no "text" that repeats a finished state is a message from you,
                                      so the latest one is where the current task began.
  ~/.claude/sessions/<pid>.json       each running claude process; "interactive" ones are terminals (busy | idle).
                                      Files of exited processes stay behind, so the pid is checked.
"""
import json
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil

CLAUDE = Path.home() / ".claude"
ENDED = {"blocked", "done", "failed"}
_lock = threading.Lock()
_cache = {"t": 0.0, "key": None, "value": None}
_timelines = {}                 # path -> ((mtime, size), (task start ms, last turn end ms))


def _ms(iso) -> int | None:
    try:
        return int(datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _home(cwd: str) -> str:
    try:
        return "~\\" + str(Path(cwd).relative_to(Path.home()))
    except ValueError:
        return cwd or ""


def _timeline(path: Path) -> tuple:
    """(when your latest message to the job arrived, when it last ended a turn), from its timeline; either may be
    None. Cached until the file changes."""
    try:
        st = path.stat()
    except OSError:
        return None, None
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _timelines.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    start, end, prev = None, None, None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if prev and prev.get("state") in ENDED and not e.get("text") and e.get("state") == prev.get("state"):
                    start = _ms(e.get("at"))
                elif e.get("state") in ENDED and e.get("text"):
                    end = _ms(e.get("at"))
                prev = e
    except OSError:
        return None, None
    _timelines[path] = (stamp, (start, end))
    return start, end


def _live_sessions() -> list:
    """sessions/<pid>.json of processes that are still running (same pid and the same start time)."""
    out = []
    for p in (CLAUDE / "sessions").glob("*.json"):
        s = _read(p)
        if not isinstance(s, dict) or s.get("spare"):      # a warm spare waiting for the next job
            continue
        try:
            proc = psutil.Process(int(s["pid"]))
            # procStart is a Windows FILETIME (100 ns since 1601); compare it with psutil's start time
            started = int(s.get("procStart") or 0) / 1e7 - 11644473600
            if started and abs(proc.create_time() - started) > 2:
                continue
        except (psutil.Error, KeyError, ValueError, TypeError):
            continue
        out.append(s)
    return out


def _job(d: Path, live: dict, now: int) -> dict | None:
    s = _read(d / "state.json")
    if not isinstance(s, dict):
        return None
    jid = s.get("daemonShort") or d.name
    state, proc = s.get("state"), live.get(jid)
    created = _ms(s.get("createdAt")) or now
    updated = _ms(s.get("updatedAt")) or created
    start, turn_end = _timeline(d / "timeline.jsonl")
    start = start or created
    # updatedAt keeps moving while it works on your reply, so it can't say when the last turn ended
    ended = turn_end or _ms(s.get("lastTerminalAt"))
    finished = None
    if state in ENDED and s.get("tempo") == "active":       # you replied and it's on that now
        status = "working"
    elif state == "done":
        status, finished = "done", ended or updated
    elif state == "failed":
        status, finished = "failed", ended or updated
    elif state == "blocked":
        status, finished = "input", ended or updated
    elif proc is None and now - updated > 120_000:       # nothing runs it any more (closed, or the PC restarted)
        status, finished = "stopped", updated
    elif s.get("tempo") == "idle" and (proc or {}).get("status") != "busy":
        status = "idle"
    else:
        status = "working"
    if finished is not None and finished < start:          # you replied after it finished: it's on that now
        status, finished = ("working" if proc or now - start < 120_000 else "stopped"), None
    result = (s.get("output") or {}).get("result") if isinstance(s.get("output"), dict) else None
    return {"id": jid, "name": s.get("name") or jid, "cwd": _home(s.get("cwd") or ""), "kind": "job",
            "status": status, "detail": s.get("detail") or "", "result": result or "",
            "started": start, "finished": finished, "session": s.get("sessionId"), "activity": finished or updated}


def _collect(hours: float) -> list:
    now = int(time.time() * 1000)
    sessions = _live_sessions()
    live = {s["jobId"]: s for s in sessions if s.get("jobId")}
    agents, claimed = [], set()
    for d in (CLAUDE / "jobs").iterdir() if (CLAUDE / "jobs").is_dir() else []:
        if d.is_dir():
            a = _job(d, live, now)
            if a:
                agents.append(a)
                claimed.update(x for x in (a["id"], a["session"]) if x)
    # terminals you have open yourself; a terminal that was moved to the background is already listed as its job
    for s in sessions:
        if s.get("kind") != "interactive" or s.get("sessionId") in claimed or s.get("parkedJobId") in claimed:
            continue
        busy = s.get("status") == "busy"
        since = s.get("statusUpdatedAt") or s.get("startedAt") or now
        agents.append({"id": str(s.get("pid")), "name": s.get("name") or "Terminal", "cwd": _home(s.get("cwd") or ""),
                       "kind": "terminal", "status": "working" if busy else "idle", "detail": "", "result": "",
                       "started": since if busy else s.get("startedAt") or since, "finished": None,
                       "session": s.get("sessionId"), "activity": now if busy else since})
        claimed.add(s.get("sessionId"))
    keep = now - hours * 3_600_000
    agents = [a for a in agents if a["status"] not in ("done", "failed", "stopped") or a["activity"] >= keep]
    agents.sort(key=lambda a: -a["activity"])
    for a in agents:
        del a["session"], a["activity"]
    return agents


def get(params: dict) -> dict:
    try:
        hours = max(0.0, float(params.get("hours", 12)))
    except ValueError:
        hours = 12.0
    with _lock:
        if _cache["key"] != hours or time.monotonic() - _cache["t"] > 1:
            _cache.update(t=time.monotonic(), key=hours, value=_collect(hours))
        return {"agents": _cache["value"], "now": int(time.time() * 1000)}
