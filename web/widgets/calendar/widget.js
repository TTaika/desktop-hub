// Your Google Calendar (through the voice assistant's login): today, this week, or this month.
// Day and week are time grids, so the free and busy hours show at a glance; month shows each day's busy hours
// as a small strip. Hovering an event (or a day of the month) shows its details.
// options (also set from the editor, see meta.settings): { view: "day" | "week" | "month", locale: "en-GB" }
import { h, header, withDefaults } from "../../lib.js";

export const css = true;
export const meta = {
  name: "Calendar", description: "Today, this week or this month from Google Calendar", defaultSize: "2x2",
  minSize: "2x1", maxSize: "4x4",
  settings: [
    { key: "view", label: "Show", type: "select", choices: [["day", "Today"], ["week", "This week"], ["month", "This month"]],
      default: "week" },
    { key: "locale", label: "Language for dates (e.g. en-GB, fi-FI)", type: "text", default: "en-GB" },
  ],
};

const DAY = 86400000, HOUR = 3600000;
const dayKey = d => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
const startOfDay = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

export function mount(el, { options, api, size }) {
  const o = withDefaults(meta, options);
  const L = o.locale || "en-GB";
  const time = d => d.toLocaleTimeString(L, { hour: "2-digit", minute: "2-digit" });
  const right = h("span", { class: "num" });
  const body = h("div", { class: "cal-body" });
  el.append(header("Calendar", "calendar", right), body);
  el.classList.add(`cal-view-${o.view}`);
  let data = null;

  const events = () => data.events.map(e => ({ ...e, s: new Date(e.start), e: new Date(e.end) }));
  const onDay = (list, day) => list.filter(e => e.s < addDays(day, 1) && e.e > day);
  const color = e => e.color || "var(--accent)";

  // The hours the grids show: at least 8-20, widened to fit every timed event in view.
  function hourRange(list) {
    let lo = 8, hi = 20;
    for (const e of list) {
      if (e.all_day) continue;
      const sameDay = dayKey(e.s) === dayKey(e.e) || e.e - startOfDay(e.e) === 0;
      lo = Math.min(lo, e.s.getHours());
      hi = Math.max(hi, sameDay ? (e.e.getHours() + (e.e.getMinutes() ? 1 : 0)) || 24 : 24);
    }
    return [lo, Math.min(hi, 24)];
  }

  // A day's timed events as blocks; events that overlap share the width side by side.
  // Overlaps that need more than maxLanes side by side become one block ("+N"); hovering it lists them all.
  function blocks(day, list, [lo, hi], now, withText, maxLanes) {
    const t0 = day.getTime() + lo * HOUR, span = (hi - lo) * HOUR;
    const timed = list.filter(e => !e.all_day).sort((a, b) => a.s - b.s || b.e - a.e);
    const out = [], groups = [];
    let cluster = [], clusterEnd = 0;
    const flush = () => {
      const lanes = [];
      for (const e of cluster) {
        let i = lanes.findIndex(end => end <= e.s);
        if (i < 0) { i = lanes.length; lanes.push(0); }
        lanes[i] = e.e;
        e.lane = i;
      }
      if (lanes.length > maxLanes) {
        const first = cluster[0];
        groups.push({ ...first, s: first.s, e: new Date(Math.max(...cluster.map(x => x.e))), lane: 0, lanes: 1,
          members: cluster.slice() });
      } else {
        for (const e of cluster) { e.lanes = lanes.length; groups.push(e); }
      }
      cluster = [];
    };
    for (const e of timed) {
      if (cluster.length && e.s >= clusterEnd) flush();
      cluster.push(e);
      clusterEnd = Math.max(clusterEnd, e.e);
    }
    flush();
    for (const e of groups) {
      const top = Math.max(0, (e.s - t0) / span), bottom = Math.min(1, (e.e - t0) / span);
      if (bottom <= 0 || top >= 1) continue;
      const short = (e.e - e.s) < 50 * 60000 || (bottom - top) * (hi - lo) < 0.9;
      const block = h("div", {
        class: `cal-block${e.e <= now ? " past" : ""}${e.s <= now && now < e.e ? " now" : ""}${short ? " short" : ""}`,
        style: {
          top: `${top * 100}%`, height: `calc(${(bottom - top) * 100}% - 2px)`,
          left: `${e.lane / e.lanes * 100}%`, width: `calc(${100 / e.lanes}% - 2px)`,
          background: color(e),
        },
      }, withText ? [
        e.members ? h("span", { class: "cal-more num" }, `+${e.members.length - 1}`) : null,
        h("span", { class: "cal-bt" }, e.title),
        short ? null : h("span", { class: "cal-bs num" }, time(e.s))] : null);
      block._events = e.members || [e];
      out.push(block);
    }
    return out;
  }

  // The hour lines and labels behind a grid, and a line at the current time.
  function hourLines([lo, hi], labels) {
    const out = [];
    const step = (hi - lo) > 14 ? 3 : (hi - lo) > 8 ? 2 : 1;
    for (let hr = lo; hr <= hi; hr++) {
      const y = `${(hr - lo) / (hi - lo) * 100}%`;
      out.push(h("div", { class: "cal-line", style: { top: y } }));
      if (labels && hr % step === 0 && hr < hi)
        out.push(h("span", { class: "cal-hour num", style: { top: y } }, String(hr).padStart(2, "0")));
    }
    return out;
  }
  function nowLine(day, [lo, hi], now) {
    const f = (now - day.getTime() - lo * HOUR) / ((hi - lo) * HOUR);
    return f >= 0 && f <= 1 ? h("div", { class: "cal-now", style: { top: `${f * 100}%` } }) : null;
  }

  function allDayRow(list) {
    const all = list.filter(e => e.all_day);
    if (!all.length) return null;
    return h("div", { class: "cal-chips" }, all.map(e => {
      const chip = h("span", { class: "cal-chip", style: { background: color(e) } }, e.title);
      chip._events = [e];
      return chip;
    }));
  }

  function renderDay(now) {
    const today = startOfDay(now), list = onDay(events(), today), range = hourRange(list);
    right.textContent = now.toLocaleDateString(L, { weekday: "short", day: "numeric", month: "short" });
    const col = h("div", { class: "cal-col" }, blocks(today, list, range, now, true, 4), nowLine(today, range, now));
    return [
      allDayRow(list),
      h("div", { class: "cal-grid" }, h("div", { class: "cal-lines" }, hourLines(range, true)), h("div", { class: "cal-cols" }, col)),
      list.length ? null : h("div", { class: "cal-free" }, "Free all day"),
    ];
  }

  function renderWeek(now) {
    const start = new Date(data.start), list = events(), today = startOfDay(now), range = hourRange(list);
    right.textContent = `Week ${weekNumber(start)}`;
    const heads = [], tops = [], cols = [];
    for (let i = 0; i < 7; i++) {
      const day = addDays(start, i), evs = onDay(list, day);
      const cls = `${dayKey(day) === dayKey(today) ? " today" : ""}${day < today ? " past" : ""}`;
      heads.push(h("div", { class: `cal-wh${cls}` },
        h("span", { class: "cal-wd" }, day.toLocaleDateString(L, { weekday: "narrow" })),
        h("span", { class: "cal-dn num" }, String(day.getDate()))));
      const all = evs.filter(e => e.all_day);
      const top = h("div", { class: "cal-wa" }, all.slice(0, 2).map(e => h("i", { style: { background: color(e) } })));
      top._events = all;
      tops.push(top);
      cols.push(h("div", { class: `cal-col${cls}` }, blocks(day, evs, range, now, true, size && size.w >= 4 ? 3 : 1),
        dayKey(day) === dayKey(today) ? nowLine(day, range, now) : null));
    }
    const anyAllDay = list.some(e => e.all_day);
    return [
      h("div", { class: "cal-row cal-heads" }, heads),
      anyAllDay ? h("div", { class: "cal-row cal-alldays" }, tops) : null,
      h("div", { class: "cal-grid" }, h("div", { class: "cal-lines" }, hourLines(range, true)), h("div", { class: "cal-cols" }, cols)),
    ];
  }

  function renderMonth(now) {
    const start = new Date(data.start), end = new Date(data.end), list = events(), today = startOfDay(now);
    const range = hourRange(list);
    right.textContent = now.toLocaleDateString(L, { month: "long", year: "numeric" });
    const heads = [];
    for (let i = 0; i < 7; i++)
      heads.push(h("span", { class: "cal-mh" }, addDays(start, i).toLocaleDateString(L, { weekday: "narrow" })));
    const cells = [];
    for (let d = new Date(start); d < end; d = addDays(d, 1)) {
      const evs = onDay(list, d), all = evs.filter(e => e.all_day);
      const cell = h("div", { class: `cal-cell${d.getMonth() !== now.getMonth() ? " out" : ""}${dayKey(d) === dayKey(today) ? " today" : ""}${d < today ? " past" : ""}` },
        h("div", { class: "cal-ch" },
          h("span", { class: "cal-num num" }, String(d.getDate())),
          h("span", { class: "cal-ad" }, all.slice(0, 3).map(e => h("i", { style: { background: color(e) } })))),
        h("div", { class: "cal-strip" }, blocks(d, evs, range, now, false, 3)));
      cell._events = evs;
      cell._day = d;
      cells.push(cell);
    }
    return [h("div", { class: "cal-mheads" }, heads), h("div", { class: "cal-month", style: { gridTemplateRows: `repeat(${cells.length / 7}, 1fr)` } }, cells)];
  }

  // Details on hover: an event's time, calendar, place and notes, or every event of a month day.
  const tip = h("div", { class: "cal-tip" });
  function dayItem(e) {                          // one line per event in a month day's list
    return h("div", { class: "cal-tip-item" },
      h("i", { style: { background: color(e) } }),
      h("span", { class: "cal-tip-time num" }, e.all_day ? "All day" : time(e.s)),
      h("span", { class: "cal-tip-name" }, e.title, e.location ? h("span", { class: "cal-tip-loc" }, " · " + e.location) : null));
  }
  function details(e) {
    const sameDay = dayKey(e.s) === dayKey(new Date(e.e.getTime() - 1));
    const when = e.all_day
      ? (sameDay ? e.s.toLocaleDateString(L, { weekday: "long", day: "numeric", month: "long" })
                 : `${e.s.toLocaleDateString(L, { day: "numeric", month: "short" })} – ${new Date(e.e.getTime() - 1).toLocaleDateString(L, { day: "numeric", month: "short" })}`)
      : `${e.s.toLocaleDateString(L, { weekday: "short", day: "numeric", month: "short" })}, ${time(e.s)}–${time(e.e)} · ${duration(e.e - e.s)}`;
    return h("div", { class: "cal-tip-ev" },
      h("div", { class: "cal-tip-title" }, h("i", { style: { background: color(e) } }), h("span", null, e.title)),
      h("div", { class: "cal-tip-row num" }, when),
      e.location ? h("div", { class: "cal-tip-row" }, "📍 " + e.location) : null,
      e.calendar ? h("div", { class: "cal-tip-row faint" }, e.calendar) : null,
      e.description ? h("div", { class: "cal-tip-desc" }, e.description.replace(/<[^>]+>/g, " ")) : null);
  }
  function showTip(target) {
    const evs = target._events || [];
    if (!evs.length && !target._day) return hideTip();
    tip.replaceChildren(...[
      target._day ? h("div", { class: "cal-tip-day" }, target._day.toLocaleDateString(L, { weekday: "long", day: "numeric", month: "long" })) : null,
      evs.length ? evs.slice(0, 8).map(target._day ? dayItem : details) : h("div", { class: "cal-tip-row faint" }, "Nothing planned"),
      evs.length > 8 ? h("div", { class: "cal-tip-row faint" }, `+${evs.length - 8} more`) : null,
    ].flat().filter(Boolean));
    if (!tip.parentNode) document.body.append(tip);
    const r = target.getBoundingClientRect(), W = window.innerWidth, H = window.innerHeight;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let x = r.right + 10, y = r.top;
    if (x + tw > W - 8) x = r.left - tw - 10;          // no room on the right: the left side
    if (x < 8) x = Math.min(Math.max(8, r.left), W - tw - 8);
    y = Math.min(Math.max(8, y), H - th - 8);
    tip.style.left = x + "px";
    tip.style.top = y + "px";
    tip.classList.add("show");
  }
  function hideTip() { tip.classList.remove("show"); }
  let hovered = null;
  body.addEventListener("mouseover", ev => {
    let t = ev.target;
    while (t && t !== body && !t._events) t = t.parentNode;
    if (t === body || !t) t = null;
    if (t === hovered) return;
    hovered = t;
    t ? showTip(t) : hideTip();
  });
  body.addEventListener("mouseleave", () => { hovered = null; hideTip(); });

  function render() {
    if (!data) return;
    hovered = null;
    hideTip();
    if (data.error) { right.textContent = ""; body.replaceChildren(h("div", { class: "tile-empty" }, data.error)); return; }
    const now = new Date();
    const parts = o.view === "day" ? renderDay(now) : o.view === "month" ? renderMonth(now) : renderWeek(now);
    body.replaceChildren(...parts.filter(Boolean));
  }

  api.poll("calendar", 300000, (d, err) => {
    if (err) console.error("calendar: " + String(err));
    data = d || { error: "Hub backend is offline" };
    render();
  }, { view: o.view });
  // The time line and the dimming of past events move on with the clock, between data updates
  const tick = setInterval(() => {
    if (!el.isConnected) { clearInterval(tick); tip.remove(); }
    else if (!hovered) render();
  }, 60000);
}

function duration(ms) {
  const m = Math.round(ms / 60000), hh = Math.floor(m / 60), mm = m % 60;
  return hh && mm ? `${hh} h ${mm} min` : hh ? `${hh} h` : `${mm} min`;
}

function weekNumber(d) {                        // ISO week number
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
  return Math.ceil(((t - Date.UTC(t.getUTCFullYear(), 0, 1)) / DAY + 1) / 7);
}
