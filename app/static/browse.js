// The deck: one card per screen, scrolled natively. The vertical axis is the
// stream — one card per snap point, `scroll-snap-stop: always` so a fling never
// skips one — and the horizontal axis inside a card is the album, one picture
// per snap point. The position is the scroll offset, never a variable that
// gestures write: the platform already knows how to move, snap, fling and
// rubber-band, and a hand-rolled version of that is how a card ends up half off
// the screen on a phone.
//
// This is the only place in the program that plays a video without a press.
// That is the point of a feed; it is muted, looped and rewinded on the way out.
// Unmuting is the transport's own control, and that is the only place the
// program's one audio preference is written from.
import { STR } from "./str.js";

let H = {};

export function init(helpers) { H = helpers; }

const PAGE = 10;         // cards per feed page and per older batch
const MAX_EMPTY = 10;    // consecutive pages with nothing unseen before saying so
const BUSY_S = 10;       // seconds the note sleeps after Shazam says "not now"
const SETTLE_MS = 150;   // no `scrollend` (Safari < 17.4): quiet means settled
// How long a story card must stay on the glass before it counts as watched.
// A card swiped past on the way to the tail is not a story anybody saw, and
// marking it seen there is what made the day's stories vanish unlooked at.
const VIEW_MS = 1000;
// Where the reader was, for this tab. Leaving for a message, or reloading, must
// not cost the deck: the remembered post is handed to the same `around_pk` path
// a link bubble uses, so it comes back even though it is already seen.
const RESUME_KEY = "00sgram.at";

function resumePk() {
  try {
    return typeof sessionStorage === "undefined"
      ? null : sessionStorage.getItem(RESUME_KEY);
  } catch { return null; }
}

function rememberPk(pk) {
  try {
    if (typeof sessionStorage !== "undefined") sessionStorage.setItem(RESUME_KEY, pk);
  } catch { /* a full or blocked store is not a reason to lose the card */ }
}

// Transport glyphs, drawn rather than spelled: a control labelled with the whole
// word takes a third of the row and says nothing a triangle does not.
const svg = inner => `<svg width="16" height="16" viewBox="0 0 16 16"
  aria-hidden="true">${inner}</svg>`;
const G_PLAY = svg('<path d="M4 2.5v11l9.5-5.5z" fill="currentColor"/>');
const G_PAUSE = svg('<path d="M4 2.5h3v11H4zM9 2.5h3v11H9z" fill="currentColor"/>');
const G_SOUND = svg('<path d="M2.5 6h2.4L8.5 3v10L4.9 10H2.5z" fill="currentColor"/>'
  + '<path d="M10.8 5.4a3.6 3.6 0 0 1 0 5.2" fill="none" stroke="currentColor"'
  + ' stroke-width="1.2"/>');
const G_MUTE = svg('<path d="M2.5 6h2.4L8.5 3v10L4.9 10H2.5z" fill="currentColor"/>'
  + '<path d="M11 6.2l3.6 3.6M14.6 6.2L11 9.8" fill="none" stroke="currentColor"'
  + ' stroke-width="1.2"/>');
const G_COPY = svg('<rect x="5.5" y="5.5" width="8" height="9" fill="none"'
  + ' stroke="currentColor" stroke-width="1.2"/><path d="M3.5 10.5v-7h8"'
  + ' fill="none" stroke="currentColor" stroke-width="1.2"/>');
const G_TICK = svg('<path d="M3 8.5l3.2 3.2L13 4.5" fill="none" stroke="currentColor"'
  + ' stroke-width="1.8"/>');
// Spotify's mark, near enough at 16px: a disc and three arcs.
const G_SPOTIFY = svg('<circle cx="8" cy="8" r="6.5" fill="currentColor"/>'
  + '<path d="M4.7 6.3c2.2-.7 4.6-.4 6.5.6M5 8.4c1.8-.5 3.7-.3 5.3.5M5.4 10.3c1.4-.4 2.9-.2 4.1.4"'
  + ' fill="none" stroke="#000" stroke-width="1.1" stroke-linecap="round"/>');
const G_NOTE = svg('<path d="M6.4 12V3.4l6-1.2v8.4" fill="none" stroke="currentColor"'
  + ' stroke-width="1.6"/><circle cx="4.5" cy="12.4" r="1.9" fill="currentColor"/>'
  + '<circle cx="10.5" cy="10.9" r="1.9" fill="currentColor"/>');

const esc = s => H.esc(s);
const pics = it => it?.resources || [];
// An album cell is a picture or a film, and the counter has to say which: a reel
// labelled "photo" is the same lie the deck refuses to tell about a failure.
const picKind = (it, k) =>
  pics(it)[k]?.type === "video" ? STR.unitVideo : STR.unitPhoto;
// Every picture carries its own moment. A story card is several uploads from
// one account, so one timestamp for the whole card was the newest segment's
// time — not when the picture on the glass was posted.
const picWhen = (it, k) => H.when(pics(it)[k]?.taken_at || it.taken_at);
// Five marks at most: the current one sits mid-window so "more to the right"
// is visible without a row of twenty pips.
const MAX_MARKS = 5;

function marksHTML(photo, n) {
  if (n < 2) return "";
  const shown = Math.min(n, MAX_MARKS);
  const start = Math.max(0, Math.min(photo - Math.floor(shown / 2), n - shown));
  let out = "";
  for (let i = 0; i < shown; i++)
    out += `<span class="bmark${start + i === photo ? " is-on" : ""}"></span>`;
  return `<span class="bmarks" aria-hidden="true">${out}</span>`;
}

// The player's own transport, the same shape the deck has always drawn — play,
// one seek bar, the clock, mute — because the platform's bar is positioned by
// the platform. It rides with its film, inside the same album cell.
// The author's own attachments — tagged accounts, the place, the song — are the
// only links in the deck, and all of them are read-only.
function linkLabel(l) {
  const name = String(l.label || "");
  if (l.kind === "profile") return name.startsWith("@") ? name : `@${name}`;
  if (l.kind === "hashtag") return name.startsWith("#") ? name : `#${name}`;
  if (l.kind === "music") return `♫ ${name}${l.detail ? ` — ${l.detail}` : ""}`;
  return name;
}

// A song in the attachments is one press from playing: Spotify's own search,
// which opens the Spotify app when it is installed (the link is universal) and
// the site when it is not. A search always lands on the track; a track id is
// only there when Instagram happens to have given one.
function spotifyURL(l) {
  const term = `${l.label || ""} ${l.detail || ""}`.trim();
  return `https://open.spotify.com/search/${encodeURIComponent(term)}`;
}

