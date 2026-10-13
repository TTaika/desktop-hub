# Status (2026-10-12)

## Done and working
- Backend `server.py` (pythonw, starts from the Startup shortcut, ~60 MB RAM) with these providers:
  - system: CPU, RAM, GPUs, network, disk, processes
  - lights: through voice_assistant's lights_tool
  - discord: StreamKit RPC login, already authorized; the token is in `data/`
  - layout: the editor's backend
- Widgets: clock, system, processes, discord (call + unread DMs), discord_chat, lights, calendar. Each one has `meta` for the editor.
- **Apple-style redesign** (following the `apple-design` skill, installed in `~/.claude/skills/apple-design`):
  Apple's dark system colours and label greys as tokens in `hub.css`, translucent tile material with a lit top
  edge, Segoe UI Variable with tracking set per size, springs (`spring()` in `lib.js`) for every value change,
  press feedback on pointer-down, a segmented control in Processes, a Control Center style Lights tile, and
  reduced-motion support.
- **System widget settings** in the editor (⚙ on the tile): gauges, chart lines, chart history (default 20 s),
  update rate (default 1 s), footer row, GPU and colours. Settings are a general mechanism (`meta.settings`), so
  other widgets can declare their own. The chart plays back ~1.5 updates behind live and scrolls smoothly.
- Video backgrounds, streamed from Wallpaper Engine's workshop folder, and tile styles (default / glass / solid / bare).
- Editor at http://127.0.0.1:8765/?edit, tested in headless Chrome: move, resize, widget bank, background picker,
  widget settings, save.
- **Overlay (`overlay/`)**: C# + Ultralight 1.3, a transparent window on monitor 2 above any Wallpaper Engine
  wallpaper, scenes included. In the Startup folder since 2026-10-12. Memory levels off at ~100–140 MB after
  three fixes (see overlay/README.md). `web/compat.js` covers what its engine lacks.

## Open problems
- **Calendar login** expires after 7 days while the Google app is in "testing" mode. Log in again: in voice_assistant run
  `py -3.13 -m assistant.tools.calendar_tool --login`, or set the app to "In production" in Google Cloud Console.
  For it to stop expiring, publish the OAuth app ("In production") in Google Cloud Console.
- Not yet tried by hand: clicking through to desktop icons, Win+D, and the lights controls in the overlay.
- **The Wallpaper Engine web wallpaper shows flat grey (#808080) on monitor 2.** WE's browser
  (webwallpaper64) never connects to 127.0.0.1:8765, and even the loader page's own dark background doesn't render.
  Cause unknown. To debug: WE Settings → General → CEF devtools port = 9339, then inspect the page over CDP.

## Next
1. Discord: the unread-DM row is untested with a real DM notification (the payload follows Discord's RPC docs).
   It needs Discord's desktop notifications on, and only sees DMs that arrive while the hub runs.
2. Editor Background tab: a "Wallpaper Engine (whatever it shows)" option that makes the page transparent.
3. Optional: fix the pure-WE web wallpaper path once the devtools port is on.

## Known harmless
- The `ConnectionAbortedError` tracebacks in data/hub.log come from browsers closing connections mid-reply. These should
  be logged quietly instead (`_call` / `_send`).
