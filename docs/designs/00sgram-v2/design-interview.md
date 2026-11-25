# 00sgram v2 — design interview

Role: design. Input: `brief.md`, `product-owner.md`, and the v1 code
(`views.js`, `style.css`, `index.html`, `test_ui.py`). Output:
`../00sgram-v2.md`. Nothing here is code and nothing touches Instagram.

Method: the PO is interviewed again, this time by the person who has to draw
the screen. Where design and PO disagree, the loop is recorded and the
concession is named. Two loop-backs are mandatory: one to the PO, one to
engineering reality.

## 1. Design → PO

**1. D: Όταν λέτε "παράθυρο", τι βλέπετε πρώτο;**
Το πλαίσιο με τ' όνομα του προγράμματος από πάνω. "00sgram — τα νέα", και τα
τρία κουτάκια δεξιά. Το μεσαίο δεν το πιάνω ποτέ, αλλά αν λείπει μοιάζει
σπασμένο.

**2. D: Πόσα πράγματα θέλετε σε μια οθόνη;**
Ένα. Ό,τι κοιτάζω τώρα. Αν το πρόγραμμα έχει τρεις δουλειές, βάλτε τις στο
μενουδάκι από πάνω, όχι δίπλα στο κείμενο.

**3. D: Η λίστα. Τι γράφει η κάθε γραμμή;**
Όνομα, πότε, τι είναι. Σαν τον φάκελο: Μαρία, 14 Νοεμβρίου, τρία αρχεία.
Και πόσο κρατάει, αν είναι ταινία — "0:41" μου λέει αν θα κάτσω.

**4. D: Δείχνει και τη φωτογραφία η γραμμή;**
Όχι μικρογραφίες. Μια μικρή εικόνα τη βλέπω και νομίζω ότι την είδα. Γράψτε
μου ποιος και πότε· την εικόνα θα την ανοίξω όταν θέλω.

**5. D: Πόσα πατήματα για να δείτε τη φωτογραφία του εγγονού σας;**
Δύο. Ένα στη γραμμή, ένα τίποτα — ανοίγει μόνη της μεγάλη. Δύο πατήματα δεν
με πειράζουν· το ένα πάτημα που δεν ξέρω τι κάνει με πειράζει.

**6. D: Τι γράφει το παράθυρο της εικόνας από πάνω;**
Ποιος και πότε, και το ✕ στη γωνία. Μεγάλη εικόνα, μαύρο γύρω, τίποτα πάνω
της. Αν είναι ταινία, η μπάρα από κάτω. Αν είναι φωτογραφία, καμία μπάρα —
φωτογραφία είναι.

**7. D: Πώς πάτε στην επόμενη;**
Με το βελάκι δίπλα στο "2 από 5". Και με μια λίστα, αν θέλω να πάω αλλού
χωρίς να περάσω από τους ενδιάμεσους.

**8. D: Τι γίνεται στο τέλος της ταινίας;**
Στέκει στην τελευταία εικόνα. Δεν ξαναρχίζει, δεν πάει στην επόμενη. Εγώ
πατάω.

**9. D: Η λίστα τελειώνει κάπου;**
"Σελίδα 1 από 2" και δύο κουμπιά. Και στο τέλος "Αυτά είναι όλα". Αν δεν
υπάρχει τελευταία σελίδα, δεν είναι λίστα, είναι πηγάδι.

**10. D: Η μπάρα από κάτω τι λέει;**
Ό,τι κάνει το πρόγραμμα. "Συνδέομαι…", μετά "Συνδέθηκα — 6 νέα", μετά
σιωπή. Όχι κόκκινα.

**11. D: Όταν δεν έχει ίντερνετ;**
Δείξε μου ό,τι είχες, με ημερομηνία, και πες το μια φορά. Να ξέρω ότι δεν
είναι καινούργια, όχι να μου κρύψεις ότι πάει.

**12. D: Ο ήχος;**
Κλειστός. Το κουμπί να γράφει "Ήχος κλειστός", όχι εικονίδιο. Και να
θυμάται — το είπαμε.

**13. D: Τα γράμματα;**
Πιο μεγάλα από του κινητού. Και όχι γκρι ανοιχτό. Τα γκρι τα διαβάζω δύο
φορές.

**14. D: Οι ιστορίες;**
Λίστα με ονόματα από το μενού "Ιστορίες", όπως η λίστα των αναρτήσεων.
"Μαρία — είδες 2 από 5". Πατάω, μπαίνω, βγαίνω, είμαι πάλι στη λίστα.

**15. D: Τι δεν θέλετε να δείτε ποτέ ξανά;**
Κόκκινη κουκκίδα, νούμερα από καρδιές, "προτεινόμενα", και οτιδήποτε κινείται
πριν το πατήσω.

## 2. Loop A — back to the PO (4 exchanges)

The PO's first pass asked for Greek chrome and "no like button anywhere". Three
of the four points below were settled between us; the fourth is the
orchestrator's binding answer and is not mine to overturn.

### A1. The like control

**PO:** Καρδούλα πουθενά. Την έστειλα μια φορά κατά λάθος και με ρώτησε η κόρη
μου γιατί.

