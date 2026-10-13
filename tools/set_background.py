"""Choose the hub's background from the command line (the editor at http://127.0.0.1:8765/?edit does the same):
one of your Wallpaper Engine video wallpapers, any image/video file, or none.

  py -3.13 tools/set_background.py                  list the video wallpapers you have installed
  py -3.13 tools/set_background.py 3                use number 3 from that list (or its workshop id)
  py -3.13 tools/set_background.py C:/clips/x.mp4   any image or video file
  py -3.13 tools/set_background.py none             back to the plain gradient
  options: --dim 0.3 (darken 0-1)   --style glass|solid|bare|default (tile style for every widget)

The video is streamed from where it is, not copied. The wallpaper reloads itself after the change.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers._shared import MEDIA, load_layout, save_layout, video_wallpapers  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("choice", nargs="?", help="list number, workshop id, file path, or 'none'")
    ap.add_argument("--dim", type=float, help="darken the background, 0-1")
    ap.add_argument("--style", choices=["default", "glass", "solid", "bare"], help="tile style for every widget")
    a = ap.parse_args()

    vids = video_wallpapers()
    if not a.choice:
        for i, v in enumerate(vids, 1):
            print(f"{i:3}  {v['title']}  ({v['id']}, {v['mb']} MB)")
        print("\nPick one: py -3.13 tools/set_background.py <number>")
        return

    layout = load_layout()
    bg = layout.get("background") if isinstance(layout.get("background"), dict) else {}
    if a.choice.lower() == "none":
        layout["background"] = None
    else:
        if a.choice.isdigit() and 1 <= int(a.choice) <= len(vids):
            src = Path(vids[int(a.choice) - 1]["src"])
        elif any(v["id"] == a.choice for v in vids):
            src = Path(next(v["src"] for v in vids if v["id"] == a.choice))
        else:
            src = Path(a.choice).expanduser().resolve()
            if not src.is_file() or src.suffix.lower() not in MEDIA:
                sys.exit(f"Not an image or video file: {src}")
        layout["background"] = {**bg, "src": src.as_posix()}
        print(f"Background: {src}")
    if a.dim is not None and isinstance(layout["background"], dict):
        layout["background"]["dim"] = max(0.0, min(1.0, a.dim))
    if a.style:
        layout["tile_style"] = a.style
    save_layout(layout)


if __name__ == "__main__":
    main()
