// Layout editor, opened with http://127.0.0.1:8765/?edit
// Drag a tile to move it, drag its corner to resize, add widgets from the bank (drag or click), remove them,
// pick tile styles and the background, and change a widget's settings (⚙). Save writes layout.json through /api/layout; the wallpaper then
// reloads itself. Nothing changes on the wallpaper until you save.
import { api, h, withDefaults } from "./lib.js";
import { grid, STYLES, sizeOf, placeTile, mountWidget, unmountWidget, setBackground } from "./hub.js";

let layout, entries, cols, rows;
const metas = {};
let overlayGrid, ghost, drawer, toastEl, statusEl, dirty = false;
let drawerTabs, drawerShow, settingsTab, settingsEntry = null;

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

export async function start(lay, ents) {
  layout = lay;
  entries = ents;
  cols = layout.columns || 8;
  rows = layout.rows || 4;
  document.head.append(h("link", { rel: "stylesheet", href: "edit.css" }));
  document.body.classList.add("editing");

  const info = await api.get("layout");
  await Promise.all(info.types.map(async t => {
    try {
      const m = await import(`./widgets/${t}/widget.js`);
      metas[t] = { name: t, description: "", defaultSize: "2x2", ...(m.meta || {}) };
    } catch (e) { console.warn(`widget ${t} failed to load`, e); }
  }));

  pinPositions();
  buildOverlay();
  buildToolbar();
  buildDrawer(info.backgrounds);
  toastEl = h("div", { class: "edit-toast" });
  document.body.append(toastEl);

  window.addEventListener("beforeunload", e => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
  window.addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); }
    if (e.key === "Escape") drawer.classList.remove("open");
  });
}

// ----------------------------------------------------------------- geometry --
function metrics() {
  const r = grid.getBoundingClientRect(), cs = getComputedStyle(grid);
  const pl = parseFloat(cs.paddingLeft), pr = parseFloat(cs.paddingRight);
  const pt = parseFloat(cs.paddingTop), pb = parseFloat(cs.paddingBottom);
  const gx = parseFloat(cs.columnGap) || 0, gy = parseFloat(cs.rowGap) || 0;
  return { x0: r.left + pl, y0: r.top + pt, gx, gy,
    cw: (r.width - pl - pr - gx * (cols - 1)) / cols, ch: (r.height - pt - pb - gy * (rows - 1)) / rows };
}

function cellAt(x, y) {
  const m = metrics();
  return { col: clamp(Math.floor((x - m.x0 + m.gx / 2) / (m.cw + m.gx)) + 1, 1, cols),
           row: clamp(Math.floor((y - m.y0 + m.gy / 2) / (m.ch + m.gy)) + 1, 1, rows) };
}

function fits(r, except) {
  if (r.col < 1 || r.row < 1 || r.col + r.w - 1 > cols || r.row + r.h - 1 > rows) return false;
  return entries.every(o => {
    if (o === except) return true;
    const s = sizeOf(o.w);
    return r.col + r.w <= o.w.col || o.w.col + s.w <= r.col || r.row + r.h <= o.w.row || o.w.row + s.h <= r.row;
  });
}

function firstFree(s) {
  for (let row = 1; row <= rows - s.h + 1; row++)
    for (let col = 1; col <= cols - s.w + 1; col++)
      if (fits({ col, row, w: s.w, h: s.h })) return { col, row };
  return null;
}

// Widgets placed automatically (no col/row) get the position they have on screen now.
function pinPositions() {
  for (const e of entries) {
    if (e.w.col && e.w.row) continue;
    const r = e.tile.getBoundingClientRect();
    Object.assign(e.w, cellAt(r.left + 2, r.top + 2));
    placeTile(e.tile, e.w, layout);
  }
}

// ----------------------------------------------------------------- overlay --
function buildOverlay() {
  overlayGrid = h("div", { class: "edit-grid" });
  for (let r = 1; r <= rows; r++)
    for (let c = 1; c <= cols; c++)
      overlayGrid.append(h("div", { class: "edit-cell", style: { gridColumn: `${c}`, gridRow: `${r}` } }));
  ghost = h("div", { class: "edit-ghost" });
  overlayGrid.append(ghost);
  document.body.append(overlayGrid);
  entries.forEach(addOverlay);
}

