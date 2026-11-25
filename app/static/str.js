// Every Greek word the app shows. Nothing else may contain one: a string a
// screen writes for itself is a string nobody can fix in one place.
// `key` is what app.js, views.js and browse.js refer to; `(x)` is a function.
// One entry per line, so the table stays parseable and greppable.
export const STR = {
  // the two screens
  browse: "Περιήγηση",
  browseFresh: "Ανανέωση",
  browseFreshTitle: "Ξαναρχίζει από τα νεότερα",
  browseNewest: "Νεότερα",
  browseNewestTitle: "Πίσω στην πρώτη κάρτα",
  unread: "νέο",
  freshAsk: "Να ξαναρχίσω από τα νεότερα; Θα χάσεις τη θέση σου.",
  inbox: "Μηνύματα",

  // the deck
  browseDone: "Τα νέα τελείωσαν.",
  older: "Παλαιότερα…",
  noOlder: "Δεν υπάρχουν παλαιότερα αποθηκευμένα.",
  of: (n, m) => `${n} από ${m}`,
  photoN: (n, m, kind = "φωτό") => `${kind} ${n} από ${m}`,
  unitPhoto: "φωτό",
  unitVideo: "βίντεο",
  storyLoading: "Φορτώνω την ιστορία…",
  storyCount: n => (n === 1 ? "1 ιστορία" : `${n} ιστορίες`),
  storyFailed: "Η ιστορία δεν φόρτωσε.",
  imgFailed: "Η εικόνα δεν κατέβηκε.",
  vidFailed: "Το βίντεο δεν άνοιξε.",

  // the transport under a film
  play: "Αναπαραγωγή",
  pause: "Παύση",
  seekLabel: "Θέση βίντεο",
  mute: "Ήχος",
  muteOff: "Ήχος κλειστός",
  muteOn: "Ήχος ανοιχτός",

  // what the author attached: one control, because five chips re-flow the card
  links: "Σύνδεσμοι",
  close: "Κλείσιμο",

  // «Τι παίζει;»
  hear: "Αναγνώριση τραγουδιού",
  hearing: "Ακούω…",
  hearNone: "Δεν το αναγνώρισα.",
  hearFail: "Δεν μπόρεσα να την αναγνωρίσω.",
  hearBusy: "Πολλές προσπάθειες — ξαναδοκίμασε σε {s} δ.",
  openSpotify: "Αναζήτηση στο Spotify",
  copyTrack: "Αντιγραφή τίτλου",
  copied: "Αντιγράφηκε",

  // failures, one panel
  failed: "Δεν φόρτωσε.",
  retry: "Δοκιμή ξανά",
  noConnection: "Δεν υπάρχει σύνδεση.",
  loading: "Φορτώνω…",

  // the way in
  signIn: "Σύνδεση",
  password: "Κωδικός",
  wrongPassword: "Λάθος κωδικός.",

  // the inbox
  inboxStale: "Δεν φόρτωσαν τώρα — δείχνω την τελευταία λίστα.",
  inboxEmpty: "Κανένα μήνυμα.",
  inboxFail: "Δεν φόρτωσαν τα μηνύματα.",
  inboxBack: "Πίσω",

  // the chat screen
  msgsNoToken: "Λείπει το token του Telegram — δεν έρχονται μηνύματα.",
  msgsSend: "Αποστολή",
  msgsPlaceholder: "Γράψε ένα μήνυμα…",
  msgsSending: "Στέλνω…",
  msgsSendFailed: "Το μήνυμα δεν στάλθηκε.",
  msgsResolving: "Φορτώνω το ποστ…",
  msgsResolveFailed: "Το ποστ δεν φόρτωσε.",
  msgsResolveUnsupported: "Το ποστ είναι ιστορία — δεν ανοίγει εδώ.",
  msgsOpenDeck: "Άνοιγμα στην περιήγηση",
  msgsOpenInstagram: "Άνοιγμα στο Instagram",
  msgsKindPhoto: "φωτογραφία",
  msgsKindVideo: "βίντεο",
  msgsKindVoice: "φωνητικό",
  msgsKindFile: "αρχείο",
  msgsKindSticker: "αυτοκόλλητο",
  msgsKindPoll: "ψηφοφορία",
  msgsKindLink: "σύνδεσμος",
};

// Pinned array, not Intl: el-GR month forms differ between WebKit builds and
// the deck pins `14 Νοε 21:14`.
export const MONTHS = ["Ιαν", "Φεβ", "Μαρ", "Απρ", "Μαΐ", "Ιουν",
                       "Ιουλ", "Αυγ", "Σεπ", "Οκτ", "Νοε", "Δεκ"];
export const YESTERDAY = "χθες";
