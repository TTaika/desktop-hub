# Desktop Hub: notes for Claude

A widget screen for the second monitor: `server.py` (Python 3.13, stdlib HTTP on 127.0.0.1:8765) serves `web/` and
`/api/<provider>`. The page runs in Chrome/Edge, Wallpaper Engine, and the overlay (Ultralight 1.3, WebKit from ~2020).
README.md is the user-facing manual and STATUS.md the project log. Everything below is here so you don't have to
re-read the codebase to add a widget.

## Adding a widget: the whole recipe

A widget is one folder plus, if it needs local data, one provider. Both are found automatically: no registry, no
edits to `server.py`, `hub.js` or `edit.js`.

```
web/widgets/<type>/widget.js     required. <type> is the folder name and the "type" in layout.json
web/widgets/<type>/widget.css    optional, loaded when widget.js exports `css = true`
providers/<name>.py              optional, serves GET/POST /api/<name>; files starting with "_" are skipped
```

### widget.js

```js
// One or two lines on what the tile shows. options: { ... } (also set from the editor, see meta.settings)
import { h, header, withDefaults } from "../../lib.js";

export const css = true;
export const meta = {
  name: "My widget", description: "What it shows",           // the editor's widget bank
  defaultSize: "2x2", minSize: "2x1", maxSize: "4x4",         // "<cols>x<rows>"; no maxSize = up to the whole grid
  settings: [                                                 // optional: the tile's ⚙ in the editor
    { key: "hours", label: "Keep for", type: "range", min: 0, max: 48, step: 1, unit: " h", default: 12 },
    { key: "compact", label: "Compact rows", type: "bool", default: false },
    { key: "view", label: "Show", type: "select", choices: [["day", "Today"], ["week", "Week"]], default: "week" },
  ],
};

export function mount(el, { options, api, size }) {          // el = the tile <section class="tile w-<type>">
  const o = withDefaults(meta, options);                      // options with meta.settings defaults filled in
  const body = h("div", { class: "my-body" });
  el.append(header("My widget", "chip", rightSideElement), body);
  api.poll("mydata", o.interval || 2000, d => {               // d === null when the request failed
    if (!d) { body.replaceChildren(h("div", { class: "tile-empty" }, "Hub backend is offline")); return; }
    // ...update the DOM...
  }, { hours: o.hours });                                     // query params
}
```

- `size` is `{ w, h }` in grid cells. Use it for compact layouts, e.g. `el.classList.toggle("x-compact", size.h < 2)`.
- `api.poll` is scoped to the tile: hub.js stops it when the tile is removed (editor, preset switch). It skips ticks
  while the page is hidden. Your own `setInterval`s are not stopped for you: clear them when `!el.isConnected`.
- Settings types: `bool`, `select` (choices `[[value, label]]`), `multi` (several choices, value is an array),
  `range` (min, max, step, unit), `colors` (keys, palette), anything else is a text field (placeholder). They are
  saved as the widget's `options` in layout.json (only non-default values) and the tile re-mounts on every change.
  `meta.panel({ api, h }) -> element` adds a custom block under them for settings that live outside layout.json
  (see widgets/assistant).
- `lib.js`: `h(tag, attrs, ...children)` (`on*` attrs are listeners, `style` can be an object, SVG tags supported),
  `header(title, iconName, rightEl)`, `icon(name, size)`, `withDefaults`, `spring()`, `ring()`, `sparkline()`,
  `fmtBytes()`, `fmtDuration()`. Icons are the `ICONS` map in lib.js (24x24 stroke paths): add one there if needed.
- Update in place rather than rebuilding: keep rows in a `Map` by id and reorder with `insertBefore`
  (see widgets/agents, widgets/discord). Rebuilding every poll restarts animations and flickers.

### widget.css