function addOverlay(entry) {
  const meta = metas[entry.w.type] || { name: entry.w.type };
  entry.styleBtn = h("button", { class: "eo-btn", title: "Tile style (auto = the style chosen for all tiles)",
    onclick: () => cycleStyle(entry) });
  entry.sizeEl = h("span", { class: "eo-size" });
  const handle = h("div", { class: "eo-resize", title: "Drag to resize" });
  entry.ov = h("div", { class: "edit-overlay" },
    h("div", { class: "eo-bar" },
      h("span", { class: "eo-name" }, meta.name), entry.sizeEl, h("span", { class: "eo-fill" }),
      meta.settings ? h("button", { class: "eo-btn", title: "Settings", onclick: () => openSettings(entry) }, "⚙") : null,
      entry.styleBtn,
      h("button", { class: "eo-btn eo-del", title: "Remove", onclick: () => removeEntry(entry) }, "✕")),
    handle);
  entry.ov.addEventListener("pointerdown", e => {
    if (e.button !== 0 || e.target.closest("button")) return;
    e.target === handle ? startResize(entry, e) : startMove(entry, e);
  });
  overlayGrid.append(entry.ov);
  syncEntry(entry);
}

function syncEntry(entry) {
  const { w } = entry, s = sizeOf(w);
  entry.ov.style.gridColumn = `${w.col} / span ${s.w}`;
  entry.ov.style.gridRow = `${w.row} / span ${s.h}`;
  entry.sizeEl.textContent = `${s.w}×${s.h}`;
  entry.styleBtn.textContent = w.style || "auto";
  placeTile(entry.tile, w, layout);
}

function showGhost(r, ok) {
  ghost.style.gridColumn = `${r.col} / span ${r.w}`;
  ghost.style.gridRow = `${r.row} / span ${r.h}`;
  ghost.className = `edit-ghost show ${ok ? "ok" : "bad"}`;
}

const hideGhost = () => { ghost.className = "edit-ghost"; };

// Pointer drag helper: calls onMove(event) while dragging and onEnd() on release.
function drag(el, e, onMove, onEnd) {
  e.preventDefault();
  el.setPointerCapture(e.pointerId);
  const up = () => {
    el.removeEventListener("pointermove", onMove);
    el.removeEventListener("pointerup", up);
    el.removeEventListener("pointercancel", up);
    onEnd();
  };
  el.addEventListener("pointermove", onMove);
  el.addEventListener("pointerup", up);
  el.addEventListener("pointercancel", up);
}

function startMove(entry, e) {
  const s = sizeOf(entry.w), c0 = cellAt(e.clientX, e.clientY);
  const grab = { dc: c0.col - entry.w.col, dr: c0.row - entry.w.row };
  let target = null;
  entry.ov.classList.add("dragging");
  drag(entry.ov, e, ev => {
    const c = cellAt(ev.clientX, ev.clientY);
    target = { col: clamp(c.col - grab.dc, 1, cols - s.w + 1), row: clamp(c.row - grab.dr, 1, rows - s.h + 1), w: s.w, h: s.h };
    showGhost(target, fits(target, entry));
  }, () => {
    entry.ov.classList.remove("dragging");
    hideGhost();
    if (target && fits(target, entry) && (target.col !== entry.w.col || target.row !== entry.w.row)) {
      Object.assign(entry.w, { col: target.col, row: target.row });
      syncEntry(entry);
      markDirty();
    }
  });
}

