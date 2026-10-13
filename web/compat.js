// Fills in what the overlay host's engine lacks (Ultralight 1.3, WebKit from about 2020).
// Each part checks for the feature first, so in Chrome, Edge or Wallpaper Engine this does nothing.
// When writing widgets, also avoid ?. and ?? (a syntax error there), the `inset` shorthand, var() inside
// box-shadow and inset box-shadows (both drawn opaque white), stroke-opacity (ignored; use opacity), and
// top-level await in modules (a syntax error).

if (!Element.prototype.replaceChildren)
  Element.prototype.replaceChildren = function (...nodes) { this.textContent = ""; this.append(...nodes); };

// In the overlay, requests to the hub's own server go through the host (window.__hostFetch, see
// overlay/HostFetch.cs): Ultralight leaks memory on every fetch, and the widgets poll all day.
if (window.__hostFetch) {
  const pending = {};
  let next = 0;
  window.__hostFetchDone = (id, status, text) => {
    const p = pending[id];
    delete pending[id];
    if (!p) return;
    if (!status) { p.reject(new TypeError("Network request failed")); return; }
    p.resolve({ ok: status >= 200 && status < 300, status, text: async () => text, json: async () => JSON.parse(text) });
  };
  const pageFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const url = new URL(String(input), location.href);
    if (url.origin !== location.origin) return pageFetch(input, init);
    return new Promise((resolve, reject) => {
      const id = ++next;
      pending[id] = { resolve, reject };
      window.__hostFetch(id, init.method || "GET", url.href, init.body || "");
    });
  };
}

// Flex `gap` (grid gap works): emulated with margins on the children of every flex container that has one.
function flexGapWorks() {
  const box = document.createElement("div");
  box.style.cssText = "display:flex;flex-direction:column;row-gap:1px;position:absolute;visibility:hidden";
  box.append(document.createElement("div"), document.createElement("div"));
  document.body.append(box);
  const ok = box.scrollHeight === 1;
  box.remove();
  return ok;
}

function applyGap(el) {
  const cs = getComputedStyle(el);
  if (!cs.display.endsWith("flex")) return;
  const row = parseFloat(cs.rowGap) || 0, col = parseFloat(cs.columnGap) || 0;
  if (!row && !col) return;
  const vertical = cs.flexDirection.startsWith("column"), wrap = cs.flexWrap !== "nowrap";
  let first = true;
  for (const c of el.children) {
    const pos = getComputedStyle(c).position;
    if (pos === "absolute" || pos === "fixed") continue;
    if (wrap) {                         // trailing space after the last item is fine for our layouts
      c.style.marginRight = col + "px";
      c.style.marginBottom = row + "px";
    } else if (vertical) c.style.marginTop = first ? "" : row + "px";
    else c.style.marginLeft = first ? "" : col + "px";
    first = false;
  }
}

function applyAll(root) {
  if (root.nodeType !== 1) return;
  applyGap(root);
  for (const el of root.querySelectorAll("*")) applyGap(el);
}

function startFlexGap() {
  if (flexGapWorks()) return;
  // Runs as a microtask: after the code that changed the page, but before the next paint, so new elements
  // never show for a frame without their spacing (a later timer made rows jump, e.g. in the Discord list).
  new MutationObserver(records => {
    const items = new Set();
    for (const r of records) {
      items.add(r.target);
      r.addedNodes.forEach(n => items.add(n));
    }
    items.forEach(applyAll);
  }).observe(document.body, { childList: true, subtree: true });
  // widget.css files arrive after their tiles: redo the whole page when a stylesheet loads
  document.addEventListener("load", e => { if (e.target.tagName === "LINK") applyAll(document.body); }, true);
  applyAll(document.body);
}

if (document.body) startFlexGap();
else document.addEventListener("DOMContentLoaded", startFlexGap);
