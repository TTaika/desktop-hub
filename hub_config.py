"""Settings shared by the server and the providers (config.json next to this file).

config.json: see config.example.json and assistant/config.py.
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DATA = ROOT / "data"          # runtime files: log, Discord token. Git-ignored.
DATA.mkdir(exist_ok=True)

# config.json and web/layout.json are your own (git-ignored); the first start makes them from the examples.
for mine, example in ((ROOT / "config.json", ROOT / "config.example.json"),
                      (WEB / "layout.json", WEB / "layout.default.json")):
    if not mine.exists():
        shutil.copyfile(example, mine)

CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
PORT = int(CONFIG.get("port", 8765))


def voice_assistant_dir():
    """The voice assistant project from config.json, or None. When set, the lights and calendar widgets use its tools
    and logins; otherwise the copies in assistant/ with the settings in config.json and the logins in data/."""
    va = CONFIG.get("voice_assistant_dir")
    return str(Path(va)) if va and (Path(va) / "assistant").is_dir() else None
