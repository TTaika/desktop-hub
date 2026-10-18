// A todo.txt list (providers/todo.py): open tasks by deadline, their +tags, tick them off or add one.
// The same file is edited on other devices (sleek, Markor) and synced by Syncthing.
// options (also set from the editor, see meta.settings): { tag: "work", done: false, add: true, interval: 3000 }
import { h, header, icon, withDefaults } from "../../lib.js";

export const css = true;
export const meta = {
  name: "To-do", description: "Tasks from a todo.txt file: deadlines and tags",
  defaultSize: "2x2", minSize: "2x1", maxSize: "4x4",
  settings: [
    { key: "tag", label: "Only tasks tagged (+tag or @context, empty = all)", type: "text", placeholder: "work", default: "" },
    { key: "done", label: "Show tasks done today", type: "bool", default: true },
    { key: "add", label: "Add field", type: "bool", default: true },
  ],
};

const DAY = 86400000;
const startOfDay = d => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
const isoToday = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };

// "Overdue 3d" / "Today" / "Tomorrow" / "Fri" / "25 Oct", and how urgent it is.
function dueLabel(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const due = new Date(y, m - 1, d);
  const days = Math.round((due.getTime() - startOfDay(new Date())) / DAY);
  if (days < 0) return [`${-days}d overdue`, "late"];
  if (days === 0) return ["Today", "today"];
  if (days === 1) return ["Tomorrow", "soon"];
  if (days < 7) return [due.toLocaleDateString("en-GB", { weekday: "short" }), "week"];
  return [due.toLocaleDateString("en-GB", { day: "numeric", month: "short" }), "later"];
}

function sortKey(t) {
  return [t.done ? 1 : 0, t.due || "9999", t.priority || "Z", t.id];
}
function cmp(a, b) {
  const x = sortKey(a), y = sortKey(b);
  for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1;
  return 0;
}

export function mount(el, { options, api, size }) {
  const o = withDefaults(meta, options);
  const filter = String(o.tag || "").trim().replace(/^[+@]/, "").toLowerCase();
  const summary = h("div", { class: "td-summary" });
  const banner = h("div", { class: "td-banner" });
  const list = h("div", { class: "td-list" });
  const input = h("input", { class: "td-input", type: "text", spellcheck: "false",
    placeholder: filter ? `Add a task (gets +${filter})` : "Add a task  +tag due:fri",
    onkeydown: e => { if (e.key === "Enter") add(); if (e.key === "Escape") input.blur(); } });
  const addRow = h("div", { class: "td-add" }, h("span", { class: "td-plus" }, "+"), input);
  el.classList.toggle("td-compact", size.h < 2);
  el.append(...[header(filter ? `To-do · ${filter}` : "To-do", "check", summary), banner, list,
    o.add && size.h >= 2 && addRow].filter(Boolean));

  const rows = new Map();                    // line text (+ #n for repeats) -> row; a line edited elsewhere is a new row
  let poller, busy = false;

  async function send(body) {
    if (busy) return;
    busy = true;
    try {
      const r = await api.post("todo", body);
      banner.textContent = r.error && r.error !== "changed" ? r.error : "";
    } catch (e) { banner.textContent = "Hub backend is offline"; }
    busy = false;
    poller.now();
  }

  function add() {
    let text = input.value.trim();
    if (!text) return;
    const tagged = text.split(/\s+/).some(w => /^[+@]/.test(w) && w.slice(1).toLowerCase() === filter);
    if (filter && !tagged) text += ` +${filter}`;
    input.value = "";
    send({ action: "add", text });
  }

  function row(t) {
    let r = rows.get(t.key);
    if (r) return r;
    r = {
      check: h("button", { class: "td-check press", title: "Done / not done", onclick: () => send({ action: "toggle", id: r.t.id, raw: r.t.raw }) },
        icon("check", 13)),
      text: h("div", { class: "td-text" }), meta: h("div", { class: "td-meta" }), due: h("span", { class: "td-due num" }),
    };
    r.del = h("button", { class: "td-del press", title: "Delete", onclick: () => send({ action: "delete", id: r.t.id, raw: r.t.raw }) }, "×");
    r.el = h("div", { class: "td-row td-enter" }, r.check, h("div", { class: "td-main" }, r.text, r.meta), r.due, r.del);
    r.el.addEventListener("animationend", () => r.el.classList.remove("td-enter"));
    rows.set(t.key, r);
    return r;
  }

  function render(d) {
    if (!d.exists) {
      rows.clear();
      summary.replaceChildren();
      list.replaceChildren(h("div", { class: "tile-empty" }, "No todo.txt yet", h("br"), h("small", {}, d.file),
        h("br"), h("small", {}, "Add a task below, or set todo.file in config.json")));
      return;
    }
    const today = isoToday();
    const shown = d.tasks
      .filter(t => !filter || t.tags.concat(t.contexts).some(x => x.toLowerCase() === filter))
      .filter(t => !t.done || (o.done && t.completed === today))
      .sort(cmp);
    const open = shown.filter(t => !t.done);
    const late = open.filter(t => t.due && t.due < today).length, due = open.filter(t => t.due === today).length;
    summary.replaceChildren(...[
      late && h("span", { class: "td-count c-late" }, `${late} overdue`),
      due && h("span", { class: "td-count c-today" }, `${due} today`),
      !late && !due && h("span", { class: "td-count" }, `${open.length} open`),
    ].filter(Boolean));
    if (d.conflicts.length && !banner.textContent)
      banner.textContent = `Sync conflict: ${d.conflicts.length === 1 ? d.conflicts[0] : d.conflicts.length + " copies"} next to todo.txt`;
    else if (!d.conflicts.length && banner.textContent.startsWith("Sync conflict")) banner.textContent = "";

    const seen = {};
    shown.forEach(t => { seen[t.raw] = (seen[t.raw] || 0) + 1; t.key = `${t.raw}#${seen[t.raw]}`; });
    const keep = new Set(shown.map(t => t.key));
    for (const [key, r] of rows) if (!keep.has(key)) { r.el.remove(); rows.delete(key); }
    shown.forEach((t, i) => {
      const r = row(t);
      r.t = t;
      r.el.classList.toggle("td-done", t.done);
      r.text.textContent = t.text || t.raw;
      r.el.title = t.raw;
      const [label, urgency] = t.due && !t.done ? dueLabel(t.due) : ["", ""];
      r.due.textContent = label;
      r.due.className = `td-due num u-${urgency}`;
      r.meta.replaceChildren(...[
        t.priority && !t.done ? h("span", { class: `td-pri p-${t.priority}` }, t.priority) : null,
        ...t.tags.filter(x => x.toLowerCase() !== filter).map(x => h("span", { class: "td-tag" }, `+${x}`)),
        ...t.contexts.filter(x => x.toLowerCase() !== filter).map(x => h("span", { class: "td-ctx" }, `@${x}`)),
      ].filter(Boolean));
      r.meta.style.display = r.meta.childElementCount ? "" : "none";
      if (list.children[i] !== r.el) list.insertBefore(r.el, list.children[i] || null);
    });
    const empty = list.querySelector(".tile-empty");
    if (!shown.length) { if (!empty) list.append(h("div", { class: "tile-empty" }, filter ? `Nothing tagged ${filter}` : "Nothing to do")); }
    else if (empty) empty.remove();
  }

  poller = api.poll("todo", o.interval || 3000, d => {
    if (!d) { rows.clear(); list.replaceChildren(h("div", { class: "tile-empty" }, "Hub backend is offline")); return; }
    if (d.error) { banner.textContent = d.error; return; }
    render(d);
  });
}
