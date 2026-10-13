"""Task-manager numbers: CPU, RAM, GPUs, network, disk, and the busiest processes.

GET /api/system                   -> summary (cached 1 s)
GET /api/system?view=processes    -> top processes by CPU and by memory, grouped by exe name (cached 2.5 s)
Nothing is measured between requests, so a paused wallpaper costs nothing.
"""
import threading
import time

import psutil

try:
    import pynvml
    pynvml.nvmlInit()
    _GPUS = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(pynvml.nvmlDeviceGetCount())]
except Exception:
    pynvml, _GPUS = None, []

_lock = threading.Lock()
_cache = {}
_last = {}                      # previous counters for the per-second rates and CPU load


def _cpu_name() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            return " ".join(winreg.QueryValueEx(k, "ProcessorNameString")[0].split())
    except OSError:
        return "CPU"


CPU_NAME = _cpu_name()


def _cached(key: str, ttl: float, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        value = fn()
        _cache[key] = (time.monotonic(), value)
        return value


def _rate(name: str, value: int, now: float) -> float:
    prev = _last.get(name)
    _last[name] = (value, now)
    if not prev or now <= prev[1]:
        return 0.0
    return max(0.0, (value - prev[0]) / (now - prev[1]))


def _cpu_percent() -> float:
    """Load since the previous reading. psutil.cpu_percent(None) remembers its last reading per thread,
    and every request runs on a new thread, so it would always answer 0."""
    t = psutil.cpu_times()
    busy, total = sum(t) - t.idle, sum(t)
    prev = _last.get("cpu")
    _last["cpu"] = (busy, total)
    if not prev or total <= prev[1]:
        return 0.0
    return round(min(100.0, max(0.0, (busy - prev[0]) / (total - prev[1]) * 100)), 1)


_cpu_percent()                  # the first reading has nothing to compare with; take it now


def _gpu(h) -> dict:
    out = {}
    for key, fn in (("name", lambda: pynvml.nvmlDeviceGetName(h)),
                    ("util", lambda: pynvml.nvmlDeviceGetUtilizationRates(h).gpu),
                    ("temp", lambda: pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)),
                    ("power", lambda: round(pynvml.nvmlDeviceGetPowerUsage(h) / 1000)),
                    ("mem", lambda: pynvml.nvmlDeviceGetMemoryInfo(h))):
        try:
            out[key] = fn()
        except Exception:
            pass
    if "mem" in out:
        m = out.pop("mem")
        out["mem_used"], out["mem_total"] = m.used, m.total
    if isinstance(out.get("name"), bytes):
        out["name"] = out["name"].decode()
    out["name"] = str(out.get("name", "GPU")).replace("NVIDIA GeForce ", "")
    return out


def _summary() -> dict:
    now = time.monotonic()
    vm = psutil.virtual_memory()
    net = psutil.net_io_counters()
    disk = psutil.disk_io_counters()
    return {
        "cpu": {"name": CPU_NAME, "percent": _cpu_percent(), "cores": psutil.cpu_count()},
        "ram": {"used": vm.total - vm.available, "total": vm.total, "percent": vm.percent},
        "gpus": [_gpu(h) for h in _GPUS],
        "net": {"down": _rate("rx", net.bytes_recv, now), "up": _rate("tx", net.bytes_sent, now)},
        "disk": {"read": _rate("dr", disk.read_bytes, now) if disk else 0,
                 "write": _rate("dw", disk.write_bytes, now) if disk else 0,
                 "c_percent": psutil.disk_usage("C:\\").percent},
        "uptime": int(time.time() - psutil.boot_time()),
    }


def _processes() -> dict:
    rows = {}
    ncpu = psutil.cpu_count() or 1
    for p in psutil.process_iter(["name", "memory_info"]):     # psutil keeps these objects, so cpu_percent works
        if p.pid == 0:                                         # "System Idle Process"
            continue
        try:
            cpu = p.cpu_percent(None) / ncpu
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        name = (p.info.get("name") or "").removesuffix(".exe")
        if not name:                                           # protected process we may not read
            continue
        mi = p.info.get("memory_info")
        r = rows.setdefault(name, {"name": name, "cpu": 0.0, "mem": 0, "count": 0})
        r["cpu"] += cpu
        r["mem"] += mi.rss if mi else 0
        r["count"] += 1
    items = list(rows.values())
    for r in items:
        r["cpu"] = round(r["cpu"], 1)
    return {"by_cpu": sorted(items, key=lambda r: -r["cpu"])[:8],
            "by_mem": sorted(items, key=lambda r: -r["mem"])[:8]}


def get(params: dict) -> dict:
    if params.get("view") == "processes":
        return _cached("processes", 2.5, _processes)
    return _cached("summary", 1.0, _summary)
