// Runs the shipped deck against a fake DOM. There is no browser in this repo,
// so this is the only way to move a card before shipping. H.api is a stub that
// records calls; nothing here touches the network or Instagram.
//
// The deck scrolls instead of stepping, so the fake has to be a scroller: a
// tiny HTML parser and selector engine, an element that can hold children, and
// a scroll offset it can be asked about. A string of innerHTML cannot tell
// "which card is on the glass" from "which cards exist", and that is the whole
// question this file asks.
import * as browseView from "../app/static/browse.js";
import { STR } from "../app/static/str.js";

let fail = 0;
const ok = (cond, msg) => {
  console.log(`${cond ? "ok  " : "FAIL"} ${msg}`);
  if (!cond) fail++;
};

// ------------------------------------------------------------------ fake DOM
const VOID = new Set(["img", "input", "br", "hr", "meta", "link", "source"]);
const kebab = s => s.replace(/[A-Z]/g, c => `-${c.toLowerCase()}`);

function compile(sel) {
  return String(sel).trim().split(/\s+/).map(part => {
    const out = [];
    const tag = part.match(/^[a-zA-Z][\w-]*/);
    let rest = part;
    if (tag) { out.push({ tag: tag[0].toLowerCase() }); rest = part.slice(tag[0].length); }
    for (const m of rest.matchAll(/\.([\w-]+)|\[([\w-]+)(?:=(?:"([^"]*)"|([^\]]*)))?\]/g)) {
      if (m[1]) out.push({ cls: m[1] });
      else out.push({ attr: m[2], val: m[3] ?? m[4] ?? null });
    }
    return out;
  });
}

function matchesTokens(el, tokens) {
  if (typeof el === "string") return false;
  return tokens.every(t => (t.tag ? el.tag === t.tag
    : t.cls ? el.classes.has(t.cls)
      : (t.attr in el.attrs && (t.val === null || el.attrs[t.attr] === t.val))));
}

function descendants(el, out = []) {
  for (const child of el.children) {
    if (typeof child === "string") continue;
    out.push(child);
    descendants(child, out);
  }
  return out;
}

function serialize(nodes) {
  return nodes.map(n => {
    if (typeof n === "string") return n;
    const attrs = [];
    if (n.classes.size) attrs.push(`class="${[...n.classes].join(" ")}"`);
    for (const [k, v] of Object.entries(n.attrs)) if (k !== "class") attrs.push(`${k}="${v}"`);
    const open = `<${n.tag}${attrs.length ? " " + attrs.join(" ") : ""}>`;
    return VOID.has(n.tag) ? open : `${open}${serialize(n.children)}</${n.tag}>`;
  }).join("");
}

function parseHTML(html) {
  const root = [];
  const stack = [root];
  for (const tok of String(html ?? "").match(/<[^>]+>|[^<]+/g) || []) {
    const top = stack[stack.length - 1];
    if (tok.startsWith("</")) {
      if (stack.length > 1) stack.pop();
      continue;
    }
    if (tok.startsWith("<")) {
      const name = (tok.match(/^<\s*([a-zA-Z][\w-]*)/) || [])[1];
      if (!name) continue;
      const tag = name.toLowerCase();
      const el = new El(tag);
      const rest = tok.slice(1 + name.length).replace(/\/?>$/, "").trim();
      for (const a of rest.matchAll(/([\w:-]+)(?:="([^"]*)")?/g))
        el.setAttribute(a[1], a[2] ?? "");
      top.push(el);
      el.parentNode = null;
      if (!VOID.has(tag) && !tok.endsWith("/>")) stack.push(el.children);
      continue;
    }
    if (tok.trim()) top.push(tok);
  }
  const adopt = nodes => {
    for (const n of nodes) {
      if (typeof n === "string") continue;
      n.parentNode = null;
      adopt(n.children);
    }
  };
  adopt(root);
  // Parent links are rebuilt on append, so a parsed subtree only needs its own.
  const link = (nodes, parent) => nodes.forEach(n => {
    if (typeof n === "string") return;
    n.parentNode = parent;
    link(n.children, n);
  });
  link(root, null);
  return root;
}

class El {
  constructor(tag) {
    this.tag = tag;
    this.tagName = String(tag).toUpperCase();
    this.attrs = {};
    this.children = [];
    this.parentNode = null;
    this.handlers = Object.create(null);
    this.classes = new Set();
    this.hidden = false;
    this.disabled = false;
    // <video>
    this.paused = true;
    this.readyState = 0;      // nothing decoded until `load` fetches it
    this.currentTime = 0;
    this.muted = false;
    this.loop = false;
    this.duration = NaN;
    this.plays = 0;
    // <input type=range>
    this.value = "0";
    // scrolling
    this.scrollTop = 0;
    this.scrollLeft = 0;
    const attrs = this.attrs;
    this.dataset = new Proxy({}, {
      get: (_, k) => attrs[`data-${kebab(k)}`],
      set: (_, k, v) => { attrs[`data-${kebab(k)}`] = String(v); return true; },
      has: (_, k) => `data-${kebab(k)}` in attrs,
    });
    this.classList = {
      add: c => this.classes.add(c),
      remove: c => this.classes.delete(c),
      contains: c => this.classes.has(c),
      toggle: (c, on) => {
        const want = on === undefined ? !this.classes.has(c) : !!on;
        if (want) this.classes.add(c); else this.classes.delete(c);
        return want;
      },
    };
  }
  get clientHeight() { return 800; }
  get clientWidth() { return 400; }
  get className() { return [...this.classes].join(" "); }
  set className(v) { this.classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get innerHTML() { return serialize(this.children); }
  set innerHTML(v) { this.children = parseHTML(v); this.link(); }
  // Replacing a node in place, the way `paintPic` redraws the marks row.
  get outerHTML() { return serialize([this]); }
  set outerHTML(v) {
    const parent = this.parentNode;
    if (!parent) return;
    const at = parent.children.indexOf(this);
    const fresh = parseHTML(String(v));
    for (const n of fresh) if (typeof n !== "string") n.parentNode = parent;
    parent.children.splice(at, 1, ...fresh);
    parent.link();
  }
  get textContent() {
    return this.children.map(c => (typeof c === "string" ? c : c.textContent)).join("");
  }
  set textContent(v) { this.children = [String(v)]; }
  link() {
    for (const c of this.children) {
      if (typeof c === "string") continue;
      c.parentNode = this;
      c.link();
    }
    return this;
  }
  append(...nodes) {
    for (const n of nodes) {
      if (n.parentNode) n.parentNode.children = n.parentNode.children.filter(c => c !== n);
      n.parentNode = this;
      this.children.push(n);
    }
  }
  insertBefore(node, ref) {
    if (node.parentNode) node.parentNode.children = node.parentNode.children.filter(c => c !== node);
    const at = this.children.indexOf(ref);
    node.parentNode = this;
    if (at < 0) this.children.push(node); else this.children.splice(at, 0, node);
  }
  remove() {
    if (this.parentNode) this.parentNode.children =
      this.parentNode.children.filter(c => c !== this);
    this.parentNode = null;
  }
  focus() { this.focused = true; }
  setAttribute(k, v) {
    if (k === "class") { this.className = v; return; }
    this.attrs[k] = String(v);
    // The platform mirrors these onto the element; a <video loop> really loops.
    if (this.tag === "video" && (k === "loop" || k === "muted" || k === "controls"))
      this[k] = true;
  }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, fn) { (this.handlers[t] ||= []).push(fn); }
  removeEventListener(t, fn) {
    this.handlers[t] = (this.handlers[t] || []).filter(f => f !== fn);
  }
  fire(t, ev = {}) {
    if (!ev.target) ev.target = this;
    if (!ev.preventDefault) ev.preventDefault = () => {};
    for (let node = this; node; node = node.parentNode)
      for (const fn of [...(node.handlers[t] || [])]) fn(ev);
    return ev;
  }
  querySelectorAll(sel) {
    const levels = compile(sel);
    let set = [this];
    for (const tokens of levels) {
      const next = [];
      for (const el of set)
        for (const d of descendants(el)) if (matchesTokens(d, tokens)) next.push(d);
      set = [...new Set(next)];
    }
    return [...new Set(set)];
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  closest(sel) {
    const tokens = compile(sel).at(-1);
    for (let node = this; node; node = node.parentNode)
      if (matchesTokens(node, tokens)) return node;
    return null;
  }
  scrollTo({ top, left }) {
    if (typeof top === "number") this.scrollTop = top;
    if (typeof left === "number") this.scrollLeft = left;
  }
  play() {
    this.plays += 1;
    this.paused = false;
    this.fire("play");
    return Promise.resolve();
  }
  pause() { if (!this.paused) { this.paused = true; this.fire("pause"); } }
  load() {
    this.loaded = true;
    // A real engine fetches, decodes, and only then says the first frame is
    // there. That is what playback waits for.
    this.readyState = 4;
    this.fire("canplay");
  }
}

const doc = new El("document");
globalThis.document = {
  documentElement: new El("html"),
  createElement: tag => new El(tag),
  addEventListener: (t, fn, cap) => doc.addEventListener(t, fn, cap),
  removeEventListener: (t, fn, cap) => doc.removeEventListener(t, fn, cap),
};
globalThis.localStorage = { store: {}, getItem() { return null; }, setItem() {} };

// ---------------------------------------------------------------- fixture
const seen = [];
const exits = [];
const calls = [];
let api = {};
const state = {
  session: { id: "s1", remaining: 4 },
  settings: {},
  feed: { seenLocal: new Set(), remaining: 4 },
};

const muteStore = { "00sgram.muted": "1" };
const initMain = () => browseView.init({
  state,
  esc: s => String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])),
  when: ts => (ts ? `14 Νοε 21:${String(Number(ts) % 60).padStart(2, "0")}` : ""),
  navigate: () => {},
  exit: () => exits.push("exit"),
  markSeenLocally: pk => { seen.push(pk); state.feed.seenLocal.add(pk); },
  loadBase: async () => {},
  mutedPref: () => muteStore["00sgram.muted"] !== "0",
  rememberMute: m => { muteStore["00sgram.muted"] = m ? "1" : "0"; },
  beginSession: async body => {
    calls.push("POST /api/sessions");
    if (body) calls.push("filters " + JSON.stringify(body.filters || {}));
  },
  reenter: () => calls.push("reenter"),
  api: async (path, opts = {}) => {
    calls.push(`${opts.method || "GET"} ${path}`);
    const hit = Object.keys(api).sort((a, b) => b.length - a.length)
      .find(k => path.startsWith(k));
    return hit ? api[hit](path, opts) : { items: [], next_cursor: null };
  },
});
initMain();

const post = (i, extra = {}) => ({
  pk: `p${i}`, account: { pk: "a1", username: "maria",
                          pic: "/api/media/account/a1" }, kind: "photo",
  taken_at: 1_700_000_000, caption: "η θάλασσα", seen: false, liked: false,
  resources: [{ idx: 0, type: "photo", thumb: "/t", full: `/f${i}` }],
  ...extra,
});
const album = n => Array.from({ length: n }, (_, i) =>
  ({ idx: i, type: "photo", thumb: "/t", full: `/a${i}` }));
const sticker = (kind, label, url, detail) => ({ kind, label, url, detail });

const page1 = [post(1), post(2, { resources: album(3) })];
const page2 = [post(3, { resources: [{ idx: 0, type: "video", thumb: "/t", full: "/v3" }] }),
  post(4)];

// Two feed pages: the second one is only reachable by prefetch.
api["/api/feed"] = path => {
  if (path.includes("cursor=c1")) return { items: page2, next_cursor: null,
                                           tail_cursor: "1700000000_9" };
  return { items: page1, next_cursor: "c1", tail_cursor: "1700000000_5" };
};

// -------------------------------------------------------------------- mount
const app = new El("app");
calls.length = 0;
const stop1 = await browseView.browse(app);
const root = app.children[0];
ok(!!root && root.className === "browse", "the stage mounts on #app");
ok(root.getAttribute("aria-label") === STR.browse, "the stage names the mode for a reader");
ok(root.getAttribute("role") === "group" && root.tabIndex === -1 && root.focused === true,
  "the stage is a focusable group and takes focus");

const stage = root.querySelector(".bstage");
const slides = () => stage.children.filter(c => c.classes?.has("bslide"));
const slide = i => slides()[i];
const tail = () => slides().at(-1);
const at = i => Math.round(stage.scrollTop / stage.clientHeight);
// The browser says the scroll has settled; the deck then says what is true.
const settle = async i => {
  stage.scrollTop = i * stage.clientHeight;
  stage.fire("scrollend");
  await new Promise(r => setTimeout(r, 0));
};
const strip = i => slide(i).querySelector(".bpics");
const setPic = async (i, k) => {
  const s = strip(i);
  s.scrollLeft = k * s.clientWidth;
  s.fire("scrollend");
  await new Promise(r => setTimeout(r, 0));
};
const marksOf = i =>
  slide(i).querySelectorAll(".bmark").map(m => m.classes.has("is-on"));

ok(!!stage, "the stage owns one scroller");
// The second page is a background prefetch, so it lands a tick after the mount
// returns — the deck never waits on the network for the first card.
await new Promise(r => setTimeout(r, 0));
ok(slides().length === 5, "four cards and the tail, one slide each");
ok(calls.some(c => c.includes("cursor=c1")),
  "the next page arrives without a press: scrolling never waits on the network");
ok(at(0) === 0, "the deck opens at the first card");
const first = slide(0);
ok(first.textContent.includes("maria"), "the card names the account");
ok(first.getAttribute("data-pk") === "p1", "the card carries the post it shows");
ok(first.textContent.includes("14 Νοε 21:20"), "the card carries the publication time");
// The face sits beside the name, and a missing one is absent, not broken.
ok(first.querySelector("img.bavatar")?.getAttribute("src") === "/api/media/account/a1",
  "the account's face sits next to its name");
const face = first.querySelector("img.bavatar");
face.fire("error");
ok(face.parentNode === null, "a face that never arrived is removed, not a broken icon");
ok(first.textContent.includes(STR.of(1, 4)), "the counter is 1 of this session's unseen 4");
ok(first.querySelector("img.bmedia")?.getAttribute("src") === "/f1",
  "the media is the first picture");
ok(!!first.querySelector(".bcap"), "the caption is clampable, not printed whole");
ok(calls.some(c => c.startsWith("GET /api/feed")), "the first page is fetched once");
ok(seen.includes("p1"), "a card on the glass is seen, through the existing seam");
ok(!calls.some(c => c.includes("/api/posts/seen")),
  "browse writes seen through markSeenLocally, not itself");
ok(root.querySelector('[data-act="exit"]') !== null, "the exit control is on the glass");
ok(root.querySelector('[data-act="fresh"]') !== null,
  "the newest-posts control is on the glass");

// A session holds a snapshot, so a post that arrived later is not in the deck:
// the control takes the session over again and re-enters at the top.
{
  const had = state.session;
  state.session = { id: "s1", remaining: 4, mode: "unseen", filters: { account: "42" } };
  const before = calls.length;
  root.querySelector('[data-act="fresh"]').fire("click");
  await new Promise(r => setTimeout(r, 0));
  const did = calls.slice(before);
  ok(did.includes("POST /api/sessions"),
    "the newest control asks for a fresh snapshot");
  ok(did.includes("reenter"), "and re-enters the deck, which starts at the newest post");
  ok(did.includes('filters {"account":"42"}'),
    "the session's filters are carried over, not reset");
  state.session = had;
}

// The caption is where a thumb rests: a press lifts the clamp.
const cap = first.querySelector(".bcap");
cap.fire("click");
ok(cap.classes.has("is-open"), "a press on the caption lifts the two-line clamp");

// ------------------------------------------------------------------- scroll
// Down is the older post, and the offset is the whole truth about where it is.
await settle(1);
ok(at(1) === 1, "scrolling one screen lands on the second card");
ok(seen.includes("p2"), "the card that settled is the card that is seen");
ok(slide(1).textContent.includes(STR.photoN(1, 3)),
  "the album card opens on its first picture");
ok(marksOf(1).length === 3, "a three-picture post carries three marks");
ok(marksOf(1).join() === "true,false,false", "on picture one the first mark is lit");

// The album is its own snap axis, so it reads its own offset.
await setPic(1, 1);
ok(slide(1).querySelector("[data-photo]").textContent === STR.photoN(2, 3),
  "a picture further right is the second of three");
ok(marksOf(1).join() === "false,true,false", "on picture two, the middle mark is lit");
ok(slide(1).querySelectorAll(".bmarks").length === 1,
  "and the marks stay one row: redrawing them never nests a row in a row");
await setPic(1, 2);
ok(marksOf(1).join() === "false,false,true",
  "on the last picture, the last mark is the lit one");
await setPic(1, 9);
ok(slide(1).querySelector("[data-photo]").textContent === STR.photoN(3, 3),
  "the album stops at its last picture");

// iOS can leave a flick resting between two cells. The deck finishes the snap
// itself, so a card never shows half of one picture and half of the next.
const mid = slide(1).querySelector(".bpics");
mid.scrollLeft = 1.5 * mid.clientWidth;
mid.fire("scrollend");
ok(mid.scrollLeft === 2 * mid.clientWidth,
  "a strip that stopped between cells is snapped to the nearer one");
ok(slide(1).querySelector("[data-photo]").textContent === STR.photoN(3, 3),
  "and the counter names the picture that is actually on screen");

// A picture whose file never arrived says so in the deck's words — after one
// silent second ask, because the media route loses a cold race now and then.
await settle(0);
const shot = slide(0).querySelector("img.bmedia");
shot.fire("error");
ok(slide(0).querySelector("img.bmedia") === shot && shot.getAttribute("src") === "/f1?r=1",
  "the first miss is retried, not reported");
shot.fire("error");
ok(slide(0).querySelector(".bfail")?.textContent === STR.imgFailed,
  "a picture that fails twice becomes the deck's sentence, not a broken icon");

// ------------------------------------------------------------------- video
await settle(2);
const film = slide(2);
const vid = film.querySelector("video");
ok(!!vid, "the third card is a film");
ok(vid.getAttribute("src") === "/v3", "the film is downloaded only when its card is reached");
ok(vid.plays === 1 && vid.paused === false, "a film plays on activation, without a press");
ok(vid.muted === true && vid.loop === true, "it is muted and looped");
// Starting the film before its first frame is decoded is the black flash: the
// poster goes away the moment playback starts, and there is nothing under it.
vid.readyState = 0;
vid.plays = 0;
shot.fire("scroll");             // leave the card...
await settle(0);                 // ...and come back to it
await settle(2);
ok(vid.plays === 0, "a film whose first frame is not decoded yet is not started");
vid.fire("canplay");
ok(vid.plays === 1, "and starts the moment the frame is there, with no press");
ok(!!film.querySelector(".bbar") && film.innerHTML.includes(`aria-label="${STR.pause}"`),
  "a film carries its own transport: play/pause, seek, clock, mute");
// VLC-like: the controls are glyphs. The word lives in the label, not the bar.
ok(/data-act="pp"[^>]*>\s*<svg/.test(film.innerHTML),
  "pause is a glyph, not the word for it");
ok(/data-act="mute"[^>]*>\s*<svg/.test(film.innerHTML), "and so is mute");
ok(/data-act="hear"[^>]*>\s*<svg/.test(film.innerHTML)
  && film.innerHTML.includes(`aria-label="${STR.hear}"`),
  "a note is the bar's «what is this?», drawn and named like the others");
ok(!/<video[^>]*\scontrols[\s>]/.test(film.innerHTML),
  "the platform's own controls are not what draws it");
ok(seen.includes("p3"), "a film is seen like a picture");

doc.fire("keydown", { key: " ", preventDefault() {} });
ok(vid.paused === true, "Space pauses it");
doc.fire("keydown", { key: " ", preventDefault() {} });
ok(vid.paused === false, "and Space resumes it");

// The transport's mute is the only mute, so it is the only writer.
const bar = film.querySelector(".bbar");
bar.querySelector('[data-act="mute"]').fire("click");
ok(vid.muted === false && muteStore["00sgram.muted"] === "0",
  "the transport's mute unmutes and writes the program's one audio preference");
bar.querySelector('[data-act="mute"]').fire("click");
ok(vid.muted === true && muteStore["00sgram.muted"] === "1",
  "and muting again is remembered too");
// Leave it unmuted: the next assertion is about the card that comes back.
bar.querySelector('[data-act="mute"]').fire("click");

// «Τι παίζει;» — the note asks the house about the post it stands on, and the
// answer is a line under the transport with a link to the track.
api["/api/recognize"] = () => ({ found: true, artist: "Autechre", title: "Amber" });
const heard = film.querySelector(".bheard");
bar.querySelector('[data-act="hear"]').fire("click");
for (let i = 0; i < 5; i++) await Promise.resolve();
const heardCalls = calls.filter(c => c.startsWith("POST /api/recognize/"));
ok(heardCalls.length === 1 && /^POST \/api\/recognize\/[^/]+\/0$/.test(heardCalls[0]),
  "the note asks about the post it stands on, by pk and picture");
ok(heard.textContent.includes("Autechre") && heard.textContent.includes("Amber"),
  "the answer names the track");
ok(heard.innerHTML.includes('href="https://open.spotify.com/search/Autechre%20Amber"')
  && heard.innerHTML.includes('class="bopen"'),
  "and offers Spotify's own search for that term, as a link the reader presses");
ok(/data-act="copytrack"/.test(heard.innerHTML), "with a glyph that copies the term");

// The copy glyph is a real clipboard write, not a look.
let copied = null;
// Node's own `navigator` is a getter, so it is replaced, not assigned.
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: { clipboard: { writeText: async text => { copied = text; } } },
});
heard.querySelector('[data-act="copytrack"]').fire("click");
for (let i = 0; i < 3; i++) await Promise.resolve();
ok(copied === "Autechre Amber", "one press puts artist and title on the clipboard");
// The common answer is "I don't know it", and it is said in words.
api["/api/recognize"] = () => ({ found: false });
bar.querySelector('[data-act="hear"]').fire("click");
for (let i = 0; i < 5; i++) await Promise.resolve();
ok(heard.textContent === STR.hearNone, "an unknown song is said, not left blank");
// A throttle is not "I don't know this song": it says why, and for how long.
api["/api/recognize"] = () => ({ found: false, error: "RateLimited" });
bar.querySelector('[data-act="hear"]').fire("click");
for (let i = 0; i < 5; i++) await Promise.resolve();
ok(heard.textContent === STR.hearBusy.replace("{s}", "10"),
  "a throttle names itself and the wait, not the song as unknown");
