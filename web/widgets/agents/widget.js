// Claude Code agents on this PC: background jobs and open terminals, what each is doing, where, and for how long.
// The ones that need you come first, then the ones still working; finished ones show when they finished.
// providers/agents.py reads Claude Code's own files (~/.claude/jobs, ~/.claude/sessions).
// options (also set from the editor, see meta.settings): { hours: 12, idle: 60, terminals: true, interval: 2000 }
// idle: minutes an idle agent (or one waiting for you) stays listed, 0 = always
import { h, header, withDefaults } from "../../lib.js";

export const css = true;
export const meta = {
  name: "Claude agents", description: "Which Claude Code agents are working, need you, or are done",
  defaultSize: "2x2", minSize: "2x1", maxSize: "4x4",
  settings: [
    { key: "hours", label: "Keep finished agents for", type: "range", min: 0, max: 48, step: 1, unit: " h", default: 12 },
    { key: "idle", label: "Hide idle agents after", type: "range", min: 0, max: 240, step: 15, unit: " min", default: 60 },
    { key: "terminals", label: "Show terminals you have open", type: "bool", default: true },
  ],
};

const STATUS = {                           // label, sort order (lower = higher up)
  input: ["Needs input", 0], working: ["Working", 1], idle: ["Idle", 2],
  stopped: ["Stopped", 3], failed: ["Failed", 4], done: ["Done", 5],
};
const SHORT = { input: "need you", working: "working", idle: "idle" };
const ACTIVE = new Set(["input", "working", "idle"]);
const order = a => STATUS[a.status] ? STATUS[a.status][1] : 9;

function fmtSpan(ms, rough) {          // rough: no seconds past the first minute
  const s = Math.max(0, Math.floor(ms / 1000)), d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600),
    mm = Math.floor(s % 3600 / 60), ss = s % 60;
  if (d) return `${d}d ${hh}h`;
  if (hh) return `${hh}h ${String(mm).padStart(2, "0")}m`;
  if (rough) return mm ? `${mm} min` : `${ss}s`;
  return `${mm}m ${String(ss).padStart(2, "0")}s`;
}

function fmtWhen(ms) {
  const t = new Date(ms), now = new Date();
  const time = t.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (t.toDateString() === now.toDateString()) return time;
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (t.toDateString() === yesterday.toDateString()) return `Yesterday ${time}`;
  return `${t.toLocaleDateString("en-GB", { day: "numeric", month: "short" })} ${time}`;
}

// The status mark: a spinning arc while working, ! when it needs you, a check when done.
function glyph() {
  return h("svg", { class: "ag-glyph", width: 26, height: 26, viewBox: "0 0 26 26" },
    h("circle", { class: "ag-g-track", cx: 13, cy: 13, r: 10.5 }),
    h("circle", { class: "ag-g-arc", cx: 13, cy: 13, r: 10.5 }),
    h("path", { class: "ag-g-mark" }));
}
const MARKS = { done: "M8.5 13.3l3 3 6-6.3", failed: "M9.5 9.5l7 7M16.5 9.5l-7 7", input: "M13 8v6M13 17.6v.1",
  stopped: "M10 10h6v6h-6z", idle: "M9 13h.01M13 13h.01M17 13h.01", working: "" };

