// Gauges (CPU, RAM, GPU, VRAM, disk), a scrolling load chart, and network and disk rates.
// Every part can be chosen in the editor (⚙ on the tile); the settings are stored as options in layout.json.
import { h, ring, sparkline, fmtBytes, fmtDuration, header, icon, withDefaults } from "../../lib.js";

export const css = true;

const METRICS = { cpu: "CPU", ram: "RAM", gpu: "GPU", vram: "VRAM", disk: "Disk" };
const COLORS = { cpu: "#30d158", ram: "#0a84ff", gpu: "#ff9f0a", vram: "#bf5af2", disk: "#40c8e0" };

export const meta = {
  name: "System", description: "Gauges, a scrolling load chart, network and disk", defaultSize: "4x2", minSize: "2x2", maxSize: "8x3",
  settings: [
    { key: "gauges", label: "Gauges", type: "multi", choices: Object.entries(METRICS), default: ["cpu", "ram", "gpu", "vram"] },
    { key: "chart", label: "Chart lines", type: "multi", choices: [["cpu", "CPU"], ["gpu", "GPU"], ["ram", "RAM"], ["vram", "VRAM"]],
      default: ["cpu", "gpu"] },
    { key: "chart_seconds", label: "Chart history", type: "range", min: 10, max: 120, step: 5, unit: " s", default: 20 },
    { key: "interval", label: "Update every", type: "select", choices: [[500, "0.5 s"], [1000, "1 s"], [2000, "2 s"], [5000, "5 s"]],
      default: 1000 },
    { key: "footer", label: "Network and disk row", type: "bool", default: true },
    { key: "gpu", label: "GPU (part of its name; empty = the busiest)", type: "text", default: "" },
    { key: "colors", label: "Colours", type: "colors", keys: Object.entries(METRICS), palette: COLORS, default: {} },
  ],
};

const shortGpu = name => name.replace(/NVIDIA |GeForce /g, "");

export function mount(el, { options, api }) {
  const o = withDefaults(meta, options);
  const color = k => (o.colors && o.colors[k]) || COLORS[k];
  const gaugeKeys = o.gauges.filter(k => METRICS[k]);
  const chartKeys = o.chart.filter(k => METRICS[k]);

  const gauges = {}, subs = {};
  const gaugeRow = h("div", { class: "sys-gauges", style: { gridTemplateColumns: `repeat(${gaugeKeys.length}, 1fr)` } },
    gaugeKeys.map(k => {
      gauges[k] = ring({ color: color(k) });
      return h("div", { class: "sys-gauge" }, gauges[k].el,
        h("div", { class: "sys-label t-caption" }, METRICS[k].toUpperCase()),
        subs[k] = h("div", { class: "sys-sub t-caption num" }));
    }));

  const sparks = {};
  chartKeys.forEach(k => { sparks[k] = sparkline({ color: color(k), seconds: o.chart_seconds }); });
  const legend = h("div", { class: "sys-legend t-caption" },
    chartKeys.map(k => h("span", { style: { color: color(k) } }, `● ${METRICS[k]}`)));
  // later lines draw on top, so the first one chosen stays the most visible
  const chart = h("div", { class: "sys-chart" }, chartKeys.slice().reverse().map(k => sparks[k].el), legend);

  const net = h("div", { class: "sys-stat num" });
  const disk = h("div", { class: "sys-stat num" });
  const other = h("div", { class: "sys-stat num" });
  const uptime = h("span", { class: "num" });

  el.append(...[header("System", "chip", uptime),
    gaugeKeys.length && gaugeRow,
    chartKeys.length && chart,
    o.footer && h("div", { class: "sys-footer t-caption" }, net, disk, other)].filter(Boolean));
  el.classList.toggle("sys-no-chart", !chartKeys.length);

  const pickGpu = (gpus) => {
    if (!gpus.length) return null;
    const want = (o.gpu || "").toLowerCase();
    return gpus.find(g => want && g.name.toLowerCase().includes(want)) || [...gpus].sort((a, b) => b.util - a.util)[0];
  };

  api.poll("system", Number(o.interval) || 1000, (d) => {
    if (!d) { uptime.textContent = "offline"; return; }
    const g = pickGpu(d.gpus);
    const values = {
      cpu: d.cpu.percent,
      ram: d.ram.percent,
      gpu: g ? g.util : 0,
      vram: g && g.mem_total ? g.mem_used / g.mem_total * 100 : 0,
      disk: d.disk.c_percent,
    };
    const details = {
      cpu: d.cpu.name.replace(/\(R\)|\(TM\)|CPU|Processor|\d+-Core/gi, "").replace(/\s+/g, " ").trim(),
      ram: `${fmtBytes(d.ram.used)} of ${fmtBytes(d.ram.total, 0)}`,
      gpu: g ? `${shortGpu(g.name)} · ${g.temp != null ? g.temp : "–"}°` : "No GPU",
      vram: g ? `${fmtBytes(g.mem_used)} of ${fmtBytes(g.mem_total, 0)}` : "",
      disk: "C: used",
    };
    gaugeKeys.forEach(k => { gauges[k].set(values[k]); subs[k].textContent = details[k]; });
    chartKeys.forEach(k => sparks[k].push(values[k]));

    if (o.footer) {
      net.replaceChildren(icon("down", 13), ` ${fmtBytes(d.net.down)}/s   `, icon("up", 13), ` ${fmtBytes(d.net.up)}/s`);
      disk.textContent = `Disk  ${fmtBytes(d.disk.read)}/s read · ${fmtBytes(d.disk.write)}/s write`;
      const others = d.gpus.filter(x => x !== g);
      other.textContent = others.map(x => `${shortGpu(x.name)} ${x.util}% · ${x.temp}°`).join("   ")
        || `C: ${d.disk.c_percent}% full`;
    }
    uptime.textContent = `Up ${fmtDuration(d.uptime)}`;
  });
}
