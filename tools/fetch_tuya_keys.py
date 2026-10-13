"""Fetch Tuya local keys via a Smart Life QR login and write data/devices.json (the lights widget's bulbs).

No iot.tuya.com developer project needed: this is the same QR login Home Assistant's Tuya
integration uses (tuya-device-sharing-sdk), and its device list includes each device's local key.

    py -3.13 tools/fetch_tuya_keys.py <user code>

User code: Smart Life app -> Me -> Settings (gear) -> Account and Security -> User Code.
A QR code opens; scan it in Smart Life (Me -> scan icon, top right) and confirm.
The cloud only supplies id/name/key; IP and protocol version come from a LAN scan.
Keys only: the login token is not saved.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import qrcode
import tinytuya
from tuya_sharing import LoginControl, Manager

CLIENT_ID = "HA_3y9q4ak7g4ephrvke"   # Home Assistant's client id for this login flow
SCHEMA = "haauthorize"
OUT = Path(__file__).resolve().parent.parent / "data" / "devices.json"
LOGIN_TIMEOUT = 180   # seconds
# Tuya light categories: bulb, strip, ceiling, ambient, string lights. Others (plugs, batteries) are left out.
LIGHT_CATEGORIES = {"dj", "dd", "xdd", "fwd", "dc"}


def login(user_code: str) -> dict:
    lc = LoginControl()
    resp = lc.qr_code(CLIENT_ID, SCHEMA, user_code)
    if not resp.get("success"):
        sys.exit(f"QR request refused: {resp.get('msg') or resp}. Check the user code.")
    token = resp["result"]["qrcode"]

    png = Path(tempfile.gettempdir()) / "tuya_login_qr.png"
    qrcode.make(f"tuyaSmart--qrLogin?token={token}").save(png)
    os.startfile(png)
    print(f"QR code opened ({png}). Scan it in Smart Life: Me -> scan icon, then confirm.")

    deadline = time.time() + LOGIN_TIMEOUT
    while time.time() < deadline:
        time.sleep(2)
        ok, info = lc.login_result(token, CLIENT_ID, user_code)
        if ok:
            print(f"Logged in as {info.get('username', '?')}.")
            png.unlink(missing_ok=True)
            return info
    sys.exit("QR code not scanned in time. Run again.")


def cloud_devices(user_code: str, info: dict) -> list:
    m = Manager(CLIENT_ID, user_code, info["terminal_id"], info["endpoint"], info)
    m.update_device_cache()
    return list(m.device_map.values())


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    user_code = sys.argv[1].strip()

    devices = cloud_devices(user_code, login(user_code))
    if not devices:
        sys.exit("Logged in, but the account has no devices. Is the bulb added in Smart Life?")
    print(f"Cloud: {len(devices)} device(s): " + ", ".join(d.name for d in devices))

    print("Scanning the LAN for IP and protocol version (~20 s)...")
    found = tinytuya.deviceScan(verbose=False, poll=False, byID=True)

    out = []
    for d in devices:
        if d.category not in LIGHT_CATEGORIES:
            print(f"  {d.name}: not a light ({d.category}), skipped")
            continue
        if not d.local_key:
            print(f"  {d.name}: no local key (hub sub-device or cloud-only), skipped")
            continue
        lan = found.get(d.id, {})
        out.append({"name": d.name, "id": d.id, "key": d.local_key,
                    "ip": lan.get("ip", ""), "version": lan.get("version", ""),
                    "product_name": d.product_name, "category": d.category})
        where = f"{lan['ip']} (v{lan.get('version')})" if lan else "not seen on LAN - powered off?"
        print(f"  {d.name}: {where}")

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(out)} device(s) to {OUT}")


if __name__ == "__main__":
    main()