ok(bar.querySelector('[data-act="hear"]').disabled === true,
  "and the note stays asleep while that clock runs");

// The seek bar is the peek: half way is half way.
vid.duration = 20;
const seek = bar.querySelector("[data-seek]");
seek.value = "500";
seek.fire("input");
ok(Math.round(vid.currentTime) === 10,
  "the seek bar moves the film to where it is dragged");

// Leaving the card pauses and rewinds the film; the file stays, so coming back
// is instant and does not ask the house for the same bytes twice.
await settle(1);
ok(vid.paused === true && vid.currentTime === 0,
  "leaving the card pauses and rewinds the film");
await settle(2);
ok(film.querySelector("video").muted === false,
  "a film opened again is unmuted, because the preference is remembered");

// A key held down must not walk the stream: no repeat, no surprise seen marks.
const before = seen.length;
doc.fire("keydown", { key: "ArrowDown", repeat: true, preventDefault() {} });
ok(seen.length === before, "a repeated key does nothing");
// The keys move the same scroller a thumb moves.
await settle(0);
doc.fire("keydown", { key: "ArrowDown", preventDefault() {} });
await settle(at(0));
ok(at(0) === 1, "ArrowDown moves one screen down");
doc.fire("keydown", { key: "ArrowUp", preventDefault() {} });
await settle(at(0));
ok(at(0) === 0, "ArrowUp comes back to the newer card");

