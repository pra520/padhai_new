/* Padhai — practice questions module (Phase 2).
 * Renders MCQ, fill-in-the-blank, match (drag & drop), true/false,
 * short and long answer questions with instant feedback. */

"use strict";

(() => {
  const { api, escapeHtml, state, showLoader, hideLoader } = window.Padhai;
  const $ = (id) => document.getElementById(id);

  const els = {
    form: $("pr-form"),
    count: $("pr-count"),
    difficulty: $("pr-difficulty"),
    topic: $("pr-topic"),
    instructions: $("pr-instructions"),
    score: $("pr-score"),
    container: $("pr-questions"),
    empty: $("pr-empty"),
  };

  // score = auto-gradable questions only (mcq / fillblank / truefalse / match)
  let answered = 0, correct = 0, gradable = 0;
  let lastMark = 0;   // start of thinking time for the next answered question

  document.addEventListener("padhai:docchange", () => {
    els.container.innerHTML = "";
    els.score.hidden = true;
    els.empty.hidden = false;
  });

  els.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.activeDocId) return;

    const types = [...els.form.querySelectorAll("input[name=qtype]:checked")]
      .map((c) => c.value);
    if (!types.length) {
      window.Padhai.toast("Pick at least one question type", "warn");
      els.form.querySelector(".type-picker")?.classList.add("shake");
      setTimeout(() => els.form.querySelector(".type-picker")?.classList.remove("shake"), 500);
      return;
    }

    showLoader("Generating questions…");
    try {
      const data = await api(`/api/questions/${state.activeDocId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          types,
          count: Number(els.count.value),
          difficulty: els.difficulty.value,
          topic: els.topic.value.trim(),
          instructions: els.instructions.value.trim(),
        }),
      });
      renderQuestions(data.questions || []);
    } catch (err) {
      window.Padhai.toast(`⚠ Could not generate questions: ${err.message}`, "error");
    } finally {
      hideLoader();
    }
  });

  function renderQuestions(questions) {
    els.container.innerHTML = "";
    answered = 0; correct = 0;
    gradable = questions.filter((q) =>
      ["mcq", "fillblank", "truefalse", "match"].includes(q.type)
    ).length;
    updateScore();
    els.score.hidden = questions.length === 0;
    els.empty.hidden = questions.length > 0;

    const renderers = {
      mcq: renderMcq, fillblank: renderFillblank, match: renderMatch,
      truefalse: renderTrueFalse, short: renderOpen, long: renderOpen,
    };
    questions.forEach((q, i) => {
      const card = document.createElement("div");
      card.className = "q-card";
      renderers[q.type]?.(card, q, i + 1);
      els.container.appendChild(card);
    });
    lastMark = Date.now();
  }

  function updateScore() {
    els.score.textContent = gradable
      ? `Score: ${correct} / ${answered} answered (${gradable} gradable questions)`
      : "Self-assessed practice — model answers available per question.";
  }

  function recordResult(ok, q) {
    answered++; if (ok) correct++;
    updateScore();
    document.dispatchEvent(new CustomEvent("padhai:action", {
      detail: { type: ok ? "practice_correct" : "practice_answered" },
    }));

    // Approximate thinking time: questions are usually answered top to bottom,
    // so the gap since the previous answer (or since render) is a fair guess.
    const seconds = Math.min((Date.now() - lastMark) / 1000, 600);
    lastMark = Date.now();

    // Feed the progress report (signed-in students only; guests skip silently)
    if (!window.Padhai.user || !q) return;
    const doc = state.documents.find((d) => d.id === state.activeDocId);
    api("/api/report/practice", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        qtype: q.type,
        correct: ok,
        seconds: Math.round(seconds),
        topic: els.topic.value.trim(),
        doc_name: doc?.filename || "",
        question: (q.question || q.statement || q.instruction || "").slice(0, 300),
      }),
    }).catch(() => { /* reporting must never break practice */ });
  }

  const TYPE_LABELS = {
    mcq: "Multiple choice", fillblank: "Fill in the blank", match: "Match the following",
    truefalse: "True or false", short: "Short answer", long: "Long answer",
  };

  function header(card, q, n, title) {
    card.innerHTML =
      `<div class="q-head"><span class="q-num">Q${n}</span>` +
      `<span class="pill pill-tag">${TYPE_LABELS[q.type]}</span></div>` +
      `<p class="q-text">${escapeHtml(title)}</p>`;
  }

  function feedbackEl(card) {
    const div = document.createElement("div");
    div.className = "q-feedback";
    div.hidden = true;
    card.appendChild(div);
    return div;
  }

  function showFeedback(el, ok, text) {
    el.hidden = false;
    el.className = `q-feedback ${ok ? "ok" : "bad"}`;
    el.textContent = text;
  }

  // ---------------- MCQ ----------------
  function renderMcq(card, q, n) {
    header(card, q, n, q.question);
    const feedback = feedbackEl(card);
    const wrap = document.createElement("div");
    wrap.className = "q-options";
    card.insertBefore(wrap, feedback);

    q.options.forEach((opt, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "q-option";
      btn.textContent = opt;
      btn.addEventListener("click", () => {
        if (wrap.classList.contains("locked")) return;
        wrap.classList.add("locked");
        const ok = i === q.answer_index;
        btn.classList.add(ok ? "correct" : "wrong");
        wrap.children[q.answer_index].classList.add("correct");
        showFeedback(feedback, ok, (ok ? "Correct! " : "Not quite. ") + (q.explanation || ""));
        recordResult(ok, q);
      });
      wrap.appendChild(btn);
    });
  }

  // ---------------- Fill in the blank ----------------
  function renderFillblank(card, q, n) {
    header(card, q, n, q.question);
    const feedback = feedbackEl(card);
    const row = document.createElement("div");
    row.className = "q-answer-row";
    row.innerHTML =
      '<input type="text" placeholder="Your answer…" />' +
      '<button type="button" class="btn-secondary">Check</button>';
    card.insertBefore(row, feedback);

    const input = row.querySelector("input");
    row.querySelector("button").addEventListener("click", () => {
      if (row.classList.contains("locked") || !input.value.trim()) return;
      row.classList.add("locked");
      const guess = input.value.trim().toLowerCase();
      const target = q.answer.trim().toLowerCase();
      const ok = guess === target || guess.includes(target) || target.includes(guess);
      showFeedback(feedback, ok,
        (ok ? "Correct! " : `Answer: ${q.answer}. `) + (q.explanation || ""));
      recordResult(ok, q);
    });
  }

  // ---------------- True / False ----------------
  function renderTrueFalse(card, q, n) {
    header(card, q, n, q.statement);
    const feedback = feedbackEl(card);
    const row = document.createElement("div");
    row.className = "q-options q-tf";
    card.insertBefore(row, feedback);

    [["True", true], ["False", false]].forEach(([label, val]) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "q-option";
      btn.textContent = label;
      btn.addEventListener("click", () => {
        if (row.classList.contains("locked")) return;
        row.classList.add("locked");
        const ok = val === q.answer;
        btn.classList.add(ok ? "correct" : "wrong");
        showFeedback(feedback, ok, (ok ? "Correct! " : "Not quite. ") + (q.explanation || ""));
        recordResult(ok, q);
      });
      row.appendChild(btn);
    });
  }

  // ---------------- Match the following (drag & drop) ----------------
  function renderMatch(card, q, n) {
    header(card, q, n, q.instruction);
    const feedback = feedbackEl(card);

    const grid = document.createElement("div");
    grid.className = "match-grid";
    card.insertBefore(grid, feedback);

    // Left column: fixed terms with a drop slot next to each
    const leftCol = document.createElement("div");
    leftCol.className = "match-col";
    q.pairs.forEach((p, i) => {
      const row = document.createElement("div");
      row.className = "match-row";
      row.innerHTML =
        `<div class="match-left">${escapeHtml(p.left)}</div>` +
        `<div class="match-slot" data-index="${i}">drop here</div>`;
      leftCol.appendChild(row);
    });

    // Right column: shuffled draggable answers
    const rightCol = document.createElement("div");
    rightCol.className = "match-col match-pool";
    const shuffled = q.pairs
      .map((p, i) => ({ text: p.right, index: i }))
      .sort(() => Math.random() - 0.5);
    shuffled.forEach((item) => {
      const chip = document.createElement("div");
      chip.className = "match-chip";
      chip.draggable = true;
      chip.textContent = item.text;
      chip.dataset.index = String(item.index);
      chip.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("text/plain", item.index);
        chip.classList.add("dragging");
      });
      chip.addEventListener("dragend", () => chip.classList.remove("dragging"));
      rightCol.appendChild(chip);
    });

    grid.append(leftCol, rightCol);

    grid.querySelectorAll(".match-slot").forEach((slot) => {
      slot.addEventListener("dragover", (e) => {
        e.preventDefault();
        slot.classList.add("over");
      });
      slot.addEventListener("dragleave", () => slot.classList.remove("over"));
      slot.addEventListener("drop", (e) => {
        e.preventDefault();
        slot.classList.remove("over");
        const chipIndex = e.dataTransfer.getData("text/plain");
        const chip = rightCol.querySelector(`.match-chip[data-index="${chipIndex}"]`) ||
                     grid.querySelector(`.match-slot .match-chip[data-index="${chipIndex}"]`);
        if (!chip) return;
        // If the slot already holds a chip, send it back to the pool
        const existing = slot.querySelector(".match-chip");
        if (existing) rightCol.appendChild(existing);
        slot.textContent = "";
        slot.appendChild(chip);
      });
    });

    const checkBtn = document.createElement("button");
    checkBtn.type = "button";
    checkBtn.className = "btn-secondary";
    checkBtn.textContent = "Check matches";
    card.insertBefore(checkBtn, feedback);

    checkBtn.addEventListener("click", () => {
      if (card.classList.contains("locked")) return;
      const slots = [...grid.querySelectorAll(".match-slot")];
      if (slots.some((s) => !s.querySelector(".match-chip"))) {
        showFeedback(feedback, false, "Place every answer before checking.");
        feedback.className = "q-feedback";
        return;
      }
      card.classList.add("locked");
      let right = 0;
      slots.forEach((slot) => {
        const chip = slot.querySelector(".match-chip");
        const ok = chip.dataset.index === slot.dataset.index;
        slot.classList.add(ok ? "slot-correct" : "slot-wrong");
        if (ok) right++;
      });
      const ok = right === slots.length;
      showFeedback(feedback, ok, `${right} / ${slots.length} matched correctly.`);
      recordResult(ok, q);
    });
  }

  // ---------------- Short / long answer ----------------
  function renderOpen(card, q, n) {
    header(card, q, n, q.question);
    const area = document.createElement("textarea");
    area.className = "q-textarea";
    area.rows = q.type === "long" ? 6 : 3;
    area.placeholder = "Write your answer here…";
    card.appendChild(area);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn-secondary";
    btn.textContent = "Show model answer";
    card.appendChild(btn);

    const model = document.createElement("div");
    model.className = "q-feedback ok";
    model.hidden = true;
    model.textContent = q.model_answer;
    card.appendChild(model);

    btn.addEventListener("click", () => {
      model.hidden = !model.hidden;
      btn.textContent = model.hidden ? "Show model answer" : "Hide model answer";
    });
  }
})();
