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
        lights.py         Airam/Tuya bulbs via assistant/tools/lights_tool.py
assistant/                the voice assistant's lights and calendar tools, with settings from config.json
tools/fetch_tuya_keys.py  gets the bulbs' local keys (Smart Life QR login) into data/devices.json
        discord.py        Discord via the local RPC socket (StreamKit's login): your call, the open chat, unread DMs
        calendar.py       Google Calendar via assistant/tools/calendar_tool.py
        presets.py        saved layouts, and the global hotkey + number that switches between them
        assistant.py      the voice assistant (Clanker) through its local API: conversation, typed questions, approvals
        agents.py         Claude Code agents on this PC, read from ~/.claude/jobs and ~/.claude/sessions
wallpaper/                Wallpaper Engine project: a loader that frames http://127.0.0.1:8765/
overlay/                  C# + Ultralight host that shows the page as a transparent overlay on monitor 2
```

## Setup

Needs Windows, Python 3.13 (`py -3.13 -m pip install -r requirements.txt`) and, for the overlay, the .NET 8 SDK.

1. `powershell -ExecutionPolicy Bypass -File install.ps1`. This copies the wallpaper into Wallpaper Engine,
   adds Startup shortcuts, starts the server, downloads Ultralight (first time only), and builds and starts the overlay.
   The first start makes `config.json` and `web/layout.json` from `config.example.json` and `web/layout.default.json`.
   Both are yours and stay out of git.
2. In Wallpaper Engine, select the second monitor, then go to **Installed → Desktop Hub**. If the wallpaper is missing, use
   **Open Wallpaper → Open from file** and pick `projects\myprojects\desktop_hub\index.html`.
3. The first time, Discord shows an **Authorize** window. The token is kept in `data/discord_token.json`.
   To log out, delete that file.
4. **Calendar** (optional): in Google Cloud Console, make a project, enable the Google Calendar API, create an
   OAuth client ID of type *Desktop app* and save its JSON as `data/google_credentials.json`. Then log in once with
   `py -3.13 -m assistant.tools.calendar_tool --login` in this folder. Set `"timezone"` in `config.json`
   (e.g. `"Europe/Helsinki"`). Google expires the login after 7 days while the OAuth app is in "testing" mode;
   set it to "In production" to keep it. Read-only alternative without Google Cloud: put the calendar's
   "secret address in iCal format" in `calendar.ics_url`.
5. **Lights** (optional, Airam / Tuya WiFi bulbs): `py -3.13 tools/fetch_tuya_keys.py <user code>` (the user code
   is in the Smart Life app under Me → Settings → Account and Security). It writes the bulbs' local keys to
   `data/devices.json`; the bulbs are then controlled on your network, without the cloud.

6. **Assistant** (optional): the assistant widget is a window onto the voice assistant (the separate
   `voice_assistant` project, "Clanker"), which runs on its own with push-to-talk. Start it as usual
   (`pyw -3.13 main.py --tray` there); it serves a local API on 127.0.0.1:8766 that the hub relays
   (`assistant_url` in `config.json`). See **The assistant widget** below.

The lights and calendar tools in `assistant/tools/` come from a separate voice assistant project. If you have it,
set `voice_assistant_dir` in `config.json` and the hub uses its copy, logins and bulbs instead.

Nothing personal is in the repository: your calendar and Discord data are read live and never saved, and
`data/` (Discord and Google logins, bulb keys, logs), `config.json` and your layout are git-ignored.

Open http://127.0.0.1:8765/ in a browser to work on widgets with DevTools. The wallpaper reloads itself
within a few seconds of any change under `web/`.

## Editing the layout

Open **http://127.0.0.1:8765/?edit** in a browser. For the true look, use full screen (F11) on the second monitor.
- Drag a tile to move it, and drag its bottom-right corner to resize it. Green means the spot is free, red means it's taken.
- Each tile has a style button (auto / default / glass / solid / bare) and a ✕ to remove it.
- **+ Widgets & background** opens a drawer with two tabs:
  - **Widgets:** drag a widget onto the grid, or click it to drop it in the first free space.
  - **Background:** pick one of your Wallpaper Engine videos, set how much to darken it, and choose the tile style for all widgets.
- **Save** (Ctrl+S) writes `layout.json`, and the wallpaper switches to it within about a second. **Done** saves and leaves edit mode.

## Presets and the hotkey

**Presets** in the editor's toolbar has ten slots, 1–9 and 0. **Save here** stores the layout you see (widgets,
background and tile style) in a slot. **Load** switches to it, and clicking a preset's name renames it.
**New preset from a blank layout** clears the widgets so you can start over (Discard brings them back), then
add widgets and save the result to a slot.

Press the hotkey with a slot's number, **Ctrl + Shift + 1** by default, to switch the hub to that preset from any
window. This includes a full-screen game, so you don't need to alt-tab. The number row and the numpad both work. To change the
hotkey, click it in the Presets tab, hold the keys you want (Ctrl and/or Alt, optionally Shift) and let go.
Ctrl + Alt is AltGr on Finnish and many other keyboards, so with it, typing @ or { would switch presets.

The server registers the keys with Windows (`providers/presets.py`), so they work while the hub's own windows are
in the background. Windows then gives that key combination to the hub instead of the focused window. Many games, League of
Legends among them, switch such hotkeys off while they have the focus. For those, the server also checks which
keys are held every 25 ms. It only reads the keyboard state and never touches the game, but the game also sees the
keypress, so pick a combination the game doesn't use. Only slots that have a preset are registered. If another program already has a combination, the slot says so. Presets are kept in `data/presets.json`.

A widget's name, description and allowed sizes come from `export const meta` in its `widget.js`.

## The assistant widget

The voice assistant is one service with several front ends: its push-to-talk key, its tray icon and this widget.
The widget shows the same conversation whichever way you used it:
- **Talk:** hold the push-to-talk key (F9) anywhere, games included. What it heard and what it answered appear in
  the tile, with a mic mark on spoken lines.
- **Type:** click the field at the bottom, type, press Enter. Answers to typed questions are shown, not spoken,
  unless you switch on "Read answers to typed questions aloud" in the tile's ⚙. While an approval is open, typing
  yes or no answers it. Esc leaves the field.
- **Approve:** anything that changes files, the calendar, the volume or a program shows an approval card with
  **Yes** / **No**. Saying yes or no with push-to-talk still works too. No answer within a minute means no.
- **Model:** **Local** (Ollama on the GTX 1660), **Cloud** (Claude through Anthropic's API, or any OpenAI-compatible
  service), or **Auto** (local, and the cloud when Ollama is down or fails). The choice is saved by the assistant and
  shared with its tray settings. Each answer is tagged with the model that wrote it. The Cloud button is dimmed until
  there is an API key. In cloud mode, what you say or type, and the results of the tools that ran (file names,
  calendar events), are sent to that service.
- **Models and API key:** in the editor, the tile's ⚙ opens **Assistant settings**. Below the tile's own options:
  - **Cloud model:** the service (Anthropic, or any OpenAI-compatible one with its address), your API key
    (**Save** / **Remove**), and the model: Opus 5.5, Sonnet 5.5 or Haiku 5.5, or any name the service offers.
    **Test the key** checks the key and the model without spending anything.
  - **Local model:** Ollama's address and the model name. **Test** loads it, as the first command would.

  These belong to the assistant: it saves them in its own `config/settings.json` and uses them from the next
  question, push-to-talk included. They aren't part of the layout's Save. The key never goes into `layout.json`,
  and the page only ever sees its last four characters.
- **Status** in the header: Ready, Listening, Transcribing, Thinking, Needs approval, Speaking. Click it while it
  speaks to stop it.

In the overlay, clicking the field gives the overlay the keyboard until you press Esc or click another window.
At all other times it never takes the focus. When the assistant isn't running, the tile says so and
reconnects by itself once it starts.

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
| calendar | `view` (`"day"`, `"week"`, `"month"`), `locale`. Day and week are time grids (busy and free hours at a glance). Month lists each day's events by name when the tile is at least 3 wide and 2 tall, up to the whole screen (with start times from 4 wide), and otherwise shows each day's busy hours as a strip; hover an event or a day for details. Any size from 2×1 up to the whole grid. Needs the calendar setup above |
| discord | `interval` (ms, default 400), `dms` (unread DMs along the bottom; click one to open it in Discord), `expire` (minutes before an unread DM is dropped, default 180) |
| assistant | `speak` (read answers to typed questions aloud, default `false`), `backendSwitch` (show Local / Cloud / Auto, default `true`). 2×2 up to 4×4 |
| discord_chat | `text` (`small`, `normal`, `large`), `avatars`. The server channel open in Discord, found from the Discord window title; DMs can't be shown. Pictures show as thumbnails (gifs as a still frame); click one to open it in the browser |
| agents | `hours` (how long finished agents stay listed, default 12), `terminals` (also list terminals you have open, default `true`), `interval` (ms, default 2000). 2×1 up to 4×4; at 2×1 one line per agent |

## The Claude agents widget

Every Claude Code agent on this PC, background jobs and open terminals alike, with its name, the folder it works in
(`~\aikansio\desktop_hub`) and its status. Agents that **need input** come first, with an orange glow and how long
they have been waiting, then the **working** ones, with a spinner and how long they have spent on the current task.
**Idle** ones come next, and last the finished ones: **Done**, **Failed** or **Stopped** (the process ended mid-task),
each with the time it finished and how long the task took. The header counts how many need you, are working and are idle.
Hover a row for what the agent is doing, or for its result.

The time counts from your latest message to that agent, not from when the session was opened. The widget only reads
Claude Code's own files (`~/.claude/jobs/*/state.json` and `timeline.jsonl`, `~/.claude/sessions/*.json`); it
never writes to them or talks to the agents.

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

The full recipe (meta and settings fields, CSS conventions, what breaks in the overlay, provider rules, and how to
test on a second port with headless Chrome) is in [CLAUDE.md](CLAUDE.md). In short:

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