**D:** Το κουμπί υπάρχει στο v1 και ο ιδιοκτήτης το ζήτησε. Αν το σβήσω, του
παίρνω λειτουργία που ζήτησε — αυτό δεν είναι δικό μου να το κάνω. Προτείνω:
μέσα στα "Στοιχεία" του ανοιγμένου στοιχείου, με λέξη, όχι εικονίδιο, και
ποτέ πάνω σε γραμμή λίστας.

**PO:** Μέσα στα στοιχεία, με τη λέξη "Μου αρέσει" και τετραγωνάκι, εντάξει.
Έτσι δεν το πατάω κατά λάθος· κατά λάθος πατιέται η καρδούλα δίπλα στο όνομα,
όχι ένα τετραγωνάκι που γράφει τι κάνει. Νούμερο δίπλα δεν θέλω.

**Recorded:** PO concedes that the control exists; design concedes on the bare
heart (never a glyph, never in a row, never a count). The orchestrator's answer
is binding: it stays, in the details panel, labelled, ≥44px.

### A2. Story reactions

**PO:** Ούτε αντιδράσεις. Έστειλα καρδιά σε ιστορία και δεν ήξερα πώς.

**D:** Ίδια αρχή. Μία λέξη "Αντιδράσεις" που ανοίγει, και μετά "Σίγουρα; Θα
σταλεί στη Μαρία." με "Ναι" και "Άκυρο".

**PO:** Με το "Σίγουρα;" καλά. Δύο πατήματα για να στείλω, και το δεύτερο να
λέει τι θα στείλει. Τότε δεν στέλνω κατά λάθος, στέλνω όταν θέλω.

**Recorded:** both concede. The emoji row is never on screen until the
disclosure is opened and the confirm is accepted; the send path is unchanged
(`POST /api/stories/{pk}/react`).

### A3. The pictures leave the list

**D:** Η λίστα είναι λίστα: όνομα, πότε, τι είναι. Οι φωτογραφίες μπαίνουν
στο παράθυρο της αναπαραγωγής. Άρα δύο πατήματα για μια φωτογραφία, όχι ένα.

**PO:** Δύο πατήματα; Χθες την είδα με ένα. … Αλλά με ένα πάτημα βλέπω και
πέντε φωτογραφίες που δεν ζήτησα, και χάνομαι. Βάλτε μου όμως λίγα λόγια από
την περιγραφή στη γραμμή, να ξέρω ποια ανοίγω, και την ώρα. Τότε δύο
πατήματα, εντάξει.

**Recorded:** design concedes two things (a caption snippet and the time stay in
the row); PO concedes the extra press. If this had gone the other way the whole
2000 frame collapses back into a card feed, which is Alternative (a).

### A4. Greek chrome, data as written

**PO:** Όλα ελληνικά. Και τα ονόματα; Η Μαρία είναι Μαρία.

**D:** Τα κουμπιά, τα μενού, τα μηνύματα: ελληνικά. Ό,τι έγραψε ο άλλος —
ονόματα, περιγραφές, τοποθεσίες — μένει όπως το έγραψε. Και χωρίς κουμπί
γλώσσας· μια γλώσσα, μία φορά.

**Recorded:** agreed, no loop. `lang="el"` on the document; no switcher.

## 3. Loop B — design meets the environment

Two proposals came back from engineering-in-me. Both are recorded with what
replaced them.

### B1. A period typeface ("MS Sans Serif" as a web font)

**D proposed:** ship a 2000 bitmap-look face as `.woff2` under `app/static/` and
use it for chrome, so the window *reads* like 2000 even on a phone.

**Engineering:** the brief forbids web fonts (CSP, no build step, no new
network calls), and there is no subsetting step, so the file arrives whole over
a Pi on a phone connection. Worse, a face with different metrics breaks every
fixed height in this document on the devices that do not have it.

**Revision:** system stack only —
`Tahoma, Verdana, "DejaVu Sans", "Noto Sans", Roboto, "Segoe UI", sans-serif`,
sizes in px (chrome 12, body/lists 15, captions 16) so wrap points are stable
across fallbacks. The 2000 feeling comes from bevels, 1px rules and chrome
heights, not from the letterforms. No layout may depend on a glyph's width:
names ellipsise with the full text in `title` and `aria-label`.

### B2. Inline `onclick` for the menu items

**D proposed:** the menu markup writes `onclick="menu('file')"` on each item —
one attribute, no wiring, exactly how this was done in 2000.

**Engineering:** `script-src 'self'` (brief, hard) blocks inline handlers, and
they fail *silently* — v1 already ships one dead handler at `views.js:353`
(`onclick="location.hash='#/'"` on the feed's "no session" card), which nobody
noticed because the card is rare. A menu that does nothing when tapped is the
PO's worst case: "a press does nothing".

**Revision:** one delegated `click` listener on the menu bar in `shell.js`,
`data-menu`/`data-item` attributes only, and the v1 inline handler is deleted in
the same commit. A cheap test (`assert "onclick" not in views_js`) keeps it
from coming back.