// --------------------------------------------------------- prefetch and end
await settle(0);
ok(slides().length === 5, "the prefetched page is already in the deck");
await settle(3);
ok(slide(3).textContent.includes(STR.of(4, 4)),
  "the last unseen post is the fourth card");
await settle(4);
ok(tail().textContent.includes(STR.browseDone),
  "one screen more and the unseen run says it is over");
ok(!!tail().querySelector('[data-act="older"]') && tail().textContent.includes(STR.older),
  "the end block offers one way further back, in words");
ok(!calls.some(c => c.includes("/api/older")), "and fetches nothing until it is pressed");

const older = Array.from({ length: 10 }, (_, i) => post(100 + i, { seen: true }));
api["/api/older"] = () => ({ items: older, next_cursor: null });
tail().querySelector('[data-act="older"]').fire("click");
await new Promise(r => setTimeout(r, 0));
await settle(at(0));
ok(calls.filter(c => c.includes("/api/older")).length === 1,
  "one press is exactly one batch");
ok(slides().length === 15, "the batch appends ten cards and the tail");
ok(at(0) === 4, "and the deck lands on the first of them");
ok(slide(4).textContent.includes("maria")
  && !slide(4).textContent.includes(STR.browseDone),
  "closing the end block shows the fetched cards");
ok(seen.length === 4, "an already-seen archive card is not marked again");