- Scope every rule to your widget: `.w-<type> ...` or a short class prefix of your own (`ag-`, `dc-`, `cal-`).
- Use the tokens from `web/hub.css`: `--text --muted --faint`, `--fill --fill-strong --track`, `--accent` (per-tile
  colour from layout.json), `--blue --green --orange --red --purple --teal --yellow --indigo --pink`.
- Shared classes: `.tile-head` (from `header()`), `.tile-empty` / `.tile-error` (centred message), `.num` (tabular
  digits), `.t-display .t-title .t-caption`, `.press` (button press feedback).
- A scrolling list: `flex: 1; min-height: 0; overflow-y: auto` and `> * { flex: none; }`, otherwise the overlay
  squeezes rows instead of scrolling. Hide the scrollbar with `::-webkit-scrollbar { width: 0; height: 0; }`.
- Add a `@media (prefers-reduced-motion: reduce)` block for any animation.

### The overlay's engine (Ultralight): what breaks there

Listed at the top of `web/compat.js`. In short, never use:
- `?.` or `??` (a syntax error: the whole widget fails to load), or top-level `await` in a module.
- the `inset` shorthand, `var()` inside `box-shadow`, inset box-shadows (drawn opaque white), `stroke-opacity`
  (use `opacity`).
- `replaceChildren` is polyfilled. Don't pass it `null`, which is written as the text "null"; `.filter(Boolean)` first.

### providers/<name>.py

```python
"""What it serves. GET /api/<name>?x=1 -> {...}"""

def get(params: dict) -> dict: ...      # params: the query string as str -> str
def post(body: dict) -> dict: ...       # optional, JSON body (the server only accepts it from the hub's own page)
def start(): ...                        # optional, called once at startup in the server's loader thread
```

- An exception becomes HTTP 500 `{"error": ...}` and is logged to `data/hub.log`.
- Requests run on separate threads: guard shared caches with a `threading.Lock`, and cache anything slow for about a
  second (see `_cached` in providers/system.py), since several tiles may poll the same provider.
- Available: the stdlib, `psutil`, and whatever is in requirements.txt. Settings come from
  `hub_config.CONFIG` (config.json, git-ignored; document new keys in config.example.json), and runtime files go in
  `hub_config.DATA` (`data/`, git-ignored).
- The running server only loads providers at startup: restart it after adding one (stop the `pythonw.exe` running
  server.py, then `pyw -3.13 server.py`). Changes under `web/` reload the page by themselves within a few seconds.

### Then document it

- README.md: add a row to the options table under "layout.json by hand", and a line in the diagram at the top
  if there's a provider.
- STATUS.md: add it to "Done and working".

## Testing without touching the running hub

The user's hub is always running on :8765 (and registers global hotkeys in providers/presets.py), so don't start a
second full server. Serve just your provider on another port from a small script:

```python
import sys; sys.path.insert(0, r"<repo or worktree>")
from http.server import ThreadingHTTPServer
import server
from providers import mydata
server.PROVIDERS["mydata"] = mydata
server.ALLOWED_ORIGINS.add("http://127.0.0.1:8798")   # module imports send Origin; without this every .js is a 403
ThreadingHTTPServer(("127.0.0.1", 8798), server.Handler).serve_forever()
```

In a worktree, `config.json` and `web/layout.json` don't exist (git-ignored). Write a test `web/layout.json` with your
widget at a few sizes (`{"columns": 8, "rows": 4, "widgets": [{"type": "mine", "size": "2x2", "col": 1, "row": 1}]}`);
`hub_config` creates `config.json` from the example on first import. Screenshot with headless Chrome:

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu --hide-scrollbars
  --window-size=1920,1080 --virtual-time-budget=6000 --user-data-dir=<temp dir> --screenshot=<file.png> http://127.0.0.1:8798/
```

A blank page with only the background means a widget module failed to load (a 403 or a syntax error). Check with
`node --check web/widgets/<type>/widget.js`. To exercise states the live data doesn't have right now, wrap the
provider's `get` in the test script and append fake entries.
