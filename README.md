# Padhai 📚

An AI study assistant that runs entirely on **free services**. Open the site,
upload what you're studying (PDF / TXT / CSV) and everything — summary, key
points, definitions, mind maps, flashcards — is generated **up front, in
parallel**, so every tab opens instantly.

**Accounts are optional.** As a guest it works exactly as before and your
uploads expire after a few hours. Sign in and your material, generated
analyses and sticky notes are saved to a local SQLite file, so they're still
there tomorrow — and are never sent to the AI a second time.

> Upload anything you are studying and instantly get a personal AI exam
> preparation system.

## Features

**Phase 1**
- 📄 **Upload PDF / TXT / CSV** — drag & drop; kept in memory as a guest, saved to your account if you sign in
- 🧠 **AI analysis** — chapter summary, key points, important definitions, mind-map notes
- 💬 **Chat with your material** — answers come only from what you uploaded
- 🔌 **Offline fallback** — works without any API key using built-in extractive analysis

**Phase 2**
- 🃏 **AI flashcards** — question/answer sides, difficulty levels, topic tags,
  flip animation, prev/next navigation, progress bar, keyboard shortcuts
  (←/→ to navigate, Space to flip)
- ✏️ **Practice questions** in six formats: MCQ, fill-in-the-blank,
  match-the-following (drag & drop), true/false, short answer, long answer —
  with instant feedback, explanations, and a live score counter.
  Choose types, count, difficulty, and an optional topic focus.

**Phase 3**
- 📝 **Full exam papers** — choose total marks, difficulty, time limit, and an
  optional chapter/topic. Generates a six-section paper (MCQ, fill blanks,
  true/false, match the following, short answers, long answers) with an
  exam-style interface: question cards, answer inputs, a question-navigation
  palette (jump to any question; answered ones turn green), live countdown
  timer with auto-submit, and a submit-with-confirmation flow.
- 📊 **Exam report** — total marks, percentage, grade, per-question review
  (your answer vs the correct one, with explanations), weak-topic detection,
  and improvement suggestions. Short/long answers are graded by AI with
  partial marks (keyword-based grading offline). Answer keys stay on the
  server — they never reach the browser.

**Phase 4**
- 🎧 **Audio lectures** — upload MP3/WAV/M4A/OGG/FLAC/WebM; transcribed
  **locally** with open-source Whisper (free, no API), then usable like any
  document: summaries, chat, flashcards, exams.
- 🔊 **Text-to-speech** — "Listen" buttons on summaries, chat answers, and
  AI model answers using the browser's built-in SpeechSynthesis (free, offline).
- 📜 **Previous year paper intelligence** — **search the web** for real past
  papers via the **Google Programmable Search API** (100 searches/day free,
  keyless DuckDuckGo fallback) and import PDF results straight into the
  question bank, or upload your own. Questions
  are extracted (AI or pattern-based) and organised by the full hierarchy:
  subject → chapter → topic → year → difficulty (plus marks). Search the
  bank ("electricity"), filter by any level, and practise questions one at
  a time with AI model answers.
- 🎮 **Game-like learning** — XP for studying, levels, a daily streak, and
  11 badges (progress panel in the top bar). Stored in your browser's
  localStorage.

**Phase 5 — interface**
- 🧠 **Visual mind maps, five ways** — the mind-map tab draws a real diagram,
  not a bullet list, and the same notes can be shown as a **branch tree**
  (colour-coded branches with CSS elbow connectors, collapsible, leaf counts),
  a **flow chart** (numbered steps with arrows), **revision cards** (a grid,
  prints well), a **wheel** (branches radiating from the centre, click to
  drill in) or a **timeline** (alternating cards on a spine).
  **Download** any map as PNG, SVG or markdown — all rendered locally, no
  libraries and no upload.