// The way back up. The control is absent on the newest card and one press away
// everywhere else, because forty swipes is not a way back.
const newest = () => root.querySelector('[data-act="newest"]');
await settle(0);
ok(newest().hidden === true,
  "on the newest card there is nothing above to go back to");
await settle(4);
ok(newest().hidden === false, "four cards down, one press offers the way back");
ok(newest().textContent === STR.browseNewest,
  "and it says so in words: the newest card");
newest().fire("click");
await new Promise(r => setTimeout(r, 0));
ok(at(0) === 0, "the press lands on the first card, not near it");
ok(newest().hidden === true, "and the control goes away again at the top");

// Exhausted: the button becomes a line and offers nothing.
await settle(slides().length - 1);
ok(tail().textContent.includes(STR.noOlder) && !tail().querySelector('[data-act="older"]'),
  "an exhausted archive replaces the button with a terminal line");

// --------------------------------------------------------------- failures
const retried = [];
api = { "/api/feed": () => { throw Object.assign(new Error("nope"), { status: 500 }); } };
const app2 = new El("app");
const stop2 = await browseView.browse(app2);
const root2 = app2.children[0];
const stage2 = root2.querySelector(".bstage");
ok(stage2.textContent.includes(STR.failed) && !!stage2.querySelector('[data-act="retry"]'),
  "a failed first page is words and one retry, not an empty screen");
