// The voice assistant (Clanker): the conversation, whether spoken (push-to-talk) or typed here, its approvals
// with Yes / No buttons, and which model answers (local, cloud, or auto). A route answer comes with a small map
// (car, walk, bike) or the public transport options as blocks, like reittiopas. ↺ makes the assistant forget the
// earlier messages (it keeps the last few as short-term memory).
// The assistant is its own service (voice_assistant, providers/assistant.py relays); this tile only shows and asks.
// options (also set from the editor, see meta.settings): { speak: false, backendSwitch: true }
import { h, header, icon, withDefaults } from "../../lib.js";

export const css = true;
export const meta = {
  name: "Assistant", description: "Talk or type to the voice assistant, approve its actions, pick local or cloud",
  defaultSize: "2x3", minSize: "2x2", maxSize: "4x4",
  settings: [
    { key: "speak", label: "Read answers to typed questions aloud", type: "bool", default: false },
    { key: "backendSwitch", label: "Show the model switch (Local / Cloud / Auto)", type: "bool", default: true },
  ],
  panel: settingsPanel,
};

// The models, in the editor's Assistant settings. These belong to the assistant, which saves them in its own
// config/settings.json and applies them at once; the API key never goes into layout.json or back to the page
// (only its last four characters).
const CLAUDE = [["claude-opus-5-5", "Opus 5.5", "most capable"], ["claude-sonnet-5-5", "Sonnet 5.5", "balanced"],
  ["claude-haiku-5-5", "Haiku 5.5", "fastest, cheapest"]];
// How fast you walk to the stop and between lines, in m/s: reittiopas's own choices
const WALK_SPEEDS = [[0.69, "Slow", "2.5 km/h"], [0.97, "Calm", "3.5 km/h"], [1.2, "Average", "4.3 km/h"],
  [1.67, "Brisk", "6 km/h"], [2.22, "Fast", "8 km/h"]];

