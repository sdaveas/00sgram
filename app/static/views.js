// Two screens: the deck and the inbox. There is no bulletin, no accounts, no
// history and no settings screen — the program is one stream of posts and one
// list of conversations, so the copy, the helpers and the frame are all here.

import { STR } from "./str.js";

let H = {};
let state;
export function init(env) { H = env; state = env.state; }

// One audio preference for the whole app. A clip that needs unmuting again on
// every segment, post and reload is worse than a silent one.
const MUTE_KEY = "00sgram.muted";
export function mutedPref() {
  try { return localStorage.getItem(MUTE_KEY) !== "0"; } catch { return true; }
}
export function rememberMute(muted) {
  try { localStorage.setItem(MUTE_KEY, muted ? "1" : "0"); } catch {}
}

// What the deck remembers between routes: the posts this device has already
// reported seen, so a page fetched twice does not offer a seen post as new.
export function blankDeck() {
  return { seenLocal: new Set() };
}

// The feed is a rolling day, not a backlog: "what is new" means yesterday and
// today, and a post from last week is not the news however unseen it is.
const WINDOW_S = 24 * 60 * 60;

// A session is a finite snapshot: opening a new one throws the old seen marks
// away, because nothing in them is still true on the other side.
export async function beginSession(body = {}) {
  // The window is recomputed every time, never inherited: a session opened
  // yesterday would otherwise still be asking for yesterday's day.
  const from = Math.floor(Date.now() / 1000) - WINDOW_S;
  await H.api("/api/sessions", { method: "POST",
    body: { mode: "unseen", ...body,
            filters: { ...(body.filters || {}), from },
            take_over: state.session?.id ?? null } });
  state.feed = blankDeck();
  await H.loadBase();
}

// ----------------------------------------------------------------- screens

export function login(el) {
  el.innerHTML = `
    <form class="login sheet stack">
      <h1 class="screen">00sgram</h1>
      <label class="field small">${STR.password}
        <input type="password" name="password" autocomplete="current-password"
               autofocus>
      </label>
      <button class="primary" type="submit">${STR.signIn}</button>
      <p class="small" data-err></p>
    </form>`;
  const form = el.querySelector("form");
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const err = form.querySelector("[data-err]");
    try {
      await H.api("/login", { method: "POST",
                              body: { password: form.password.value } });
      H.navigate("/browse");
    } catch (e) {
      // A network failure is not a wrong password: saying it is sends the reader
      // to retype a password that was never the problem.
      err.textContent = e?.status ? STR.wrongPassword : STR.noConnection;
    }
  });
}

// A chat list and one thread at a time. A message is a bubble; an Instagram
// link inside one resolves in place, because the post behind the link is what
// the reader wanted, not the URL. The server owns storage and the Telegram
// token; this screen owns what a message looks like.
const KIND_PREVIEW = {
  photo: STR.msgsKindPhoto, video: STR.msgsKindVideo, voice: STR.msgsKindVoice,
  file: STR.msgsKindFile, sticker: STR.msgsKindSticker, poll: STR.msgsKindPoll,
  link: STR.msgsKindLink,
};

// One line, and a link is never that line: the URL is the thing the card is
// for, so the list says what kind of thing arrived instead of showing it.
function preview(chat) {
  const words = String(chat.last_text || "")
    .replace(/https?:\/\/\S+/g, " ").replace(/\s+/g, " ").trim();
  if (words) return words;
  return KIND_PREVIEW[chat.last_kind] || STR.msgsKindLink;
}

// A link reads as the part that identifies it: host and path, no scheme, no
// trailing slash. The word for it is the URL itself, not a translation.
function shortLink(url) {
  try {
    const u = new URL(url);
    return `${u.hostname.replace(/^www\./, "")}${u.pathname.replace(/\/+$/, "")}`;
  } catch { return String(url); }
}

