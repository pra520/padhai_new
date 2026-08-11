/* Padhai — viva mode (the AI asks, you answer).
 *
 * An examiner-style oral test over the current document. The AI asks one
 * question at a time; the student types an answer; the server marks it and
 * reveals the ideal answer before moving on. The AI only ever asks — it never
 * answers on the student's behalf. */

"use strict";

(() => {
  const { api, renderMarkdown, escapeHtml, state, showLoader, hideLoader, icon } = window.Padhai;
  const $ = (id) => document.getElementById(id);

  const els = {
    setup: $("vv-setup"),
    form: $("vv-form"),
    count: $("vv-count"),
    difficulty: $("vv-difficulty"),
    focus: $("vv-focus"),
    instructions: $("vv-instructions"),
    run: $("vv-run"),
    counter: $("vv-counter"),
    bar: $("vv-bar-fill"),
    score: $("vv-score"),
    quit: $("vv-quit"),
    thread: $("vv-thread"),
    answerForm: $("vv-answer-form"),
    answer: $("vv-answer"),
    skip: $("vv-skip"),
    submit: $("vv-submit"),
    summary: $("vv-summary"),
  };

  // Config echoed back to the server so it rebuilds the exact same set for grading
  let cfg = {};
  let questions = [];
  let index = 0;
  let scoreGot = 0, scoreMax = 0;
  const results = [];  // {question, score, verdict, feedback, ideal, answer}

  function resetToSetup() {
    els.setup.hidden = false;
    els.run.hidden = true;
    els.summary.hidden = true;
    els.thread.innerHTML = "";
    els.summary.innerHTML = "";
    questions = []; index = 0; scoreGot = 0; scoreMax = 0; results.length = 0;
  }
  document.addEventListener("padhai:docchange", resetToSetup);

  // ---------------- Start ----------------
  els.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.activeDocId) return;

    cfg = {
      count: Number(els.count.value),
      difficulty: els.difficulty.value,
      focus: els.focus.value.trim(),
    };

    showLoader("The examiner is preparing your questions…");
    try {
      const data = await api(`/api/viva/${state.activeDocId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...cfg, instructions: els.instructions.value.trim() }),
      });
      questions = data.questions || [];
      if (!questions.length) {
        window.Padhai.toast("Couldn't prepare a viva from this material", "warn");
        return;
      }
      index = 0; scoreGot = 0; scoreMax = 0; results.length = 0;
      els.setup.hidden = true;
      els.summary.hidden = true;
      els.run.hidden = false;
      els.thread.innerHTML = "";
      askCurrent();
    } catch (err) {
      window.Padhai.toast(`⚠ Could not start the viva: ${err.message}`, "error");
    } finally {
      hideLoader();
    }
  });

  // ---------------- Ask ----------------
  function askCurrent() {
    const q = questions[index];
    els.counter.textContent = `${index + 1} / ${questions.length}`;
    els.bar.style.width = `${(index / questions.length) * 100}%`;
    els.score.textContent = `${scoreGot} / ${scoreMax}`;

    const bubble = document.createElement("div");
    bubble.className = "vv-ask";
    bubble.innerHTML =
      `<span class="vv-avatar">${icon("viva", 18)}</span>` +
      `<div class="vv-bubble"><span class="vv-q-label">Question ${index + 1}</span>` +
      `<p>${escapeHtml(q.question)}</p></div>`;
    els.thread.appendChild(bubble);
    scrollThread();

    els.answerForm.hidden = false;
    els.answer.value = "";
    els.answer.disabled = false;
    els.submit.disabled = false;
    els.answer.focus();
  }

  // ---------------- Answer ----------------
  els.answerForm.addEventListener("submit", (e) => { e.preventDefault(); submitAnswer(els.answer.value.trim()); });
  els.skip.addEventListener("click", () => submitAnswer(""));
  els.answer.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submitAnswer(els.answer.value.trim()); }
  });

  let awaitingMark = false;

  async function submitAnswer(answer) {
    if (awaitingMark) return;               // ignore a double-tap while marking
    awaitingMark = true;
    const q = questions[index];
    // Hide the answer box until the next question is asked, so the same
    // question can't be answered twice and appended to the results.
    els.answerForm.hidden = true;
    els.answer.disabled = true;
    els.submit.disabled = true;

    // Echo the student's answer into the thread
    if (answer) {
      const mine = document.createElement("div");
      mine.className = "vv-reply";
      mine.innerHTML = `<div class="vv-bubble vv-mine"><p>${escapeHtml(answer)}</p></div>`;
      els.thread.appendChild(mine);
    }
    const thinking = document.createElement("div");
    thinking.className = "vv-ask vv-marking";
    thinking.innerHTML =
      `<span class="vv-avatar">${icon("viva", 18)}</span>` +
      `<div class="vv-bubble"><em>Marking…</em></div>`;
    els.thread.appendChild(thinking);
    scrollThread();

    try {
      const r = await api(`/api/viva/${state.activeDocId}/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...cfg, question_id: q.id, answer }),
      });
      thinking.remove();
      scoreGot += r.score; scoreMax += 10;
      results.push({ question: q.question, answer, ...r });
      renderMark(r);
      els.score.textContent = `${scoreGot} / ${scoreMax}`;
    } catch (err) {
      thinking.remove();
      els.answerForm.hidden = false;       // let them retry this question
      els.answer.disabled = false;
      els.submit.disabled = false;
      window.Padhai.toast(`⚠ Couldn't mark that: ${err.message}`, "error");
    } finally {
      awaitingMark = false;
    }
  }

  function renderMark(r) {
    const cls = r.verdict === "correct" ? "ok" : r.verdict === "partial" ? "mid" : "bad";
    const mark = document.createElement("div");
    mark.className = `vv-ask`;
    mark.innerHTML =
      `<span class="vv-avatar">${icon("viva", 18)}</span>` +
      `<div class="vv-bubble vv-mark vv-${cls}">` +
        `<div class="vv-mark-head"><span class="vv-verdict vv-${cls}">${r.verdict}</span>` +
        `<span class="vv-points">${r.score}/10</span></div>` +
        `<p>${escapeHtml(r.feedback)}</p>` +
        (r.ideal ? `<details class="vv-ideal"><summary>Model answer</summary>` +
          `<div class="markdown">${renderMarkdown(r.ideal)}</div></details>` : "") +
      `</div>`;
    // Continue button
    const next = document.createElement("button");
    next.type = "button";
    next.className = "btn-primary vv-next";
    next.textContent = index < questions.length - 1 ? "Next question →" : "See results →";
    next.addEventListener("click", () => {
      index++;
      if (index < questions.length) askCurrent();
      else finish();
    });
    mark.querySelector(".vv-bubble").appendChild(next);
    els.thread.appendChild(mark);
    scrollThread();
    document.dispatchEvent(new CustomEvent("padhai:action", { detail: { type: "viva_answer" } }));
  }

  // ---------------- Finish ----------------
  function finish() {
    els.answerForm.hidden = true;
    els.bar.style.width = "100%";
    els.counter.textContent = `${questions.length} / ${questions.length}`;

    const pct = scoreMax ? Math.round((scoreGot / scoreMax) * 100) : 0;
    const grade = pct >= 80 ? "Excellent" : pct >= 60 ? "Good" : pct >= 40 ? "Keep going" : "Needs work";
    const cls = pct >= 60 ? "rep-ok" : pct >= 40 ? "" : "rep-low";

    els.summary.hidden = false;
    els.summary.innerHTML =
      `<div class="rep-score ${cls}">
        <div class="rep-grade">${pct}%</div>
        <div>
          <div class="rep-big">${grade}</div>
          <div class="rep-pct">${scoreGot} of ${scoreMax} marks across ${questions.length} questions</div>
        </div>
      </div>
      <h2 class="rep-h">Question by question</h2>
      <div id="vv-review"></div>
      <div class="rep-actions">
        <button id="vv-again" class="btn-primary">Ask me again</button>
      </div>`;

    const review = $("vv-review");
    results.forEach((r, i) => {
      const cls2 = r.verdict === "correct" ? "ok" : r.verdict === "partial" ? "mid" : "bad";
      const item = document.createElement("div");
      item.className = "rep-item";
      item.style.setProperty("--i", Math.min(i, 12));
      item.innerHTML =
        `<div class="rep-item-head"><span><b>Q${i + 1}.</b> ${escapeHtml(r.question)}</span>` +
        `<span class="rep-marks vv-${cls2}">${r.score}/10</span></div>` +
        `<div class="rep-item-body">` +
          `<div><span class="rep-label">You:</span> ${r.answer ? escapeHtml(r.answer) : "<em>skipped</em>"}</div>` +
          `<div class="rep-expl">${escapeHtml(r.feedback)}</div>` +
          (r.ideal ? `<div><span class="rep-label">Model:</span> ${escapeHtml(r.ideal)}</div>` : "") +
        `</div>`;
      review.appendChild(item);
    });

    $("vv-again").addEventListener("click", resetToSetup);
    document.dispatchEvent(new CustomEvent("padhai:action", { detail: { type: "viva_done", pct } }));
    scrollThread();
  }

  els.quit.addEventListener("click", async () => {
    const midway = results.length && index < questions.length;
    if (midway) {
      const ok = await window.Padhai.confirm({
        title: "End the viva now?",
        body: `You've answered ${results.length} of ${questions.length}. `
          + "You'll still get your results for those.",
        confirmText: "End viva",
      });
      if (!ok) return;
    }
    if (results.length) finish();
    else resetToSetup();
  });

  function scrollThread() {
    requestAnimationFrame(() => els.thread.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
  }
})();