function startResize(entry, e) {
  const meta = metas[entry.w.type] || {};
  const min = sizeOf({ size: meta.minSize || "1x1" }), max = sizeOf({ size: meta.maxSize || `${cols}x${rows}` });
  let target = null;
  entry.ov.classList.add("dragging");
  drag(entry.ov, e, ev => {
    const c = cellAt(ev.clientX, ev.clientY);
    target = { col: entry.w.col, row: entry.w.row,
      w: clamp(c.col - entry.w.col + 1, min.w, Math.min(max.w, cols - entry.w.col + 1)),
      h: clamp(c.row - entry.w.row + 1, min.h, Math.min(max.h, rows - entry.w.row + 1)) };
    showGhost(target, fits(target, entry));
  }, () => {
    entry.ov.classList.remove("dragging");
    hideGhost();
    if (target && fits(target, entry) && `${target.w}x${target.h}` !== entry.w.size) {
      entry.w.size = `${target.w}x${target.h}`;
      // remount, so the widget lays itself out for the new size
      unmountWidget(entry.tile);
      entry.tile = mountWidget(entry.w, layout);
      syncEntry(entry);
      markDirty();
    }
  });
}

function cycleStyle(entry) {
  const order = [undefined, ...STYLES];
  const next = order[(order.indexOf(entry.w.style) + 1) % order.length];
  if (next) entry.w.style = next; else delete entry.w.style;
  syncEntry(entry);
  markDirty();
}

function addEntry(type, pos) {
  const meta = metas[type];
  const w = { type, size: meta.defaultSize, col: pos.col, row: pos.row };
  const entry = { w, tile: mountWidget(w, layout) };
  entries.push(entry);
  addOverlay(entry);
  markDirty();
}

function removeEntry(entry) {
  if (entry === settingsEntry) closeSettings();
  unmountWidget(entry.tile);
  entry.ov.remove();
  entries.splice(entries.indexOf(entry), 1);
  markDirty();
}

// ----------------------------------------------------------------- toolbar --
function buildToolbar() {
  statusEl = h("span", { class: "et-status" }, "No changes");
  document.body.append(h("div", { class: "edit-toolbar" },
    h("span", { class: "et-title" }, "Editing layout"), statusEl,
    h("button", { class: "et-btn", onclick: () => drawer.classList.toggle("open") }, "＋ Widgets & background"),
    h("button", { class: "et-btn", onclick: () => { if (!dirty || confirm("Throw away your changes?")) { dirty = false; location.reload(); } } }, "Discard"),
    h("button", { class: "et-btn", onclick: save }, "Save"),
    h("button", { class: "et-btn primary", onclick: async () => { if (!dirty || await save()) location.href = "/"; } }, "Done")));
}

function markDirty() {
  dirty = true;
  statusEl.textContent = "Unsaved changes";
  statusEl.classList.add("dirty");
}

function toast(text, bad = false) {
  toastEl.textContent = text;
  toastEl.className = `edit-toast show${bad ? " bad" : ""}`;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { toastEl.className = "edit-toast"; }, 3500);
}

async function save() {
  try {
    const r = await api.post("layout", { layout: { ...layout, widgets: entries.map(e => e.w) } });
    if (r.error) { toast(r.error, true); return false; }
  } catch (e) {
    toast("Could not reach the hub backend", true);
    return false;
  }
  dirty = false;
  statusEl.textContent = "Saved";
  statusEl.classList.remove("dirty");
  toast("Saved. The wallpaper updates in a few seconds.");
  return true;
}

// ------------------------------------------------------------------ drawer --
function buildDrawer(backgrounds) {
  const tabs = drawerTabs = { widgets: widgetBank(), background: backgroundPicker(backgrounds), settings: null };
  const names = { widgets: "Widgets", background: "Background", settings: "Settings" };
  const tabBtns = Object.keys(tabs).map(k => h("button", { class: "ed-tab", "data-tab": k, onclick: () => show(k) }, names[k]));
  settingsTab = tabBtns[2];
  settingsTab.hidden = true;                // appears once a tile's ⚙ is clicked
  const body = h("div", { class: "ed-body" });
  const show = drawerShow = k => {
    tabBtns.forEach(b => b.classList.toggle("active", b.dataset.tab === k));
    body.replaceChildren(tabs[k]);
  };
  drawer = h("aside", { class: "edit-drawer" },
    h("div", { class: "ed-head" }, ...tabBtns, h("button", { class: "ed-close", onclick: () => drawer.classList.remove("open") }, "✕")),
    body);
  show("widgets");
  document.body.append(drawer);
}

