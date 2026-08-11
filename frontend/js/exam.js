/* Padhai — exam module (Phase 3).
 * Generates a sectioned exam paper, runs it under a countdown timer,
 * collects answers, and renders the graded report. Answer keys never
 * reach the browser — grading happens server-side. */

"use strict";

(() => {
  const { api, escapeHtml, state, showLoader, hideLoader } = window.Padhai;
  const $ = (id) => document.getElementById(id);

  const els = {
    setup: $("ex-setup"),
    form: $("ex-form"),
    marks: $("ex-marks"),
    difficulty: $("ex-difficulty"),
    time: $("ex-time"),
    topic: $("ex-topic"),
    instructions: $("ex-instructions"),
    taking: $("ex-taking"),
    palette: $("ex-palette"),
    title: $("ex-title"),
    info: $("ex-info"),
    timer: $("ex-timer"),
    submit: $("ex-submit"),
    sections: $("ex-sections"),
    report: $("ex-report"),
  };

  let exam = null;          // exam payload from the server (no answers in it)
  let timerId = null;
  let secondsLeft = 0;

  // Per-question thinking time: each timer tick is credited to the question
  // the student last interacted with. Sent with the submission so the report
  // can show where their time actually went.
  let qTimes = {};
  let activeQid = null;

  /* While a paper is running, tools like the calculator are locked. Everyone
   * interested (tools.js, the topbar) listens for this one event. */
  function setExamMode(on) {
    if (window.Padhai.examMode === !!on) return;
    window.Padhai.examMode = !!on;
    document.dispatchEvent(new CustomEvent("padhai:exammode", { detail: { on: !!on } }));
  }

  function resetToSetup() {
    stopTimer();
    setExamMode(false);
    exam = null;
    qTimes = {};
    activeQid = null;
    els.setup.hidden = false;
    els.taking.hidden = true;
    els.report.hidden = true;
    els.sections.innerHTML = "";
    els.palette.innerHTML = "";
    els.report.innerHTML = "";
  }

  document.addEventListener("padhai:docchange", resetToSetup);

  // ---------------- Create paper ----------------
  els.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.activeDocId) return;

    showLoader("Building your exam paper…");
    try {
      exam = await api(`/api/exam/${state.activeDocId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          marks: Number(els.marks.value),
          difficulty: els.difficulty.value,
          time_minutes: Number(els.time.value),
          topic: els.topic.value.trim(),
          instructions: els.instructions.value.trim(),
        }),
      });
      renderPaper();
    } catch (err) {
      window.Padhai.toast(`⚠ Could not create the exam: ${err.message}`, "error");
    } finally {
      hideLoader();
    }
  });

  function renderPaper() {
    els.setup.hidden = true;
    els.report.hidden = true;
    els.taking.hidden = false;

    els.title.textContent = `Exam — ${exam.total_marks} marks`;
    els.info.textContent =
      ` · ${exam.difficulty}${exam.topic ? ` · ${exam.topic}` : ""} · ${exam.time_minutes} min`;

    els.sections.innerHTML = "";
    for (const sec of exam.sections) {
      const secDiv = document.createElement("div");
      secDiv.className = "ex-section";
      secDiv.innerHTML = `<h2>${escapeHtml(sec.title)}` +
        (sec.marks_each ? ` <span class="doc-meta">(${sec.marks_each} mark${sec.marks_each > 1 ? "s" : ""} each)</span>` : "") +
        `</h2>`;
      sec.questions.forEach((q) => secDiv.appendChild(renderQuestion(q)));
      els.sections.appendChild(secDiv);
    }

    buildPalette();
    qTimes = {};
    activeQid = els.sections.querySelector(".q-card")?.dataset.qid || null;
    setExamMode(true);
    startTimer(exam.time_minutes * 60);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // Whichever question the student touches last owns the clock from then on
  ["focusin", "click", "input", "change"].forEach((ev) =>
    els.sections.addEventListener(ev, (e) => {
      const card = e.target.closest?.(".q-card");
      if (card?.dataset.qid) activeQid = card.dataset.qid;
    })
  );

  // ---------------- Question navigation palette ----------------
  function buildPalette() {
    els.palette.innerHTML = "";
    els.sections.querySelectorAll(".q-card").forEach((card) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ex-pal-btn";
      btn.textContent = card.dataset.qid.replace("q", "");
      btn.title = `Go to question ${btn.textContent}`;
      btn.addEventListener("click", () => {
        card.scrollIntoView({ behavior: "smooth", block: "center" });
        card.classList.add("q-flash");
        setTimeout(() => card.classList.remove("q-flash"), 1200);
      });
      els.palette.appendChild(btn);
    });
  }

  function isAnswered(card) {
    const t = card.dataset.qtype;
    if (t === "mcq" || t === "truefalse")
      return !!card.querySelector("input[type=radio]:checked");
    if (t === "fillblank") return card.querySelector("input").value.trim() !== "";
    if (t === "match")
      return [...card.querySelectorAll("select")].every((s) => s.value !== "");
    return card.querySelector("textarea").value.trim() !== "";
  }

  function refreshPalette() {
    const cards = els.sections.querySelectorAll(".q-card");
    els.palette.querySelectorAll(".ex-pal-btn").forEach((btn, i) => {
      btn.classList.toggle("answered", isAnswered(cards[i]));
    });
  }

  els.sections.addEventListener("change", refreshPalette);
  els.sections.addEventListener("input", refreshPalette);

  function renderQuestion(q) {
    const card = document.createElement("div");
    card.className = "q-card";
    card.dataset.qid = q.id;
    card.dataset.qtype = q.type;

    const num = q.id.replace("q", "");
    if (q.type === "mcq") {
      card.innerHTML =
        `<p class="q-text"><span class="q-num">${num}.</span> ${escapeHtml(q.question)}</p>` +
        `<div class="q-options">` +
        q.options.map((o, i) =>
          `<label class="ex-option"><input type="radio" name="${q.id}" value="${i}" /> ${escapeHtml(o)}</label>`
        ).join("") +
        `</div>`;
    } else if (q.type === "fillblank") {
      card.innerHTML =
        `<p class="q-text"><span class="q-num">${num}.</span> ${escapeHtml(q.question)}</p>` +
        `<input type="text" class="ex-input" placeholder="Your answer…" />`;
    } else if (q.type === "truefalse") {
      card.innerHTML =
        `<p class="q-text"><span class="q-num">${num}.</span> ${escapeHtml(q.question)}</p>` +
        `<div class="q-options q-tf">` +
        `<label class="ex-option"><input type="radio" name="${q.id}" value="true" /> True</label>` +
        `<label class="ex-option"><input type="radio" name="${q.id}" value="false" /> False</label>` +
        `</div>`;
    } else if (q.type === "match") {
      const options = q.rights.map((r, i) =>
        `<option value="${i}">${escapeHtml(r)}</option>`).join("");
      card.innerHTML =
        `<p class="q-text"><span class="q-num">${num}.</span> ${escapeHtml(q.instruction)}</p>` +
        `<div class="ex-match">` +
        q.lefts.map((l, i) =>
          `<div class="ex-match-row"><span>${escapeHtml(l)}</span>` +
          `<select data-row="${i}"><option value="">— choose —</option>${options}</select></div>`
        ).join("") +
        `</div>`;
    } else { // short / long
      card.innerHTML =
        `<p class="q-text"><span class="q-num">${num}.</span> ${escapeHtml(q.question)}</p>` +
        `<textarea class="q-textarea" rows="${q.type === "long" ? 7 : 3}" placeholder="Write your answer…"></textarea>`;
    }

    const badge = document.createElement("span");
    badge.className = "pill pill-tag ex-marks-badge";
    badge.textContent = `${q.marks} mark${q.marks > 1 ? "s" : ""}`;
    card.appendChild(badge);
    return card;
  }

  // ---------------- Timer ----------------
  function startTimer(seconds) {
    stopTimer();
    secondsLeft = seconds;
    paintTimer();
    timerId = setInterval(() => {
      secondsLeft--;
      if (activeQid) qTimes[activeQid] = (qTimes[activeQid] || 0) + 1;
      paintTimer();
      if (secondsLeft <= 0) {
        stopTimer();
        window.Padhai.toast("⏰ Time is up — submitting your paper", "warn");
        submitPaper();
      }
    }, 1000);
  }

  function stopTimer() {
    if (timerId) { clearInterval(timerId); timerId = null; }
  }

  function paintTimer() {
    const m = Math.floor(secondsLeft / 60);
    const s = secondsLeft % 60;
    els.timer.textContent = `${m}:${String(s).padStart(2, "0")}`;
    els.timer.classList.toggle("ex-timer-low", secondsLeft <= 120);
  }

  // ---------------- Collect & submit ----------------
  els.submit.addEventListener("click", async () => {
    const blanks = countUnanswered();
    const ok = await window.Padhai.confirm({
      title: blanks ? "Submit with blanks?" : "Submit your paper?",
      body: blanks
        ? `${blanks} question${blanks > 1 ? "s are" : " is"} still unanswered. `
          + "They'll be marked as zero."
        : "Your answers will be graded and the paper closed.",
      confirmText: "Submit paper",
      danger: !!blanks,
    });
    if (ok) submitPaper();
  });

  function countUnanswered() {
    let n = 0;
    for (const [, value] of collectAnswers()) {
      if (value === null || value === "" ||
          (Array.isArray(value) && value.some((v) => v === null))) n++;
    }
    return n;
  }

  function collectAnswers() {
    const out = [];
    els.sections.querySelectorAll(".q-card").forEach((card) => {
      const qid = card.dataset.qid;
      const type = card.dataset.qtype;
      let value = null;
      if (type === "mcq") {
        const checked = card.querySelector("input[type=radio]:checked");
        value = checked ? Number(checked.value) : null;
      } else if (type === "truefalse") {
        const checked = card.querySelector("input[type=radio]:checked");
        value = checked ? checked.value : null;
      } else if (type === "fillblank") {
        value = card.querySelector("input").value.trim();
      } else if (type === "match") {
        value = [...card.querySelectorAll("select")].map((s) =>
          s.value === "" ? null : Number(s.value));
      } else {
        value = card.querySelector("textarea").value.trim();
      }
      out.push([qid, value]);
    });
    return out;
  }

  async function submitPaper() {
    if (!exam) return;
    stopTimer();

    const answers = {};
    for (const [qid, value] of collectAnswers()) answers[qid] = value;

    showLoader("Grading your paper…");
    try {
      const report = await api(`/api/exam/${exam.exam_id}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers, timings: qTimes }),
      });
      renderReport(report);
    } catch (err) {
      window.Padhai.toast(`⚠ Grading failed: ${err.message}`, "error");
      startTimer(Math.max(secondsLeft, 60)); // let them try submitting again
    } finally {
      hideLoader();
    }
  }

  // ---------------- Report ----------------
  function fmtSecs(s) {
    if (s == null) return "";
    return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
  }

  function renderReport(r) {
    stopTimer();
    setExamMode(false);
    els.taking.hidden = true;
    els.report.hidden = false;

    const pctClass = r.percentage >= 70 ? "ok" : r.percentage >= 45 ? "mid" : "low";
    const rows = r.details.map((d) => {
      const full = d.awarded >= d.max;
      const partial = !full && d.awarded > 0;
      const icon = full ? "✅" : partial ? "🟡" : "❌";
      const time = d.time_seconds != null
        ? `<span class="rep-time${d.slow ? " slow" : ""}" title="${d.slow
            ? "You spent a long time thinking about this one"
            : "Time spent on this question"}">${d.slow ? "🐢 " : "⏱ "}${fmtSecs(d.time_seconds)}</span>`
        : "";
      return `
        <div class="rep-item">
          <div class="rep-item-head">
            <span>${icon} <strong>${d.id.replace("q", "Q")}</strong> ${escapeHtml(d.question || "")}</span>
            <span class="rep-marks">${time}${d.awarded} / ${d.max}</span>
          </div>
          <div class="rep-item-body">
            <p><span class="rep-label">Your answer:</span> ${escapeHtml(String(d.student_answer))}</p>
            ${full ? "" : `<p><span class="rep-label">Correct answer:</span> ${escapeHtml(String(d.correct_answer))}</p>`}
            ${d.explanation ? `<p class="rep-expl">${escapeHtml(d.explanation)}</p>` : ""}
          </div>
        </div>`;
    }).join("");

    els.report.innerHTML = `
      <div class="rep-score rep-${pctClass}">
        <div class="rep-grade">${escapeHtml(r.grade)}</div>
        <div>
          <div class="rep-big">${r.total_awarded} / ${r.total_marks} marks</div>
          <div class="rep-pct">${r.percentage}%</div>
        </div>
      </div>

      ${r.weak_topics.length ? `
        <h2 class="rep-h">Weak topics</h2>
        <div class="rep-weak">${r.weak_topics.map((t) =>
          `<span class="pill pill-hard">${escapeHtml(t)}</span>`).join(" ")}</div>` : ""}

      <h2 class="rep-h">How to improve</h2>
      <ul class="rep-suggestions">
        ${r.suggestions.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}
      </ul>

      <h2 class="rep-h">Detailed review</h2>
      ${rows}

      ${r.saved
        ? `<p class="rep-saved">📊 Noted down for your progress report — weak points
             and thinking times included. <button class="linkish" id="ex-to-report">Open my report →</button></p>`
        : `<p class="rep-saved rep-saved-guest">💡 Sign in and your results build an
             AI progress report automatically (weak points, timings, 14-day plan).</p>`}

      <div class="rep-actions">
        <button class="btn-primary" id="ex-again">Take another exam</button>
      </div>`;

    $("ex-again").addEventListener("click", resetToSetup);
    $("ex-to-report")?.addEventListener("click", () => window.Padhai.openReport?.());
    document.dispatchEvent(new CustomEvent("padhai:action", {
      detail: { type: "exam_done", pct: r.percentage },
    }));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
})();