retried.push(api);
api = { "/api/feed": () => ({ items: [post(9)], next_cursor: null, tail_cursor: "1_1" }) };
stage2.querySelector('[data-act="retry"]').fire("click");
await new Promise(r => setTimeout(r, 0));
ok(stage2.textContent.includes("maria"), "retry fetches again and paints the card");
stop2();

// An entirely-seen page is not an error: the loop asks for the next one.
let asked = 0;
api = { "/api/feed": () => (++asked === 1
  ? { items: [post(20, { seen: true })], next_cursor: "c9", tail_cursor: "1_20" }
  : { items: [post(21)], next_cursor: null, tail_cursor: "1_21" }) };
const app3 = new El("app");
const stop3 = await browseView.browse(app3);
const stage3 = app3.children[0].querySelector(".bstage");
ok(asked === 2, "a page of already-seen posts is skipped, not painted");
ok(stage3.innerHTML.includes("/f21"), "the first unseen post is what fills the screen");
ok(!stage3.innerHTML.includes("/f20"), "and the seen one is never shown as new");

// A twenty-picture album gets five marks, and the window slides with the card.
const wide = new El("app");
api = { "/api/feed": () => ({ items: [post(30, { resources: album(20) })],
                              next_cursor: null, tail_cursor: "1_30" }) };
const stopWide = await browseView.browse(wide);
const wideStage = wide.children[0].querySelector(".bstage");
const wideSlide = wideStage.querySelector(".bslide");
ok(wideSlide.querySelectorAll(".bmark").length === 5,
  "a twenty-picture album caps at five marks");
ok(wideSlide.querySelectorAll(".bmark").map(m => m.classes.has("is-on")).join()
  === "true,false,false,false,false",
  "the first of twenty lights the first mark");
const wideStrip = wideSlide.querySelector(".bpics");
for (let i = 0; i < 10; i++) {
  wideStrip.scrollLeft = (i + 1) * wideStrip.clientWidth;
  wideStrip.fire("scrollend");
}
await new Promise(r => setTimeout(r, 0));
ok(wideSlide.querySelectorAll(".bmark").length === 5,
  "ten pictures in, the window is still five marks");
ok(wideSlide.querySelectorAll(".bmark").map(m => m.classes.has("is-on")).join()
  === "false,false,true,false,false",
  "and the lit mark has slid to the middle of the window");
stopWide();
stop3();

// What the author attached is a row of read-only links under the picture, and a
// mention typed into the caption is a link too — Instagram sends no list for it.
api = { "/api/feed": () => ({ items: [post(60, {
  caption: "με τον @billbak7 και #poledance, εδώ",
  links: [sticker("profile", "xara.gian", "https://www.instagram.com/xara.gian/",
                  "ΧΑΡΑ"),
          sticker("place", "Εξάρχεια",
                  "https://www.instagram.com/explore/locations/77/", "Athens"),
          sticker("music", "Little Moon", null, "Gone Gone Beyond")] })],
  next_cursor: null, tail_cursor: "1_60" }) };