// A post carries them once; a story segment carries its own, because a sticker
// belongs to the picture it was put on. They are behind one control, not laid
// out on the card: five chips and a ninety-character ticket URL re-flow the
// picture, which is the thing the card exists to show. The control rides the
// name row, so a card with five attachments and a card with none lay out the
// same height — the picture never jumps from one post to the next.
function linksInner(it, k) {
  const n = ((it.kind === "story" ? pics(it)[k]?.links : it.links) || []).length;
  return n ? `${esc(STR.links)}${n > 1 ? ` <span class="blinks-n">${n}</span>` : ""}` : "";
}

function linksHTML(it, k) {
  return `<button type="button" class="blinks" data-act="links">${
    linksInner(it, k)}</button>`;
}

// The sheet's rows: every attachment, in the order the author put them, with
// the name a tag was given as a line under it rather than a hover tooltip —
// there is no hover on the glass that needs it.
function linkRows(it, k) {
  const links = (it.kind === "story" ? pics(it)[k]?.links : it.links) || [];
  return links.map(l => {
    const label = esc(linkLabel(l));
    const detail = l.detail && l.kind !== "music"
      ? `<span class="bsheet-detail">${esc(l.detail)}</span>` : "";
    // A song is a press away even when Instagram gives no URL for it.
    const href = l.url || (l.kind === "music" ? spotifyURL(l) : "");
    return href
      ? `<li><a href="${esc(href)}" target="_blank" rel="noopener">${
        label}</a>${detail}</li>`
      : `<li><span class="bsheet-plain">${label}</span>${detail}</li>`;
  }).join("");
}

