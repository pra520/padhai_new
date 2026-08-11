/* Padhai — flashcards module (Phase 2).
 * Generates a deck from the active document and drives the flip-card viewer. */

"use strict";

(() => {
  const { api, escapeHtml, state, showLoader, hideLoader } = window.Padhai;
  const $ = (id) => document.getElementById(id);

  const els = {
    form: $("fc-form"),
    count: $("fc-count"),
    difficulty: $("fc-difficulty"),
    viewer: $("fc-viewer"),
    empty: $("fc-empty"),
    counter: $("fc-counter"),
    barFill: $("fc-bar-fill"),
    card: $("fc-card"),
    question: $("fc-question"),
    answer: $("fc-answer"),
    diffBadge: $("fc-difficulty-badge"),
    tags: $("fc-tags"),
    prev: $("fc-prev"),
    next: $("fc-next"),
    flip: $("fc-flip"),
  };

  let deck = [];
  let index = 0;

  // Reset the deck whenever the user switches documents
  document.addEventListener("padhai:docchange", () => {
    deck = [];
    index = 0;
    els.viewer.hidden = true;
    els.empty.hidden = false;
  });

  els.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.activeDocId) return;

    showLoader("Creating flashcards…");
    try {
      const data = await api(`/api/flashcards/${state.activeDocId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          count: Number(els.count.value),
          difficulty: els.difficulty.value,
        }),
      });
      deck = data.cards || [];
      index = 0;
      deckCompleted = false;
      els.viewer.hidden = deck.length === 0;
      els.empty.hidden = deck.length > 0;
      render();
    } catch (err) {
      window.Padhai.toast(`⚠ Could not generate flashcards: ${err.message}`, "error");
    } finally {
      hideLoader();
    }
  });

  function render() {
    if (!deck.length) return;
    const card = deck[index];

    els.card.classList.remove("flipped");
    els.question.textContent = card.question;
    els.answer.textContent = card.answer;

    els.counter.textContent = `${index + 1} / ${deck.length}`;
    els.barFill.style.width = `${((index + 1) / deck.length) * 100}%`;

    els.diffBadge.textContent = card.difficulty;
    els.diffBadge.className = `pill pill-${card.difficulty}`;
    els.tags.innerHTML = (card.tags || [])
      .map((t) => `<span class="pill pill-tag">${escapeHtml(t)}</span>`)
      .join(" ");

    els.prev.disabled = index === 0;
    els.next.disabled = index === deck.length - 1;
  }

  let deckCompleted = false;

  const flip = () => {
    els.card.classList.toggle("flipped");
    document.dispatchEvent(new CustomEvent("padhai:action", { detail: { type: "card_flip" } }));
    // Completing the deck = flipping the last card
    if (!deckCompleted && index === deck.length - 1 && deck.length >= 5) {
      deckCompleted = true;
      document.dispatchEvent(new CustomEvent("padhai:action", { detail: { type: "deck_done" } }));
    }
  };

  els.card.addEventListener("click", flip);
  els.flip.addEventListener("click", flip);
  els.prev.addEventListener("click", () => { if (index > 0) { index--; render(); } });
  els.next.addEventListener("click", () => { if (index < deck.length - 1) { index++; render(); } });

  // Keyboard shortcuts while the flashcards tab is open
  document.addEventListener("keydown", (e) => {
    if (state.activeTab !== "flashcards" || els.viewer.hidden) return;
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.key === "ArrowLeft") els.prev.click();
    else if (e.key === "ArrowRight") els.next.click();
    else if (e.key === " ") { e.preventDefault(); flip(); }
  });
})();
