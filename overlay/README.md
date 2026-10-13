# Overlay (Ultralight demo)

Shows the hub on monitor 2 as a transparent window *above* the Wallpaper Engine wallpaper, so it works over
scenes too. It's a small C# host around [Ultralight](https://ultralig.ht) 1.3, a lightweight HTML engine that
runs in this one process.

- The page is rendered on the CPU into a per-pixel-alpha layered window. Fully transparent pixels let clicks
  through to the desktop, so only the tiles take the mouse.
- The window is owned by Progman (the desktop), which keeps it above the wallpaper and below normal windows.
- A user stylesheet in `Program.cs` removes the page's own background. Glass tiles turn into a denser tint by
  themselves (`hub.css` checks for `backdrop-filter`, which Ultralight lacks).
- It ticks at up to 60 Hz while something moves and at 20 Hz when the page is still, and sends Windows only the
  changed rectangle.
- Requests to the hub's server go through the host (`HostFetch.cs`): Ultralight 1.3 leaks about 150 KB of native
  memory on every `fetch`, with or without keep-alive. `web/compat.js` routes same-origin `fetch` calls to
  `window.__hostFetch` when the overlay provides it.
- Memory levels off at about 100–140 MB. Three things were needed, each found by measuring (`--offscreen 1` runs a
  copy that renders without showing, so test pages can run side by side):
  1. Requests through the host (above): Ultralight leaks ~150 KB per `fetch`.
  2. `JSC_useConcurrentGC=false`, `JSC_numberOfGCMarkers=1`, set before the engine starts: JavaScriptCore's
     parallel GC kept starting helper threads and letting them exit, and each new thread left allocator memory
     behind. Collecting on the main thread keeps the thread count fixed; for this page it costs nothing visible.
  3. A JS collection and `ulPurgeMemory` every 10 s: Ultralight's paint caches only shrink when asked, so any page
     that animates grew by ~0.2 MB/s without it.
- Startup: `install.ps1` builds it and adds "Desktop Hub Overlay.lnk" to the Startup folder. Only one copy runs
  at a time, and it keeps retrying the page until the server is up. It has no window of its own: logs go to
  `overlay.log` next to the exe. To stop it, end `hub_overlay.exe` in Task Manager.

## Run

```
dotnet build -c Release
bin\Release\net8.0-windows\hub_overlay.exe [options]
```

| Option | Default | |
| --- | --- | --- |
| `--monitor N` | first non-primary | which monitor to cover |
| `--fps N` | 60 | tick rate while animating |
| `--url URL` | `http://127.0.0.1:8765/` | page to show |
| `--gc S` | 10 | seconds between JavaScript collections, 0 = off |
| `--purge S` | 10 | seconds between `ulPurgeMemory` calls (paint caches), 0 = off |
| `--threads N` | Ultralight's choice | paint threads |
| `--offscreen 1` | off | render without showing a window, for measurements (not limited to one copy) |
| `--snapshot F` / `--snapshot-at S` | off / 8 | save the frame as raw BGRA after S seconds |

The server (`server.py`) must be running. Every 10 s it logs memory and frame timing (JS and layout, paint, present,
size of the changed area) to the console and to `overlay.log` next to the exe, along with any page errors.
`--snapshot` lets you check the rendering when windows cover the monitor.

## Engine limits

Ultralight's WebKit dates from about 2020. `web/compat.js` fills in `replaceChildren` and flex `gap`, and lists
what widgets should avoid: `?.` and `??` (a syntax error that stops the whole module), the `inset` shorthand,
`var()` inside `box-shadow` and inset box-shadows (drawn opaque white), `stroke-opacity`, top-level `await` in
modules, `backdrop-filter` and `<video>`.

## Files

- `ultralight/`: the SDK runtime (bin, resources, license), downloaded by `install.ps1` and not in git. It's free for
  non-commercial use, see `ultralight/license`.
