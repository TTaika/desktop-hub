"""Opens the layout editor in the default browser, for the hub's settings button on the overlay and in
Wallpaper Engine, which can't open a browser tab themselves.

POST /api/editor {} -> {"ok": true}
"""
import os

from hub_config import PORT


def post(body: dict) -> dict:
    os.startfile(f"http://127.0.0.1:{PORT}/?edit")
    return {"ok": True}