function settingsPanel({ api, h }) {
  const root = h("div", { class: "asp" });
  let s = null;

  const save = async changes => {
    note.textContent = "Saving...";
    note.className = "asp-note";
    const r = await api.post("assistant", { settings: changes }).catch(() => ({ error: "The hub's server is offline" }));
    if (r.error) { note.textContent = r.error; note.className = "asp-note bad"; return false; }
    s = r;
    draw();
    note.textContent = "Saved. The assistant uses it from the next question.";
    note.className = "asp-note good";
    return true;
  };
  const test = async (target, out, btn) => {
    btn.disabled = true;
    out.textContent = target === "local" ? "Loading the model..." : "Checking...";
    out.className = "asp-note";
    const r = await api.post("assistant", { test: target }).catch(() => ({ ok: false, message: "The hub's server is offline" }));
    out.textContent = (r.ok ? "✓ " : "") + (r.message || r.error);
    out.className = `asp-note ${r.ok ? "good" : "bad"}`;
    btn.disabled = false;
  };
  const fillModels = async (target, list) => {
    const r = await api.get("assistant", { models: target }).catch(() => ({}));
    list.replaceChildren(...(r.models || []).map(m => h("option", { value: m })));
  };
  const field = (label, ...control) => h("div", { class: "st-field" }, h("div", { class: "ed-label" }, label), ...control);
  const note = h("div", { class: "asp-note" });

  function draw() {
    const c = s.cloud, l = s.local;
    // cloud: provider, key, address (OpenAI-compatible only), model
    const provider = h("div", { class: "segs" }, [["anthropic", "Anthropic (Claude)"], ["openai", "OpenAI-compatible"]]
      .map(([v, label]) => h("button", { class: `seg${c.provider === v ? " active" : ""}`,
        onclick: () => { if (c.provider !== v) save({ cloud_provider: v, cloud_model: "" }); } }, label)));
    const key = h("input", { type: "password", class: "st-text", autocomplete: "off", spellcheck: "false",
      placeholder: c.key_set ? `Saved key ${c.key_hint}. Paste a new one to replace it` : "Paste your API key" });
    const keyRow = h("div", { class: "asp-row" }, key,
      h("button", { class: "asp-btn primary", onclick: async () => {
        if (key.value.trim() && await save({ cloud_api_key: key.value.trim() })) key.value = "";
      } }, "Save"),
      c.key_set ? h("button", { class: "asp-btn", title: "Forget the key", onclick: () => save({ cloud_api_key: "" }) }, "Remove") : null);
    const url = h("input", { type: "text", class: "st-text", value: c.url, spellcheck: "false",
      placeholder: "https://api.openai.com/v1", onchange: () => save({ cloud_url: url.value.trim() }) });
    const cloudList = h("datalist", { id: "asp-cloud-models" });
    // with an OpenAI-compatible service the default (a Claude model) means nothing: ask for the service's own name
    const shown = c.provider === "openai" && /^claude-/.test(c.model) ? "" : c.model;
    const model = h("input", { type: "text", class: "st-text", value: shown, list: "asp-cloud-models", spellcheck: "false",
      placeholder: "The service's model name",
      onchange: () => { if (model.value.trim()) save({ cloud_model: model.value.trim() }); } });
    const chips = c.provider === "anthropic" ? h("div", { class: "st-chips" }, CLAUDE.map(([id, name, what]) =>
      h("button", { class: `st-chip${c.model === id ? " on" : ""}`, title: what, onclick: () => save({ cloud_model: id }) },
        name, h("span", { class: "asp-what" }, what)))) : null;
    const cloudOut = h("div", { class: "asp-note" });
    const cloudTest = h("button", { class: "asp-btn", onclick: () => test("cloud", cloudOut, cloudTest) }, "Test the key");
    if (c.key_set || c.provider === "openai") fillModels("cloud", cloudList);

    // local: Ollama's address and model
    const lurl = h("input", { type: "text", class: "st-text", value: l.url, spellcheck: "false",
      placeholder: "http://127.0.0.1:11434", onchange: () => save({ ollama_url: lurl.value.trim() }) });
    const localList = h("datalist", { id: "asp-local-models" });
    const lmodel = h("input", { type: "text", class: "st-text", value: l.model, list: "asp-local-models", spellcheck: "false",
      onchange: () => { if (lmodel.value.trim()) save({ local_model: lmodel.value.trim() }); } });
    const localOut = h("div", { class: "asp-note" });
    const localTest = h("button", { class: "asp-btn", onclick: () => test("local", localOut, localTest) }, "Test");
    fillModels("local", localList);

    // public transport: walking speed (older assistants don't send it)
    const t = s.travel;
    const speeds = t ? h("div", { class: "st-chips" }, WALK_SPEEDS.map(([v, name, kmh]) =>
      h("button", { class: `st-chip${Math.abs(t.walk_speed - v) < 0.01 ? " on" : ""}`, title: `${v} m/s`,
        onclick: () => save({ hsl_walk_speed: v }) }, name, h("span", { class: "asp-what" }, kmh)))) : null;
    const custom = t && !WALK_SPEEDS.some(([v]) => Math.abs(t.walk_speed - v) < 0.01)
      ? h("div", { class: "asp-note" }, `Now ${t.walk_speed} m/s (${(t.walk_speed * 3.6).toFixed(1)} km/h), set in the assistant's config.`) : null;

    root.replaceChildren(...[
      h("div", { class: "asp-head" }, "Cloud model"),
      field("Service", provider),
      field("API key", keyRow),
      c.provider === "openai" ? field("Address", url) : null,
      field("Model", chips, model, cloudList),
      h("div", { class: "asp-row" }, cloudTest, cloudOut),
      h("div", { class: "asp-head" }, "Local model (Ollama)"),
      field("Address", lurl),
      field("Model", lmodel, localList),
      h("div", { class: "asp-row" }, localTest, localOut),
      t ? h("div", { class: "asp-head" }, "Public transport") : null,
      t ? field("Walking speed", speeds, custom) : null,
      t ? h("p", { class: "ed-hint" }, "To the stop and between lines. Faster finds tighter connections that a slower ",
        "pace would miss. Used for HSL routes, spoken or shown, and the Reittiopas link.") : null,
      note,
      h("p", { class: "ed-hint" }, "These are the assistant's own settings: they apply right away, also to push-to-talk, ",
        "and aren't part of Save. The key stays on this PC, in the assistant's config/settings.json."),
    ].filter(Boolean));               // replaceChildren would write a skipped field as the text "null"
  }

  root.append(h("div", { class: "asp-note" }, "Loading the assistant's settings..."));
  api.get("assistant", { settings: 1 }).then(r => {
    if (r.error || !r.cloud) {
      root.replaceChildren(h("div", { class: "asp-head" }, "Models"),
        h("p", { class: "ed-hint" }, "Start the assistant to change its models and API key."));
      return;
    }
    s = r;
    draw();
  }).catch(() => root.replaceChildren(h("p", { class: "ed-hint" }, "The hub's server is offline.")));
  return root;
}

