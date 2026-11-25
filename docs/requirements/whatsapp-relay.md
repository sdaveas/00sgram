# WhatsApp relay

Stage 1 output. The design is `docs/designs/whatsapp-relay.md` (stage 2); this file
says what the thing must do, and — more usefully — what it must never grow into.

## Problem — who hurts, and what breaks today

One person lives in Telegram, and a second life happens in WhatsApp: a family group,
a landlord, a courier, the self chat used as a notepad. Reading WhatsApp means picking
up the phone, unlocking it, and being handed every other app on the way. The Instagram
relay already solves exactly this shape of problem for DMs (one forum topic per
conversation, reply and react from Telegram), and the two apps are now structurally
similar enough that the same relay can be pointed at WhatsApp's DOM.

What breaks today: there is no WhatsApp relay at all, and the Instagram one cannot be
reused as-is — its trigger is a GraphQL last-message id, and WhatsApp Web exposes no
API, no chat id, and no message list for anything but the currently opened chat.

Constraints that are accepted, not solved:

- **There is no chat id anywhere in the DOM.** Topics are keyed by the conversation
  name. A rename on either side creates a second topic; the old one is not migrated.
- **Reading requires opening the chat**, which marks it read on the other side. The
  relay does not try to hide that.
- **Automation is against WhatsApp's terms.** A logged-in browser doing human-shaped
  clicks keeps the risk low; nothing here talks to any private endpoint.

## Requirements

Numbered, EARS. `relay` means the WhatsApp relay process; `topic` means a Telegram
forum topic in `WA_RELAY_CHAT`.

1. When the relay reads the conversation list, it shall treat
   `#pane-side [role="row"]` with `data-testid^="list-item-"` as the conversations,
   and shall ignore rows it cannot name.
2. When the relay names a conversation, it shall use the collapsed text of
   `cell-frame-title` (whitespace and newlines folded to one space), including a
   trailing `(You)` for the self chat, and shall use that name as the conversation's
   only identity.
3. When the relay runs its first cycle after a fresh database, the system shall adopt
   every mounted conversation without posting anything — no history is backfilled.
4. When a known conversation shows a message whose `data-id` is not in that
   conversation's stored id set, the system shall post one Telegram message per such
   message, in DOM order, and shall store each id.
5. When a conversation is seen for the first time after priming, the system shall post
   only its newest message.
6. When a message carries no text (photo, video, voice, audio, sticker, gif, document,
   location, contact, poll), the system shall post a label (`[φωτογραφία]`,
   `[φωνητικό]`, `[sticker]`, …) and shall not download or upload media.
7. When a message arrives in a group conversation, the system shall prefix it with
   `<sender>: `; in a direct conversation and in the self chat the text shall be bare.
8. When a message contains a link, the system shall include the literal URL in the
   message text.
9. When the self chat gains a message, the system shall relay it as well — the self
   chat relays everything, because everything in it is the account's own — and shall
   never relay a message the relay itself typed into WhatsApp.
10. When a Telegram message is typed in a topic bound to a WhatsApp conversation, the
    system shall focus the composer of that conversation, type the text, press Enter,
    and store the resulting message id so it is not relayed back.
11. When Telegram sends a `message_reaction` for a message the relay posted, the
    system shall, if the emoji is one of 👍 ❤️ 😂 😮 😢 🙏, hover that bubble, open the
    reaction bar, click the matching `img[alt="<emoji>"]`, and confirm the bubble now
    shows that reaction; an empty reaction shall remove it.
12. When the reaction emoji is not one of those six, the system shall record the reason,
    mark the reaction done, and click nothing.
13. When a conversation has no topic yet, the system shall create one in
    `WA_RELAY_CHAT` whose name is the conversation name, and shall reuse it forever.
14. When the relay restarts, the system shall not repost any message whose id is
    already stored, and shall not re-send any Telegram→WhatsApp message.
15. When the WhatsApp page is not logged in or the list never appears, the system
    shall leave the app and the Instagram relay running, record the condition, and
    retry on the next cycle.
16. When more than one mounted row carries the same name, the system shall skip that
    conversation and log it. *Amended during stage 2:* the name is the only identity
    (R2), so two rows sharing one cannot have separate topics or separate marks —
    "disambiguating" by preview would only decide which of the two gets both
    conversations' messages. Skipping is the safe reading.
17. When the relay touches WhatsApp, it shall do so on a page belonging to the
    WhatsApp origin, and shall never navigate, reload, or evaluate on the Instagram
    page.
18. When invoked with the QR flag, the system shall write a PNG of the WhatsApp login
    screen to the given path.
19. When Telegram refuses a topic id (deleted by hand), the system shall forget it,
    create a new topic on the next message, and shall not retry the lost message.
20. When a cycle finds a burst, the system shall post at most N messages and continue
    on the next cycle.

## Out of scope

Each of these is something a later session will try to add. The answer is no for v1:

- **WhatsApp → Telegram reactions.** A reaction creates no message, so it cannot be a
  trigger; it would need a diff of every open chat.
- **Media.** WhatsApp media are encrypted blob URLs behind the page's own store.
  Labels only.
- **Status, channels, broadcast lists, calls.** Not conversations, not topics.
- **Backfill.** No history on first sight, none on request.
- **Delete/edit propagation.** A message already posted stays posted.
- **Renaming a topic when a contact renames.** Name is the key; a rename is a new topic.
- **Hiding read receipts.** Opening a chat marks it read; accepted.
- **Emoji outside the six quick ones.** No driving the "+" emoji drawer.
- **Timestamps in Telegram.** The DOM's per-bubble time is not parsed; ids order things.
- **A second WhatsApp account.** One browser profile, one session.
- **Making `relay.py` generic.** It is Instagram-specific and stays that way.

## Open unknowns

| Unknown | Cheapest experiment |
|---|---|
| Where a group bubble's sender name is readable (aria-label vs nested span) | Open one group chat, dump the `aria-label` and inner text of the last three bubbles. ~2 min. |
| Message ids survive a page reload and a phone reconnect | Reload the WhatsApp tab with the relay off, compare the `data-id` set before/after. ~1 min. |
| Clicking a row that sits under the sticky list header | Click the last mounted row (index ~19) and check the opened chat's header. ~1 min. |
| Whether the composer accepts typing right after a row click, without an extra focus click | Type without clicking the composer; read the composer's text back. ~1 min. |
| A Telegram reaction in a topic the bot did not create | Press a reaction in a hand-made topic; the outbox must drop it, not crash. ~1 min. |
