// Router, API client, seen tracking, dates. Two screens: the deck and the
// inbox. There is no frame, no menu bar, no status bar — the deck owns the
// glass, and the inbox is the one place with a page around it.

// No offset is restored by the browser: a reload starts at the top of whatever
// screen the hash names.
history.scrollRestoration = "manual";
import * as views from "/static/views.js";
import { MONTHS, YESTERDAY, STR } from "/static/str.js";

export const state = {
  session: null,          // open feed session for this device
  settings: {},           // string values from /api/settings
  feed: views.blankDeck(), // the posts this device has already reported seen
};

export class ApiError extends Error {
  constructor(code, status, body) {
    super(code); this.code = code; this.status = status; this.body = body;
  }
}

export async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const type = res.headers.get("content-type") || "";
  const body = type.includes("json") ? await res.json().catch(() => null) : null;
  if (res.status === 401 && !path.startsWith("/login")) {
    showLogin();
    throw new ApiError("unauthorised", 401, body);
  }
  if (!res.ok) throw new ApiError(body?.error?.code || "error", res.status, body);
  return body;
}

// ------------------------------------------------------------------ seen

const queue = new Set();
let flushTimer = null;

export async function flushSeen() {
  flushTimer = null;
  const pks = [...queue];
  queue.clear();
  if (!pks.length) return;
  try {
    await api("/api/posts/seen", { method: "POST", body: { pks } });
  } catch {
    pks.forEach(pk => queue.add(pk));
  }
}

export function markSeenLocally(pk) {
  if (state.feed.seenLocal.has(pk)) return;
  state.feed.seenLocal.add(pk);
  queue.add(pk);
  if (!flushTimer) flushTimer = setTimeout(flushSeen, 2000);
}

addEventListener("pagehide", flushSeen);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") flushSeen();
});

// ----------------------------------------------------------------- utils

export const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// One date format in the whole app: day, month abbreviation, time, and the
// word for yesterday's calendar day.
const pad = n => String(n).padStart(2, "0");
const sameDay = (a, b) => a.getFullYear() === b.getFullYear()
  && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

export function when(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const now = new Date();
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (sameDay(d, new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1)))
    return `${YESTERDAY} ${hm}`;
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${hm}`;
}
export const ago = when;

export function navigate(path, opts = {}) {
  const next = `#${path}`;
  // `replace` keeps a screen out of the history: Back must not bounce between
  // the two. replaceState fires no hashchange, so the route is run by hand.
  if (opts.replace) {
    history.replaceState(null, "", next);
    route();
  } else if (location.hash === next) route();
  else location.hash = path;
}

// The deck has no way out of itself except the inbox, so its exit control is
// the other screen rather than a window it no longer has.
function leaveBrowse(chat) {
  // A card opened from a conversation goes back to that conversation, not to
  // the list of them.
  navigate(chat ? `/messages?chat=${encodeURIComponent(chat)}` : "/messages",
           { replace: true });
}

// ---------------------------------------------------------------- routing

let cleanup = null;

function showLogin() {
  location.hash = "/login";
}

// One failure panel: the program's sentence, never the machine's code and never
// the browser's English, and exactly one action.
function failure(el, err) {
  el.innerHTML = `<div class="banner">
    <strong>${esc(err.status ? STR.failed : STR.noConnection)}</strong>
    <div class="row"><button type="button" data-act="retry">${esc(STR.retry)}</button></div>
  </div>`;
  el.querySelector('[data-act="retry"]')?.addEventListener("click", route);
}

export async function loadBase() {
  const [settings, session] = await Promise.all([
    api("/api/settings"),
    api("/api/sessions/current"),
  ]);
  state.settings = settings;
  state.session = session;
}

async function route() {
  // The hash is a path and, after a `?`, a query. The query carries one thing
  // only — the post a link bubble asked for — so the screen is the path alone.
  const [raw, qs] = location.hash.replace(/^#/, "").split("?");
  const q = new URLSearchParams(qs || "");
  const el = document.getElementById("app");
  // Teardown first, before any await and before every early return: a playing
  // <video> in the deck must not outlive its route.
  if (cleanup) { cleanup(); cleanup = null; }
  document.documentElement.classList.remove("mode-browse");
  if (raw === "/login") return views.login(el);
  try {
    if (raw === "/messages") {
      await loadBase();
      // The screen keeps a timer; it must die with the route, not outlive it.
      cleanup = (await views.messages(el, q.get("chat"))) || null;
      return;
    }
    // Everything else is the deck: `/`, an old `#/feed` bookmark, nonsense.
    // The hash is rewritten without adding a history entry, so Back leaves the
    // program rather than bouncing inside it.
    if (raw !== "/browse") history.replaceState(null, "", "#/browse");
    // A link bubble in the inbox names one post: `#/browse?at=<pk>`, and the
    // conversation it came from: `&chat=<id>`, so the exit goes back there.
    return await deck(el, q.get("at"), q.get("chat"));
  } catch (err) {
    if (err.status === 401) return;
    failure(el, err);
  }
}

// No chrome, and its own loadBase: the frame must be gone before the network
// call, not after it. The module is fetched only when this route is really the
// one being shown, so a broken browse.js cannot take the inbox down with it.
async function deck(el, at, chat) {
  document.documentElement.classList.add("mode-browse");
  const view = await import("/static/browse.js");
  view.init({ state, api, ApiError, esc, when, navigate, markSeenLocally,
              loadBase, beginSession: views.beginSession, reenter: route,
              mutedPref: views.mutedPref, rememberMute: views.rememberMute,
              exit: () => leaveBrowse(chat) });
  cleanup = await view.browse(el, at);
}

window.addEventListener("hashchange", route);

views.init({ state, api, ApiError, esc, ago, when, navigate, loadBase });
await route();
