"""Helpers shared by the layout provider, the server and tools/set_background.py (not a provider itself)."""
import json
import re
import time
import winreg
from pathlib import Path

from hub_config import WEB

LAYOUT = WEB / "layout.json"
MEDIA = {".mp4", ".webm", ".m4v", ".mov", ".jpg", ".jpeg", ".png", ".webp", ".gif"}
STYLES = {"default", "glass", "solid", "bare"}
SIZE = re.compile(r"^(\d{1,2})x(\d{1,2})$")

_vids = {"t": 0.0, "list": []}


def steam_dir() -> Path:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
        return Path(winreg.QueryValueEx(k, "SteamPath")[0])


def video_wallpapers() -> list:
    """Installed Wallpaper Engine video wallpapers: [{id, title, src, preview, mb}]. Cached 30 s."""
    if time.monotonic() - _vids["t"] < 30:
        return _vids["list"]
    out = []
    steam = steam_dir()
    for root in (steam / "steamapps/workshop/content/431960", steam / "steamapps/common/wallpaper_engine/projects/myprojects"):
        for proj in sorted(root.glob("*/project.json")) if root.is_dir() else []:
            try:
                j = json.loads(proj.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            f = proj.parent / str(j.get("file", ""))
            if str(j.get("type", "")).lower() != "video" or not f.is_file():
                continue
            prev = proj.parent / str(j.get("preview", ""))
            out.append({"id": proj.parent.name, "title": j.get("title") or proj.parent.name, "src": f.as_posix(),
                        "preview": prev if j.get("preview") and prev.is_file() else None,
                        "mb": round(f.stat().st_size / 1e6)})
    _vids.update(t=time.monotonic(), list=out)
    return out


def widget_types() -> list:
    return sorted(p.parent.name for p in (WEB / "widgets").glob("*/widget.js"))


def load_layout() -> dict:
    return json.loads(LAYOUT.read_text(encoding="utf-8"))


def save_layout(layout: dict):
    """layout.json with one line per widget, so it stays easy to edit by hand."""
    lines = ["{"]
    for k, v in layout.items():
        if k != "widgets":
            lines.append(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)},")
    ws = layout.get("widgets", [])
    lines.append('  "widgets": [')
    lines += ["    " + json.dumps(w, ensure_ascii=False) + ("," if i < len(ws) - 1 else "") for i, w in enumerate(ws)]
    lines += ["  ]", "}", ""]
    tmp = LAYOUT.with_suffix(".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(LAYOUT)
