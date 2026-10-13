# Desktop Hub

Phone-style widget screen for the second monitor. It can run two ways:
- **Overlay** (`overlay/`): a transparent window above any Wallpaper Engine wallpaper, scenes included.
  See [overlay/README.md](overlay/README.md).
- **Web wallpaper** (`wallpaper/`): the page itself is the Wallpaper Engine wallpaper, with its own video background.

```
server.py (pythonw, ~60 MB RAM, 127.0.0.1:8765)
 ├─ web/                  the page: grid from layout.json, one folder per widget
 └─ providers/*.py        data sources -> /api/<name>
        system.py         CPU, RAM, GPUs (NVML), network, disk, top processes
        lights.py         Airam/Tuya bulbs via voice_assistant's lights_tool (same devices.json + scenes)
        discord.py        Discord via the local RPC socket (StreamKit's login): your call, the open chat, unread DMs
        calendar.py       Google Calendar via voice_assistant's calendar_tool (same login and calendars)
wallpaper/                Wallpaper Engine project: a loader that frames http://127.0.0.1:8765/
overlay/                  C# + Ultralight host that shows the page as a transparent overlay on monitor 2
```

## Setup

Needs Windows, Python 3.13 (`py -3.13 -m pip install psutil nvidia-ml-py websocket-client`) and, for the overlay,
the .NET 8 SDK.

1. `powershell -ExecutionPolicy Bypass -File install.ps1`. This copies the wallpaper into Wallpaper Engine,
   adds Startup shortcuts, starts the server, downloads Ultralight (first time only), and builds and starts the overlay.
   The first start makes `config.json` and `web/layout.json` from `config.example.json` and `web/layout.default.json`.
   Both are yours and stay out of git.
2. In Wallpaper Engine, select the second monitor, then go to **Installed → Desktop Hub**. If the wallpaper is missing, use
   **Open Wallpaper → Open from file** and pick `projects\myprojects\desktop_hub\index.html`.
3. The first time, Discord shows an **Authorize** window. The token is kept in `data/discord_token.json`.
   To log out, delete that file.
4. The **lights** and **calendar** widgets use a separate voice assistant project (its bulb setup and Google login).
   Without it, leave `voice_assistant_dir` empty in `config.json` and those widgets say so.

Nothing personal is in the repository: your calendar and Discord data are read live and never saved, and the
Discord token, logs, `config.json` and your layout are git-ignored.

Open http://127.0.0.1:8765/ in a browser to work on widgets with DevTools. The wallpaper reloads itself
within about 4 s of any change under `web/`.

## Editing the layout

Open **http://127.0.0.1:8765/?edit** in a browser. For the true look, use full screen (F11) on the second monitor.
- Drag a tile to move it, and drag its bottom-right corner to resize it. Green means the spot is free, red means it's taken.
- Each tile has a style button (auto / default / glass / solid / bare) and a ✕ to remove it.
- **+ Widgets & background** opens a drawer with two tabs:
  - **Widgets:** drag a widget onto the grid, or click it to drop it in the first free space.
  - **Background:** pick one of your Wallpaper Engine videos, set how much to darken it, and choose the tile style for all widgets.
- **Save** (Ctrl+S) writes `layout.json`, and the wallpaper picks up the change within a few seconds. **Done** saves and leaves edit mode.

A widget's name, description and allowed sizes come from `export const meta` in its `widget.js`.

## layout.json by hand

`web/layout.json` sets an 8×4 grid (`columns`, `rows`). Each widget entry looks like this:

```json
{ "type": "lights", "size": "2x2", "col": 7, "row": 1, "accent": "#ffd60a", "style": "glass", "options": { "name": "all" } }
```

Leave out `col` and `row` to let the widget fill the next free spot. `accent` colours that tile's title, rings
and highlights. `options` per widget:

| Widget | Options |
| --- | --- |
| clock | `locale` (`"en-GB"`, `"fi-FI"`, ...), `seconds` (`true` / `false`) |
| system | `gpu` (part of the GPU's name, e.g. `"5060"`), `interval` (ms, default 2000) |
| processes | `sort` (`"cpu"` / `"mem"`), `count` (rows, default 7), `interval` (ms, default 3000) |
| lights | `name` (bulb or room, default `"all"`), `rows` (`["temps", "colours", "scenes"]`), `interval` (ms, default 10000). Also 2×1, where it shows two rows |
| calendar | `view` (`"day"`, `"week"`, `"month"`), `locale`. Day and week are time grids (busy and free hours at a glance), month shows each day's busy hours as a strip; hover an event or a day for details. Reads Google Calendar through the voice assistant's login |
| discord | `interval` (ms, default 400), `dms` (unread DMs along the bottom; click one to open it in Discord), `sound` (play `sounds/dm.wav` for a DM while in a call), `expire` (minutes before an unread DM is dropped, default 180) |
| discord_chat | `text` (`small`, `normal`, `large`), `avatars`. The server channel open in Discord, found from the Discord window title; DMs can't be shown. Pictures show as thumbnails (gifs as a still frame); click one to open it in the browser |

## Colours, type and motion

The look comes from the tokens at the top of `web/hub.css`: Apple's dark-mode system colours (`--blue`, `--green`,
`--orange`, ...), the label greys (`--text`, `--muted`, `--faint`), the tile material (`--material`,
`--material-dense`), `--radius`, `--gap` and `--pad`. Change one there and every widget follows.

Values animate on springs (`spring()` in `lib.js`, Apple's response + damping model): new data glides in from
whatever is on screen, and an update arriving mid-animation never makes anything jump. The system chart plays
back about 3 s behind live and scrolls at a steady speed. Buttons react on press. With Windows' "Animation
effects" off (`prefers-reduced-motion`), values change without motion.

## Background and tile styles

```
py -3.13 tools/set_background.py              # list your Wallpaper Engine video wallpapers
py -3.13 tools/set_background.py 5 --dim 0.15 --style glass
py -3.13 tools/set_background.py C:/clips/loop.mp4
py -3.13 tools/set_background.py none
```

This writes `"background": {"src": ..., "dim": 0.15, "fit": "cover", "position": "center", "speed": 1}` to
`layout.json`. A file given by an absolute path is streamed from where it is, so it's never copied. A relative path means a file in `web/`.
Videos play muted on a loop and pause along with the wallpaper.

Tile styles go in `"tile_style"` for every widget, or `"style"` on one widget:
- `default`: a translucent tile.
- `glass`: frosted, blurs the video behind the tile. It's the most readable over a video, but costs some GPU for the
  tile area. In the overlay, which can't blur, it turns into a denser tint instead.
- `solid`: dark and almost opaque. Readable, with no extra cost.
- `bare`: no box, just shadowed text on the wallpaper. Suits the clock.

## Adding a widget

1. Create `web/widgets/<type>/widget.js`:

   ```js
   import { h, header } from "../../lib.js";
   export const css = true;                      // also load widget.css from this folder
   export const meta = { name: "My widget", description: "What it shows",
                         defaultSize: "2x2", minSize: "2x1", maxSize: "4x4" };   // for the editor
   export function mount(el, { options, api, size }) {
     const value = h("div", { class: "big" });
     el.append(header("My widget", "chip"), value);
     api.poll("mydata", 5000, d => { value.textContent = d ? d.text : "offline"; });
   }
   ```

   `lib.js` provides `h()` for elements, `api.get / post / poll`, plus `spring()`, `ring()`, `sparkline()`, `icon()`,
   `fmtBytes()` and `fmtDuration()`. `poll` skips its updates while Wallpaper Engine has the wallpaper paused.
   The overlay's engine is older than Chrome: read the list at the top of `web/compat.js`, and check a new widget
   with the overlay's `--snapshot`.
2. If the widget needs data from Windows, add `providers/mydata.py` with `get(params) -> dict`, and
   optionally `post(body) -> dict` and `start()`. Then restart the server: stop `pythonw.exe` (server.py) and
   run `install.ps1`, or log out and back in.
3. Add it in the editor's widget bank. It appears there by itself.

A widget that only needs public web data (weather, for example) can skip step 2 and `fetch` that data directly.

## Notes

- The server only accepts requests addressed to 127.0.0.1 or localhost. A POST must be JSON and come from the hub's own origin, so
  other web pages can't switch your lights.
- `data/hub.log` holds the server log.
- Clicks reach the wallpaper only where the desktop is visible on that monitor (a Wallpaper Engine limit).
