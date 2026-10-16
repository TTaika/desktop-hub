// Shared helpers for widgets: talking to the backend and small UI pieces.
import "./compat.js";

export const api = {
  async get(name, params = {}) {
    const qs = new URLSearchParams(params).toString();
    const r = await fetch(`/api/${name}${qs ? "?" + qs : ""}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
    return r.json();
  },
  async post(name, body) {
    const r = await fetch(`/api/${name}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    return r.json();
  },
  // Calls cb(data) every `ms` (cb(null, error) on failure). Skips while the page is hidden,
  // e.g. when Wallpaper Engine pauses the wallpaper. Returns { stop(), now() }.
  // A provider that answers with "ver" pushes instead: the next request asks with wait=<ver>, the server holds it
  // until something changes, and it goes out again right away. `ms` is then only the pause after a failure.
  poll(name, ms, cb, params = {}) {
    let timer, stopped = false, busy = false, ver = null;
    const tick = async () => {
      clearTimeout(timer);
      if (stopped || busy) return;            // busy: a held request answers by itself
      let next = ms;
      if (!document.hidden) {
        busy = true;
        try {
          const d = await api.get(name, ver == null ? params : { ...params, wait: ver });
          if (d && d.ver != null) { ver = d.ver; delete d.ver; next = 0; }
          if (!stopped) cb(d);
        } catch (e) { ver = null; if (!stopped) cb(null, e); }
        busy = false;
      }
      if (!stopped) timer = setTimeout(tick, next);
    };
    tick();
    return { stop() { stopped = true; clearTimeout(timer); }, now: tick };
  },
};

// h("div", {class: "x", onclick: fn}, child, "text", ...) -> element
export function h(tag, attrs = {}, ...children) {
  const svg = ["svg", "path", "circle", "polyline", "polygon", "line", "rect", "g", "defs", "linearGradient", "stop"].includes(tag);
  const el = svg ? document.createElementNS("http://www.w3.org/2000/svg", tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}

export function fmtBytes(n, digits = 1) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i === 0 ? 0 : digits)} ${units[i]}`;
}

export function fmtDuration(s) {
  const d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600), mm = Math.floor(s % 3600 / 60);
  return d ? `${d}d ${hh}h` : hh ? `${hh}h ${mm}m` : `${mm}m`;
}

// Springs, the way Apple parameterises them: `response` (seconds, roughly how fast it gets there) and
// `damping` (1 = critically damped: no overshoot). set(target) re-targets from wherever the value is on
// screen right now and keeps its velocity, so data that arrives mid-animation never makes anything jump.
const reducedMotion = window.matchMedia ? matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };

export function spring(value, onFrame, { response = 0.45, damping = 1, precision = 0.01 } = {}) {
  const stiffness = (2 * Math.PI / response) ** 2, friction = 4 * Math.PI * damping / response;
  let target = value, velocity = 0, raf = 0, last = 0;
  function step(now) {
    const dt = Math.min(0.064, Math.max(0.001, (now - last) / 1000));
    last = now;
    for (let i = 0; i < 4; i++) {              // small sub-steps keep it stable at low frame rates
      velocity += (-stiffness * (value - target) - friction * velocity) * dt / 4;
      value += velocity * dt / 4;
    }
    if (Math.abs(target - value) < precision && Math.abs(velocity) < precision * 10) {
      value = target; velocity = 0; raf = 0;
    } else raf = requestAnimationFrame(step);
    onFrame(value);
  }
  return {
    get value() { return value; },
    set(t) {
      target = t;
      if (reducedMotion.matches) { value = t; velocity = 0; onFrame(value); return; }
      if (!raf) { last = performance.now(); raf = requestAnimationFrame(step); }
    },
    // puts the value straight at t with no motion, e.g. while the user drags it 1:1
    jump(t) {
      if (raf) cancelAnimationFrame(raf);
      raf = 0; value = target = t; velocity = 0;
      onFrame(value);
    },
    // moves the value by delta at once (velocity kept) and lets it settle back to the target
    shift(delta) {
      value += delta;
      onFrame(value);
      this.set(target);
    },
  };
}

// A circular gauge in the style of Apple's activity rings: the track is the ring's own colour, faint.
// ring.set(percent, label) springs the arc and counts the number along with it.
export function ring({ color = "var(--accent)", size = 92, stroke = 10 } = {}) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, mid = size / 2;
  const arc = h("circle", { cx: mid, cy: mid, r, fill: "none", stroke: color, "stroke-width": stroke,
    "stroke-linecap": "round", "stroke-dasharray": c, "stroke-dashoffset": c, transform: `rotate(-90 ${mid} ${mid})` });
  const num = h("span", {}, "0"), unit = h("small", {}, "%");
  const text = h("div", { class: "ring-text" }, num, unit);
  const el = h("div", { class: "ring", style: { width: size + "px", height: size + "px" } },
    h("svg", { width: size, height: size, viewBox: `0 0 ${size} ${size}` },
      h("circle", { cx: mid, cy: mid, r, fill: "none", stroke: color, opacity: 0.2, "stroke-width": stroke }), arc),
    text);
  let label = null;
  const s = spring(0, p => {
    arc.setAttribute("stroke-dashoffset", c * (1 - Math.max(0.004, p) / 100));  // a dot stays visible at 0
    if (label == null) num.textContent = Math.round(p);
  });
  return {
    el,
    set(pct, newLabel) {
      label = newLabel != null ? newLabel : null;
      if (label != null) { num.textContent = label; unit.textContent = ""; } else unit.textContent = "%";
      s.set(Math.max(0, Math.min(100, pct || 0)));
    },
  };
}

// A line chart of the last `seconds` of values (0-100) over a fading gradient, like Apple's Stocks.
// spark.push(value) adds a sample. It plays back a moment in the past (`delay`, by default 1.5 sample intervals)
// and places every sample by its time, so the line scrolls at a steady speed and its head grows toward the next
// sample instead of the whole chart jumping each time data arrives. It redraws only when the line has moved a
// whole pixel, and at most `fps` times a second.
let gradients = 0;
export function sparkline({ color = "var(--accent)", seconds = 20, height = 60, delay, fps = 30 } = {}) {
  const samples = [];                       // { t, v }, oldest first
  const w = 300, id = `spark-grad-${++gradients}`;
  const line = h("polyline", { fill: "none", stroke: color, "stroke-width": 2, "vector-effect": "non-scaling-stroke",
    "stroke-linejoin": "round", "stroke-linecap": "round" });
  const area = h("polygon", { fill: `url(#${id})` });
  const el = h("svg", { class: "spark", viewBox: `0 0 ${w} ${height}`, preserveAspectRatio: "none" },
    h("defs", {}, h("linearGradient", { id, x1: 0, y1: 0, x2: 0, y2: 1 },
      h("stop", { offset: 0, style: { stopColor: color, stopOpacity: 0.22 } }),
      h("stop", { offset: 1, style: { stopColor: color, stopOpacity: 0 } }))),
    area, line);
  const y = v => (height - 2 - v / 100 * (height - 6)).toFixed(1);
  const span = seconds * 1000;                             // ms across the full width
  let interval = 1000, raf = 0, drawnAt = -1, lastFrame = 0;

  function draw(now) {
    raf = requestAnimationFrame(draw);
    if (samples.length < 2 || document.hidden || now - lastFrame < 1000 / fps - 2) return;
    const T = now - (delay != null ? delay : interval * 1.5);
    const minMove = span / Math.max(1, el.getBoundingClientRect().width);   // one screen pixel, in ms
    if (Math.abs(T - drawnAt) < minMove) return;
    drawnAt = T;
    lastFrame = now;
    const x = t => w - (T - t) / span * w;
    const pts = [];
    let i = 0;
    while (i < samples.length && samples[i].t <= T) i++;   // samples[i] is the first one still in the future
    for (let k = 0; k < i; k++) pts.push([x(samples[k].t), samples[k].v]);
    if (i > 0 && i < samples.length) {                      // the head: part-way along to the next sample
      const a = samples[i - 1], b = samples[i], f = (T - a.t) / (b.t - a.t);
      pts.push([w, a.v + (b.v - a.v) * f]);
    }
    if (!pts.length) return;
    const s = pts.map(([px, v]) => `${px.toFixed(1)},${y(v)}`).join(" ");
    line.setAttribute("points", s);
    area.setAttribute("points", `${pts[0][0].toFixed(1)},${height} ${s} ${pts[pts.length - 1][0].toFixed(1)},${height}`);
    while (samples.length > 2 && x(samples[1].t) < 0) samples.shift();   // keep one point just past the left edge
  }

  return {
    el,
    push(v) {
      const t = performance.now();
      if (samples.length) interval = interval * 0.7 + (t - samples[samples.length - 1].t) * 0.3;   // learns the poll rate
      samples.push({ t, v: Math.max(0, Math.min(100, v || 0)) });
      if (!raf) raf = requestAnimationFrame(draw);
    },
  };
}

