"""The layout editor's backend (http://127.0.0.1:8765/?edit).

GET  /api/layout -> {"layout": layout.json, "types": [widget folder names],
                     "backgrounds": [{id, title, src, mb, preview_url}]}   installed Wallpaper Engine videos
POST /api/layout {"layout": {...}} -> checks it and writes layout.json; open wallpapers reload themselves
"""
from pathlib import Path

from hub_config import WEB

from ._shared import MEDIA, SIZE, STYLES, load_layout, save_layout, video_wallpapers, widget_types

WIDGET_KEYS = ("type", "size", "col", "row", "style", "accent", "options")


def get(params: dict) -> dict:
    return {"layout": load_layout(), "types": widget_types(),
            "backgrounds": [{k: v for k, v in b.items() if k != "preview"}
                            | {"preview_url": f"/media/preview/{b['id']}" if b["preview"] else None}
                            for b in video_wallpapers()]}


def _int(v, lo, hi, what):
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise ValueError(f"{what} must be a whole number {lo}-{hi}")
    return v


def _background(bg):
    if bg is None:
        return None
    src = bg.get("src") if isinstance(bg, dict) else bg
    if not isinstance(src, str) or not src:
        raise ValueError("background needs a src")
    p = Path(src)
    if p.suffix.lower() not in MEDIA:
        raise ValueError("background must be an image or video")
    if p.is_absolute() and not p.is_file():
        raise ValueError(f"background file not found: {src}")
    if not p.is_absolute() and not (WEB / src).resolve().is_relative_to(WEB):
        raise ValueError("background path leaves web/")
    if not isinstance(bg, dict):
        return src
    out = {"src": src}
    for k in ("fit", "position"):
        if isinstance(bg.get(k), str):
            out[k] = bg[k]
    for k, lo, hi in (("dim", 0, 1), ("speed", 0.1, 4)):
        if isinstance(bg.get(k), (int, float)) and not isinstance(bg.get(k), bool):
            out[k] = max(lo, min(hi, float(bg[k])))
    return out


def check(new) -> dict:
    """A clean copy of a layout from the editor (or a saved preset), or ValueError saying what is wrong."""
    if not isinstance(new, dict) or not isinstance(new.get("widgets"), list):
        raise ValueError("layout with a widgets list expected")
    old = load_layout()
    cols = _int(new.get("columns", old.get("columns", 8)), 1, 24, "columns")
    rows = _int(new.get("rows", old.get("rows", 4)), 1, 24, "rows")
    types = set(widget_types())
    widgets = []
    for w in new["widgets"]:
        if not isinstance(w, dict) or w.get("type") not in types:
            raise ValueError(f"unknown widget: {w.get('type') if isinstance(w, dict) else w}")
        m = SIZE.match(str(w.get("size", "2x2")))
        if not m:
            raise ValueError(f"bad size for {w['type']}")
        cw, ch = int(m[1]), int(m[2])
        if "col" in w:
            _int(w["col"], 1, cols - cw + 1, f"{w['type']} column")
        if "row" in w:
            _int(w["row"], 1, rows - ch + 1, f"{w['type']} row")
        if "style" in w and w["style"] not in STYLES:
            raise ValueError(f"bad style for {w['type']}")
        widgets.append({k: w[k] for k in WIDGET_KEYS if k in w})
    return {"columns": cols, "rows": rows,
            "padding": str(new.get("padding", old.get("padding", "32px"))),
            "gap": str(new.get("gap", old.get("gap", "20px"))),
            "background": _background(new.get("background")),
            "tile_style": new.get("tile_style") if new.get("tile_style") in STYLES else "default",
            "widgets": widgets}


def post(body: dict) -> dict:
    try:
        layout = check(body.get("layout"))
    except ValueError as e:
        return {"error": str(e)}
    save_layout(layout)
    return {"ok": True}
