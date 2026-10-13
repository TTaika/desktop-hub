// Time and date, laid out like the lock screen: the date above, the time large below it.
// options: { locale: "en-GB", seconds: false }
import { h } from "../../lib.js";

export const css = true;
export const meta = { name: "Clock", description: "Time and date", defaultSize: "2x1", minSize: "2x1", maxSize: "4x2" };

export function mount(el, { options }) {
  const locale = options.locale || "en-GB";
  const date = h("div", { class: "clock-date t-title" });
  const time = h("div", { class: "clock-time t-display num" });
  el.append(date, time);
  let started = false;

  const tick = () => {
    if (!el.isConnected && started) return;     // removed in the editor
    started = true;
    const now = new Date();
    time.textContent = now.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit",
      second: options.seconds ? "2-digit" : undefined });
    date.textContent = now.toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "long" });
    setTimeout(tick, options.seconds ? 1000 - now.getMilliseconds() : (60 - now.getSeconds()) * 1000);
  };
  tick();
}
