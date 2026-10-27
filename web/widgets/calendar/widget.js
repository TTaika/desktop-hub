// Your Google Calendar (through the voice assistant's login): today, this week, or this month.
// Day and week are time grids, so the free and busy hours show at a glance. Month lists each day's events by
// name when the tile has room for them (3x2 and up, the whole screen included), and otherwise shows each day's
// busy hours as a small strip. Hovering an event (or a day of the month) shows its details. In the month view the
// arrows beside the month's name step to other months (clicking the name comes back to this one, and so does
// five minutes without a click).
// options (also set from the editor, see meta.settings): { view: "day" | "week" | "month", locale: "en-GB" }
import { h, header, withDefaults } from "../../lib.js";

export const css = true;
export const meta = {
  name: "Calendar", description: "Today, this week or this month from Google Calendar", defaultSize: "2x2",
  minSize: "2x1",                                  // no maxSize: it can take the whole screen
  settings: [
    { key: "view", label: "Show", type: "select", choices: [["day", "Today"], ["week", "This week"], ["month", "This month"]],
      default: "week" },
    { key: "locale", label: "Language for dates (e.g. en-GB, fi-FI)", type: "text", default: "en-GB" },
  ],
  panel: loginPanel,
};

// The Google login, in the editor's Calendar settings: it belongs to the calendar tool, not to layout.json.
// "Log in" opens Google's consent in this PC's browser; the panel follows along until it's done.
function loginPanel({ api, h }) {
  const root = h("div", { class: "cal-login" });
  const note = h("div", { class: "cal-login-note" });
  let timer = 0;

  const show = r => {
    clearTimeout(timer);
    if (!root.isConnected && timer) return;            // the settings were closed
    const st = r.state || "error";
    note.textContent = r.error || r.message || "";
    note.className = `cal-login-note ${st === "ok" || st === "ics" ? "good" : st === "logging_in" ? "" : "bad"}`;
    const file = h("input", { type: "file", accept: ".json,application/json", style: { display: "none" },
      onchange: () => {
        const f = file.files[0];
        if (!f) return;
        const rd = new FileReader();
        rd.onload = () => send({ credentials: String(rd.result) });
        rd.readAsText(f);
      } });
    const btn = (label, cls, onclick, title) => h("button", { class: `cal-login-btn ${cls}`, onclick, title: title || "" }, label);
    const login = st === "logging_in" ? null
      : st === "no_client" || st === "ics" || st === "error" ? null
      : btn(st === "ok" ? "Log in again" : "Log in with Google", st === "ok" ? "" : "primary", () => send({ login: true }));
    const client = st === "logging_in" ? null
      : btn(st === "no_client" ? "Choose the OAuth client file..." : "Replace client file...", st === "no_client" ? "primary" : "",
          () => file.click(), r.credentials ? `Saved as ${r.credentials}` : "");
    root.replaceChildren(...[
      h("div", { class: "cal-login-head" }, "Google login"),
      note,
      h("div", { class: "cal-login-row" }, ...[login, client, file].filter(Boolean)),
      st === "no_client" ? h("div", { class: "cal-login-help" },
        "Google Cloud Console: make a project, enable the Google Calendar API, create an OAuth client of type " +
        "\"Desktop app\" and download its JSON. Then choose that file here and log in.") : null,
    ].filter(Boolean));
    if (st === "logging_in") timer = setTimeout(refresh, 1500);
  };
  const send = body => api.post("calendar", body).then(show, () => show({ error: "The hub's server is offline" }));
  const refresh = () => api.get("calendar", { status: 1 }).then(show, () => show({ error: "The hub's server is offline" }));

  root.append(h("div", { class: "cal-login-note" }, "Checking the calendar login..."));
  refresh();
  return root;
}

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
  let offset = 0, back = 0;                       // months away from this one (month view), and the timer back to it
  const go = n => {
    offset = n ? offset + n : 0;
    clearTimeout(back);
    if (offset) back = setTimeout(() => el.isConnected && go(0), 5 * 60000);
    right.textContent = shownMonth(addMonths(new Date(), offset));   // the new name right away, the days when they load
    poller.stop();
    poller = api.poll("calendar", 300000, onData, { view: o.view, offset });
  };
  const arrow = (dir, label) => h("button", { class: "cal-arrow press", title: label, "aria-label": label,
    onclick: () => go(dir) }, dir < 0 ? "‹" : "›");
  const nav = o.view !== "month" ? right : h("span", { class: "cal-nav" },
    arrow(-1, "Previous month"),
    h("button", { class: "cal-mname", title: "Back to this month", onclick: () => go(0) }, right),
    arrow(1, "Next month"));
  el.append(header("Calendar", "calendar", nav), body);
  el.classList.add(`cal-view-${o.view}`);
  let data = null;
  const shownMonth = d => d.toLocaleDateString(L, { month: "long", year: "numeric" });

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
    const range = hourRange(list), month = addDays(start, 6);     // the first week's Sunday is always in the month
    right.textContent = shownMonth(month);
    right.parentNode.classList.toggle("away", offset !== 0);
    const heads = [];
    for (let i = 0; i < 7; i++)
      heads.push(h("span", { class: "cal-mh" }, addDays(start, i).toLocaleDateString(L, { weekday: "narrow" })));
    const weeks = Math.round((end - start) / DAY / 7), fit = monthFit(weeks);
    const cells = [];
    for (let d = new Date(start); d < end; d = addDays(d, 1)) {
      const evs = onDay(list, d), all = evs.filter(e => e.all_day);
      const cell = h("div", { class: `cal-cell${d.getMonth() !== month.getMonth() ? " out" : ""}${dayKey(d) === dayKey(today) ? " today" : ""}${d < today ? " past" : ""}` },
        h("div", { class: "cal-ch" },
          h("span", { class: "cal-num num" }, String(d.getDate())),
          fit ? null : h("span", { class: "cal-ad" }, all.slice(0, 3).map(e => h("i", { style: { background: color(e) } })))),
        fit ? names(evs, fit, now) : h("div", { class: "cal-strip" }, blocks(d, evs, range, now, false, 3)));
      cell._events = evs;
      cell._day = d;
      cells.push(cell);
    }
    return [h("div", { class: "cal-mheads" }, heads),
      h("div", { class: `cal-month${fit ? " named" : ""}${fit && fit.big ? " big" : ""}`,
        style: { gridTemplateRows: `repeat(${weeks}, minmax(0, 1fr))` } }, cells)];
  }

  // Whether a month day has room for event names, from the size the tile has on screen: null when it doesn't
  // (a 2x2 tile, say), else { lines, time, big }. Times are added once a day is wide enough for them.
  function monthFit(weeks) {
    const W = body.clientWidth, H = body.clientHeight;
    if (!W || !H) return null;
    const cellW = (W - 6 * 3) / 7, cellH = (H - 17 - 3 * (weeks - 1)) / weeks;
    const big = cellW >= 170 && cellH >= 110, lineH = big ? 21 : 16;
    const lines = Math.floor((cellH - (big ? 37 : 27) + 2) / lineH);    // cell padding, day number, list margin
    return cellW >= 64 && lines >= 1 ? { lines, time: cellW >= (big ? 150 : 110), big } : null;
  }

  // A month day's events by name: all-day ones as coloured bars first, then timed ones in order. When they
  // don't all fit, the last line says how many more there are (hovering the day lists them all).
  function names(evs, fit, now) {
    const sorted = evs.slice().sort((a, b) => (b.all_day - a.all_day) || (a.s - b.s));
    const shown = sorted.length > fit.lines ? fit.lines - 1 : sorted.length;
    return h("div", { class: "cal-names" },
      sorted.slice(0, shown).map(e => e.all_day
        ? h("div", { class: "cal-nm all", style: { background: color(e) } }, e.title)
        : h("div", { class: `cal-nm${e.e <= now ? " past" : ""}` },
            h("i", { style: { background: color(e) } }),
            fit.time ? h("span", { class: "cal-nt num" }, time(e.s)) : null,
            h("span", { class: "cal-nn" }, e.title))),
      sorted.length > shown ? h("div", { class: "cal-nm more" }, `+${sorted.length - shown} more`) : null);
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

  function onData(d, err) {
    if (err) console.error("calendar: " + String(err));
    data = d || { error: "Hub backend is offline" };
    render();
  }
  let poller = api.poll("calendar", 300000, onData, { view: o.view });
  // The time line and the dimming of past events move on with the clock, between data updates
  const tick = setInterval(() => {
    if (!el.isConnected) { clearInterval(tick); clearTimeout(back); poller.stop(); tip.remove(); window.removeEventListener("resize", onResize); }
    else if (!hovered) render();
  }, 60000);
  // whether month days have room for event names depends on the tile's size on screen
  let resizeTimer;
  const onResize = () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => el.isConnected && render(), 150); };
  if (o.view === "month") window.addEventListener("resize", onResize);
}

function addMonths(d, n) { return new Date(d.getFullYear(), d.getMonth() + n, 1); }

function duration(ms) {
  const m = Math.round(ms / 60000), hh = Math.floor(m / 60), mm = m % 60;
  return hh && mm ? `${hh} h ${mm} min` : hh ? `${hh} h` : `${mm} min`;
}

function weekNumber(d) {                        // ISO week number
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
  return Math.ceil(((t - Date.UTC(t.getUTCFullYear(), 0, 1)) / DAY + 1) / 7);
}
