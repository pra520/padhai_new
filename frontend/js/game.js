/* Padhai — game-like learning mode (Phase 4).
 * XP, levels, daily streak, and badges. All state lives in the browser's
 * localStorage — no accounts, no server, and clearing browser data wipes it.
 * Tone: motivating for students, not childish. */

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
  const $ = (id) => document.getElementById(id);
  const KEY = "padhai_progress";

  // XP awarded per action (listed in padhai:action events)
  const XP = {
    upload: 10, analysis: 5, chat: 2, card_flip: 1, deck_done: 15,
    practice_correct: 5, practice_answered: 1, exam_done: 20,
    viva_answer: 3, viva_done: 15,
  };

  const BADGES = [
    { id: "first_upload", name: "Getting Started", desc: "Uploaded your first study material", icon: "📄" },
    { id: "bookworm", name: "Bookworm", desc: "Uploaded 5 study files", icon: "📚" },
    { id: "curious", name: "Curious Mind", desc: "Asked 10 questions in chat", icon: "💬" },
    { id: "deck_master", name: "Deck Master", desc: "Completed a full flashcard deck", icon: "🃏" },
    { id: "sharpshooter", name: "Sharpshooter", desc: "25 correct practice answers", icon: "🎯" },
    { id: "exam_ready", name: "Exam Ready", desc: "Completed a full exam", icon: "📝" },
    { id: "ace", name: "Ace", desc: "Scored 80%+ on an exam", icon: "🏆" },
    { id: "streak_3", name: "On a Roll", desc: "3-day study streak", icon: "🔥" },
    { id: "streak_7", name: "Locked In", desc: "7-day study streak", icon: "⚡" },
    { id: "scholar", name: "Scholar", desc: "Reached level 5", icon: "🎓" },
  ];

  // ---------------- State ----------------
  function load() {
    try {
      const s = JSON.parse(localStorage.getItem(KEY)) || {};
      return {
        xp: s.xp || 0,
        streak: s.streak || 0,
        lastDay: s.lastDay || null,
        badges: s.badges || [],
        counters: s.counters || {},
      };
    } catch {
      return { xp: 0, streak: 0, lastDay: null, badges: [], counters: {} };
    }
  }

  const g = load();
  const save = () => localStorage.setItem(KEY, JSON.stringify(g));

  const level = () => Math.floor(Math.sqrt(g.xp / 60)) + 1;
  const xpForLevel = (lvl) => 60 * (lvl - 1) ** 2;

  // ---------------- Streak ----------------
  function touchStreak() {
    const today = new Date().toDateString();
    if (g.lastDay === today) return;
    const yesterday = new Date(Date.now() - 86400000).toDateString();
    g.streak = g.lastDay === yesterday ? g.streak + 1 : 1;
    g.lastDay = today;
    if (g.streak >= 3) unlock("streak_3");
    if (g.streak >= 7) unlock("streak_7");
  }

  // ---------------- Badges ----------------
  function unlock(id) {
    if (g.badges.includes(id)) return;
    g.badges.push(id);
    const b = BADGES.find((x) => x.id === id);
    if (b) toast(`${b.icon} Badge unlocked: ${b.name}`, "badge");
  }

  function checkBadges(type, detail) {
    const c = g.counters;
    if (type === "upload") {
      unlock("first_upload");
      if ((c.upload || 0) >= 5) unlock("bookworm");
    }
    if (type === "chat" && (c.chat || 0) >= 10) unlock("curious");
    if (type === "deck_done") unlock("deck_master");
    if (type === "practice_correct" && (c.practice_correct || 0) >= 25) unlock("sharpshooter");
    if (type === "exam_done") {
      unlock("exam_ready");
      if ((detail.pct || 0) >= 80) unlock("ace");
    }
    if (level() >= 5) unlock("scholar");
  }

  // ---------------- Event sink ----------------
  document.addEventListener("padhai:action", (e) => {
    const { type } = e.detail;
    const gain = XP[type] || 0;
    if (!gain) return;

    g.xp += gain;
    g.counters[type] = (g.counters[type] || 0) + 1;
    touchStreak();
    checkBadges(type, e.detail);
    save();
    paint();

    // Toast only for meaningful gains — a +1 every flip would be noise
    if (gain >= 5) toast(`+${gain} XP`);
  });

  // ---------------- UI ----------------
  const els = {
    chip: $("game-chip"), level: $("game-level"), xpfill: $("game-xpfill"),
    streak: $("game-streak"), panel: $("game-panel"), close: $("gp-close"),
    title: $("gp-title"), xp: $("gp-xp"), plevel: $("gp-level"),
    pstreak: $("gp-streak"), nextbar: $("gp-nextbar"), nexttext: $("gp-nexttext"),
    badges: $("gp-badges"),
  };

  function paint() {
    const lvl = level();
    const cur = xpForLevel(lvl);
    const next = xpForLevel(lvl + 1);
    const frac = Math.min(1, (g.xp - cur) / (next - cur || 1));

    els.level.textContent = `Lv ${lvl}`;
    els.xpfill.style.width = `${Math.round(frac * 100)}%`;
    els.streak.textContent = `🔥 ${g.streak}`;

    els.title.textContent = `Level ${lvl}${lvl >= 5 ? " Scholar" : ""}`;
    els.xp.textContent = g.xp;
    els.plevel.textContent = lvl;
    els.pstreak.textContent = g.streak;
    els.nextbar.style.width = `${Math.round(frac * 100)}%`;
    els.nexttext.textContent = `${next - g.xp} XP to level ${lvl + 1}`;

    els.badges.innerHTML = BADGES.map((b) => {
      const got = g.badges.includes(b.id);
      return `<div class="gp-badge ${got ? "earned" : ""}" title="${b.desc}">
        <span class="gp-badge-icon">${got ? b.icon : "🔒"}</span>
        <span>${b.name}</span></div>`;
    }).join("");
  }

  els.chip.addEventListener("click", () => {
    els.panel.hidden = !els.panel.hidden;
    if (!els.panel.hidden) paint();
  });
  els.close.addEventListener("click", () => (els.panel.hidden = true));
  document.addEventListener("click", (e) => {
    if (!els.panel.hidden && !els.panel.contains(e.target) && !els.chip.contains(e.target)) {
      els.panel.hidden = true;
    }
  });

  const toast = (text, kind = "xp") => window.Padhai.toast(text, kind);

  paint();
})();