export async function messages(el, openChatId = null) {
  let chats = [];
  let configured = true;
  let listFailed = false;
  let chatId = null;
  let isGroup = false;

  el.innerHTML = `<div class="msgs">
    <header class="msgs-head">
      <h1 class="msgs-title">${STR.inbox}</h1>
      <button type="button" data-act="back" hidden>${STR.inboxBack}</button>
      <button type="button" data-act="deck">${STR.browse}</button>
    </header>
    <p class="msgs-note" role="status"></p>
    <div data-view="list"><ul class="msgs-list"></ul></div>
    <div class="mthread" data-view="thread" role="log" aria-live="polite"
         aria-relevant="additions" tabindex="-1" hidden></div>
    <form class="mcomposer" hidden>
      <input name="text" autocomplete="off" aria-label="${STR.msgsPlaceholder}"
             placeholder="${STR.msgsPlaceholder}">
      <button class="msend" type="submit">${STR.msgsSend}</button>
    </form>
  </div>`;

  const root = el.querySelector(".msgs");
  const title = root.querySelector(".msgs-title");
  const note = root.querySelector(".msgs-note");
  const listView = root.querySelector('[data-view="list"]');
  const listEl = root.querySelector(".msgs-list");
  const thread = root.querySelector(".mthread");
  const back = root.querySelector('[data-act="back"]');
  const form = root.querySelector(".mcomposer");
  const input = form.querySelector("input");
  const send = form.querySelector(".msend");

  // ------------------------------------------------------------- the rows
  function paintList() {
    listEl.innerHTML = chats.length
      ? chats.map(c => `
        <li class="msg-row${c.unread === 0 ? " is-read" : ""}">
          <button type="button" data-chat="${H.esc(c.chat_id)}">
            <span class="mk" aria-hidden="true"></span>
            ${c.unread === 0 ? "" : `<span class="sr">${STR.unread}</span>`}
            <span class="who">${H.esc(c.title || c.chat_id)}</span>
            <span class="sub">${H.esc(preview(c))}</span>
            <span class="when">${H.esc(H.when(c.last_at))}</span>
          </button>
        </li>`).join("")
      // A failed read says so in the note; claiming "nobody wrote" would lie.
      : listFailed ? "" : `<li class="msgs-empty">${STR.inboxEmpty}</li>`;
  }

  async function refresh() {
    const data = await H.api("/api/messages");
    configured = data.configured !== false;
    chats = data.chats || [];
  }

  // A chat is only a chat if it moves on its own. The store is local, so a tick
  // costs one query, not a page render — and nothing already on screen is
  // touched, because a re-render would stop the film the reader is watching.
  let timer = null;

  async function tick() {
    if (document.hidden) return;
    if (!chatId) {
      const before = JSON.stringify(chats);
      try { await refresh(); } catch { return; }
      if (JSON.stringify(chats) !== before) paintList();
      note.textContent = configured ? "" : STR.msgsNoToken;
      return;
    }
    const watched = chatId;
    let data;
    try {
      data = await H.api(
        `/api/messages/thread?chat_id=${encodeURIComponent(watched)}`);
    } catch {
      return;              // a tick that fails says nothing; the next may work
    }
    if (chatId !== watched) return;           // the reader moved on meanwhile
    const have = new Set([...thread.querySelectorAll(".mb")]
      .map(n => n.dataset.msg));
    const fresh = (data.messages || [])
      .filter(m => !have.has(String(m.msg_id)));
    if (!fresh.length) return;
    thread.insertAdjacentHTML("beforeend", fresh.map(bubble).join(""));
    // Follow only when the reader is already at the bottom: having scrolled up
    // to read is not a reason to be yanked back down.
    if (thread.dataset.stick !== "0") thread.scrollTop = thread.scrollHeight;
    autoResolve();
  }

  function stopPoll() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  // The newest message's link is the thing a friend just sent, so it loads as
  // the thread opens. Older links wait to be pressed: each one is a page load.
  function autoResolve() {
    if (!configured) return;
    const last = thread.querySelector(".mb:last-child");
    const chip = last && last.querySelector(
      ".mb-linkrow:not(.is-done) [data-resolve]");
    if (chip) resolve(chip);
  }

  // ------------------------------------------------------------ the bubbles
  // The sender's text usually carries the same URL the link row shows under it,
  // so the thread reads as a wall of https. The URL comes out of the words and
  // the words that are left are kept exactly; nothing else is rewritten.
  function wordsOnly(text, links) {
    let out = String(text || "");
    for (const url of links) out = out.split(url).join("");
    return out.replace(/[ \t]{2,}/g, " ").replace(/\n{3,}/g, "\n\n").trim();
  }

  function bubble(m) {
    const links = (m.links || []).filter(Boolean);
    const said = wordsOnly(m.text, links);
    return `<div class="mb ${m.mine ? "mine" : "theirs"}" data-msg="${
      H.esc(String(m.msg_id))}">
      ${!m.mine && isGroup && m.who
        ? `<span class="mb-who">${H.esc(m.who)}</span>` : ""}
      ${said ? `<p class="mb-text">${H.esc(said)}</p>` : ""}
      ${links.length ? `<div class="mb-links">${links.map(u => `
        <div class="mb-linkrow">
          <button type="button" data-resolve="${H.esc(u)}">${
            H.esc(shortLink(u))}</button>
          <div class="mb-card"></div>
          <div class="mb-foot"></div>
        </div>`).join("")}</div>` : ""}
      <span class="mb-at">${H.esc(H.when(m.at))}</span>
    </div>`;
  }

  function failCard(row, unsupported = false) {
    row.classList.add("is-done");
    const card = row.querySelector(".mb-card");
    const foot = row.querySelector(".mb-foot");
    // The URL chip is hidden once the row is done, so the URL has to travel with
    // the failure: a story, or a post that will not load, is still a page
    // Instagram itself can open.
    const url = row.querySelector("[data-resolve]")?.dataset.resolve || "";
    card.className = `mb-card ${unsupported ? "is-unsupported" : "is-failed"}`;
    card.innerHTML = `<p class="mb-line">${unsupported
      ? STR.msgsResolveUnsupported : STR.msgsResolveFailed}</p>${unsupported ? ""
      : `<button type="button" data-act="retry-card">${STR.retry}</button>`}${
      url ? `<a class="mb-open" href="${H.esc(url)}" target="_blank"
        rel="noopener">${STR.msgsOpenInstagram}</a>` : ""}`;
    foot.removeAttribute("data-pk");
    foot.innerHTML = "";
  }

  // The resolved post: one picture or one film, the album's marks, the song,
  // the caption, and the two ways out. Nothing here plays by itself.
  function paintCard(row, item) {
    if (!item) return failCard(row);
    row.classList.add("is-done");
    const card = row.querySelector(".mb-card");
    const foot = row.querySelector(".mb-foot");
    const res = item.resources || [];
    // One cell per resource. A single picture is the card; more than one is a
    // strip, because the dots underneath are a promise the reader can act on.
    const cell = r => r.type === "video"
      ? `<video class="mb-video" controls playsinline preload="metadata"
           src="/api/media/post/${H.esc(item.pk)}/${H.esc(String(r.idx))}"
           ${r.thumb ? `poster="${H.esc(r.thumb)}"` : ""}></video>`
      : `<img class="mb-photo" loading="lazy" alt=""
           src="${H.esc(r.full)}">`;
    let out = "";
    if (res.length > 1) {
      out += `<div class="mb-strip">${res.map(cell).join("")}</div>`;
      out += `<div class="mb-marks">${res.map((_, i) =>
        `<span class="mb-mark${i ? "" : " is-on"}"></span>`).join("")}</div>`;
    } else if (res.length === 1) {
      out += cell(res[0]);
    }
    const song = (item.links || []).find(l => l && l.kind === "music");
    if (song) out += `<p class="mb-music">♫ ${H.esc(song.label || "")}</p>`;
    if (item.caption) out += `<p class="mb-cap">${H.esc(item.caption)}</p>`;
    card.className = "mb-card";
    card.innerHTML = out;
    // The marks follow the strip, they do not guess: the lit dot is the cell
    // the reader settled on.
    const strip = card.querySelector(".mb-strip");
    if (strip) {
      const dots = [...card.querySelectorAll(".mb-mark")];
      strip.addEventListener("scroll", () => {
        const i = Math.round(strip.scrollLeft / (strip.clientWidth || 1));
        dots.forEach((d, k) => d.classList.toggle("is-on", k === i));
      }, { passive: true });
    }
    // Three lines here, two in the deck: both open on a press.
    const cap = card.querySelector(".mb-cap");
    cap?.addEventListener("click", () => cap.classList.toggle("is-open"));
    foot.dataset.pk = item.pk;
    foot.innerHTML = `<button type="button" data-act="open-deck">${
      STR.msgsOpenDeck}</button>${item.permalink
      ? `<a class="mb-open" href="${H.esc(item.permalink)}" target="_blank" rel="noopener">${
        STR.msgsOpenInstagram}</a>` : ""}`;
    // The picture or the film sets the card's height, and it does so after this
    // has run: stick to the bottom once more when the box is final. One event,
    // not a loop — and never against a reader who has scrolled up.
    const media = card.querySelector("img, video");
    if (media) {
      media.addEventListener(media.tagName === "VIDEO" ? "loadedmetadata" : "load",
        () => {
          if (thread.dataset.stick !== "0") thread.scrollTop = thread.scrollHeight;
        }, { once: true });
    }
  }

  async function resolve(btn) {
    const row = btn.closest(".mb-linkrow") || btn.closest(".mb");
    const card = row.querySelector(".mb-card");
    const foot = row.querySelector(".mb-foot");
    btn.disabled = true;
    card.className = "mb-card is-loading";
    card.innerHTML = `<p class="mb-line">${STR.msgsResolving}</p>`;
    foot.innerHTML = "";
    try {
      const data = await H.api(
        `/api/resolve?url=${encodeURIComponent(btn.dataset.resolve)}`);
      if (data && data.kind === "post" && data.item) paintCard(row, data.item);
      else failCard(row);
    } catch (err) {
      failCard(row, !!err && err.code === "unsupported_link");
    } finally {
      btn.disabled = false;
      // The newest thing in a thread is at the bottom, so the card that just
      // arrived is reached by going there — unless the reader scrolled up to
      // read something, which is a choice, not an accident.
      if (thread.dataset.stick !== "0") thread.scrollTop = thread.scrollHeight;
    }
  }

  // ------------------------------------------------------------ the thread
  function showList() {
    const from = chatId;
    chatId = null;
    listView.hidden = false;
    thread.hidden = true;
    back.hidden = true;
    form.hidden = true;
    title.textContent = STR.inbox;
    note.textContent = configured ? "" : STR.msgsNoToken;
    paintList();
    // Back lands on the conversation it came from, not on the top of the list.
    [...listEl.querySelectorAll("[data-chat]")]
      .find(b => b.dataset.chat === from)?.focus();
  }

  async function open(id) {
    chatId = String(id);
    const chat = chats.find(c => String(c.chat_id) === chatId) || {};
    isGroup = chat.kind === "group";
    title.textContent = chat.title || chatId;
    listView.hidden = true;
    thread.hidden = false;
    back.hidden = false;
    form.hidden = !configured;
    note.textContent = "";
    thread.innerHTML = `<p class="msgs-wait">${STR.loading}</p>`;
    try {
      const data = await H.api(
        `/api/messages/thread?chat_id=${encodeURIComponent(chatId)}`);
      title.textContent = data.title || chat.title || chatId;
      thread.innerHTML = (data.messages || []).map(bubble).join("");
      thread.scrollTop = thread.scrollHeight;
      // The list the reader was on is gone; put the cursor in the thread so the
      // next Tab is inside the conversation, not back at the first row.
      thread.focus?.({ preventScroll: true });
      autoResolve();
    } catch {
      thread.innerHTML = "";
      note.textContent = STR.inboxFail;
    }
    // The thread call marks the chat read at the source. Pull the rows again in
    // the background so Back shows the mark already gone, with no second mount.
    try {
      await refresh();
      paintList();
      if (!configured) note.textContent = STR.msgsNoToken;
    } catch {
      note.textContent = STR.inboxStale;
    }
  }

  // ------------------------------------------------------------- the actions
  root.addEventListener("click", e => {
    const t = e.target;
    if (!t || typeof t.closest !== "function") return;
    const row = t.closest("[data-chat]");
    if (row) { open(row.dataset.chat); return; }
    const link = t.closest("[data-resolve]");
    if (link) { if (!link.disabled) resolve(link); return; }
    const again = t.closest('[data-act="retry-card"]');
    if (again) {
      const linkBtn = again.closest(".mb-linkrow")
        ?.querySelector("[data-resolve]");
      if (linkBtn) resolve(linkBtn);
      return;
    }
    if (t.closest('[data-act="open-deck"]')) {
      const pk = t.closest(".mb-foot")?.dataset.pk;
      // Carry the conversation, so the deck's exit is Back to here, not Back to
      // a list of strangers.
      if (pk) H.navigate("/browse?at=" + encodeURIComponent(pk)
        + (chatId ? "&chat=" + encodeURIComponent(chatId) : ""));
      return;
    }
    if (t.closest('[data-act="back"]')) { showList(); return; }
    if (t.closest('[data-act="deck"]')) H.navigate("/browse");
  });

  // Where the reader is when a message arrives decides whether the thread
  // follows it. A press that scrolls is the reader choosing, not noise.
  thread.addEventListener("scroll", () => {
    thread.dataset.stick =
      thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80
        ? "1" : "0";
  }, { passive: true });

  // One film at a time in a thread: a second play is a second soundtrack.
  thread.addEventListener("play", e => {
    if (!e.target || e.target.tagName !== "VIDEO") return;
    for (const other of thread.querySelectorAll("video"))
      if (other !== e.target && !other.paused) other.pause();
  }, true);

  form.addEventListener("submit", async e => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || !chatId) return;
    send.disabled = true;
    send.textContent = STR.msgsSending;
    try {
      const data = await H.api("/api/messages/send",
        { method: "POST", body: { chat_id: chatId, text } });
      input.value = "";
      note.textContent = "";
      if (data && data.message) {
        thread.insertAdjacentHTML("beforeend", bubble(data.message));
        thread.scrollTop = thread.scrollHeight;
      }
    } catch (err) {
      if (err && err.code === "not_configured") {
        configured = false;
        form.hidden = true;
        note.textContent = STR.msgsNoToken;
      } else {
        note.textContent = STR.msgsSendFailed;
      }
    } finally {
      send.disabled = false;
      send.textContent = STR.msgsSend;
    }
  });

  // The rows arrive after the first paint, so the screen is never a blank glass
  // while the list is on its way.
  paintList();
  note.textContent = STR.loading;
  try {
    await refresh();
    note.textContent = configured ? "" : STR.msgsNoToken;
  } catch {
    listFailed = true;
    note.textContent = STR.inboxFail;
  }
  paintList();
  timer = setInterval(tick, 6000);
  // A deck card sent us back to its conversation: open it, do not show the list.
  if (openChatId) open(openChatId);
  return stopPoll;
}