// A caption is a sentence. `@name` and `#tag` in it are the only links
// Instagram gives as text — it publishes no mention list for captions — so they
// are found on the raw text and escaped as they are wrapped.
function captionHTML(text) {
  const raw = String(text || "");
  let out = "";
  let at = 0;
  for (const m of raw.matchAll(/(^|\s)([@#])([^\s@#]+)/g)) {
    const start = m.index + m[1].length;
    const name = m[3].replace(/[.,;:!?]+$/, "");
    if (!name) continue;
    const href = m[2] === "@"
      ? `https://www.instagram.com/${encodeURIComponent(name)}/`
      : `https://www.instagram.com/explore/tags/${encodeURIComponent(name)}/`;
    out += esc(raw.slice(at, start));
    out += `<a href="${href}" target="_blank" rel="noopener">${esc(m[2] + name)}</a>`;
    out += esc(m[3].slice(name.length));
    at = m.index + m[0].length;
  }
  return out + esc(raw.slice(at));
}

function barHTML(hear) {
  return `<div class="bbar">
    <button type="button" data-act="pp" aria-label="${esc(STR.pause)}"
            title="${esc(STR.pause)}">${G_PAUSE}</button>
    <input type="range" data-seek min="0" max="1000" step="1" value="0"
           aria-label="${esc(STR.seekLabel)}">
    <span class="btime" data-time>0:00 / 0:00</span>
    ${hear ? `<button type="button" data-act="hear" aria-label="${esc(STR.hear)}"
            title="${esc(STR.hear)}">${G_NOTE}</button>` : ""}
    <button type="button" data-act="mute" aria-pressed="true"
            aria-label="${esc(STR.mute)}" title="${esc(STR.muteOff)}">${
      G_MUTE}</button>
  </div>`;
}

export async function browse(el, at = null) {
  // A link bubble names a post; coming back to the deck with nothing named means
  // "where I was". Both are the same mechanism.
  const resume = at || resumePk();
  const S = {
    items: [],            // posts and story cards, newest first
    nodes: [],            // the slide element for each item, same index
    tailNode: null,       // the last slide: loading, retry, or the way back
    i: 0,                 // the settled index; the tail is at items.length
    total: 0,             // unseen posts in this session at mount
    added: 0,             // cards appended from /api/older
    // The post a link bubble asked for. Consumed once, by the first feed page:
    // later pages and the tail are the plain feed, so `around_pk` never repeats.
    at: resume,
    // A named post is always shown; a remembered one only when there is a deck
    // to come back to. Resurrecting a read card onto an empty deck is what made
    // the first card appear again before the way back.
    atNamed: !!at,
    tailCursor: null,
    unseen: { cursor: null, more: true, busy: false, failed: false },
    older: { cursor: null, fetched: false, next_cursor: null,
             busy: false, failed: false },
    retry: null,          // what the retry button re-runs, when it is not a page
    quiet: null,           // the fallback settle timer
    closed: false,
    // Stories ride the same deck as posts; a card is one account's unseen
    // segments on the album axis. Nothing is fetched until the card is reached.
    stories: {},          // account_pk → {state: idle|fetching|done|failed}
    storySeen: new Set(), // segment pks already reported this mount
    storyOpen: null,      // the account whose card is on screen
    storyTimer: null,     // the dwell that turns "on screen" into "watched"
  };

  const root = document.createElement("div");
  root.className = "browse";
  root.tabIndex = -1;
  root.setAttribute("role", "group");
  root.setAttribute("aria-label", esc(STR.browse));
  // The two ways off the deck come before the stage in the DOM, so they are the
  // first two tab stops instead of the last two. They are positioned absolutely,
  // so where they sit on the glass does not move.
  root.innerHTML = `<div class="bchrome">
      <button type="button" class="btop" data-act="newest" hidden
              title="${esc(STR.browseNewestTitle)}">${esc(STR.browseNewest)}</button>
      <button type="button" class="bnew" data-act="fresh"
              title="${esc(STR.browseFreshTitle)}">${esc(STR.browseFresh)}</button>
      <button type="button" class="bexit" data-act="exit"
              title="${esc(STR.inbox)}">${esc(STR.inbox)}</button>
    </div>
    <div class="bstage"></div>
    <dialog class="bsheet"></dialog>`;
  el.innerHTML = "";
  el.append(root);
  const stage = root.querySelector(".bstage");
  const height = () => stage.clientHeight || 1;

  // ------------------------------------------------------------- painting

  // The deck's counter is the session's, and the session counts posts. A story
  // card sits between two posts, so the number must not move when it is shown.
  function postOrdinal(idx) {
    let n = 0;
    for (let k = 0; k <= idx && k < S.items.length; k++)
      if (S.items[k].kind !== "story") n += 1;
    return n || 1;
  }

  // The session's own count, but never smaller than the cards on the glass: an
  // older batch pushed the ordinal past the total and the counter read 21 of 20.
  const feedPosts = idx => Math.max(S.total + S.added, postOrdinal(idx));

  function cellHTML(it, pic, k, who, story) {
    // The thumbnail paints while the full file is still coming down. Without
    // it a cold card is a black hole that fills in from nowhere; with it, the
    // card is already the picture and the file only sharpens it.
    const bg = pic?.thumb
      ? ` style="background-image:url('${esc(pic.thumb)}')"` : "";
    const media = !pic
      ? `<p class="bfail">${esc(STR.imgFailed)}</p>`
      : pic.type === "video"
        ? `<video class="bmedia" data-src="${esc(pic.full)}"
             poster="${esc(pic.thumb || "")}" muted loop playsinline
             preload="none" draggable="false"${bg}></video>
           ${barHTML(!story)}
           ${story ? "" : `<p class="bheard" aria-live="polite"></p>`}`
        : `<img class="bmedia" src="${esc(pic.full)}" alt="${esc(who)}"
             loading="lazy" draggable="false"${bg}>`;
    return `<div class="bpic" data-i="${k}">${media}</div>`;
  }

  function bodyHTML(it, idx) {
    const who = it.account?.username || it.account?.pk || "";
    const face = it.account?.pic || "";
    const story = it.kind === "story";
    const res = pics(it);
    const n = res.length;
    const cells = n
      ? res.map((p, k) => cellHTML(it, p, k, who, story)).join("")
      : cellHTML(it, null, 0, who, story);
    const caption = (it.caption || "").trim();
    return `<div class="bcard"><div class="bpics">${cells}</div></div>
      <div class="bmeta">
        <p class="bwho">${face
          ? `<img class="bavatar" src="${esc(face)}" alt="">` : ""}<span
          class="bwho-name">${esc(who)}</span>${linksHTML(it, 0)}</p>
        <p class="bwhen">${story || !feedPosts() ? "" : `<span class="bcount"
          role="status">${esc(STR.of(postOrdinal(idx), feedPosts(idx)))}</span> · `}${
          n > 1 ? `<span data-when>${esc(picWhen(it, 0))}</span>`
                : esc(picWhen(it, 0))}${n > 1
            ? ` · <span data-photo>${esc(STR.photoN(1, n,
              picKind(it, 0)))}</span>` : ""}</p>
        ${marksHTML(0, n)}
        ${caption ? `<p class="bcap">${captionHTML(caption)}</p>` : ""}
      </div>`;
  }

  // A story card whose segments are not stored yet: the fetch is the person's,
  // spent on arrival, and it registers a view on Instagram — so it happens when
  // the card is reached and nowhere earlier. It is still the same card, though:
  // the sentence sits where the picture will be and the name stays in the meta
  // row, because a card whose name is in the middle of the glass is a card that
  // looks broken next to the one before it.
  function pendingHTML(it) {
    const who = it.account?.username || it.account?.pk || "";
    const face = it.account?.pic || "";
    const failed = S.stories[it.account_pk]?.state === "failed";
    return `<div class="bcard"><div class="bpics"><div class="bpic"><div class="bhold">
        ${failed
          ? `<p class="bfail">${esc(STR.storyFailed)}</p>
             <button type="button" data-act="story">${esc(STR.retry)}</button>`
          : `<p class="bdone">${esc(STR.storyLoading)}</p>`}
      </div></div></div></div>
      <div class="bmeta">
        <p class="bwho">${face
          ? `<img class="bavatar" src="${esc(face)}" alt="">` : ""}<span
          class="bwho-name">${esc(who)}</span>${linksHTML(it, 0)}</p>
        ${it.count ? `<p class="bwhen">${esc(STR.storyCount(it.count))}</p>` : ""}
      </div>`;
  }

  function slideNode(it, idx) {
    const node = document.createElement("div");
    node.className = `bslide${it.kind === "story" ? " is-story" : ""}`;
    node.setAttribute("data-pk", it.pk);
    node.innerHTML = it.kind === "story" && it.pending
      ? pendingHTML(it) : bodyHTML(it, idx);
    bindSlide(node, it);
    return node;
  }

  // The tail is the one slide that is always there: the next page's loading
  // sentence, the retry after a failure, or the hard stop with the one way
  // further back. The unseen run ends here and the deck never walks past it.
  function tailHTML() {
    if (S.unseen.failed) {
      return `<div class="bend">
        <p class="bfail">${esc(STR.failed)}</p>
        <button type="button" data-act="retry">${esc(STR.retry)}</button>
      </div>`;
    }
    if (S.unseen.more) {
      return `<div class="bend"><p class="bdone">${esc(STR.loading)}</p></div>`;
    }
    const canOlder = !S.older.fetched || S.older.next_cursor !== null;
    return `<div class="bend">
      <p class="bdone">${esc(STR.browseDone)}</p>
      ${canOlder
        ? `<button type="button" data-act="older">${esc(STR.older)}</button>`
        : `<p class="bnone">${esc(STR.noOlder)}</p>`}
      ${S.older.failed ? `<p class="bfail">${esc(STR.failed)}</p>` : ""}
    </div>`;
  }

  function paintTail() {
    if (!S.tailNode) return;
    S.tailNode.innerHTML = tailHTML();
    const b = (act, fn) => S.tailNode.querySelector(`[data-act="${act}"]`)
      ?.addEventListener("click", fn);
    b("older", loadOlder);
    b("retry", retry);
  }

  function renderAll() {
    stage.innerHTML = "";
    S.nodes = [];
    S.items.forEach((it, idx) => {
      const node = slideNode(it, idx);
      stage.append(node);
      S.nodes.push(node);
    });
    S.tailNode = document.createElement("div");
    S.tailNode.className = "bslide is-tail";
    paintTail();
    stage.append(S.tailNode);
    S.i = 0;
    stage.scrollTop = 0;
  }

  // Appending never rebuilds what is already on the glass: the card a person is
  // looking at must not restart its film because the next page arrived.
  function appendItems(list) {
    for (const it of list) {
      const node = slideNode(it, S.nodes.length);
      stage.insertBefore(node, S.tailNode);
      S.nodes.push(node);
    }
    paintTail();
  }

  // One picture per snap point inside the card, so the album index is read the
  // same way the post index is — from the scroll offset.
  function picIndex(node) {
    const strip = node.querySelector(".bpics");
    const cell = node.querySelector(".bpic");
    const w = cell?.offsetWidth || strip?.clientWidth || 1;
    const n = node.querySelectorAll(".bpic").length;
    const k = Math.round((strip?.scrollLeft || 0) / w);
    return Math.max(0, Math.min(Math.max(0, n - 1), k));
  }

  // The platform snaps the album, except when it does not: a flick that crosses
  // the axis lock on iOS can come to rest between two cells, and a card showing
  // half of one picture and half of the next while the counter claims one of
  // them is a lie. This only runs after the scrolling has already stopped, so it
  // cannot fight a gesture.
  function snapStrip(node) {
    const strip = node?.querySelector(".bpics");
    const cells = node?.querySelectorAll?.(".bpic");
    if (!strip || !cells || cells.length < 2) return;
    const w = cells[0]?.offsetWidth || strip.clientWidth || 1;
    const k = Math.max(0, Math.min(cells.length - 1,
      Math.round(strip.scrollLeft / w)));
    if (Math.abs(strip.scrollLeft - k * w) < 2) return;
    strip.scrollLeft = Math.round(k * w);
  }

  function paintPic(node, it) {
    const n = pics(it).length;
    const k = picIndex(node);
    // What the author attached belongs to the picture, so it follows the album.
    const links = node.querySelector(".blinks");
    if (links) links.innerHTML = linksInner(it, k);
    // The time is the picture's, not the card's: the newest segment of a story
    // is not when the segment on the glass was posted.
    const group = node.querySelector("[data-when]");
    if (group) group.textContent = picWhen(it, k);
    if (n < 2) return;
    const marks = node.querySelector(".bmarks");
    // Replaced, not filled: `marksHTML` brings its own row, and filling that row
    // with another one nests it — the dots then bunch at the left edge instead of
    // spread across the card.
    if (marks) marks.outerHTML = marksHTML(k, n);
    const label = node.querySelector("[data-photo]");
    if (label) label.textContent = STR.photoN(k + 1, n, picKind(it, k));
  }

  // ----------------------------------------------------------- the video

  let playing = null;

  function setPlaying(v) {
    if (playing === v) return;
    if (playing) {
      const old = playing;
      playing = null;
      old.pause();
      old.currentTime = 0;
    }
    if (!v) return;
    playing = v;
    v.muted = H.mutedPref();
    const at = v;
    const start = () => {
      if (playing !== at || S.closed) return;
      const p = at.play();
      if (p && p.catch) p.catch(() => {
        // No gesture on this page yet: start silent, keep the preference for
        // once there is one. The bar shows what is actually happening.
        if (playing !== at || S.closed) return;
        at.muted = true;
        const q = at.play();
        if (q && q.catch) q.catch(() => {});
      });
    };
    // The film is not downloaded until its card is reached: a deck of ten
    // reels must not pull ten films to show one.
    if (!v.getAttribute("src")) {
      v.setAttribute("src", v.getAttribute("data-src"));
      v.preload = "auto";
      v.load();
    }
    // Starting a film whose first frame is not decoded yet is the black flash:
    // the poster goes away the moment playback starts. Wait for the frame.
    if (v.readyState >= 3) start();
    else v.addEventListener("canplay", start, { once: true });
  }

  function currentCell(node) {
    return node?.querySelectorAll(".bpic")[picIndex(node)] || null;
  }

  function currentVideo(node) {
    return currentCell(node)?.querySelector("video") || null;
  }

  function togglePlay() {
    if (!playing) return;
    if (playing.paused) {
      const p = playing.play();
      if (p && p.catch) p.catch(() => {});
    } else {
      playing.pause();
    }
  }

  // A picture whose file never came down is the deck's sentence, not the
  // browser's broken-image icon on a black screen. A face that never came down
  // is simply absent — an icon beside a name is worse than a name on its own.
  function onMediaError(e, it) {
    const target = e.target;
    if (S.closed || !target) return;
    if (target.classList?.contains("bavatar")) { target.remove(); return; }
    const cell = target.closest?.(".bpic");
    if (!cell) return;
    const isVideo = target.tagName === "VIDEO" || target.tagName === "video";
    if (!isVideo && !target.dataset.retried) {
      // One silent second ask: the media route proxies a CDN link, and a cold
      // card loses that race once in a while (404 on first paint, 200 after).
      target.dataset.retried = "1";
      const src = target.getAttribute("src") || "";
      target.setAttribute("src", `${src}${src.includes("?") ? "&" : "?"}r=1`);
      return;
    }
    // The card stays put and offers a way out of the failure. A transient CDN
    // blip used to cost the post with no way to ask again.
    cell.innerHTML = `<p class="bfail">${
      esc(isVideo ? STR.vidFailed : STR.imgFailed)}</p>
      <button type="button" data-act="media">${esc(STR.retry)}</button>`;
    cell.querySelector('[data-act="media"]')?.addEventListener("click", () => {
      if (!S.closed) rerender(it);
    });
  }

  // Everything the author attached, in one sheet: the card keeps its picture.
  // `<dialog>` is the platform's own modal — Escape, the backdrop and the focus
  // trap come with it, and on a phone it is already a bottom sheet.
  function openLinks(it, k) {
    const rows = linkRows(it, k);
    const sheet = root.querySelector(".bsheet");
    if (!rows || !sheet) return;
    sheet.innerHTML = `<div class="bsheet-h">
        <h2 id="bsheet-t">${esc(STR.links)}</h2>
        <button type="button" data-act="close">${esc(STR.close)}</button>
      </div>
      <ul>${rows}</ul>`;
    sheet.setAttribute("aria-labelledby", "bsheet-t");
    sheet.querySelector('[data-act="close"]')
      ?.addEventListener("click", () => closeLinks(sheet));
    if (sheet.showModal) sheet.showModal();
    else sheet.setAttribute("open", "");
  }

  function closeLinks(sheet) {
    if (sheet.close) sheet.close();
    else sheet.removeAttribute("open");
  }

  // Bound once per slide, on the real elements: the transport rides with its own
  // film, so nothing has to be re-found when the album moves.
  function bindSlide(node, it) {
    node.addEventListener("error", e => onMediaError(e, it), true);
    // The links control is re-drawn when the album moves, so the press is caught
    // on the card rather than on a button that no longer exists.
    node.addEventListener("click", e => {
      if (!e.target?.closest?.('[data-act="links"]')) return;
      openLinks(it, picIndex(node));
    });
    node.querySelectorAll(".bbar").forEach(bar => {
      const cell = bar.closest(".bpic") || node;
      const v = cell.querySelector("video") || node.querySelector("video");
      if (!v) return;
      const pp = bar.querySelector('[data-act="pp"]');
      const seek = bar.querySelector("[data-seek]");
      const time = bar.querySelector("[data-time]");
      const mute = bar.querySelector('[data-act="mute"]');
      const hear = bar.querySelector('[data-act="hear"]');
      const dur = () => (Number.isFinite(v.duration) ? v.duration : 0);
      const clock = t => {
        const n = Math.max(0, Math.round(t || 0));
        return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;
      };
      const paintTime = () => {
        if (time) time.textContent = `${clock(v.currentTime)} / ${clock(dur())}`;
        if (seek && dur()) {
          seek.value = String(Math.round((v.currentTime / dur()) * 1000));
        }
      };
      const paintPP = () => {
        if (!pp) return;
        pp.innerHTML = v.paused ? G_PLAY : G_PAUSE;
        const label = v.paused ? STR.play : STR.pause;
        pp.setAttribute("aria-label", label);
        pp.setAttribute("title", label);
      };
      const paintMute = () => {
        if (!mute) return;
        mute.innerHTML = v.muted ? G_MUTE : G_SOUND;
        // One name, state in `aria-pressed`: a control that renames itself is
        // two controls to a screen reader, and the state is announced twice.
        // The `title` keeps the sentence for a sighted hover.
        mute.setAttribute("aria-label", STR.mute);
        mute.setAttribute("title", v.muted ? STR.muteOff : STR.muteOn);
        mute.setAttribute("aria-pressed", String(v.muted));
      };
      v.addEventListener("loadedmetadata", paintTime);
      v.addEventListener("durationchange", paintTime);
      v.addEventListener("timeupdate", paintTime);
      v.addEventListener("play", paintPP);
      v.addEventListener("pause", paintPP);
      seek?.addEventListener("input", () => {
        if (dur()) v.currentTime = (Number(seek.value) / 1000) * dur();
      });
      pp?.addEventListener("click", () => {
        if (v === playing) return togglePlay();
        setPlaying(v);
      });
      mute?.addEventListener("click", () => {
        v.muted = !v.muted;
        if (v === playing) H.rememberMute(v.muted);
        paintMute();
      });
      hear?.addEventListener("click", () => {
        const out = cell.querySelector(".bheard");
        hearIt(hear, out, it, Number(cell.getAttribute("data-i") || 0));
      });
      paintPP();
      paintMute();
      paintTime();
    });
    const cap = node.querySelector(".bcap");
    // A press on a mention is a link, not a request to open the caption: doing
    // both leaves the card re-laid-out when the reader comes back.
    cap?.addEventListener("click", e => {
      if (e.target.closest?.("a")) return;
      cap.classList.toggle("is-open");
    });
    node.querySelector('[data-act="story"]')?.addEventListener("click", () => {
      S.stories[it.account_pk] = { state: "idle" };
      loadStory(it, true);
    });
  }

  // "What is this?" — the one control that leaves the machine. Nothing is sent
  // before the press and nothing after the answer; the film goes to the house,
  // which asks Shazam, so no account and no token reach the page. The answer is a
  // line under the transport, not a window: iOS blocks a scripted `window.open`
  // once a promise has been awaited, and a link the reader presses also opens the
  // Spotify app rather than a tab.
  let busyTimer = null;
  function clearBusy() {
    if (busyTimer) { clearInterval(busyTimer); busyTimer = null; }
  }

  async function hearIt(btn, out, it, photo) {
    if (!out || !it || btn.disabled) return;
    const idx = S.items.indexOf(it);
    btn.disabled = true;
    out.textContent = STR.hearing;
    try {
      // A press that hangs on a throttled service must end: twenty-five seconds
      // is past every honest answer and short enough to still feel like a button.
      const stop = new AbortController();
      const giveUp = setTimeout(() => stop.abort(), 25000);
      let r;
      try {
        r = await H.api(`/api/recognize/${encodeURIComponent(it.pk)}/${photo}`,
                        { method: "POST", signal: stop.signal });
      } finally {
        clearTimeout(giveUp);
      }
      if (S.closed || S.items.indexOf(it) !== idx) return;
      if (!r.found) {
        if (r.error !== "RateLimited") { out.textContent = STR.hearNone; return; }
        // A throttle is not a verdict on the song, so it is not said like one:
        // name the reason and the wait, and count the wait down while the note
        // is asleep on exactly that clock.
        let left = BUSY_S;
        out.textContent = STR.hearBusy.replace("{s}", String(left));
        out.setAttribute("aria-live", "off");   // a ticking number is not news
        busyTimer = setInterval(() => {
          left -= 1;
          if (left > 0) {
            out.textContent = STR.hearBusy.replace("{s}", String(left));
            return;
          }
          clearBusy();
          out.textContent = "";
          out.setAttribute("aria-live", "polite");
          btn.disabled = false;
        }, 1000);
        return;
      }
      // Two glyphs, because both are one press: the term on the clipboard, and
      // Spotify's own search for it — a search always lands on the track, while
      // a track id is only there when Shazam happens to know one.
      const term = `${r.artist} ${r.title}`.trim();
      out.innerHTML = `<span class="btrack">${esc(r.artist)} — ${esc(r.title)}</span>
        <button type="button" data-act="copytrack" aria-label="${esc(STR.copyTrack)}"
                title="${esc(STR.copyTrack)}">${G_COPY}</button>
        <a class="bopen" href="https://open.spotify.com/search/${
          esc(encodeURIComponent(term))}" target="_blank" rel="noopener"
           aria-label="${esc(STR.openSpotify)}"
           title="${esc(STR.openSpotify)}">${G_SPOTIFY}</a>`;
      const copy = out.querySelector('[data-act="copytrack"]');
      copy?.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(term);
        } catch {
          return;              // a refusal leaves the glyph as it was
        }
        copy.innerHTML = G_TICK;
        copy.setAttribute("aria-label", STR.copied);
        copy.setAttribute("title", STR.copied);
        // Back to the copy glyph: a tick that stays forever stops looking like a
        // button and the next press has nothing to say.
        setTimeout(() => {
          copy.innerHTML = G_COPY;
          copy.setAttribute("aria-label", STR.copyTrack);
          copy.setAttribute("title", STR.copyTrack);
        }, 1600);
      });
    } catch {
      if (S.closed || S.items.indexOf(it) !== idx) return;
      out.textContent = STR.hearFail;
    } finally {
      // Only the countdown wakes the note when there is one; it owns the button.
      if (!busyTimer) btn.disabled = false;
    }
  }

  // --------------------------------------------------------------- data

  // O(n²) over one session's snapshot, which is tens of posts.
  // ponytail: linear scan per append; index by pk if a session ever reaches
  // thousands.
  function push(list) {
    for (const it of list || []) {
      if (!S.items.some(x => x.pk === it.pk)) S.items.push(it);
    }
  }

  async function fetchUnseen() {
    if (S.unseen.busy || !S.unseen.more) return;
    S.unseen.busy = true;
    S.unseen.failed = false;
    const around = S.at;
    const named = S.atNamed;
    S.at = null;             // spent: a retry asks for the plain feed
    S.atNamed = false;
    try {
      let empty = 0;
      // The session snapshot keeps posts already seen in it, for the bulletin.
      // The deck is about unseen posts, so they are dropped here — including the
      // ones only the local set knows about, because the POST lags by 2s.
      while (S.unseen.more && empty < MAX_EMPTY) {
        const p = new URLSearchParams({
          session: String(H.state.session.id), limit: String(PAGE) });
        if (S.unseen.cursor) p.set("cursor", S.unseen.cursor);
        const body = await H.api(`/api/feed?${p}`);
        if (S.closed) return;
        S.tailCursor = body.tail_cursor ?? S.tailCursor;
        S.unseen.cursor = body.next_cursor ?? null;
        S.unseen.more = !!body.next_cursor;
        const before = S.items.length;
        push((body.items || []).filter(
          it => !it.seen && !H.state.feed.seenLocal.has(it.pk)));
        if (S.items.length > before) break;
        empty += 1;
      }
      // The card the reader asked for, or the one they left off on. It is
      // already read server-side, so the unseen run above can never hold it —
      // and asking for it alone used to hide the whole run (the "around" page
      // answers with one card and no cursor). Fetched separately, merged by
      // time, it lands where it belongs in the deck's order.
      if (around && (named || S.items.length)) {
        const p = new URLSearchParams({
          session: String(H.state.session.id), limit: String(PAGE),
          around_pk: around });
        const body = await H.api(`/api/feed?${p}`).catch(() => null);
        if (S.closed) return;
        for (const it of body?.items || [])
          if (it.pk === around || (!it.seen && !H.state.feed.seenLocal.has(it.pk)))
            push([it]);
        S.items.sort((x, y) => (y.taken_at || 0) - (x.taken_at || 0));
      }
      // The top of the deck is the newest post we have, full stop. A session
      // holds unseen posts only, so its first card can be a week old — or, when
      // the reader comes back to a remembered card, the deck can start halfway
      // down and have nothing above it at all. Both are why the newest control used to
      // land on a week-old post.
      // Nothing unseen is the end of the run, not a reason to re-show a card
      // reader already read: the tail's older button is the way forward
      // from there. With a deck, the newest post we have still sits on top —
      // the session's first unseen card can be a week old.
      if (S.items.length) {
        const lead = await H.api("/api/newest").catch(() => null);
        if (S.closed) return;
        const newest = lead?.items?.[0];
        const firstAt = S.items[0]?.taken_at || 0;
        if (newest && (newest.taken_at || 0) > firstAt) {
          S.items.unshift(newest);
          S.total += 1;          // it is a card of this deck now
        }
      }
    } catch (err) {
      if (err?.status === 401) return;
      S.unseen.failed = true;
    } finally {
      S.unseen.busy = false;
    }
  }

  // The next page arrives where the reader is, not on a press: scrolling into
  // the tail is the press.
  function loadUnseen() {
    const from = S.items.length;
    return fetchUnseen().then(() => {
      if (S.closed) return;
      if (S.items.length > from) appendItems(S.items.slice(from));
      paintTail();
    });
  }

  function prefetch() {
    if (S.unseen.busy || !S.unseen.more) return;
    if (S.i < S.items.length - 2) return;
    loadUnseen();
  }

  // ---------------------------------------------------------------- stories

  // A story account is one card: its segments are the card's pictures, which is
  // what an album already means. `pending` is a card whose segments are not
  // stored yet — the fetch happens when it is reached, never before, because it
  // registers a view on Instagram.
  function storyItem(e) {
    return {
      pk: `story:${e.account.pk}`, kind: "story", taken_at: e.when || 0,
      account: e.account, account_pk: e.account.pk, caption: null, seen: false,
      pending: !!e.pending, count: e.count || 0, resources: e.resources || [],
    };
  }

  async function fetchStories() {
    try {
      const body = await H.api("/api/browse/stories");
      return S.closed ? [] : (body.items || []);
    } catch {
      return [];   // stories are an addition; the posts stand on their own
    }
  }

  // Stories are appended behind the posts, never sorted into them: "what is
  // new" is the question the deck exists to answer, and it must not cost
  // thirty-four story swipes first. A story card that arrives after the first
  // paint is inserted, never a rebuild, so nothing under the thumb moves.
  function mergeStories(entries) {
    for (const e of entries) {
      const it = storyItem(e);
      const at = S.items.findIndex(x => x.pk === it.pk);
      if (at >= 0) S.items[at] = it;
      else S.items.push(it);
    }
  }

  function markStorySeen(pk) {
    if (!pk || S.storySeen.has(pk)) return;
    S.storySeen.add(pk);
    H.api("/api/stories/seen", { method: "POST", body: { pks: [pk] } })
      .catch(() => {});
  }

  // Arrival is not watching. The segment counts as seen only if the card is
  // still the one on the glass a moment later — a swipe through the deck keeps
  // the rings alive, and leaving the card is still what marks the account done.
  function watchStory(it, node) {
    clearTimeout(S.storyTimer);
    S.storyTimer = setTimeout(() => {
      S.storyTimer = null;
      if (S.closed || S.items[S.i] !== it) return;
      markStorySeen(pics(it)[picIndex(node)]?.pk);
    }, VIEW_MS);
  }

  // Leaving the card is not finishing the ring: swiping past a story nobody
  // watched used to mark the account done, and its unwatched segments were
  // hidden for ever. The segments decide — the ring is offered while any live
  // one is unseen, and disappears when the last one is watched.
  function closeStory() {
    S.storyOpen = null;
  }

  function rerender(it) {
    const idx = S.items.indexOf(it);
    const stale = S.nodes[idx];
    if (idx < 0 || !stale) return;
    const fresh = slideNode(it, idx);
    stage.insertBefore(fresh, stale);
    stale.remove();
    S.nodes[idx] = fresh;
    if (S.i === idx) activate();
  }

  // A ring the server no longer has costs one fetch and then leaves the deck:
  // a card that says "loading" for ever is worse than a card that is not there.
  function dropStory(it) {
    const idx = S.items.indexOf(it);
    if (idx < 0 || S.closed) return;
    const node = S.nodes[idx];
    S.items.splice(idx, 1);
    S.nodes.splice(idx, 1);
    node?.remove();
    S.stories[it.account_pk] = { state: "empty" };
    H.api(`/api/stories/${encodeURIComponent(it.account_pk)}/done`,
          { method: "POST" }).catch(() => {});
    if (idx < S.i) S.i -= 1;
    if (S.i === idx) {
      stage.scrollTop = Math.max(0, idx - 1) * height();
      S.i = Math.max(0, idx - 1);
    }
    activate();
  }

  function applyStory(it, segs) {
    it.pending = false;
    it.count = segs.length;
    it.resources = segs.map((s, k) => ({
      pk: s.pk, idx: k, type: s.media_type === 2 ? "video" : "photo",
      duration: null,
      taken_at: s.taken_at,
      // The stickers ride with the segment: one picture, one set of tags.
      links: s.links || [],
      // The media route is the truth; `src` is only filled in while the segment
      // is still live enough for the viewer to offer it.
      full: s.src || `/api/media/story/${s.pk}`,
      thumb: s.thumb || `/api/media/story/${s.pk}?thumb=1`,
    }));
    rerender(it);
  }

  async function loadStory(it, force = false) {
    const acc = it.account_pk;
    const st = S.stories[acc] || (S.stories[acc] = { state: "idle" });
    if (st.state === "fetching" || (st.state === "done" && !force)) return;
    st.state = "fetching";
    try {
      await H.api(`/api/stories/${encodeURIComponent(acc)}/fetch`,
                  { method: "POST" });
      // 202: the fetch runs on the executor. Poll the endpoint the viewer uses,
      // then take what it stored; a failure there is a sentence, not a spinner.
      const deadline = Date.now() + 30000;
      let body = null;
      let polls = 0;
      let ran = false;
      while (!S.closed && Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 700));
        polls += 1;
        body = await H.api(`/api/stories/${encodeURIComponent(acc)}`)
          .catch(() => null);
        const state = body?.fetch_state;
        if (state === "failed") throw new Error(body.error || "failed");
        if (state === "running" || state === "queued") ran = true;
        // `viewed` is a picture too: the ring may already have been watched
        // somewhere, and those segments still have bytes.
        if ((body?.items || []).some(s => s.state !== "expired")) break;
        // The job is over and it stored nothing — a ring whose media expired
        // while the tray still counted it. That is not a failure to report.
        if (state === "idle" && (ran || polls >= 3)) break;
      }
      if (S.closed) return;
      const segs = (body?.items || []).filter(s => s.state !== "expired");
      if (!segs.length) { dropStory(it); return; }
      st.state = "done";
      applyStory(it, segs);
    } catch {
      st.state = "failed";
      if (!S.closed) rerender(it);
    }
  }

  async function loadOlder() {
    if (S.older.busy) return;
    if (S.older.fetched && S.older.next_cursor === null) return;
    S.older.busy = true;
    S.older.failed = false;
    try {
      const p = new URLSearchParams({ limit: String(PAGE) });
      const cursor = S.older.fetched ? S.older.cursor : S.tailCursor;
      if (cursor) p.set("cursor", cursor);
      const body = await H.api(`/api/older?${p}`);
      if (S.closed) return;
      S.older.fetched = true;
      S.older.cursor = body.next_cursor ?? null;
      S.older.next_cursor = body.next_cursor ?? null;
      const before = S.items.length;
      push(body.items);
      if (S.items.length > before) {
        S.added += S.items.length - before;
        appendItems(S.items.slice(before));
        // Reading `scrollHeight` forces the layout the new cards need. Without
        // it the scroll below clamps against the old end and the deck lands
        // back on the tail, so the older button looked like it did nothing.
        void stage.scrollHeight;
        goTo(before, true);    // the first card of the batch, not the stop block
      } else {
        paintTail();
      }
    } catch (err) {
      if (err?.status === 401) return;
      S.older.failed = true;
      paintTail();
    } finally {
      S.older.busy = false;
    }
  }

  // ------------------------------------------------------------- movement

  // The deck reads its position, it never writes one: the browser moves, and the
  // settle says where it stopped.
  // Motion is a preference, not a default. A one-card step can glide; a jump of
  // more than two cards lands instantly for everyone, because ten cards of
  // fly-by is disorienting even to people who never asked for less motion.
  const reducedMotion = () =>
    typeof matchMedia === "function"
    && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const glide = cards => (reducedMotion() || cards > 2 ? "auto" : "smooth");

  function indexAt() {
    const i = Math.round(stage.scrollTop / height());
    return Math.max(0, Math.min(S.items.length, i));
  }

  function goTo(i, instant = false) {
    const k = Math.max(0, Math.min(S.items.length, i));
    // `auto` picks up the CSS `scroll-behavior`; a jump the reader asked for by
    // name lands now, so a nine-card fly-by cannot overshoot the blocker.
    stage.scrollTo({ top: k * height(),
                     behavior: instant ? "instant" : glide(Math.abs(k - S.i)) });
  }

  function slideAlbum(dir) {
    const node = S.nodes[S.i];
    const strip = node?.querySelector(".bpics");
    if (!strip) return;
    const w = strip.clientWidth || 1;
    const k = Math.max(0, Math.min(pics(S.items[S.i]).length - 1, picIndex(node) + dir));
    strip.scrollTo({ left: k * w, behavior: glide(1) });
  }

  // Called on every settle, once per index: what is on the glass is what gets
  // played, marked seen and fetched. Nothing before, nothing in the middle.
  function activate() {
    if (S.closed) return;
    paintNewest();
    const it = S.items[S.i];
    if (S.storyOpen && S.storyOpen !== (it?.kind === "story" ? it.account_pk : null))
      closeStory();
    if (!it) {
      // The tail: either the unseen run is over, or this is where the next page
      // is asked for. Scrolling into the stop block is the whole gesture.
      setPlaying(null);
      if (S.unseen.more && !S.unseen.busy && !S.unseen.failed) loadUnseen();
      return;
    }
    const node = S.nodes[S.i];
    if (it.kind === "story") {
      if (it.pending) loadStory(it);
      else {
        paintPic(node, it);
        watchStory(it, node);
        S.storyOpen = it.account_pk;
      }
    } else if (!it.seen) {
      it.seen = true;
      H.markSeenLocally(it.pk);
    }
    // The card the reader stopped on is the one to come back to.
    if (it.kind !== "story") rememberPk(it.pk);
    // Under `prefers-reduced-motion` nothing starts by itself: the card offers
    // a play button and that is the only thing that starts a film.
    setPlaying(reducedMotion() ? null : currentVideo(node));
    prefetch();
  }

  function onSettle(e) {
    if (S.closed) return;
    const target = e?.target;
    if (target && target !== stage) {
      // A nested scroller settled: the album strip inside one card.
      const node = target.closest?.(".bslide");
      const idx = S.nodes.indexOf(node);
      if (idx < 0) return;
      const it = S.items[idx];
      if (!it) return;
      snapStrip(node);
      paintPic(node, it);
      if (idx === S.i && it.kind === "story")
        markStorySeen(pics(it)[picIndex(node)]?.pk);
      if (idx === S.i)
        setPlaying(reducedMotion() ? null : currentVideo(node));
      return;
    }
    const i = indexAt();
    if (i !== S.i || !playing) { S.i = i; activate(); }
  }

  function onScroll(e) {
    if (S.closed) return;
    // Moving off the card cancels its dwell: the story was not watched.
    clearTimeout(S.storyTimer);
    S.storyTimer = null;
    // `scrollend` is the browser's own answer; this is the fallback for the
    // engines that do not have it yet.
    clearTimeout(S.quiet);
    S.quiet = setTimeout(() => onSettle(e), SETTLE_MS);
  }

  function onKey(e) {
    if (S.closed || e.repeat) return;
    // The sheet owns Escape while it is up: the platform closes it, and the
    // deck must not read the same press as "leave".
    if (e.key === "Escape") {
      const sheet = root.querySelector(".bsheet");
      if (sheet && sheet.getAttribute("open") !== null) return;
      e.preventDefault();
      return leave();
    }
    // A focused control owns its own keys: Space on a button is that button's
    // press, and on the seek bar it is the bar's. Only the deck itself gets the
    // shortcuts. Without this the deck swallowed Space before the button saw it,
    // and toggled whichever film happened to be playing instead.
    const inControl = !!e.target?.closest?.(
      "[data-act], input, textarea, select, a, button");
    if (e.key === " " || e.key === "Spacebar") {
      if (inControl) return;
      e.preventDefault();
      return togglePlay();
    }
    if (inControl) return;
    let handled = true;
    // Down is next, and the keys move the same scroller a thumb moves.
    if (e.key === "ArrowDown") goTo(S.i + 1);
    else if (e.key === "ArrowUp") goTo(S.i - 1);
    else if (e.key === "ArrowRight") slideAlbum(1);
    else if (e.key === "ArrowLeft") slideAlbum(-1);
    // A sixty-card deck must not be walked with sixty presses.
    else if (e.key === "Home") goTo(0);
    else if (e.key === "End") goTo(S.items.length - 1);
    else if (e.key === "PageDown") goTo(S.i + 5);
    else if (e.key === "PageUp") goTo(S.i - 5);
    else handled = false;
    if (handled) e.preventDefault();
  }

  function retry() {
    const again = S.retry;
    S.retry = null;
    S.unseen.failed = false;
    if (again) again();
    else {
      paintTail();
      loadUnseen();
    }
  }

  function leave() {
    if (S.closed) return;
    cleanup();
    H.exit();
  }

  // A session's snapshot is taken when it starts, so a post that arrives later
  // is outside the deck the reader is holding. Taking the session over again is
  // the same thing a fresh visit does — and the newest post is then at the top.
  // The «Newer» button throws away the deck the reader is holding, and their
  // place in it. So: only offered when there is something newer to show, and
  // only after a press that says what it costs. A failed take-over is a
  // sentence, not a button that does nothing.
  function newCount() {
    return Number(H.state.session?.new_since_start || 0);
  }

  function paintFresh() {
    const b = root.querySelector('[data-act="fresh"]');
    if (!b) return;
    b.hidden = newCount() === 0;
  }

  // Forty cards down, the only way back is forty swipes. The newest card is one
  // press away, and the control is absent where it would do nothing.
  const toNewest = () => {
    // The control leads the settle: a press that looks like nothing happened
    // until the scroll ends is a press people press again.
    root.querySelector('[data-act="newest"]').hidden = true;
    goTo(0, true);
  };

  function paintNewest() {
    const b = root.querySelector('[data-act="newest"]');
    if (!b) return;
    b.hidden = S.i === 0;
  }

  async function fresh() {
    if (newCount() > 0 && typeof confirm === "function"
        && !confirm(STR.freshAsk)) return;
    try {
      await H.beginSession({
        mode: H.state.session?.mode || "unseen",
        filters: H.state.session?.filters || {},
      });
    } catch {
      const b = root.querySelector('[data-act="fresh"]');
      if (!b) return;
      const was = b.textContent;
      b.textContent = STR.noConnection;
      setTimeout(() => { if (!S.closed) b.textContent = was; }, 3000);
      return;
    }
    H.reenter?.();
  }

  // ---------------------------------------------------------------- mount

  async function mount() {
    // The tail alone first: the loading sentence fills the glass, never a
    // blank screen.
    renderAll();
    try {
      // The base call comes first even when nothing is known yet: a page loaded
      // straight onto `#/browse` has an empty `state`, while this device may
      // still have an open session — and POSTing one with `take_over: null` is
      // a 409 by design (one open session per device).
      await H.loadBase();
      if (S.closed) return;
      if (!H.state.session) await H.beginSession();
    } catch {
      if (S.closed) return;
      S.retry = mount;
      S.unseen.failed = true;
      paintTail();
      return;
    }
    if (S.closed) return;
    S.total = Number(H.state.session?.remaining ?? 0);
    // Posts first, stories after. The first paint is the answer to "what came in
    // since this morning", and it must not wait on the story tray: those calls
    // hit Instagram per account, and a card nobody is looking at yet is not
    // worth a fourteen-second blank screen.
    await fetchUnseen();
    if (S.closed) return;
    renderAll();
    if (S.unseen.failed) { S.retry = null; paintTail(); return; }
    if (!S.items.length) {
      // Nothing new to read is not nothing new to see: the tray's story cards
      // are new things too. The answer is awaited before the tail is left
      // standing — a tail that says "that is everything" while the story list
      // is still in flight is the lie this branch exists to avoid.
      const list = await fetchStories();
      if (S.closed) return;
      mergeStories(list);
      appendItems(S.items.slice(0));
      if (S.i < S.items.length) { activate(); paintFresh(); }
      return;
    }
    // A link bubble asked for one card: the first paint already holds it, so the
    // deck opens on it without a scroll animation. A target that never came — a
    // failed page, or a post outside this session — leaves the deck at the top.
    const landing = resume ? S.items.findIndex(x => x.pk === resume) : -1;
    if (landing >= 0) {
      stage.scrollTop = landing * height();
      S.i = landing;
    }
    activate();
    paintFresh();
    fetchStories().then(list => {
      if (S.closed || !list.length) return;
      const from = S.items.length;
      const wasTail = S.i >= from;
      mergeStories(list);
      if (S.items.length === from) return;
      appendItems(S.items.slice(from));
      // The tail is where the reader was; it moved down with the cards, so the
      // offset moves with it and the glass does not jump.
      if (wasTail) {
        S.i = S.items.length;
        stage.scrollTop = S.i * height();
      }
    });
  }

  let gone = false;
  function cleanup() {
    if (gone) return;
    gone = true;
    closeStory();
    S.closed = true;
    clearBusy();
    clearTimeout(S.quiet);
    clearTimeout(S.storyTimer);
    setPlaying(null);
    document.removeEventListener("keydown", onKey, true);
    root.querySelector('[data-act="exit"]')
      ?.removeEventListener("click", leave);
    root.querySelector('[data-act="fresh"]')
      ?.removeEventListener("click", fresh);
    root.querySelector('[data-act="newest"]')
      ?.removeEventListener("click", toNewest);
    stage.removeEventListener("scrollend", onSettle, true);
    stage.removeEventListener("scroll", onScroll, true);
    root.remove();
  }

  document.addEventListener("keydown", onKey, true);
  root.querySelector('[data-act="exit"]').addEventListener("click", leave);
  root.querySelector('[data-act="fresh"]').addEventListener("click", fresh);
  root.querySelector('[data-act="newest"]')
    .addEventListener("click", toNewest);
  // A press on the dimmed glass is a "no", like every other sheet.
  root.querySelector(".bsheet")?.addEventListener("click", e => {
    if (e.target === root.querySelector(".bsheet")) closeLinks(e.target);
  });
  // Capture, because a nested scroller's events do not reach us otherwise.
  stage.addEventListener("scrollend", onSettle, true);
  stage.addEventListener("scroll", onScroll, true);

  root.focus?.();
  await mount();
  return cleanup;
}
