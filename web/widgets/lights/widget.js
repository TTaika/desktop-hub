// The Airam smart bulbs: power, brightness, white tone, colour and saved scenes.
// options (also set from the editor, see meta.settings): { name: "all", rows: ["temps", "colours", "scenes"] }
import { h, header, icon, spring, withDefaults } from "../../lib.js";

export const css = true;
const ROWS = { temps: "White tones", colours: "Colours", scenes: "Scenes" };

export const meta = {
  name: "Lights", description: "Smart bulbs: power, brightness, colour, scenes", defaultSize: "2x2", minSize: "2x1", maxSize: "3x3",
  settings: [
    { key: "name", label: "Bulb or room (as the voice assistant knows it)", type: "text", default: "all" },
    { key: "rows", label: "Rows of buttons (a 2×1 tile fits two)", type: "multi", choices: Object.entries(ROWS),
      default: ["temps", "colours", "scenes"] },
  ],
};

export function mount(el, { options, api, size }) {
  const o = withDefaults(meta, options);
  const target = o.name || "all";
  // One row high: smaller controls, and room for two rows of buttons, scenes first.
  const compact = size && size.h === 1;
  const shown = compact ? ["scenes", "colours", "temps"].filter(k => o.rows.includes(k)).slice(0, 2) : o.rows;
  el.classList.toggle("li-compact", !!compact);
  const status = h("span", { class: "li-status" });
  const power = h("button", { class: "li-power press", title: "On / off", onclick: () => send({ state: isOn() ? "off" : "on" }) },
    icon("power", compact ? 22 : 28));

  // Brightness: a Control Center style pill. An invisible range input on top takes the drag; the fill tracks
  // it 1:1 while dragging and springs to the bulbs' own value when a status update comes in.
  const fill = h("div", { class: "li-fill" });
  const pct = h("span", { class: "li-pct num" });
  const level = spring(0, v => { fill.style.width = `${v}%`; });
  let dragging = false;
  const slider = h("input", { type: "range", min: 1, max: 100, class: "li-range", "aria-label": "Brightness",
    onmousedown: () => { dragging = true; },
    oninput: () => { dragging = true; level.jump(Number(slider.value)); pct.textContent = `${slider.value}%`; },
    onchange: () => { dragging = false; send({ brightness: Number(slider.value) }); } });
  const bright = h("div", { class: "li-bright" }, fill, h("span", { class: "li-sun" }, icon("sun", 18)), pct, slider);

  const temps = h("div", { class: "li-row" });
  const colours = h("div", { class: "li-row li-colours" });
  const scenes = h("div", { class: "li-row" });
  const msg = h("div", { class: "li-msg" });

  const rowEls = { temps, colours, scenes };
  el.append(header("Lights", "bulb", status), h("div", { class: "li-top" }, power, bright),
    ...shown.map(k => rowEls[k]), msg);

  let state = null, busy = false, poller;
  const isOn = () => !!(state && state.lights && state.lights.some(l => l.on));

  async function send(args) {
    if (busy) return;
    busy = true;
    el.classList.add("busy");
    msg.textContent = "";
    try {
      const r = await api.post("lights", { name: target, ...args });
      if (r.error) msg.textContent = r.error;
    } catch (e) {
      msg.textContent = "Hub backend is offline";
    }
    busy = false;
    el.classList.remove("busy");
    setTimeout(() => poller.now(), 600);   // the bulb answers status a moment after a change
  }

  function render(d) {
    state = d;
    const on = isOn();
    el.classList.toggle("on", on);
    const lit = d.lights.filter(l => l.on);
    status.textContent = d.lights.some(l => l.error) ? "Unreachable"
      : on ? (d.lights.length > 1 ? `${lit.length} of ${d.lights.length} on` : "On") : "Off";
    const b = lit.length ? Math.round(lit.reduce((s, l) => s + (l.brightness || 0), 0) / lit.length) : 0;
    if (!dragging) {
      slider.value = b || 1;
      level.set(on ? b : 0);
      pct.textContent = on ? `${b}%` : "Off";
    }
    if (!temps.childElementCount) {
      temps.append(...d.temps.map(t => h("button", { class: `li-chip press li-temp-${t}`, onclick: () => send({ color_temp: t }) },
        h("i", {}), t)));
      colours.append(...Object.entries(d.colours).map(([name, hex]) =>
        h("button", { class: "li-dot press", title: name, style: { background: hex }, onclick: () => send({ color: name }) })));
    }
    scenes.replaceChildren(...d.scenes.map(s => h("button", { class: "li-chip li-scene press", onclick: () => send({ scene: s }) }, s)));
  }

  poller = api.poll("lights", options.interval || 10000, (d) => {
    if (busy) return;
    if (!d) { status.textContent = "Offline"; return; }
    if (d.error) { msg.textContent = d.error; return; }
    render(d);
  });
}