export function mount(el, { options, api, size }) {
  const o = withDefaults(meta, options);
  const summary = h("div", { class: "ag-summary" });
  const list = h("div", { class: "ag-list" });
  el.classList.toggle("ag-compact", size.h < 2);
  el.append(header("Claude agents", "terminal", summary), list);
  const rows = new Map();                   // agent id -> row
  let agents = [], skew = 0;                // skew: server clock minus ours, so the timers agree with the server

  function row(a) {
    let r = rows.get(a.id);
    if (r) return r;
    r = { glyph: glyph(), name: h("div", { class: "ag-name" }), cwd: h("div", { class: "ag-cwd" }),
      pill: h("span", { class: "ag-pill" }), time: h("div", { class: "ag-time num" }), status: null };
    r.el = h("div", { class: "ag-row ag-enter" }, r.glyph,
      h("div", { class: "ag-main" }, r.name, r.cwd),
      h("div", { class: "ag-side" }, r.pill, r.time));
    r.el.addEventListener("animationend", () => r.el.classList.remove("ag-enter", "ag-changed"));
    rows.set(a.id, r);
    return r;
  }

  function tick() {
    const now = Date.now() + skew;
    for (const a of agents) {
      const r = rows.get(a.id);
      if (!r) continue;
      if (a.status === "done" || a.status === "failed" || a.status === "stopped") {
        r.time.replaceChildren(h("b", {}, fmtWhen(a.finished)), h("span", {}, ` · took ${fmtSpan(a.finished - a.started, true)}`));
        r.time.title = `Worked ${fmtSpan(a.finished - a.started)} on the last task, finished ${new Date(a.finished).toLocaleString("en-GB")}`;
      } else if (a.status === "input") {
        r.time.replaceChildren(h("span", {}, "waiting "), h("b", {}, fmtSpan(now - a.finished)));
        r.time.title = `Worked ${fmtSpan(a.finished - a.started)}, then asked you something`;
      } else {
        r.time.replaceChildren(h("b", {}, fmtSpan(now - a.started)));
        r.time.title = a.status === "idle" ? "Since the task began; nothing running right now" : "On the current task";
      }
    }
  }

  function render() {
    const shown = agents.filter(a => o.terminals || a.kind !== "terminal");
    const counts = {};
    shown.forEach(a => { counts[a.status] = (counts[a.status] || 0) + 1; });
    summary.replaceChildren(...["input", "working", "idle"].filter(s => counts[s]).map(s =>
      h("span", { class: `ag-count st-${s}`, title: STATUS[s][0] }, h("i"), size.w > 2 ? `${counts[s]} ${s === "input" && counts[s] === 1 ? "needs you" : SHORT[s]}` : String(counts[s]))));
    if (!summary.children.length && shown.length) summary.append(h("span", { class: "ag-count ag-all" }, "All done"));

    const ids = new Set(shown.map(a => a.id));
    for (const [id, r] of rows) if (!ids.has(id)) { r.el.remove(); rows.delete(id); }
    shown.forEach((a, i) => {
      const r = row(a);
      if (r.status && r.status !== a.status) r.el.classList.add("ag-changed");
      r.status = a.status;
      r.el.className = r.el.className.replace(/\bst-\S+/g, "").trim() + ` st-${a.status}`;
      r.glyph.querySelector(".ag-g-mark").setAttribute("d", MARKS[a.status] || "");
      r.name.textContent = a.name;
      r.cwd.textContent = `‎${a.cwd}‎`;       // keeps ~\ at the start under direction: rtl
      r.cwd.title = a.cwd;
      r.pill.textContent = STATUS[a.status] ? STATUS[a.status][0] : a.status;
      const what = a.status === "done" && a.result ? a.result : a.detail;
      r.el.title = [a.name, a.kind === "terminal" ? "Terminal" : "Background job", what].filter(Boolean).join("\n");
      if (list.children[i] !== r.el) list.insertBefore(r.el, list.children[i] || null);
    });
    if (!shown.length) list.replaceChildren(h("div", { class: "tile-empty" }, "No Claude Code agents right now"));
    else { const empty = list.querySelector(".tile-empty"); if (empty) empty.remove(); }
    tick();
  }

  api.poll("agents", o.interval || 2000, d => {
    if (!d) { agents = []; rows.clear(); list.replaceChildren(h("div", { class: "tile-empty" }, "Hub backend is offline")); return; }
    skew = d.now - Date.now();
    agents = d.agents.slice().sort((a, b) =>
      order(a) - order(b) ||
      (ACTIVE.has(a.status) ? a.started - b.started : b.finished - a.finished));
    render();
  }, { hours: o.hours, idle: o.idle });

  const timer = setInterval(() => { if (!el.isConnected) clearInterval(timer); else if (!document.hidden) tick(); }, 1000);
}
