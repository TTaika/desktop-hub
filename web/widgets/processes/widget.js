// The busiest apps, like Task Manager's Processes tab (grouped by exe). The CPU / Memory switch picks the sort.
// options: { sort: "cpu" | "mem", count: 7 }
import { h, fmtBytes, header, spring } from "../../lib.js";

export const css = true;
export const meta = { name: "Processes", description: "Busiest apps by CPU or memory", defaultSize: "2x2", minSize: "2x2", maxSize: "3x4" };

export function mount(el, { options, api }) {
  let sort = options.sort === "mem" ? "mem" : "cpu";
  let last = null;

  // Segmented control: the thumb slides to the chosen side on a spring.
  const thumb = h("div", { class: "seg-thumb" });
  const segs = { cpu: h("button", { class: "seg-opt" }, "CPU"), mem: h("button", { class: "seg-opt" }, "Memory") };
  const slide = spring(sort === "cpu" ? 0 : 1, p => { thumb.style.left = `${2 + p * 50}%`; }, { response: 0.35 });
  const choose = (s) => {
    sort = s;
    segs.cpu.classList.toggle("on", s === "cpu");
    segs.mem.classList.toggle("on", s === "mem");
    slide.set(s === "cpu" ? 0 : 1);
    render();
  };
  // react on press, not on release
  Object.entries(segs).forEach(([k, b]) => b.addEventListener("mousedown", () => choose(k)));
  const seg = h("div", { class: "seg" }, thumb, segs.cpu, segs.mem);

  const list = h("div", { class: "proc-list" });
  el.append(header("Processes", "list", seg), list);

  // Rows are kept and refilled, so each bar springs from its old length instead of being rebuilt.
  const rows = [];
  function row(i) {
    if (rows[i]) return rows[i];
    const bar = h("div", { class: "proc-bar" });
    const r = { bar, name: h("span", { class: "proc-name" }), val: h("span", { class: "proc-val num" }) };
    r.el = h("div", { class: "proc-row" }, bar, r.name, r.val);
    r.width = spring(0, w => { bar.style.width = `${w}%`; });
    list.append(r.el);
    return rows[i] = r;
  }

  function render() {
    if (!last) return;
    const data = (sort === "cpu" ? last.by_cpu : last.by_mem).slice(0, options.count || 7);
    const value = r => sort === "cpu" ? r.cpu : r.mem;
    const max = Math.max(...data.map(value), sort === "cpu" ? 10 : 1);
    data.forEach((d, i) => {
      const r = row(i);
      r.name.replaceChildren(d.name, d.count > 1 ? h("span", { class: "proc-count" }, ` ${d.count}`) : "");
      r.val.textContent = sort === "cpu" ? `${d.cpu.toFixed(1)}%` : fmtBytes(d.mem);
      r.width.set(value(d) / max * 100);
    });
    rows.slice(data.length).forEach(r => { r.el.remove(); });
    rows.length = Math.min(rows.length, data.length);
  }

  choose(sort);
  api.poll("system", options.interval || 3000, (d) => {
    if (!d) { list.replaceChildren(h("div", { class: "tile-empty" }, "Hub backend is offline")); rows.length = 0; return; }
    last = d;
    render();
  }, { view: "processes" });
}