- 🔢 **Formulas in plain language** — LaTeX like `$H \propto I^2 R t$` becomes
  `H ∝ I²Rt` with a spoken reading underneath ("H is proportional to I squared
  R t"), everywhere: mind maps, summaries, chat and answers.
- 🧮 **Calculator** — a floating, draggable panel that stays open while you read
  a question. It parses expressions itself (no `eval`), handling brackets,
  powers, roots, logs, trig in degrees or radians, percentages, implicit
  multiplication (`3(4+5)`, `2π`) and `Ans`, with a live answer preview and
  reusable history.

- 🌗 **Light & dark themes** — one click in the top bar, remembered between
  visits; follows your OS preference until you pick a side.
- 🧭 **Radial navigation dock** — the floating compass button (bottom right,
  or press <kbd>N</kbd>) blooms into a circle of icons that jump straight to
  any view: summary, key points, definitions, mind map, flashcards, practice,
  exam, chat, past papers, sticky notes, calculator, upload.
- ✨ **Motion everywhere** — sliding tab indicator, orbiting icon ring on the
  welcome screen, staggered card entrances, shimmering loading skeletons,
  button ripples and hover lifts. All of it collapses automatically when the
  OS asks for `prefers-reduced-motion`.

**Phase 6 — saving your work**
- 📌 **Sticky notes** — a corkboard of its own. Double-click anywhere to stick a
  note down, then drag it wherever you want: it straightens and lifts under
  your hand, and settles back at a fresh angle when you let go. Six paper
  colours, resize handles, handwriting font, tape and a curled corner.
- 👤 **Optional accounts** — the app is fully usable signed out. Signing in
  keeps your documents, mind maps and notes between visits, and anything you
  made as a guest is carried into the new account automatically.
  Passwords are stored as PBKDF2-HMAC-SHA256 (210k iterations, per-user salt);
  session tokens live in an HttpOnly cookie that page scripts can't read.
- ⚡ **Everything generated once, up front** — uploading fans out all five
  generations across a thread pool instead of firing one per tab click, and
  every result is written to SQLite. Measured on a sample chapter: upload
  returns in **0.4 s**, all five views finish in **~27 s** in the background,
  and after a server restart they load from disk in **50–270 ms** each.

**Phase 7 — steer the AI**
- 🎙️ **Viva mode** — a new tab where the roles flip: the AI plays an oral
  examiner and *asks* the questions, one at a time, about your material. You
  type an answer, it marks each out of 10 with feedback and reveals the model
  answer, then moves on — ending with a percentage and a question-by-question
  review. The model answers stay on the server until you've answered, so they
  can't be read ahead from the network tab.
- ✍️ **Custom instructions** — practice, exam and viva each have a free-text box
  to steer the generator: *"only numerical problems"*, *"give a hint in each
  question"*, *"focus long answers on real-world applications"*. The text is
  sanitised and framed as a preference that can't override the required
  question format or count.
- 🧹 **Tidier top bar** — the feature buttons (report, sticky notes, calculator)
  now live in a single **Menu** dropdown so nothing is cut off on smaller
  screens, and the AI-status pill collapses to a coloured dot when space is
  tight.

**Phase 8 — the AI pipeline, rebuilt**
- 🎯 **Output quality gate** (`services/quality.py`) — one shared contract in
  every prompt, plus post-processing that enforces what prompting cannot.
  Bullets like *"This – the core technology"* are repaired into
  *"Retrieval-Augmented Generation – the core technology"* by resolving the
  pronoun against the preceding sentence, and dropped when it can't be
  resolved. Also removes fragments, near-duplicates and vacuous filler
  ("These formulas are important"). Applies to **every** feature and to the
  offline mode too.
- 🔁 **Multi-provider failover** (`services/providers.py`) — Gemini →
  OpenRouter → Groq → Hugging Face. A provider that 429s, times out or errors
  is benched with exponential backoff (30 s → 15 min); one success puts it
  straight back in rotation. Nothing to configure, no user action, and with
  every provider down the app degrades to local mode instead of failing.
- 🔍 **Real RAG** (`services/retrieval.py`) — BM25 + phrase and proximity
  boosts, reranking on question coverage, neighbour-chunk expansion, context
  compression, and **source attribution** so every answer cites
  `chapter2.pdf › Ohm's law › page 4` and the student can check it.
- 📄 **Better parsing & chunking** — PDF hard-wrap repair (mid-sentence line
  breaks are re-joined), hyphenation repair, running header/footer removal,
  and heading-aware semantic chunking that never splits mid-sentence and
  carries its heading and page with it.
- 🚀 **Zero-click documents** — every uploaded file joins the working context
  automatically; deleting one removes it from the AI immediately. Upload →
  Generate → Results.

## Deploying to Vercel

The repository is already configured. Four files handle it, and no application
code was changed:

| File | Purpose |
|---|---|
| `api/index.py` | Puts `backend/` on `sys.path`, then imports the existing Flask `app` |
| `vercel.json` | Serves `frontend/` statically; rewrites `/api/*` to the function |
| `requirements.txt` (root) | Points at `backend/requirements.txt` |
| `.vercelignore` | Keeps the local database and `.env` out of the bundle |

Set every secret as an **Environment Variable** in the Vercel dashboard —
`.env` is not uploaded. At minimum one AI key (`GEMINI_API_KEY` or
`OPENROUTER_API_KEY`); add `BREVO_API_KEY`, `CONTACT_TO` and `CONTACT_FROM`
for the contact form.

### Known limitation: SQLite does not persist

Vercel functions run on a **read-only filesystem** (only `/tmp` is writable,
and it is wiped between invocations). Anything that writes to the database
returns a 500:

- Accounts, sign-in and sessions
- Saved documents and cached analyses
- Sticky notes, progress reports, stored contact messages

Setting `PADHAI_DB=/tmp/padhai.db` stops the 500s but the data disappears on
the next cold start, which is worse than failing honestly. Everything that
does not need the database — uploading, summaries, mind maps, flashcards,
practice, exams, viva, chat — works normally as a guest.

To make persistence work, point the app at a hosted Postgres (Vercel Postgres,
Supabase or Neon) by rewriting `services/db.py`. That is a genuine code change,
not configuration, so it is deliberately not done automatically.

## Contact form

`#/home`, `#/about` and `#/contact` are real linkable pages inside the app.

Every message is **written to the database before any delivery is attempted**,
so nothing is lost when email is unconfigured or a provider is down. Read them
with:

```bash
sqlite3 studyai.db "SELECT created, name, email, subject, body FROM messages ORDER BY created DESC;"
```

To also receive them by email, configure **one** of these in `.env`:

| Option | Free tier | Where to get the key |
|---|---|---|
| **Resend** *(quickest)* | 100/day | <https://resend.com/api-keys> |
| **Brevo** | 300/day | <https://app.brevo.com/settings/keys/api> |
| **Gmail / SMTP** | your mailbox | <https://myaccount.google.com/apppasswords> |

Set `CONTACT_TO` to the address that should receive them. Gmail requires a
16-character **App Password** — your normal password will be rejected.

Protections: a hidden honeypot field silently discards bots, and
`CONTACT_RATE_PER_HOUR` (default 5) limits messages per IP address.

## Capacity and limits

Nothing is capped for product reasons — every limit is a tunable in `.env`.

| Setting | Default | What it controls |
|---|---|---|
| `MAX_DOCS` | `0` (unlimited) | Documents per account |
| `MAX_COMBINE_DOCS` | `60` | How many may be studied together |
| `MAX_UPLOAD_MB` | `100` | Size of a single uploaded file |
| `MAX_NOTES` | `1000` | Sticky notes per account |
| `AI_CONTEXT_CHARS` | `60000` | Material sent to the AI per generated view |
| `DOC_TTL_HOURS` | `6` | Guest document lifetime (signed-in documents never expire) |

`AI_CONTEXT_CHARS` is the only one with a real trade-off: it is bounded by
what a free model will accept in one prompt. When the material exceeds it the
budget is **shared across every document** — opening, middle and end of each —
rather than truncated at the cut-off, so a chapter is never silently omitted
from a summary. Question answering is unaffected: retrieval already selects
only the relevant passages.

## Is the AI working?

When answers look extractive rather than written, run the doctor:

```bash
python backend/doctor.py
```

It checks each layer in turn — `.env` loading → which keys are set → outbound
network → a **live call to every provider and every model** → retrieval,
quality gate and database — then prints the real HTTP status and error text
plus a numbered list of what to fix. Exit code 0 means the AI is working, 1
means the app is stuck in offline mode. Add `--quick` to skip the live calls.

The two failures it catches most often:

| What you see | What it means |
|---|---|
| `model not found` (404) | The model id was retired. Remove it from `OPENROUTER_MODELS`, or use the `-latest` Gemini aliases which never go stale. |
| `rate limited` (429) | That provider's free daily quota is used up. Configure a second provider and Padhai fails over automatically. |

## Tech stack

- **Backend:** Python Flask + SQLite (accounts, notes, documents, cached AI results)
- **Frontend:** plain HTML/CSS/JavaScript (no build step)
- **AI:** four free providers with automatic failover — Gemini, OpenRouter
  (`:free` models), Groq, Hugging Face. Configure any one; more means better
  uptime. None configured still works, in offline extractive mode.
- **Retrieval:** BM25 + rerank + neighbour expansion, pure Python (no
  embeddings service, no vector DB, nothing to pay for)
- **PDF:** `pypdf` · **Speech-to-text:** `faster-whisper` (local, optional)
  · **Text-to-speech:** browser SpeechSynthesis API
- **Paper search:** Google Programmable Search (free tier) with a keyless
  DuckDuckGo (`ddgs`) fallback

## Setup

Requires Python 3.10+.

```bash
# 1. Install dependencies
pip install -r backend/requirements.txt

# 2. Configure the free AI key (optional but recommended)
copy .env.example .env        # (cp on macOS/Linux)
```

Then edit `.env` and set your OpenRouter key:

1. Create a **free** account at <https://openrouter.ai>
2. Open <https://openrouter.ai/settings/keys> → **Create key**
3. Paste it into `.env` as `OPENROUTER_API_KEY=sk-or-...`

No billing setup is needed — Padhai only calls models with the `:free`
suffix. Without a key the app still runs in **offline mode** (extractive
summaries + relevant-passage answers).

### Optional: real Google results for past papers

Past-paper search works out of the box through DuckDuckGo (no key). For
noticeably better, properly ranked results, add a free Google Programmable
Search key — 100 searches/day, no billing:

1. **API key** — <https://developers.google.com/custom-search/v1/introduction>
   → *Get a Key* → pick or create a project.
2. **Search engine** — <https://programmablesearchengine.google.com/controlpanel/create>
   → turn **on** *Search the entire web* → copy the **Search engine ID**.
3. Put both in `.env`:

```ini
GOOGLE_API_KEY=AIza...
GOOGLE_CSE_ID=a1b2c3d4e5f6g7h8i
```

Padhai tries Google first and silently falls back to DuckDuckGo if the key
is missing, invalid, or the daily quota runs out — the results list shows
which engine answered. Pin one engine with `SEARCH_PROVIDER=google` or
`SEARCH_PROVIDER=ddg`.

### Optional: audio lecture transcription

```bash
pip install -r backend/requirements-audio.txt
```

This installs [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
(free, open source, runs fully on your machine — no API). The first
transcription downloads a ~75 MB model once; set `WHISPER_MODEL=tiny` in
`.env` for a faster/smaller model or `small` for higher accuracy.

## Run

```bash
python backend/app.py
```

Open <http://127.0.0.1:5000> in your browser.

## Project structure

```
study/
├── backend/
│   ├── app.py                 # Flask entry point + API routes
│   ├── config.py              # env-based configuration
│   ├── requirements.txt
│   ├── requirements-audio.txt # optional: local Whisper speech-to-text
│   └── services/
│       ├── extractor.py       # PDF/TXT/CSV/audio → text, chunking, topics
│       ├── ai_service.py      # OpenRouter free models + offline fallback
│       ├── generator.py       # flashcards & practice-question generation
│       ├── exam.py            # exam paper generation + server-side grading
│       ├── viva.py            # AI-asks-you oral test + answer grading
│       ├── audio_service.py   # local Whisper transcription (optional)
│       ├── papers.py          # past-paper question bank + search
│       ├── search.py          # Google Programmable Search + DuckDuckGo
│       ├── quality.py         # output contract + pronoun/duplicate gate
│       ├── providers.py       # Gemini/OpenRouter/Groq/HF failover manager
│       ├── retrieval.py       # BM25 + rerank + attribution
│       ├── db.py              # SQLite schema + helpers
│       ├── auth.py            # accounts, password hashing, sessions
│       ├── notes.py           # sticky notes CRUD
│       ├── warm.py            # parallel precompute of every view
│       └── store.py           # documents (SQLite + RAM cache)
├── frontend/
│   ├── index.html
│   ├── css/style.css          # light + dark tokens, animations
│   └── js/
│       ├── app.js             # upload, tabs, analysis views, chat
│       ├── formula.js         # LaTeX → readable symbols + spoken English
│       ├── ui.js              # icons, theme switch, radial nav, motion
│       ├── mindmap.js         # 5 diagram layouts + PNG/SVG/MD export
│       ├── tools.js           # calculator (own expression parser)
│       ├── notes.js           # sticky-notes board
│       ├── auth.js            # sign in / create account
│       ├── flashcards.js      # flip-card deck
│       ├── practice.js        # six question formats + scoring
│       ├── exam.js            # timed exam runner + report view
│       ├── papers.js          # past-paper bank UI + practice mode
│       ├── tts.js             # browser text-to-speech buttons
│       └── game.js            # XP, levels, streak, badges (localStorage)
├── .env.example
├── studyai.db                 # created on first run (git-ignored)
└── README.md
```

## Privacy model

The database is a plain `studyai.db` file next to the project — it never
leaves your machine, and it is git-ignored.

**As a guest (no account):**
- Uploads expire after 6 hours (`DOC_TTL_HOURS`) exactly as before.
- Sticky notes live in your browser's localStorage only.
- One cookie is set, and only once you sign in.

**Signed in:**
- Documents, generated analyses and notes are kept until you delete them.
- Passwords are never stored — only a PBKDF2-HMAC-SHA256 hash with a
  per-user random salt (210,000 iterations).
- The session cookie is HttpOnly and SameSite=Lax, so page scripts can't
  read it. Set `PORT`/HTTPS and it is marked Secure automatically.
- Your documents and notes are scoped to your account; another signed-in
  user cannot read, edit or delete them.

**Always:**
- Audio is transcribed locally — recordings never leave your machine.
- Game progress (XP/streak/badges) lives only in your browser's localStorage.
- No tracking, no analytics, no third-party requests beyond the AI/search
  APIs you configure.
