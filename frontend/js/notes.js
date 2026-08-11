/* Padhai — sticky notes.
 *
 * A board you can actually stick things on: drag a note anywhere, it lifts and
 * straightens under your hand, then settles back at its own slight angle when
 * you let go. Notes resize, recolour and edit in place.
 *
 * Signed in, notes live in SQLite and follow you between visits. As a guest
 * they sit in localStorage, and are offered up to the account on sign-in. */

"use strict";

/** Read a stored value, adopting the pre-rename key once so nothing is lost. */
function migratedGet(newKey, oldKey) {
  try {
    let v = localStorage.getItem(newKey);
    if (v === null) {
      v = localStorage.getItem(oldKey);
      if (v !== null) { localStorage.setItem(newKey, v); localStorage.removeItem(oldKey); }
    }
    return v;
  } catch { return null; }
}


(() => {
  const { api, icon, toast, escapeHtml } = window.Padhai;
  const $ = (id) => document.getElementById(id);

  const COLOURS = ["yellow", "pink", "blue", "green", "orange", "purple"];
  const GUEST_KEY = "padhai_notes";
  const SAVE_DELAY = 600;

  let notes = [];
  let topZ = 1;
  const pendingSaves = new Map();

  const els = {
    view: $("notes-view"),
    board: $("notes-board"),
    count: $("notes-count"),
    hint: $("notes-hint"),
  };

  const signedIn = () => !!window.Padhai.user;

  // ---------------- Persistence ----------------

  function readGuest() {
    try { return JSON.parse(localStorage.getItem(GUEST_KEY)) || []; } catch { return []; }
  }
  function writeGuest() {
    try { localStorage.setItem(GUEST_KEY, JSON.stringify(notes)); } catch { /* full/blocked */ }
  }

  /** Collect a note's current state for saving. */
  const payload = (n) => ({
    text: n.text, colour: n.colour, x: n.x, y: n.y, w: n.w, h: n.h, rot: n.rot, z: n.z,
  });

  /** Debounced per-note save so dragging doesn't hammer the server. */
  function save(note) {
    if (!signedIn()) { writeGuest(); return; }
    clearTimeout(pendingSaves.get(note.id));
    pendingSaves.set(note.id, setTimeout(async () => {
      pendingSaves.delete(note.id);
      try {
        await api(`/api/notes/${note.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload(note)),
        });
      } catch (err) {
        toast(`⚠ Couldn't save note: ${err.message}`);
      }
    }, SAVE_DELAY));
  }

  async function load() {
    if (!signedIn()) {
      notes = readGuest();
    } else {
      try {
        notes = (await api("/api/notes")).notes;
      } catch {
        notes = [];
      }
    }
    topZ = notes.reduce((m, n) => Math.max(m, n.z || 1), 1);
    render();
  }

  // ---------------- Creating / removing ----------------

  async function addNote(x, y, colour) {
    const draft = {
      text: "",
      colour: colour || COLOURS[Math.floor(Math.random() * COLOURS.length)],
      x: Math.max(0, x - 105),
      y: Math.max(0, y - 60),
      w: 210, h: 210,
      rot: Math.round((Math.random() * 8 - 4) * 10) / 10,
      z: ++topZ,
    };

    if (signedIn()) {
      try {
        const { note } = await api("/api/notes", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        });
        notes.push(note);
      } catch (err) {
        return toast(`⚠ ${err.message}`);
      }
    } else {
      notes.push({ id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, ...draft });
      writeGuest();
    }
    render();
    // Drop the caret straight into the note that was just created
    els.board.querySelector(`[data-id="${notes.at(-1).id}"] .note-text`)?.focus();
  }

  async function removeNote(note) {
    notes = notes.filter((n) => n.id !== note.id);
    render();
    if (!signedIn()) return writeGuest();
    try { await api(`/api/notes/${note.id}`, { method: "DELETE" }); }
    catch { /* already gone server-side */ }
  }

  // ---------------- Rendering ----------------

  function render() {
    els.board.querySelectorAll(".note").forEach((n) => n.remove());
    notes.forEach((note) => els.board.appendChild(buildNote(note)));

    els.count.textContent = `${notes.length} note${notes.length === 1 ? "" : "s"}`;
    els.hint.hidden = notes.length > 0;
    growBoard();
  }

  /** Keep the board tall/wide enough to hold every note plus room to spread out. */
  function growBoard() {
    const right = notes.reduce((m, n) => Math.max(m, n.x + n.w), 0);
    const bottom = notes.reduce((m, n) => Math.max(m, n.y + n.h), 0);
    els.board.style.minHeight = `${Math.max(560, bottom + 220)}px`;
    els.board.style.minWidth = `${Math.max(0, right + 220)}px`;
  }

  function buildNote(note) {
    const wrap = document.createElement("article");
    wrap.className = `note note-${note.colour}`;
    wrap.dataset.id = note.id;
    wrap.style.cssText =
      `left:${note.x}px;top:${note.y}px;width:${note.w}px;height:${note.h}px;` +
      `--rot:${note.rot}deg;z-index:${note.z}`;

    wrap.innerHTML =
      '<span class="note-tape" aria-hidden="true"></span>' +
      '<div class="note-tools">' +
        COLOURS.map((c) =>
          `<button type="button" class="note-dot note-dot-${c}` +
          `${c === note.colour ? " current" : ""}" data-colour="${c}" ` +
          `title="${c}" aria-label="Make this note ${c}"></button>`
        ).join("") +
        `<button type="button" class="note-del" title="Delete note">${icon("trash", 14)}</button>` +
      "</div>" +
      `<textarea class="note-text" spellcheck="false" placeholder="Write something…" ` +
      `maxlength="4000">${escapeHtml(note.text)}</textarea>` +
      '<span class="note-grip" title="Resize"></span>' +
      '<span class="note-curl" aria-hidden="true"></span>';

    const text = wrap.querySelector(".note-text");
    text.addEventListener("input", () => {
      note.text = text.value;
      save(note);
    });
    text.addEventListener("focus", () => lift(note, wrap));

    wrap.querySelectorAll(".note-dot").forEach((dot) =>
      dot.addEventListener("click", (e) => {
        e.stopPropagation();
        note.colour = dot.dataset.colour;
        wrap.className = `note note-${note.colour}`;
        wrap.querySelectorAll(".note-dot").forEach((d) =>
          d.classList.toggle("current", d.dataset.colour === note.colour)
        );
        save(note);
      })
    );

    wrap.querySelector(".note-del").addEventListener("click", (e) => {
      e.stopPropagation();
      wrap.classList.add("gone");
      setTimeout(() => removeNote(note), 220);
    });

    dragging(wrap, note, text);
    resizing(wrap, note);
    return wrap;
  }

  /** Bring a note to the front of the pile. */
  function lift(note, wrap) {
    if (note.z === topZ) return;
    note.z = ++topZ;
    wrap.style.zIndex = note.z;
    save(note);
  }

  // ---------------- Dragging ----------------

  function dragging(wrap, note, textEl) {
    let drag = null;

    wrap.addEventListener("pointerdown", (e) => {
      // Typing, recolouring, deleting and resizing must not start a drag
      if (e.target.closest(".note-text, .note-tools, .note-grip")) return;
      drag = { dx: e.clientX - note.x, dy: e.clientY - note.y, moved: false };
      lift(note, wrap);
      wrap.classList.add("held");
      wrap.setPointerCapture(e.pointerId);
    });

    wrap.addEventListener("pointermove", (e) => {
      if (!drag) return;
      note.x = Math.max(0, e.clientX - drag.dx);
      note.y = Math.max(0, e.clientY - drag.dy);
      drag.moved = true;
      wrap.style.left = `${note.x}px`;
      wrap.style.top = `${note.y}px`;
    });

    const drop = () => {
      if (!drag) return;
      wrap.classList.remove("held");
      // A tiny nudge to the angle each time it is re-stuck down
      if (drag.moved) {
        note.rot = Math.round((Math.random() * 8 - 4) * 10) / 10;
        wrap.style.setProperty("--rot", `${note.rot}deg`);
        wrap.classList.add("settle");
        setTimeout(() => wrap.classList.remove("settle"), 400);
        growBoard();
        save(note);
      } else {
        textEl.focus();
      }
      drag = null;
    };
    wrap.addEventListener("pointerup", drop);
    wrap.addEventListener("pointercancel", drop);
  }

  // ---------------- Resizing ----------------

  function resizing(wrap, note) {
    const grip = wrap.querySelector(".note-grip");
    let start = null;

    grip.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      start = { x: e.clientX, y: e.clientY, w: note.w, h: note.h };
      grip.setPointerCapture(e.pointerId);
    });
    grip.addEventListener("pointermove", (e) => {
      if (!start) return;
      note.w = Math.max(140, Math.min(600, start.w + e.clientX - start.x));
      note.h = Math.max(140, Math.min(600, start.h + e.clientY - start.y));
      wrap.style.width = `${note.w}px`;
      wrap.style.height = `${note.h}px`;
    });
    const stop = () => {
      if (!start) return;
      start = null;
      growBoard();
      save(note);
    };
    grip.addEventListener("pointerup", stop);
    grip.addEventListener("pointercancel", stop);
  }

  // ---------------- Board interactions ----------------

  els.board.addEventListener("dblclick", (e) => {
    if (e.target !== els.board) return;
    const r = els.board.getBoundingClientRect();
    addNote(e.clientX - r.left, e.clientY - r.top);
  });

  $("notes-add").addEventListener("click", () => {
    const r = els.board.getBoundingClientRect();
    addNote(Math.random() * Math.max(120, r.width - 320) + 150, 140 + Math.random() * 80);
  });

  $("notes-clear").addEventListener("click", async () => {
    if (!notes.length) return;
    const ok = await window.Padhai.confirm({
      title: `Delete all ${notes.length} notes?`,
      body: "The whole board will be cleared. This can't be undone.",
      confirmText: "Delete all",
      danger: true,
    });
    if (!ok) return;
    const doomed = [...notes];
    notes = [];
    render();
    if (signedIn()) {
      await Promise.allSettled(
        doomed.map((n) => api(`/api/notes/${n.id}`, { method: "DELETE" }))
      );
    } else {
      writeGuest();
    }
    toast("🗑 Board cleared");
  });

  // ---------------- View switching ----------------

  function openNotes() {
    document.querySelectorAll(".study-view").forEach((v) => (v.hidden = true));
    els.view.hidden = false;
    els.hint.hidden = notes.length > 0;
    load();
  }
  function closeNotes() {
    els.view.hidden = true;
    window.Padhai.showDefaultView?.();
  }

  $("notes-btn")?.addEventListener("click", openNotes);
  $("notes-back").addEventListener("click", closeNotes);
  document.addEventListener("padhai:docchange", () => { els.view.hidden = true; });
  // Reload from the right place whenever the account changes
  document.addEventListener("padhai:user", () => { if (!els.view.hidden) load(); });

  Object.assign(window.Padhai, {
    openNotes, closeNotes,
    guestNotes: () => (signedIn() ? [] : readGuest()),
    clearGuestNotes: () => { try { localStorage.removeItem(GUEST_KEY); } catch { /* ignore */ } },
  });

  if (!signedIn()) notes = readGuest();
})();