// Inline icons (24x24, stroke).
const ICONS = {
  power: "M12 3v9M6.3 6.3a8 8 0 1 0 11.4 0",
  mic_off: "M3 3l18 18M9 9v3a3 3 0 0 0 5.1 2.1M15 9.3V5a3 3 0 0 0-5.9-.7M19 11a7 7 0 0 1-1.2 3.9M5 11a7 7 0 0 0 11 5.7M12 18v3",
  deaf: "M3 3l18 18M4 15v-3a8 8 0 0 1 12.9-6.3M20 12v3M4 15a2 2 0 0 0 2 2h1v-5H5M20 15a2 2 0 0 1-2 2h-1v-5h2",
  headset: "M4 15v-3a8 8 0 0 1 16 0v3M4 15a2 2 0 0 0 2 2h1v-5H5a1 1 0 0 0-1 1M20 15a2 2 0 0 1-2 2h-1v-5h2a1 1 0 0 1 1 1",
  bulb: "M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.8.8 1 1.5 1 2.5h6c0-1 .2-1.7 1-2.5A6 6 0 0 0 12 3z",
  chip: "M7 7h10v10H7zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  down: "M12 5v14M5 12l7 7 7-7",
  up: "M12 19V5M5 12l7-7 7 7",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  chat: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
  gear: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  terminal: "M4 17l6-6-6-6M12 19h8",
  calendar: "M3 6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 10h18M8 2v4M16 2v4",
};
export function icon(name, size = 18) {
  return h("svg", { class: "icon", width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round" }, h("path", { d: ICONS[name] || "" }));
}

// A widget's options with the defaults from its meta.settings filled in.
export function withDefaults(meta, options = {}) {
  const out = {};
  for (const f of meta.settings || []) out[f.key] = f.default;
  return Object.assign(out, options);
}

// The standard tile header: icon + title on the left, optional element on the right.
export function header(title, iconName, right) {
  return h("header", { class: "tile-head" },
    h("div", { class: "tile-title" }, iconName ? icon(iconName, 16) : null, h("span", {}, title)),
    right || null);
}