function widgetBank() {
  return h("div", { class: "ed-list" },
    h("p", { class: "ed-hint" }, "Drag a widget onto a free spot, or click it to drop it in the first free space."),
    Object.entries(metas).map(([type, m]) => h("div", { class: "bank-item", onpointerdown: e => startAdd(type, e) },
      h("div", { class: "bank-top" }, h("span", { class: "bank-name" }, m.name), h("span", { class: "bank-size" }, m.defaultSize.replace("x", "×"))),
      m.description ? h("div", { class: "bank-desc" }, m.description) : null)));
}

function startAdd(type, e) {
  if (e.button !== 0) return;
  const s = sizeOf({ size: metas[type].defaultSize });
  const item = e.currentTarget, x0 = e.clientX, y0 = e.clientY;
  let moved = false, target = null;
  drag(item, e, ev => {
    if (!moved && Math.hypot(ev.clientX - x0, ev.clientY - y0) < 6) return;
    moved = true;
    document.body.classList.add("adding");
    const c = cellAt(ev.clientX, ev.clientY);
    target = { col: clamp(c.col, 1, cols - s.w + 1), row: clamp(c.row, 1, rows - s.h + 1), w: s.w, h: s.h };
    showGhost(target, fits(target));
  }, () => {
    document.body.classList.remove("adding");
    hideGhost();
    if (moved) {
      if (target && fits(target)) addEntry(type, target);
      else toast("That spot is taken", true);
      return;
    }
    const pos = firstFree(s);
    if (pos) addEntry(type, pos);
    else toast(`No free ${s.w}×${s.h} space. Move or remove something first.`, true);
  });
}

function backgroundPicker(backgrounds) {
  const current = () => {
    const bg = layout.background;
    return (typeof bg === "string" ? bg : (bg && bg.src) || "").toLowerCase();
  };
  const cards = h("div", { class: "bg-grid" });
  const renderCards = () => cards.replaceChildren(
    card(null, "None", "Plain gradient", null),
    ...backgrounds.map(b => card(b, b.title, `${b.mb} MB`, b.preview_url)));
  const card = (b, title, sub, img) => h("button", {
    class: `bg-card${(b ? b.src.toLowerCase() : "") === current() ? " active" : ""}`,
    onclick: () => {
      const old = layout.background && typeof layout.background === "object" ? layout.background : {};
      layout.background = b ? { ...old, src: b.src } : null;
      setBackground(layout.background);
      renderCards();
      markDirty();
    } },
    img ? h("img", { src: img, alt: "", loading: "lazy" }) : h("div", { class: "bg-noimg" }),
    h("div", { class: "bg-title" }, title), h("div", { class: "bg-sub" }, sub));
  renderCards();

  const dimVal = h("span", { class: "num" });
  const bgObj = () => (typeof layout.background === "string" ? (layout.background = { src: layout.background }) : layout.background);
  const dim = h("input", { type: "range", min: 0, max: 0.8, step: 0.05, value: (bgObj() || {}).dim || 0, oninput: () => {
    dimVal.textContent = `${Math.round(dim.value * 100)}%`;
    const bg = bgObj();
    if (!bg) return;
    bg.dim = Number(dim.value);
    const d = document.querySelector(".bg-dim");
    if (d) d.style.opacity = bg.dim;
    markDirty();
  } });
  dimVal.textContent = `${Math.round(dim.value * 100)}%`;

  const styleBtns = STYLES.map(s => h("button", { class: `seg${(layout.tile_style || "default") === s ? " active" : ""}`, onclick: () => {
    layout.tile_style = s;
    styleBtns.forEach(b => b.classList.toggle("active", b.textContent === s));
    entries.forEach(syncEntry);
    markDirty();
  } }, s));

  return h("div", { class: "ed-list" },
    h("div", { class: "ed-label" }, "Tile style for all widgets"),
    h("div", { class: "segs" }, styleBtns),
    h("div", { class: "ed-label" }, "Darken background ", dimVal), dim,
    h("div", { class: "ed-label" }, "Your Wallpaper Engine videos"), cards);
}