const STATES = { waiting: "Starting", ready: "Ready", recording: "Listening", transcribing: "Transcribing",
  thinking: "Thinking", approval: "Needs approval", speaking: "Speaking" };
const MODES = [["local", "Local"], ["cloud", "Cloud"], ["auto", "Auto"]];
const sleep = ms => new Promise(r => setTimeout(r, ms));
const PATHS = {
  spark: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM19 11a7 7 0 0 1-14 0M12 18v3",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  reset: "M3 12a9 9 0 1 0 2.6-6.4L3 8M3 3v5h5",
  walk: "M13 3.5a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3zM11 21l1.5-6.5L15 17v4M8.5 12.5L11 8.5l3 1.5 2.5 3M11 8.5l1.5 6",
  out: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
};
const glyph = (name, size) => PATHS[name]
  ? h("svg", { class: "icon", width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
      "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round" }, h("path", { d: PATHS[name] }))
  : icon(name, size);
const avatar = quiet => h("div", { class: `as-avatar${quiet ? " as-quiet" : ""}` }, glyph("spark", 13));
const clock = t => {
  const d = new Date(t * 1000);
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`;
};

// ---- What a route tool found, under its reply (item.view, from voice_assistant/assistant/tools/travel_tool.py)

// HSL's own colours, so the blocks read like reittiopas
const LEG_COLORS = { bus: "#007ac9", tram: "#00985f", metro: "#ff6319", train: "#8c4799", ferry: "#00b9e4",
  bike: "#fcbc19", funicular: "#00985f" };
const ROUTE_COLORS = { driving: "#0a84ff", walking: "#30d158", cycling: "#ffd60a" };
const MODE_WORDS = { driving: "by car", walking: "on foot", cycling: "by bike" };
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);

function routeView(v, open) {
  const box = h("div", { class: "as-view as-map", title: "Open in Google Maps", onclick: () => open(v.link) });
  box.append(h("div", { class: "as-map-pill" }, h("b", {}, v.duration), ` · ${v.distance_km} km ${MODE_WORDS[v.mode] || ""}`),
    h("div", { class: "as-map-credit" }, "Esri, HERE, Garmin, © OpenStreetMap"));
  // drawn once the box is in the list and has a width
  let tries = 0;
  const draw = () => {
    if (!box.isConnected || !box.clientWidth) { if (tries++ < 20) requestAnimationFrame(draw); return; }
    drawMap(box, v, box.clientWidth, box.clientHeight || 150);
  };
  requestAnimationFrame(draw);
  return box;
}

// Web Mercator, as the map tiles are drawn: pixels at zoom z
function project(lat, lon, z) {
  const s = 256 * Math.pow(2, z), r = lat * Math.PI / 180;
  return [(lon + 180) / 360 * s, (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * s];
}

function drawMap(box, v, W, H) {
  const pts = v.points && v.points.length > 1 ? v.points : [v.a, v.b];
  const all = pts.concat([v.a, v.b]);
  // the closest zoom at which the whole route fits, with room for the markers and the pill on top
  // (16 is as far as the basemap goes)
  let z = 16, minX, maxX, minY, maxY;
  for (; z > 2; z--) {
    const xy = all.map(p => project(p[0], p[1], z));
    minX = Math.min.apply(null, xy.map(p => p[0])); maxX = Math.max.apply(null, xy.map(p => p[0]));
    minY = Math.min.apply(null, xy.map(p => p[1])); maxY = Math.max.apply(null, xy.map(p => p[1]));
    if (maxX - minX <= W - 40 && maxY - minY <= H - 56) break;
  }
  const left = Math.round((minX + maxX) / 2 - W / 2), top = Math.round((minY + maxY) / 2 - H / 2 - 8);
  const tiles = h("div", { class: "as-map-tiles" });
  const n = Math.pow(2, z);
  for (let ty = Math.floor(top / 256); ty <= Math.floor((top + H) / 256); ty++) {
    for (let tx = Math.floor(left / 256); tx <= Math.floor((left + W) / 256); tx++) {
      if (ty < 0 || ty >= n) continue;
      const x = ((tx % n) + n) % n;
      tiles.append(h("img", { class: "as-tile", alt: "", draggable: "false",
        // Esri's dark gray canvas: no API key needed (CARTO's basemaps now want one)
        src: `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/${z}/${ty}/${x}`,
        style: { left: `${tx * 256 - left}px`, top: `${ty * 256 - top}px` } }));
    }
  }
  const at = p => { const q = project(p[0], p[1], z); return [q[0] - left, q[1] - top]; };
  const line = pts.map(p => at(p).map(c => c.toFixed(1)).join(",")).join(" ");
  const color = ROUTE_COLORS[v.mode] || "#0a84ff";
  const a = at(v.a), b = at(v.b);
  const straight = !(v.points && v.points.length > 1);      // no route line from the router: just where to where
  const svg = h("svg", { class: "as-map-line", width: W, height: H, viewBox: `0 0 ${W} ${H}` },
    h("polyline", { points: line, fill: "none", stroke: "#000", "stroke-width": 7, opacity: 0.35,
      "stroke-linecap": "round", "stroke-linejoin": "round" }),
    h("polyline", { points: line, fill: "none", stroke: color, "stroke-width": 4, "stroke-linecap": "round",
      "stroke-linejoin": "round", "stroke-dasharray": straight ? "2 7" : null }),
    h("circle", { cx: a[0], cy: a[1], r: 5, fill: "#fff", stroke: "#1c1c1e", "stroke-width": 2 }),
    h("circle", { cx: b[0], cy: b[1], r: 6.5, fill: color, stroke: "#fff", "stroke-width": 2.5 }));
  box.prepend(tiles, svg);
}

function legBlock(s) {
  const walk = s.mode === "walk";
  const label = walk ? [glyph("walk", 11), s.min >= 4 ? h("span", {}, String(s.min)) : null]
    : [s.line || cap(s.mode)];
  return h("div", { class: `as-leg${walk ? " as-leg-walk" : ""}`, title: walk ? `Walk ${s.min} min` : `${cap(s.mode)} ${s.line}`,
    style: { flexGrow: Math.max(s.min, 1), background: walk ? null : (LEG_COLORS[s.mode] || "#636366") } },
    ...label.filter(Boolean));
}

function legSteps(o, to) {
  const rows = o.steps.map(s => {
    const walk = s.mode === "walk" || s.mode === "bike";
    const color = walk ? "rgba(255, 255, 255, 0.35)" : (LEG_COLORS[s.mode] || "#636366");
    const what = walk
      ? h("div", { class: "as-step-what" }, `${cap(s.mode)} ${s.min} min`, s.m ? h("span", { class: "as-step-sub" }, ` · ${s.m} m`) : null,
        h("div", { class: "as-step-sub" }, `to ${s.to}`))
      : h("div", { class: "as-step-what" }, h("b", {}, `${cap(s.mode)} ${s.line}`), s.head ? ` → ${s.head}` : "",
        h("div", { class: "as-step-sub" }, `${s.from} → ${s.to} · ${s.end}`));
    return h("div", { class: "as-step" }, h("span", { class: "as-step-time num" }, s.start),
      h("i", { class: "as-step-dot", style: { background: color } }), what);
  });
  rows.push(h("div", { class: "as-step" }, h("span", { class: "as-step-time num" }, o.arrives),
    h("i", { class: "as-step-dot as-step-end" }), h("div", { class: "as-step-what" }, h("b", {}, cap(to)))));
  return h("div", { class: "as-steps" }, rows);
}

function transitView(v, open) {
  let shown = v.open || 0;
  const box = h("div", { class: "as-view as-trip" });
  // each option is a strip of blocks; the open one (the one asked about, else the first) also lists its legs
  const draw = () => box.replaceChildren(
    ...v.options.map((o, i) => h("div", { class: `as-opt${i === shown ? " on" : ""}`,
      onclick: () => { shown = i === shown ? -1 : i; draw(); } },
      h("div", { class: "as-opt-head" }, h("b", { class: "num" }, `${o.leaves} – ${o.arrives}`),
        h("span", { class: "as-opt-dur" }, o.duration)),
      h("div", { class: "as-strip" }, o.steps.map(legBlock)),
      i === shown ? legSteps(o, v.to) : null)),
    h("button", { class: "as-trip-link", onclick: () => open(v.link) },
      v.arrive_by ? `Be there by ${v.arrive_by} · Reittiopas` : "Reittiopas", glyph("out", 11)));
  draw();
  return box;
}

export function mount(el, { options, api }) {
  const o = withDefaults(meta, options);
  const title = header("Assistant");
  title.querySelector(".tile-title").prepend(glyph("spark", 16));
  const dot = h("i", { class: "as-dot" });
  const stateText = h("span");
  const status = h("button", { class: "as-status", title: "" }, dot, stateText);
  const reset = h("button", { class: "as-reset press", title: "Start over: forget the earlier messages",
    onclick: () => api.post("assistant", { forget: true }).then(r => { if (r.error) flash(r.error); })
      .catch(() => flash("The hub's server is offline")) }, glyph("reset", 14));
  title.append(h("div", { class: "as-head-right" }, reset, status));
  const modeBtns = MODES.map(([mode, label]) => h("button", { class: "as-mode", "data-mode": mode,
    onclick: () => setBackend(mode) }, label));
  const modes = h("div", { class: "as-modes" }, modeBtns);
  const list = h("div", { class: "as-list" });
  const empty = h("div", { class: "as-empty" });
  const input = h("input", { class: "as-input", type: "text", maxlength: 500, spellcheck: "false",
    // In the overlay the window never has the keyboard; clicking the field asks the host for it (HostKeyboard.cs).
    onmousedown: () => { if (window.__hostKeyboard) window.__hostKeyboard(1); preload(); },
    onfocus: () => preload(),
    onblur: () => { if (window.__hostKeyboard) window.__hostKeyboard(0); },
    onkeydown: e => {
      if (e.key === "Enter") { e.preventDefault(); send(); }
      else if (e.key === "Escape") input.blur();
    } });
  const sendBtn = h("button", { class: "as-send as-idle press", title: "Send", onclick: () => send() }, icon("up", 16));
  input.addEventListener("input", () => { sendBtn.classList.toggle("as-idle", !input.value.trim()); preload(); });
  const composer = h("div", { class: "as-composer" }, input, sendBtn);
  const offline = h("div", { class: "tile-empty as-offline" });
  const typingText = h("span");
  const typing = h("div", { class: "as-row as-typing", hidden: true }, avatar(false),
    h("div", { class: "as-col" }, h("div", { class: "as-bubble" },
      h("span", { class: "as-dots" }, h("i"), h("i"), h("i")), typingText)));
  list.append(typing);
  el.append(title, modes, list, empty, composer, offline);
  window.__hostKeyboardLost = () => input.blur();

  let since = 0, snap = null, sending = false;
  const items = new Map();          // id -> item
  const nodes = new Map();          // id -> [element, the item's JSON when drawn]

  status.addEventListener("click", () => {
    if (snap && snap.state === "speaking") api.post("assistant", { stop: true });
  });

  // A cold local model takes ~20 s to load and read its prompt: start that while the user is still typing.
  // The assistant ignores it when the model is already loaded or the cloud answers.
  let preloaded = 0;
  function preload() {
    if (Date.now() - preloaded < 60000) return;
    preloaded = Date.now();
    api.post("assistant", { preload: true }).catch(() => {});
  }

  async function send() {
    const text = input.value.trim();
    if (!text || sending) return;
    sending = true;
    sendBtn.disabled = true;
    try {
      const r = await api.post("assistant", { ask: text, speak: o.speak });
      if (r.error) flash(r.error);
      else { input.value = ""; sendBtn.classList.add("as-idle"); stick = true; }
    } catch (e) {
      flash("The hub's server is offline");
    }
    sending = false;
    sendBtn.disabled = false;
  }

  async function setBackend(mode) {
    modeBtns.forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
    try {
      const r = await api.post("assistant", { backend: mode });
      if (r.error) flash(r.error);
    } catch (e) { flash("The hub's server is offline"); }
  }

  // what is picked on an open approval's choices (an event's colour), by approval id, so a re-render keeps it.
  // The last pick of each choice is remembered as the next one's starting value.
  const picks = new Map();
  function pickFor(i) {
    if (!picks.has(i.id)) {
      const p = {};
      for (const c of i.choices || []) {
        let last = null;
        try { last = localStorage.getItem("as-pick-" + c.key); } catch (e) {}
        p[c.key] = c.options.some(op => op[0] === last) ? last : c.options[0][0];
      }
      picks.set(i.id, p);
    }
    return picks.get(i.id);
  }

  function choicesView(i) {
    const p = pickFor(i);
    return h("div", { class: "as-ap-choices" }, ...i.choices.map(c => {
      const name = h("span", { class: "as-ch-name" });
      const swatches = c.options.map(([value, label, colour]) => h("button", {
        class: `as-swatch press${colour ? "" : " as-sw-none"}`, title: label, "data-v": value,
        style: colour ? { background: colour } : {},
        onclick: () => { p[c.key] = value; mark(); } }));
      function mark() {
        swatches.forEach(b => b.classList.toggle("on", b.dataset.v === p[c.key]));
        const o = c.options.find(op => op[0] === p[c.key]);
        name.textContent = o ? o[1] : "";
      }
      mark();
      return h("div", { class: "as-ch" }, h("div", { class: "as-ch-head" }, h("span", {}, c.label), name),
        h("div", { class: "as-swatches" }, ...swatches));
    }));
  }

  async function approve(yes, i) {
    const body = { approve: yes };
    if (yes && i && i.choices) {
      body.choices = pickFor(i);
      for (const k in body.choices) try { localStorage.setItem("as-pick-" + k, body.choices[k]); } catch (e) {}
    }
    try {
      const r = await api.post("assistant", body);
      if (r.error) flash(r.error);
    } catch (e) { flash("The hub's server is offline"); }
  }

  // the overlay can't open a browser itself: the hub's server does
  function openLink(url) {
    api.post("assistant", { open: url }).catch(() => flash("The hub's server is offline"));
  }

  function flash(text) {
    const n = h("div", { class: "as-notice as-flash" }, text);
    list.append(n);
    list.scrollTop = list.scrollHeight;
    setTimeout(() => n.remove(), 4000);
  }

  // quiet: the item before it was also the assistant's, so it goes without its own avatar
  function itemNode(i, quiet) {
    if (i.kind === "user")
      return h("div", { class: "as-row as-me" }, h("div", { class: "as-col" },
        h("div", { class: "as-bubble" },
          i.via === "voice" ? h("span", { class: "as-via", title: "Spoken" }, glyph("mic", 12)) : null, i.text)));
    if (i.kind === "reply") {
      const view = !i.view ? null : i.view.kind === "route" ? routeView(i.view, openLink)
        : i.view.kind === "transit" && i.view.options && i.view.options.length ? transitView(i.view, openLink) : null;
      return h("div", { class: "as-row" }, avatar(quiet), h("div", { class: `as-col${view ? " as-has-view" : ""}` },
        h("div", { class: "as-bubble" }, i.text), view,
        h("div", { class: "as-meta" }, i.backend ? h("span", { class: `as-tag as-${i.backend}` }, i.backend) : null,
          i.t ? h("span", {}, clock(i.t)) : null)));
    }
    if (i.kind === "approval") {
      const open = !i.result && snap && snap.approval && snap.approval.id === i.id;
      return h("div", { class: `as-approval${i.result ? " " + i.result : ""}` },
        h("div", { class: "as-ap-head" }, glyph("shield", 14), h("span", {}, "Approval")),
        h("div", { class: "as-ap-text" }, i.text),
        open && i.choices ? choicesView(i) : null,
        open ? h("div", { class: "as-ap-btns" },
          h("button", { class: "as-no press", onclick: () => approve(false) }, "No"),
          h("button", { class: "as-yes press", onclick: () => approve(true, i) }, "Yes"))
          : h("div", { class: "as-ap-result" }, i.result === "approved" ? "Approved" : i.result === "denied" ? "Not approved" : "Closed"));
    }
    return h("div", { class: "as-notice" }, i.text);
  }

  function render() {
    const d = snap;
    el.classList.toggle("as-off", !d.online);
    if (!d.online) {
      offline.replaceChildren(h("div", { class: "as-off-title" }, "The assistant isn't running"),
        h("div", {}, "Start it from the tray, or in the voice_assistant folder: pyw -3.13 main.py --tray"));
      stateText.textContent = "Offline";
      status.className = "as-status st-off";
      return;
    }
    title.querySelector(".tile-title span").textContent = d.name;
    input.placeholder = `Ask ${d.name}...`;
    stateText.textContent = STATES[d.state] || d.state;
    status.className = `as-status st-${d.state}`;
    status.title = d.state === "speaking" ? "Click to stop speaking" : d.status;
    const b = d.backend || {};
    modes.hidden = !o.backendSwitch;
    modeBtns.forEach(btn => {
      btn.classList.toggle("active", btn.dataset.mode === b.mode);
      btn.title = btn.dataset.mode === "local" ? b.local_model
        : btn.dataset.mode === "cloud" ? (b.cloud_ready ? b.cloud_model : `${b.cloud_model}: no API key yet`)
        : "Local model; the cloud when it is unavailable";
    });
    modeBtns[1].classList.toggle("unset", !b.cloud_ready);

    let prev = null;
    for (const i of items.values()) {
      const quiet = i.kind === "reply" && prev && prev.kind === "reply";
      prev = i;
      const key = JSON.stringify(i) + (snap.approval ? snap.approval.id : "") + quiet;
      const have = nodes.get(i.id);
      if (have && have[1] === key) continue;
      const n = itemNode(i, quiet);
      if (have) have[0].replaceWith(n); else list.insertBefore(n, typing);
      nodes.set(i.id, [n, key]);
    }
    for (const [id, [n]] of nodes) if (!items.has(id)) { n.remove(); nodes.delete(id); }

    // what it is doing right now, as the last bubble
    const busy = { recording: "Listening", transcribing: "Transcribing", thinking: "" }[d.state];
    typing.hidden = busy === undefined;
    typing.classList.toggle("as-listening", d.state === "recording");
    typingText.textContent = busy || "";
    list.append(typing);                     // stays after the newest message

    if (!items.size) empty.replaceChildren(h("div", { class: "as-hello" }, glyph("spark", 24)),
      h("div", { class: "as-hello-title" }, `Hi, I'm ${d.name}`),
      h("div", {}, "Hold ", h("span", { class: "as-key" }, d.hotkey), " to talk, or type below."));
    empty.hidden = items.size > 0;
    list.hidden = items.size === 0 && typing.hidden;
    if (stick) toBottom();
  }

  // Follows the newest message unless the user has scrolled up to read. Scrolled again a little later because
  // the overlay's engine reports the list's old height until it has laid out the new messages.
  let stick = true;
  list.addEventListener("wheel", () => requestAnimationFrame(() => {
    stick = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
  }));
  function toBottom() {
    list.scrollTop = list.scrollHeight;
    requestAnimationFrame(() => { list.scrollTop = list.scrollHeight; });
    setTimeout(() => { if (stick) list.scrollTop = list.scrollHeight; }, 250);
  }

  function clear() {
    items.clear();
    nodes.forEach(([n]) => n.remove());
    nodes.clear();
    since = 0;
  }

  // Long poll: the hub holds each request until the assistant has something new (or ~8 s pass).
  (async () => {
    while (el.isConnected) {
      if (document.hidden) { await sleep(1000); continue; }
      let d;
      try {
        d = await api.get("assistant", { since, wait: since ? 8 : 0 });
      } catch (e) {
        d = { online: false };
      }
      if (!el.isConnected) break;
      if (!d.online || d.error) {
        clear();
        snap = { online: false };
        render();
        await sleep(3000);
        continue;
      }
      if (d.reset || d.seq < since) {          // the assistant restarted, or this tile fell too far behind
        clear();
        continue;
      }
      d.items.forEach(i => items.set(i.id, i));
      while (items.size > 100) items.delete(items.keys().next().value);
      since = d.seq;
      snap = d;
      render();
    }
  })();
}
