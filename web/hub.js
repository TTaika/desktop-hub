// Builds the grid from layout.json and mounts each widget from widgets/<type>/widget.js.
// With ?edit in the URL it also loads the layout editor (edit.js).
import { api, h, icon } from "./lib.js";

export const grid = document.getElementById("grid");
export const STYLES = ["default", "glass", "solid", "bare"];
export const editing = new URLSearchParams(location.search).has("edit");

export function sizeOf(w) {
  const [cw, ch] = String(w.size || "2x2").split("x").map(Number);
  return { w: cw || 2, h: ch || 2 };
}

// Grid position, tile style and accent of a mounted tile, from its layout entry.
export function placeTile(tile, w, layout) {
  const s = sizeOf(w);
  tile.style.gridColumn = w.col ? `${w.col} / span ${s.w}` : `span ${s.w}`;
  tile.style.gridRow = w.row ? `${w.row} / span ${s.h}` : `span ${s.h}`;
  const style = STYLES.includes(w.style) ? w.style : STYLES.includes(layout.tile_style) ? layout.tile_style : "default";
  tile.classList.remove(...STYLES.map(x => `style-${x}`));
  tile.classList.add(`style-${style}`);
  if (w.accent) tile.style.setProperty("--accent", w.accent);
}

// Adds a tile for one layout entry and mounts its widget into it. Returns the tile at once.
export function mountWidget(w, layout) {
  const tile = h("section", { class: `tile w-${w.type}` });
  placeTile(tile, w, layout);
  grid.append(tile);
  const pollers = [];
  tile._stop = () => pollers.forEach(p => p.stop());
  const scoped = { ...api, poll: (...args) => { const p = api.poll(...args); pollers.push(p); return p; } };
  (async () => {
    try {
      const base = `widgets/${w.type}/`;
      const mod = await import(`./${base}widget.js`);
      if (mod.css && !document.querySelector(`link[href="${base}widget.css"]`))
        document.head.append(h("link", { rel: "stylesheet", href: base + "widget.css" }));
      mod.mount(tile, { options: w.options || {}, api: scoped, size: sizeOf(w) });
    } catch (e) {
      console.error(e);
      tile.replaceChildren(h("div", { class: "tile-error" }, `${w.type}: ${e.message}`));
    }
  })();
  return tile;
}

export function unmountWidget(tile) {
  if (tile._stop) tile._stop();
  tile.remove();
}

// layout.background: "bg.jpg" (a file in web/), or
// { "src": "C:/.../video.mp4" or "bg.mp4", "dim": 0.3, "fit": "cover", "position": "center", "speed": 1 }
// An absolute path is streamed by the server from where it is (/media/background), so a Wallpaper Engine
// workshop video needs no copying. Videos play muted, on a loop, and pause while the page is hidden.
export function setBackground(bg) {
  document.querySelectorAll(".bg-media, .bg-dim").forEach(e => e.remove());
  document.body.classList.toggle("has-bg", !!bg);
  if (!bg) return;
  if (typeof bg === "string") bg = { src: bg };
  const absolute = /^([a-z]:[\\/]|\\\\)/i.test(bg.src);
  const url = absolute ? `/media/background?src=${encodeURIComponent(bg.src)}` : bg.src;
  const video = /\.(mp4|webm|m4v|mov)$/i.test(bg.src);
  const media = video
    ? h("video", { class: "bg-media", src: url, autoplay: true, loop: true, playsinline: true, disablepictureinpicture: true })
    : h("img", { class: "bg-media", src: url, alt: "" });
  media.style.objectFit = bg.fit || "cover";
  media.style.objectPosition = bg.position || "center";
  document.body.prepend(h("div", { class: "bg-dim", style: { opacity: bg.dim || 0 } }));
  document.body.prepend(media);
  if (video) {
    media.muted = true;                       // the attribute alone does not satisfy autoplay rules
    media.playbackRate = bg.speed || 1;
  }
}

document.addEventListener("visibilitychange", () => {
  const v = document.querySelector("video.bg-media");
  if (v) document.hidden ? v.pause() : v.play().catch(() => {});
});

async function main() {
  const layout = await (await fetch("layout.json", { cache: "no-store" })).json();
  const root = document.documentElement.style;
  root.setProperty("--cols", layout.columns || 8);
  root.setProperty("--rows", layout.rows || 4);
  if (layout.padding) root.setProperty("--pad", layout.padding);
  if (layout.gap) root.setProperty("--gap", layout.gap);
  setBackground(layout.background);
  const entries = layout.widgets.map(w => ({ w, tile: mountWidget(w, layout) }));
  if (editing) (await import("./edit.js")).start(layout, entries);
  else document.body.append(h("button", { class: "hub-settings press", title: "Edit layout", onclick: openEditor }, icon("gear", 16)));
}

// In a browser tab the editor opens in place. The overlay and Wallpaper Engine can't open a tab, so the
// server opens one in the default browser.
function openEditor() {
  if (window.__hostFetch || window.wallpaperRegisterAudioListener) api.post("editor", {}).catch(() => {});
  else location.href = "/?edit";
}

// Reload when a file under web/ changes, so edits show up on the wallpaper without touching it.
// Not in the editor, where it would throw away unsaved changes.
let rev = null;
if (!editing) setInterval(async () => {
  if (document.hidden) return;
  try {
    const { web_rev } = await api.get("health");
    if (rev !== null && web_rev !== rev) location.reload();
    rev = web_rev;
  } catch { /* backend restarting */ }
}, 4000);

main();
