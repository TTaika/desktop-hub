// The Discord call you are in: who is there, who is talking, who is muted. Below it, who has sent you a DM
// you haven't read yet; click one to open the conversation in Discord.
import { h, header, icon, withDefaults } from "../../lib.js";

export const css = true;
export const meta = {
  name: "Discord call", description: "Who is in your call and who is talking, and new DMs", defaultSize: "2x3",
  minSize: "2x2", maxSize: "3x4",
  settings: [
    { key: "dms", label: "Show unread DMs", type: "bool", default: true },
    { key: "expire", label: "Forget an unread DM after", type: "range", min: 15, max: 720, step: 15, unit: " min", default: 180 },
  ],
};

export function mount(el, { options, api }) {
  const o = withDefaults(meta, options);
  const where = h("span", { class: "dc-where" });
  const body = h("div", { class: "dc-body" });
  const dmList = h("div", { class: "dc-dm-list" });
  const dmBar = h("div", { class: "dc-dms", hidden: true }, h("div", { class: "dc-dms-head t-caption" }, "New messages"), dmList);
  el.append(header("Discord", "headset", where), body, dmBar);
  const dmRows = new Map();                 // channel id -> { el, badge }

  // Unread DMs, newest first. Kept by conversation so an avatar stays put while its count goes up.
  function showDms(dms) {
    dms = o.dms ? dms || [] : [];
    dmBar.hidden = !dms.length;
    const ids = new Set(dms.map(d => d.channel_id));
    for (const [id, r] of dmRows) if (!ids.has(id)) { r.el.remove(); dmRows.delete(id); }
    dms.slice(0, 6).forEach((d, i) => {
      let r = dmRows.get(d.channel_id);
      if (!r) {
        r = { badge: h("span", { class: "dc-dm-n num" }) };
        r.el = h("button", { class: "dc-dm press", title: d.name,
          onclick: () => { r.el.remove(); dmRows.delete(d.channel_id); api.post("discord", { open: d.channel_id }); } },
          h("img", { src: d.avatar, alt: "" }), r.badge);
        dmRows.set(d.channel_id, r);
      }
      r.el.title = `${d.name} · ${d.count} new`;
      r.badge.textContent = d.count > 9 ? "9+" : String(d.count);
      if (dmList.children[i] !== r.el) dmList.insertBefore(r.el, dmList.children[i] || null);
    });
  }

  const title = h("span"), count = h("span", { class: "dc-n num" });
  const channel = h("div", { class: "dc-channel t-title" }, title, count);
  const list = h("div", { class: "dc-list" });
  const rows = new Map();                   // user id -> { el, name, flags, flagKey }
  let lastKey = "", showingCall = false;

  // One row per member, kept for as long as they are in the call. Talking only toggles a class, so the green
  // ring never rebuilds anything and the rows stay exactly where they are.
  function row(m) {
    let r = rows.get(m.id);
    if (!r) {
      r = { name: h("span", { class: "dc-name" }), flags: h("span", { class: "dc-flags" }), flagKey: "" };
      r.el = h("div", { class: "dc-member" }, h("img", { class: "dc-avatar", src: m.avatar, alt: "" }), r.name, r.flags);
      rows.set(m.id, r);
    }
    r.name.textContent = m.name;
    r.el.classList.toggle("speaking", !!m.speaking);
    r.el.classList.toggle("me", !!m.me);
    const flagKey = m.deafened ? "deaf" : m.muted ? "mic_off" : "";
    if (flagKey !== r.flagKey) {
      r.flagKey = flagKey;
      r.flags.replaceChildren(...(flagKey ? [icon(flagKey, 16)] : []));
    }
    return r.el;
  }

  function message(content) {
    showingCall = false;
    rows.clear();
    list.replaceChildren();                 // the rows go with their records, or they'd come back doubled
    where.textContent = "";
    body.replaceChildren(h("div", { class: "tile-empty" }, content));
  }

  // The server pushes: it answers as soon as something changes (see api.poll), so a speaking ring follows
  // Discord within milliseconds. 1000 ms is only the pause before trying again after a failure.
  api.poll("discord", o.interval || 1000, (d) => {
    const key = JSON.stringify(d);
    if (key === lastKey) return;            // e.g. a held request that ended without a change
    lastKey = key;

    showDms(d && d.dms);
    if (!d) return message("Hub backend is offline");
    if (d.status !== "ready" || !d.channel)
      return message(d.status === "ready" ? h("div", { class: "dc-idle" }, icon("headset", 40), h("div", {}, d.message)) : d.message);

    if (!showingCall) { showingCall = true; body.replaceChildren(channel, list); }
    where.textContent = d.channel.guild || "";
    title.textContent = `${d.channel.guild_id ? "# " : ""}${d.channel.name}`;
    count.textContent = ` · ${d.members.length}`;

    const ids = new Set(d.members.map(m => m.id));
    for (const [id, r] of rows) if (!ids.has(id)) { r.el.remove(); rows.delete(id); }
    d.members.forEach((m, i) => {           // only moves a row when the order really changed
      const el = row(m);
      if (list.children[i] !== el) list.insertBefore(el, list.children[i] || null);
    });
  }, { expire: o.expire });
}