const appL = new El("app");
const stopL = await browseView.browse(appL);
const slideL = appL.children[0].querySelector(".bslide");
const capL = slideL.querySelector(".bcap");
ok(capL.querySelectorAll("a").map(a => a.getAttribute("href")).join() ===
  "https://www.instagram.com/billbak7/,"
  + "https://www.instagram.com/explore/tags/poledance/",
  "a mention and a hashtag in the caption are links to the platform");
ok(capL.textContent.includes("@billbak7") && capL.textContent.includes("#poledance"),
  "and the words themselves are unchanged");
const rowL = slideL.querySelector(".blinks");
ok(!!rowL && !rowL.hidden && rowL.tagName === "BUTTON",
  "the author's attachments sit behind one control, on the name row");
ok(rowL.textContent.trim().startsWith(STR.links),
  "and the control says what it opens");
rowL.fire("click");
const sheetL = appL.children[0].querySelector(".bsheet");
ok(!!sheetL && sheetL.textContent.includes("@xara.gian")
  && sheetL.textContent.includes("Εξάρχεια")
  && sheetL.textContent.includes("♫ Little Moon — Gone Gone Beyond"),
  "the sheet names the tagged account, the place and the song");
ok(sheetL?.querySelectorAll("a").map(a => a.getAttribute("href"))
  .includes("https://www.instagram.com/xara.gian/"),
  "and each one goes where it says");
ok(sheetL?.querySelector(".bsheet-detail")?.textContent === "ΧΑΡΑ",
  "a tag carries the name it was given");
ok(sheetL?.querySelectorAll("a").map(a => a.getAttribute("href"))
  .some(h => h.startsWith("https://open.spotify.com/search/")),
  "and the song opens Spotify's search for it");
stopL();
// A post with nothing attached draws the control nowhere — but it keeps the
// row, so its picture is the same height as the post above it.
ok(slide(0).querySelector(".blinks")?.textContent === "",
  "a post with nothing attached keeps the row but draws no control");

// An empty session opens on the end block, not on a broken card.
api = { "/api/feed": () => ({ items: [], next_cursor: null, tail_cursor: null }) };
const app4 = new El("app");
const stop4 = await browseView.browse(app4);
const stage4 = app4.children[0].querySelector(".bstage");
ok(stage4.textContent.includes(STR.browseDone)
  && !!stage4.querySelector('[data-act="older"]'),
  "nothing unseen at all opens on the end block with the one button");
stop4();

// A live ring is new things to see even when no post is: "that is everything"
// over the tray's own cards is the lie the end block must not tell.
api = { "/api/feed": () => ({ items: [], next_cursor: null, tail_cursor: null }),
        "/api/browse/stories": () => ({ items: [
          { account: { pk: "a5", username: "maria", pic: "" },
            when: 2000, count: 1, pending: true, resources: [] } ] }) };
const appRing = new El("app");
const stopRing = await browseView.browse(appRing);
const stageRing = appRing.children[0].querySelector(".bstage");
const slidesRing = () => stageRing.children.filter(c => c.classes?.has("bslide"));
ok(slidesRing().length === 2
  && slidesRing()[0].getAttribute("data-pk") === "story:a5",
  "with no post but a live ring the deck opens on the story, not on the end block");
stopRing();

// Nothing unseen is the end of the run, not a reason to re-show a card the
// reader already read: the tail's «Παλαιότερα» is the way forward from there.
const beforeAllSeen = calls.length;
api = { "/api/feed": () => ({ items: [], next_cursor: null, tail_cursor: "1_1" }),
        "/api/newest": () => ({ items: [post(41, { taken_at: 5000 })],
                                next_cursor: "4_4" }) };
const appAllSeen = new El("app");
const stopAllSeen = await browseView.browse(appAllSeen, null);
const stageAllSeen = appAllSeen.children[0].querySelector(".bstage");
const slidesAllSeen = () => stageAllSeen.children.filter(c => c.classes?.has("bslide"));
ok(slidesAllSeen().length === 1 && !!slidesAllSeen()[0].querySelector('[data-act="older"]'),
  "with nothing unseen the deck opens on the way back, not on a card already read");
ok(calls.slice(beforeAllSeen).filter(c => c.startsWith("GET /api/newest")).length === 0,
  "and does not go looking for a card to re-show");
stopAllSeen();

// ------------------------------------------------------------ story cards
// A story is one card per account, its unseen segments on the album axis — the
// same card element, the same transport, the same seen seam as a post.
const seg = (pk, links = [], taken_at = 1000) =>
  ({ pk, idx: 0, type: "photo", duration: null, taken_at,
                     links,
                     full: `/api/media/story/${pk}`,
                     thumb: `/api/media/story/${pk}?thumb=1` });
api = {
  "/api/feed": () => ({ items: [post(40, { taken_at: 1000 })], next_cursor: null,
                        tail_cursor: "1000_1" }),
  "/api/browse/stories": () => ({ items: [
    { account: { pk: "a9", username: "eleni", pic: "/api/media/account/a9" },
      when: 3000, count: 2, pending: false,
      resources: [
        seg("s1", [sticker("profile", "xara.gian",
                           "https://www.instagram.com/xara.gian/", "ΧΑΡΑ")]),
        seg("s2", [sticker("hashtag", "#athens",
                           "https://www.instagram.com/explore/tags/athens/")], 1800),
      ] },
    { account: { pk: "a8", username: "kostas", pic: "" },
      when: 2000, count: 3, pending: true, resources: [] },
  ] }),
};
const appS = new El("app");
const stopS = await browseView.browse(appS);
const stageS = appS.children[0].querySelector(".bstage");
const slideS = i => stageS.children.filter(c => c.classes?.has("bslide"))[i];
const current = () => slideS(Math.round(stageS.scrollTop / stageS.clientHeight));
const goS = async i => {
  stageS.scrollTop = i * stageS.clientHeight;
  stageS.fire("scrollend");
  await new Promise(r => setTimeout(r, 0));
};
// The tray answers after the first paint, on purpose: what is new must not wait
// on thirty-four story fetches. One tick is all it takes once it does.
await new Promise(r => setTimeout(r, 0));
const pksS = () => stageS.children.filter(c => c.classes?.has("bslide"))
  .map(c => c.getAttribute("data-pk"));