// ---------------------------------------------------------------- settings --
// A widget lists its settings in meta.settings: [{ key, label, type, default, ... }]. They are stored in the
// widget's "options" in layout.json, leaving out any that are at their default. Each change re-mounts the
// widget, so the tile shows the result straight away.
function openSettings(entry) {
  settingsEntry = entry;
  drawerTabs.settings = settingsForm(entry);
  settingsTab.textContent = `${metas[entry.w.type].name} settings`;
  settingsTab.hidden = false;
  drawerShow("settings");
  drawer.classList.add("open");
}

function closeSettings() {
  settingsEntry = null;
  settingsTab.hidden = true;
  drawerShow("widgets");
}

function remount(entry) {
  unmountWidget(entry.tile);
  entry.tile = mountWidget(entry.w, layout);
  markDirty();
}

function setOption(entry, field, value) {
  const opts = entry.w.options || (entry.w.options = {});
  if (JSON.stringify(value) === JSON.stringify(field.default)) delete opts[field.key];
  else opts[field.key] = value;
  if (!Object.keys(opts).length) delete entry.w.options;
  remount(entry);
}

function settingsForm(entry) {
  const meta = metas[entry.w.type];
  const current = withDefaults(meta, entry.w.options);
  const set = (f, v) => { current[f.key] = v; setOption(entry, f, v); };
  const fields = meta.settings.map(f => {
    const v = current[f.key];
    let control;
    if (f.type === "multi") {                 // any number of choices, kept in the order they are listed
      control = h("div", { class: "st-chips" }, f.choices.map(([val, label]) => h("button", {
        class: `st-chip${v.includes(val) ? " on" : ""}`,
        onclick: e => {
          const on = !current[f.key].includes(val);
          e.currentTarget.classList.toggle("on", on);
          set(f, f.choices.map(c => c[0]).filter(x => x === val ? on : current[f.key].includes(x)));
        } }, label)));
    } else if (f.type === "select") {
      const btns = f.choices.map(([val, label]) => h("button", { class: `seg${val === v ? " active" : ""}`, onclick: e => {
        btns.forEach(b => b.classList.toggle("active", b === e.currentTarget));
        set(f, val);
      } }, label));
      control = h("div", { class: "segs" }, btns);
    } else if (f.type === "bool") {
      control = h("button", { class: `st-switch${v ? " on" : ""}`, onclick: e => {
        const on = !current[f.key];
        e.currentTarget.classList.toggle("on", on);
        set(f, on);
      } }, h("span"));
    } else if (f.type === "range") {
      const out = h("span", { class: "num" }, `${v}${f.unit || ""}`);
      const input = h("input", { type: "range", min: f.min, max: f.max, step: f.step || 1, value: v,
        oninput: () => { out.textContent = `${input.value}${f.unit || ""}`; },
        onchange: () => set(f, Number(input.value)) });
      control = h("div", { class: "st-range" }, input, out);
    } else if (f.type === "colors") {         // one colour per key; unset ones show the widget's own (f.palette)
      control = h("div", { class: "st-colors" }, f.keys.map(([key, label]) => {
        const input = h("input", { type: "color", value: (v && v[key]) || (f.palette && f.palette[key]) || "#ffffff",
          onchange: () => set(f, { ...current[f.key], [key]: input.value }) });
        return h("label", { class: "st-color" }, input, label);
      }));
    } else {
      const input = h("input", { type: "text", class: "st-text", value: v || "", placeholder: f.placeholder || "",
        onchange: () => set(f, input.value.trim()) });
      control = input;
    }
    return h("div", { class: "st-field" }, h("div", { class: "ed-label" }, f.label), control);
  });
  return h("div", { class: "ed-list" },
    h("p", { class: "ed-hint" }, "Changes show on the tile right away. Save to keep them."),
    fields,
    h("button", { class: "st-reset", onclick: () => { delete entry.w.options; remount(entry); openSettings(entry); } },
      "Reset to defaults"));
}
