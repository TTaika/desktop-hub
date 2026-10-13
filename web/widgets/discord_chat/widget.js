// The chat you have open in Discord (a server channel), with new messages as they arrive.
// Discord's window title says which channel is open; direct messages can't be shown (see providers/discord.py).
import { h, header, icon, withDefaults } from "../../lib.js";

export const css = true;
export const meta = {
  name: "Discord chat", description: "The channel you have open in Discord", defaultSize: "2x3",
  minSize: "2x2", maxSize: "4x4",
  settings: [
    { key: "text", label: "Text size", type: "select", choices: [["small", "Small"], ["normal", "Normal"], ["large", "Large"]],
      default: "normal" },
    { key: "avatars", label: "Profile pictures", type: "bool", default: true },
  ],
};

const GROUP_MS = 7 * 60000;                     // messages by one person this close together share a header

export function mount(el, { options, api }) {
  const o = withDefaults(meta, options);
  el.classList.add(`dcc-text-${o.text}`);
  if (!o.avatars) el.classList.add("dcc-no-avatars");
  const where = h("span", { class: "dcc-where" });
  const list = h("div", { class: "dcc-list" });
  const body = h("div", { class: "dcc-body" });
  el.append(header("Discord", "chat", where), body);
  let lastKey = "", channelId = null;

  const time = d => d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  function dayName(d) {
    const today = new Date(), y = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) return "Today";
    if (d.toDateString() === y.toDateString()) return "Yesterday";
    return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: d.getFullYear() === today.getFullYear() ? undefined : "numeric" });
  }

  // Pictures are kept by their key between updates, so each one is downloaded once (the overlay engine leaks a
  // little memory on every download, and the list is rebuilt whenever a message arrives).
  const pictures = new Map();
  let seen = new Set();
  function picture(img) {
    seen.add(img.key);
    let el = pictures.get(img.key);
    if (!el) {
      el = h("img", { class: "dcc-img press", src: img.src, alt: "", title: "Open in the browser",
        onclick: () => api.post("discord", { view: img.full || img.src }) });
      pictures.set(img.key, el);
    }
    const room = Math.max(120, list.clientWidth - (o.avatars ? 44 : 0));
    const scale = Math.min(1, room / img.w, 240 / img.h);       // fit the tile, at most 240 px tall
    el.style.width = Math.round(img.w * scale) + "px";
    el.style.height = Math.round(img.h * scale) + "px";
    return el;
  }

  function line(m) {
    return h("div", { class: "dcc-text" }, m.text,
      m.edited ? h("span", { class: "dcc-edited" }, " (edited)") : null,
      (m.images || []).map(picture),
      m.files.map(f => h("div", { class: "dcc-file" }, "📎 " + f)));
  }

  function render(msgs) {
    const out = [];
    let prev = null;
    for (const m of msgs) {
      const t = new Date(m.time);
      if (!prev || new Date(prev.time).toDateString() !== t.toDateString())
        out.push(h("div", { class: "dcc-day" }, h("span", {}, dayName(t))));
      const joined = prev && prev.author_id === m.author_id && t - new Date(prev.time) < GROUP_MS
        && new Date(prev.time).toDateString() === t.toDateString();
      if (joined) out[out.length - 1].lastChild.append(line(m));
      else out.push(h("div", { class: "dcc-group" },
        o.avatars ? h("img", { class: "dcc-avatar", src: m.avatar, alt: "" }) : null,
        h("div", { class: "dcc-main" },
          h("div", { class: "dcc-head" },
            h("span", { class: "dcc-name", style: { color: m.color || "" } }, m.name),
            m.bot ? h("span", { class: "dcc-bot" }, "APP") : null,
            h("span", { class: "dcc-time num" }, time(t))),
          line(m))));
      prev = m;
    }
    return out;
  }

  function message(text, iconName) {
    channelId = null;
    where.textContent = "";
    body.replaceChildren(h("div", { class: "tile-empty dcc-empty" }, icon(iconName || "chat", 36), h("div", {}, text)));
  }

  api.poll("discord", 1000, (d) => {
    const key = JSON.stringify(d);
    if (key === lastKey) return;            // only rebuild when something changed
    lastKey = key;
    if (!d) return message("Hub backend is offline");
    if (d.status !== "ready" || !d.channel) return message(d.message || "Open a server channel in Discord");

    const atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 40;
    const switched = channelId !== d.channel.id;
    channelId = d.channel.id;
    where.replaceChildren(h("span", { class: "dcc-ch" }, "# " + d.channel.name), h("span", { class: "dcc-guild" }, d.channel.guild));
    if (list.parentNode !== body) body.replaceChildren(list);
    const top = list.scrollTop;
    seen = new Set();
    list.replaceChildren(...(d.messages.length ? render(d.messages) : [h("div", { class: "tile-empty" }, "No messages yet")]));
    for (const k of [...pictures.keys()]) if (!seen.has(k)) pictures.delete(k);
    list.scrollTop = switched || atBottom ? list.scrollHeight : top;    // follow new messages unless you scrolled up
  }, { view: "chat" });
}