ok(pksS()[0] === "p40",
  "the post is the first card: the story tray never stands between the reader and what is new");
ok(pksS()[1] === "story:a9" && pksS()[2] === "story:a8",
  "the stories follow it, newest first");
await goS(1);
ok(current().getAttribute("data-pk") === "story:a9"
  && current().textContent.includes("eleni"),
  "a story account is a card of its own, on the same axis as a post");
ok(current().textContent.includes(STR.photoN(1, 2)),
  "its segments are the card's pictures, on the album axis");
ok(current().querySelector("[data-when]")?.textContent === "14 Νοε 21:40",
  "the card is stamped with the segment on the glass");
ok(!current().querySelector(".bcount"),
  "a story card does not claim a post of the session: its one number is the segment");
ok(current().querySelectorAll(".bmark").length === 2, "two segments, two marks");
// The stickers are the segment's own, behind the same one control as a post.
const segLinks = () => current().querySelector(".blinks");
ok(segLinks()?.textContent.trim().startsWith(STR.links),
  "a segment offers its stickers through the one control");
const storySheet = () => appS.children[0].querySelector(".bsheet");
segLinks().fire("click");
ok(storySheet()?.textContent.includes("@xara.gian"),
  "and the sheet names the account it tags");
ok(storySheet()?.querySelector("a")?.getAttribute("href")
  === "https://www.instagram.com/xara.gian/",
  "as a read-only link to that account");
ok(storySheet()?.querySelector(".bsheet-detail")?.textContent === "ΧΑΡΑ",
  "with the name the tag was given");
const storySeen = () => calls.filter(c => c === "POST /api/stories/seen");
ok(storySeen().length === 0,
  "landing on a story card is not watching it");
await new Promise(r => setTimeout(r, 1100));
ok(storySeen().length === 1,
  "staying on the card is, and it is reported once");
const sStrip = current().querySelector(".bpics");
sStrip.scrollLeft = sStrip.clientWidth;
sStrip.fire("scrollend");
await new Promise(r => setTimeout(r, 0));
ok(current().textContent.includes(STR.photoN(2, 2)),
  "the right axis walks the account's stories");
ok(slideS(1).querySelector("[data-when]")?.textContent === "14 Νοε 21:00",
  "and the time is the segment's own, not the newest one's");
segLinks().fire("click");
ok(storySheet()?.textContent.includes("#athens")
  && !storySheet()?.textContent.includes("@xara.gian"),
  "and the next segment's stickers replace the last one's");
ok(storySeen().length === 2,
  "the second segment is its own view, not the first again");

// A card whose segments are not stored asks once, on arrival, and says so —
// with the account's own face and name, because a blank screen reads as broken.
await goS(2);
ok(current().textContent.includes(STR.storyLoading)
  && current().textContent.includes("kostas")
  && current().textContent.includes(STR.storyCount(3)),
  "an unfetched story names the account, counts its segments, then says it is loading");
// The name stays in the meta row and the sentence keeps the picture's place:
// a loading card must have the shape of the card it will become.
ok(!!current().querySelector(".bmeta .bwho-name")
  && !!current().querySelector(".bcard .bhold")
  && !current().querySelector(".bend .bwho"),
  "and it is laid out as a card, not as an end block");
const fetches = () => calls.filter(c => c === "POST /api/stories/a8/fetch");
ok(fetches().length === 1, "and asks the server exactly once");
ok(!calls.some(c => c.includes("/api/stories/a9/fetch")),
  "a card whose segments are known is never fetched again");
// The poll the viewer already uses. A ring that was watched elsewhere comes
// back `viewed` with no `src`; it is still a picture, at the media route.
api["/api/stories/a8"] = () => ({ fetch_state: "idle", items: [{
  pk: "k1", media_type: 2, state: "viewed", src: null, thumb: null,
  links: [{ kind: "music", label: "Theme", url: null,
            detail: "The Rembrandts" }] }] });
await new Promise(r => setTimeout(r, 900));
ok(current().innerHTML.includes('src="/api/media/story/k1"'),
  "a segment that is already viewed still becomes a picture");
ok(!!current().querySelector(".bbar") && !current().querySelector('[data-act="hear"]'),
  "a story film carries the transport but not the note: it has no post to ask about");
ok(!current().textContent.includes(STR.storyLoading),
  "and the loading sentence is gone");
current().querySelector('[data-act="links"]')?.fire("click");
ok(storySheet()?.textContent.includes("♫ Theme — The Rembrandts"),
  "a fetched story brings its own song with it");

// Leaving a story card does not finish the account: swiping past is not
// watching, and the segments decide whether the ring comes back.
await goS(3);
ok(!calls.some(c => c === "POST /api/stories/a8/done"),
  "leaving a story card does not mark an unwatched account done");
// The story cards sit behind the posts, and they never renumber them: the post
// at the top is still the first of the session.
ok(slideS(0).textContent.includes(STR.of(1, 4))
  && slideS(0).textContent.includes("maria"),
  "and the post above them is the first post of the session, not the second");
stopS();

