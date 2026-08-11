/* Padhai — Home, About and Contact pages.
 *
 * These are real, linkable pages (#/home, #/about, #/contact) built into the
 * same single-page app, so navigating between them never reloads the workspace
 * or loses uploaded material. The browser's back button works throughout.
 *
 * The contact form posts to /api/contact, which stores every message in the
 * database before attempting delivery — so a message is never lost, whether or
 * not an email provider is configured. */

"use strict";

(() => {
  const { api, icon, escapeHtml, toast, state } = window.Padhai;
  const $ = (id) => document.getElementById(id);

  const PAGES = {
    home: { label: "Home", build: buildHome },
    about: { label: "About", build: buildAbout },
    contact: { label: "Contact", build: buildContact },
  };

  const host = $("page-view");
  let built = {};

  // ---------------- Routing ----------------

  function show(name) {
    if (!PAGES[name]) return goApp();
    document.querySelectorAll(".study-view").forEach((v) => (v.hidden = true));

    if (!built[name]) {
      built[name] = PAGES[name].build();
      host.appendChild(built[name]);
    }
    Object.entries(built).forEach(([k, el]) => (el.hidden = k !== name));

    host.hidden = false;
    // A landing page shouldn't sit beside the upload sidebar
    document.body.classList.add("on-page");
    document.title = `${PAGES[name].label} — Padhai`;
    document.querySelectorAll("[data-page]").forEach((a) =>
      a.classList.toggle("current", a.dataset.page === name)
    );
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  /** Leave the marketing pages and go back to the study workspace. */
  function goApp() {
    host.hidden = true;
    document.body.classList.remove("on-page");
    document.querySelectorAll("[data-page]").forEach((a) => a.classList.remove("current"));
    window.Padhai.showDefaultView();
  }

  function route() {
    const name = (location.hash.match(/^#\/(\w+)/) || [])[1];
    if (name && PAGES[name]) show(name);
    else goApp();
  }

  window.addEventListener("hashchange", route);

  // ---------------- Shared building blocks ----------------

  const el = (tag, cls, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html !== undefined) n.innerHTML = html;
    return n;
  };

  const FEATURES = [
    ["summary", "Summaries that actually teach",
     "Every sentence names its own subject, so a line makes sense on its own — " +
     "no “This is important” filler."],
    ["mindmap", "Mind maps, five ways",
     "The same notes as a branch tree, flow chart, revision cards, a wheel or a " +
     "timeline. Download any of them as PNG or SVG."],
    ["flashcards", "Flashcards & practice",     // escapeHtml() handles the &
     "Decks and six kinds of practice question, generated from your own " +
     "chapters and steerable with plain-English instructions."],
    ["exam", "Timed exam papers",
     "A full sectioned paper with a countdown, question palette and " +
     "server-side marking. Answer keys never reach the browser."],
    ["viva", "A viva that asks you",
     "The AI plays examiner: it asks, you answer, it marks each response out " +
     "of ten with feedback and a model answer."],
    ["report", "Progress reports",
     "Weak topics, where your time actually goes, and a revision plan built " +
     "from your real performance."],
  ];

  // ---------------- Home ----------------

  function buildHome() {
    const p = el("div", "page page-home");
    p.innerHTML = `
      <section class="hero">
        <span class="hero-badge">${icon("shield", 14)} Runs on free services</span>
        <h1 class="hero-title">Turn your own notes into<br/>a complete exam-prep system.</h1>
        <p class="hero-sub">
          Upload your chapters. Padhai writes the summaries, mind maps,
          flashcards, practice questions and exam papers — grounded strictly in
          <em>your</em> material, with every answer citing the page it came from.
        </p>
        <div class="hero-actions">
          <button class="btn-primary hero-cta" data-goto="upload">
            ${icon("upload", 17)} Upload your first chapter
          </button>
          <a class="btn-secondary" href="#/about">How it works</a>
        </div>
        <p class="hero-note">No account needed to try it. Nothing is sent anywhere you don't configure.</p>
      </section>

      <section class="feature-grid">
        ${FEATURES.map(([ic, title, body], i) => `
          <article class="feature-card" style="--i:${i}">
            <span class="feature-icon">${icon(ic, 22)}</span>
            <h3>${escapeHtml(title)}</h3>
            <p>${body}</p>
          </article>`).join("")}
      </section>

      <section class="steps">
        <h2 class="page-h2">Three steps</h2>
        <ol class="step-list">
          <li><b>Upload</b><span>PDF, notes, a CSV or even a recorded lecture. Several
              chapters in one file are split automatically.</span></li>
          <li><b>Wait a moment</b><span>Every view is generated at once in the
              background, so each tab opens instantly afterwards.</span></li>
          <li><b>Study</b><span>Read, revise, test yourself, sit a mock paper, then
              check your progress report.</span></li>
        </ol>
      </section>`;

    p.querySelector('[data-goto="upload"]').addEventListener("click", () => {
      location.hash = "";
      setTimeout(() => $("file-input")?.click(), 60);
    });
    return p;
  }

  // ---------------- About ----------------

  function buildAbout() {
    const p = el("div", "page");
    p.innerHTML = `
      <header class="page-head">
        <h1>About Padhai</h1>
        <p class="page-lead">
          A study assistant that answers only from the material you give it —
          and shows you where every answer came from.
        </p>
      </header>

      <section class="prose">
        <h2 class="page-h2">Why it exists</h2>
        <p>
          A general chatbot answers from its training data. For someone revising
          for an exam that is a real problem: the answer may not match the
          syllabus, may contradict the textbook, and cannot be checked. Worse,
          when a model does not know something it tends to invent a confident
          answer.
        </p>
        <p>
          Padhai inverts that. You upload your own chapters, and every summary,
          flashcard, question and answer is built strictly from them. Each
          answer carries a citation back to the document, heading and page it
          used, so any claim can be verified in seconds. When your material
          genuinely does not contain the answer, the app says so rather than
          guessing.
        </p>

        <h2 class="page-h2">How it works</h2>
        <ol class="how-list">
          <li><b>Ingestion</b> — text is extracted and cleaned. PDF line breaks
            that fall inside a sentence are rejoined, hyphenated words repaired,
            and repeating headers removed. The text is then split into chunks
            that never cross a heading or cut a sentence in half.</li>
          <li><b>Retrieval</b> — when you ask something, only the relevant
            passages are found (BM25 ranking, then reranking on how much of your
            question each passage actually covers) and handed to the model with
            their source labels attached.</li>
          <li><b>Verification</b> — generated text is checked before you see it.
            A sentence starting with an unresolved “This” or “It” is repaired by
            naming its subject, or dropped if it cannot be. Duplicates,
            fragments and filler are removed.</li>
        </ol>

        <h2 class="page-h2">Built on free services</h2>
        <p>
          Padhai routes between several free AI providers and fails over
          automatically when one hits its daily limit, restoring it when it
          recovers. If none is reachable it still works, building summaries and
          cited answers directly from your documents. Speech transcription runs
          locally on your own machine.
        </p>

        <h2 class="page-h2">Your data</h2>
        <ul class="fact-list">
          <li>As a guest, uploads are held temporarily and expire on their own.</li>
          <li>Signed in, your material is stored in a local SQLite file on the
              machine running the app — not on anyone's server.</li>
          <li>Passwords are stored only as salted PBKDF2 hashes, never in plain text.</li>
          <li>Nothing is shared with third parties beyond the AI provider you configure.</li>
        </ul>
      </section>

      <div class="page-cta">
        <a class="btn-primary" href="#/contact">${icon("chat", 17)} Get in touch</a>
      </div>`;
    return p;
  }

  // ---------------- Contact ----------------

  function buildContact() {
    const p = el("div", "page");
    p.innerHTML = `
      <header class="page-head">
        <h1>Contact</h1>
        <p class="page-lead">
          Questions, bugs, or a feature you wish existed — send a message and
          I'll reply to the address you give.
        </p>
      </header>

      <div class="contact-grid">
        <form id="contact-form" class="contact-form" autocomplete="on" novalidate>
          <div class="contact-row">
            <label>Your name
              <input id="c-name" type="text" autocomplete="name" maxlength="80"
                     placeholder="optional" />
            </label>
            <label>Your email <span class="req">*</span>
              <input id="c-email" type="email" autocomplete="email" required
                     maxlength="160" placeholder="so I can reply" />
            </label>
          </div>
          <label>Subject
            <input id="c-subject" type="text" maxlength="120"
                   placeholder="e.g. Mind map export isn't working" />
          </label>
          <label>Message <span class="req">*</span>
            <textarea id="c-message" rows="7" required maxlength="5000"
                      placeholder="Tell me what happened, or what you'd like to see…"></textarea>
          </label>

          <!-- Bots fill every field; this one is hidden from people. -->
          <input id="c-website" class="hp-field" type="text" tabindex="-1"
                 autocomplete="off" aria-hidden="true" />

          <p id="c-error" class="auth-error" hidden></p>
          <div class="contact-actions">
            <span id="c-count" class="contact-count">0 / 5000</span>
            <button id="c-submit" class="btn-primary" type="submit">
              ${icon("chat", 16)} Send message
            </button>
          </div>
        </form>

        <aside class="contact-side">
          <div class="contact-card">
            <h3>${icon("shield", 16)} What happens to it</h3>
            <p>Your message is saved first and emailed second, so it is never
               lost even if the mail service is having a bad day.</p>
          </div>
          <div class="contact-card">
            <h3>${icon("clock", 16)} Reply time</h3>
            <p>Usually within a couple of days. Include steps to reproduce if
               you're reporting a bug — it speeds things up a lot.</p>
          </div>
          <div class="contact-card">
            <h3>${icon("chat", 16)} Straight to a person</h3>
            <p>This form is the fastest way to reach me — it goes to my inbox
               directly, and I'll reply from there.</p>
          </div>
        </aside>
      </div>

      <div id="c-done" class="contact-done" hidden></div>`;

    wireContact(p);
    return p;
  }

  function wireContact(root) {
    const form = root.querySelector("#contact-form");
    const err = root.querySelector("#c-error");
    const msg = root.querySelector("#c-message");
    const count = root.querySelector("#c-count");
    const submit = root.querySelector("#c-submit");
    const done = root.querySelector("#c-done");

    msg.addEventListener("input", () => {
      count.textContent = `${msg.value.length} / 5000`;
      count.classList.toggle("near", msg.value.length > 4500);
    });

    // Note: the destination address is deliberately NOT shown here. Publishing
    // a personal inbox on a public page invites scrapers and spam; the form
    // delivers to it server-side without ever exposing it.

    // Signed-in students get their details filled in for them
    if (window.Padhai.user) {
      root.querySelector("#c-name").value = window.Padhai.user.name || "";
      root.querySelector("#c-email").value = window.Padhai.user.email || "";
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.hidden = true;

      const payload = {
        name: root.querySelector("#c-name").value.trim(),
        email: root.querySelector("#c-email").value.trim(),
        subject: root.querySelector("#c-subject").value.trim(),
        message: msg.value.trim(),
        website: root.querySelector("#c-website").value,
      };
      if (!payload.email || !payload.message) {
        return fail(err, submit, "Please fill in your email and a message.");
      }

      submit.disabled = true;
      submit.textContent = "Sending…";
      try {
        const r = await api("/api/contact", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        form.hidden = true;
        done.hidden = false;
        done.innerHTML =
          `<span class="contact-tick">${icon("check", 26)}</span>` +
          `<h2>Message received</h2>` +
          `<p>${r.delivered
            ? "It has been emailed and I'll reply to " + escapeHtml(payload.email) + "."
            : "It has been saved safely and I'll see it. A reply will come to "
              + escapeHtml(payload.email) + "."}</p>` +
          `<button class="btn-secondary" id="c-again">Send another</button>`;
        done.querySelector("#c-again").addEventListener("click", () => {
          form.reset();
          count.textContent = "0 / 5000";
          form.hidden = false;
          done.hidden = true;
          submit.disabled = false;
          submit.innerHTML = `${icon("chat", 16)} Send message`;
        });
        toast("✓ Message sent", "ok");
      } catch (ex) {
        fail(err, submit, ex.message);
      }
    });
  }

  function fail(err, submit, message) {
    err.textContent = message;
    err.hidden = false;
    submit.disabled = false;
    submit.innerHTML = `${icon("chat", 16)} Send message`;
  }

  // ---------------- Init ----------------
  Object.assign(window.Padhai, { showPage: show });
  route();
})();