// A ring the server no longer has: the fetch finishes and stores nothing, so the
// card leaves the deck instead of hanging on «loading» for ever.
let emptyPolls = 0;
api = {
  "/api/feed": () => ({ items: [post(50, { taken_at: 500 })], next_cursor: null,
                        tail_cursor: "500_1" }),
  "/api/browse/stories": () => ({ items: [
    { account: { pk: "a7", username: "vaggelis", pic: "" },
      when: 2000, count: 1, pending: true, resources: [] }] }),
  "/api/stories/a7": path => (path.endsWith("/fetch")
    ? { queued: true, fetch_state: "queued" }
    : { fetch_state: emptyPolls++ === 0 ? "running" : "idle", items: [] }),
};
const appE = new El("app");
const stopE = await browseView.browse(appE);
const stageE = appE.children[0].querySelector(".bstage");
const pks = () => stageE.children.filter(c => c.classes?.has("bslide"))
  .map(c => c.getAttribute("data-pk"));
ok(pks()[0] === "p50", "the post is on the glass before the tray has answered");
await new Promise(r => setTimeout(r, 0));
ok(pks()[1] === "story:a7", "an unfetched ring is a card once the tray answers");
stageE.scrollTop = stageE.clientHeight;
stageE.fire("scrollend");
await new Promise(r => setTimeout(r, 1900));
ok(!pks().includes("story:a7"), "a ring with nothing in it leaves the deck");
ok(calls.includes("POST /api/stories/a7/done"),
  "and the tray is told, so the next mount does not offer it again");
ok(pks()[0] === "p50", "and the post is still where the reader left it");
stopE();


// Only one stage is ever live in the browser, because a route change always
// tears the last one down; stop the earlier fixtures so this block measures one.
stop1(); stop4();
const live = doc.handlers.keydown.length;
const app5 = new El("app");
const stop5 = await browseView.browse(app5);
ok(doc.handlers.keydown.length === live + 1, "one keydown listener per mount");
stop5();
ok(doc.handlers.keydown.length === live,
  "cleanup removes the document listener by reference");
stop5();
ok(doc.handlers.keydown.length === live, "a second cleanup is harmless");

// Exit goes through the router's own leave, so the preference and the history
// entry are written in one place.
const exitsBefore = exits.length;
const app6 = new El("app");
await browseView.browse(app6);
doc.fire("keydown", { key: "Escape", preventDefault() {} });
ok(exits.length === exitsBefore + 1, "Escape leaves the mode through the router");
ok(doc.handlers.keydown.length === live, "and tears the stage down first");

// A page that mounts onto #/browse knows no session, while the device may have
// an open one: the base call runs first and no new session is asked for.
{
  const had = state.session;
  state.session = null;
  let base = 0;
  const begin = [];
  const appS = new El("app");
  browseView.init({
    state,
    esc: s => String(s ?? ""),
    when: () => "",
    navigate: () => {},
    exit: () => {},
    markSeenLocally: () => {},
    loadBase: async () => { base++; state.session = { id: "s2", remaining: 0 }; },
    beginSession: async () => { begin.push(1); },
    mutedPref: () => true,
    rememberMute: () => {},
    api: async () => ({ items: [], next_cursor: null }),
  });
  await browseView.browse(appS);
  ok(base === 1 && begin.length === 0,
    "a mount with an open session adopts it instead of POSTing a second one");
  state.session = had;
}

// A link bubble in the inbox names one post: `#/browse?at=<pk>` opens the deck
// on that card. The post is already seen, so the plain first page would drop it;
// the first request instead asks the server to centre on it.
{
  initMain();
  api = { "/api/feed": path => (path.includes("around_pk=")
    ? { items: [post(69), post(70, { seen: true }), post(71)],
        next_cursor: null, tail_cursor: "1700000000_71" }
    : { items: [post(72)], next_cursor: null, tail_cursor: "1700000000_72" }),
    "/api/newest": () => ({ items: [post(80, { taken_at: 1_800_000_000 })],
                            next_cursor: null }) };
  calls.length = 0;
  const appT = new El("app");
  const stopT = await browseView.browse(appT, "p70");
  const stageT = appT.children[0].querySelector(".bstage");
  const glass = () => stageT.children.filter(c => c.classes?.has("bslide"))
    [Math.round(stageT.scrollTop / stageT.clientHeight)];
  ok(calls.some(c => c.startsWith("GET /api/feed") && c.includes("around_pk=p70")),
    "a mount with a target asks the first page to centre on that post");
  ok(glass().getAttribute("data-pk") === "p70",
    "and the deck opens on it, though the server sent it as already seen");
  ok(!seen.includes("p70"), "the card it opens on is not reported seen again");

  calls.length = 0;
  const appN = new El("app");
  const stopN = await browseView.browse(appN, null);
  ok(calls.some(c => c.startsWith("GET /api/feed"))
    && !calls.some(c => c.includes("around_pk")),
    "and a mount with no target still asks for the plain first page");
  // Nothing named, but the tab remembers where the reader was: the same
  // mechanism as a link bubble, not a second one.
  const store = { "00sgram.at": "p70" };
  globalThis.sessionStorage = {
    getItem: k => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
  };
  state.feed.seenLocal = new Set();   // a fresh page load starts with none
  calls.length = 0;
  const appR = new El("app");
  const stopR = await browseView.browse(appR, null);
  const stageR = appR.children[0].querySelector(".bstage");
  const glassR = () => stageR.children.filter(c => c.classes?.has("bslide"))
    [Math.round(stageR.scrollTop / stageR.clientHeight)];
  ok(calls.some(c => c.includes("around_pk=p70")),
    "a tab that remembers where it was asks for that card, not the top");
  ok(glassR().getAttribute("data-pk") === "p70",
    "and opens on it, though it is already seen");
  // A session holds unseen posts, so coming back to a remembered card used to
  // leave nothing above it — and «Νεότερα» went to that week-old card.
  ok(stageR.children.filter(c => c.classes?.has("bslide"))[0]
    .getAttribute("data-pk") === "p80",
    "the newest post sits right above the remembered card");
  ok(calls.some(c => c.startsWith("GET /api/newest")),
    "because the deck asked what is newest, not what is unread");
  stopR();
  delete globalThis.sessionStorage;
  stopN();
  stopT();
}


console.log(fail ? `\n${fail} FAILED` : "\nall ok");
process.exit(fail ? 1 : 0);
