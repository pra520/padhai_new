/* Padhai — progress report view.
 *
 * Every exam a signed-in student submits (and every practice answer) is noted
 * down server-side: score, weak topics, and how long each question took.
 * This view turns that history into a dashboard — score trend, accuracy and
 * thinking-time per question type, weak topics — plus a full AI-written
 * narrative report with a 14-day study plan, and a coach chatbot that answers
 * questions about the student's own performance. */

"use strict";

(() => {
  const { api, renderMarkdown, escapeHtml, icon, toast } = window.Padhai;
  const $ = (id) => document.getElementById(id);

  const els = {
    view: $("report-view"),
    back: $("rp-back"),
    guest: $("rp-guest"),
    signin: $("rp-signin"),
    main: $("rp-main"),
    empty: $("rp-empty"),
    dash: $("rp-dash"),
    tiles: $("rp-tiles"),
    trend: $("rp-trend"),
    types: $("rp-types"),
    times: $("rp-times"),
    weak: $("rp-weak"),
    slowCard: $("rp-slow-card"),
    slow: $("rp-slow"),
    generate: $("rp-generate"),
    genMeta: $("rp-gen-meta"),
    report: $("rp-report"),
    headline: $("rp-headline"),
    sw: $("rp-sw"),
    narrative: $("rp-narrative"),
    plan: $("rp-plan"),
    chatMessages: $("rp-chat-messages"),
    chatForm: $("rp-chat-form"),
    chatInput: $("rp-chat-input"),
    chatSend: $("rp-chat-send"),
  };

  let chatHistory = [];   // [{role, content}] — short, resent for context

  // ---------------- Helpers ----------------
  const fmtSecs = (s) => s == null ? "—"
    : s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${Math.round(s)}s`;
  const fmtDate = (ts) => new Date(ts * 1000).toLocaleDateString(undefined,
    { day: "numeric", month: "short" });
  const fmtDay = (iso) => new Date(iso + "T00:00").toLocaleDateString(undefined,
    { weekday: "short", day: "numeric", month: "short" });

  // ---------------- View switching ----------------
  function openReport() {
    document.querySelectorAll(".study-view").forEach((v) => (v.hidden = true));
    els.view.hidden = false;
    const user = window.Padhai.user;
    els.guest.hidden = !!user;
    els.main.hidden = !user;
    if (user) refresh();
  }

  function closeReport() {
    els.view.hidden = true;
    window.Padhai.showDefaultView();
  }

  $("report-btn")?.addEventListener("click", openReport);
  els.back.addEventListener("click", closeReport);
  els.signin.addEventListener("click", () => window.Padhai.openAuth?.("login"));
  document.addEventListener("padhai:docchange", () => { els.view.hidden = true; });
  Object.assign(window.Padhai, { openReport, closeReport });

  // Signing in/out while the view is open swaps its contents live
  document.addEventListener("padhai:user", () => {
    chatHistory = [];
    els.chatMessages.innerHTML = "";
    els.report.hidden = true;
    if (!els.view.hidden) openReport();
  });

  // ---------------- Dashboard ----------------
  async function refresh() {
    let data;
    try {
      data = await api("/api/report/overview");
    } catch {
      return; // signed out mid-flight or server unreachable
    }

    const hasData = data.exam_count > 0 || data.practice.answered > 0;
    els.empty.hidden = hasData;
    els.dash.hidden = !hasData;
    if (!hasData) return;

    renderTiles(data);
    renderTrend(data.exams);
    renderTypeBars(data.by_type);
    renderTimeBars(data.by_type);
    renderWeak(data.weak_topics);
    renderSlow(data.slow_questions);

    els.genMeta.textContent = data.last_report_at
      ? `Last generated ${fmtDate(data.last_report_at)} — regenerate any time`
      : "Uses everything you've solved so far";
    if (data.last_report_at && els.report.hidden) loadCachedReport();
  }

  function tile(emoji, value, label, extra = "") {
    return `<div class="rp-tile">
      <span class="rp-tile-emoji">${emoji}</span>
      <b>${value}</b><label>${label}</label>${extra}
    </div>`;
  }

  function renderTiles(d) {
    const p = d.practice;
    els.tiles.innerHTML =
      tile("📝", d.exam_count, `exam${d.exam_count === 1 ? "" : "s"} taken`) +
      tile("📊", d.avg_pct != null ? `${d.avg_pct}%` : "—", "average score") +
      tile("🏆", d.best_pct != null ? `${d.best_pct}%` : "—", "best score") +
      tile("🎯", p.accuracy != null ? `${p.accuracy}%` : "—",
           `practice accuracy`, p.answered
             ? `<small>${p.correct}/${p.answered} correct</small>` : "");
  }

  // Score trend — inline SVG line chart, theme-aware via CSS variables
  function renderTrend(exams) {
    if (!exams.length) {
      els.trend.innerHTML = '<p class="empty-hint">Take an exam to start the curve.</p>';
      return;
    }
    const W = 560, H = 210, L = 38, R = 14, T = 14, B = 30;
    const iw = W - L - R, ih = H - T - B;
    const n = exams.length;
    const x = (i) => L + (n === 1 ? iw / 2 : (i * iw) / (n - 1));
    const y = (pct) => T + ih - (pct / 100) * ih;

    const pts = exams.map((e, i) => `${x(i).toFixed(1)},${y(e.pct).toFixed(1)}`);
    const area = `M${L},${T + ih} L${pts.join(" L")} L${x(n - 1)},${T + ih} Z`;

    const grid = [0, 50, 100].map((v) =>
      `<line x1="${L}" y1="${y(v)}" x2="${W - R}" y2="${y(v)}" class="rp-grid-line"/>` +
      `<text x="${L - 6}" y="${y(v) + 4}" class="rp-axis" text-anchor="end">${v}</text>`
    ).join("");

    const dots = exams.map((e, i) =>
      `<circle cx="${x(i)}" cy="${y(e.pct)}" r="4.5" class="rp-dot">` +
      `<title>${escapeHtml(e.doc)} — ${e.pct}% (${e.grade}) · ${fmtDate(e.when)}</title></circle>` +
      (n <= 8 ? `<text x="${x(i)}" y="${y(e.pct) - 10}" class="rp-axis rp-dot-label" text-anchor="middle">${e.pct}%</text>` : "")
    ).join("");

    const labels = (n <= 8 ? exams : [exams[0], exams[n - 1]]).map((e) => {
      const i = exams.indexOf(e);
      return `<text x="${x(i)}" y="${H - 8}" class="rp-axis" text-anchor="middle">${fmtDate(e.when)}</text>`;
    }).join("");

    els.trend.innerHTML =
      `<svg viewBox="0 0 ${W} ${H}" class="rp-svg" role="img" aria-label="Exam score trend">
        ${grid}
        <path d="${area}" class="rp-area"/>
        ${n > 1 ? `<polyline points="${pts.join(" ")}" class="rp-line"/>` : ""}
        ${dots}${labels}
      </svg>`;
  }

  // Horizontal bar rows (HTML, so they reflow nicely)
  function barRow(label, valueText, frac, cls = "") {
    const pct = Math.max(2, Math.min(100, Math.round(frac * 100)));
    return `<div class="rp-bar-row ${cls}">
      <span class="rp-bar-label">${escapeHtml(label)}</span>
      <span class="rp-bar-track"><span class="rp-bar-fill" style="width:${pct}%"></span></span>
      <span class="rp-bar-value">${valueText}</span>
    </div>`;
  }

  function renderTypeBars(types) {
    els.types.innerHTML = types.length
      ? types.map((t) => barRow(
          t.label, `${t.accuracy}%`, t.accuracy / 100,
          t.accuracy < 50 ? "low" : t.accuracy >= 75 ? "good" : ""))
          .join("")
      : '<p class="empty-hint">No answers recorded yet.</p>';
  }

  function renderTimeBars(types) {
    const timed = types.filter((t) => t.avg_seconds != null);
    if (!timed.length) {
      els.times.innerHTML =
        '<p class="empty-hint">Timing appears after your next exam — every question\'s thinking time is measured.</p>';
      return;
    }
    const max = Math.max(...timed.map((t) => t.avg_seconds));
    els.times.innerHTML = timed.map((t) =>
      barRow(t.label, fmtSecs(t.avg_seconds), t.avg_seconds / max, "time")).join("");
  }

  function renderWeak(weak) {
    if (!weak.length) {
      els.weak.innerHTML = '<p class="empty-hint">No repeated weak spots found yet — nice! 💪</p>';
      return;
    }
    els.weak.innerHTML = `<table class="rp-table">
      <thead><tr><th>Topic</th><th>Flagged</th></tr></thead>
      <tbody>${weak.map((w) => `
        <tr><td>⚠️ ${escapeHtml(w.topic)}</td>
            <td><span class="pill pill-hard">${w.count}×</span></td></tr>`).join("")}
      </tbody></table>`;
  }

  function renderSlow(slow) {
    els.slowCard.hidden = !slow.length;
    if (!slow.length) return;
    els.slow.innerHTML = `<table class="rp-table">
      <thead><tr><th>Question</th><th>Type</th><th>Time</th><th>Result</th></tr></thead>
      <tbody>${slow.map((q) => `
        <tr><td>${escapeHtml(q.question)}</td>
            <td><span class="pill pill-tag">${escapeHtml(q.type)}</span></td>
            <td>🐢 ${fmtSecs(q.seconds)}</td>
            <td>${q.correct ? "✅" : "❌"}</td></tr>`).join("")}
      </tbody></table>
      <p class="empty-hint">Long thinking + a wrong answer usually means the concept
      needs a re-read, not more attempts.</p>`;
  }

  // ---------------- Full AI report ----------------
  els.generate.addEventListener("click", async () => {
    els.generate.disabled = true;
    els.generate.textContent = "✨ Writing your report…";
    try {
      const { report } = await api("/api/report/generate", { method: "POST" });
      renderFullReport(report);
      toast("📊 Report ready");
    } catch (err) {
      toast(`✗ ${err.message}`);
    } finally {
      els.generate.disabled = false;
      els.generate.textContent = "✨ Generate my full AI report";
    }
  });

  async function loadCachedReport() {
    try {
      const { report } = await api("/api/report/latest");
      if (report) renderFullReport(report, true);
    } catch { /* fine — student can generate */ }
  }

  function renderFullReport(r, cached = false) {
    els.report.hidden = false;
    els.headline.innerHTML =
      `${icon("report", 20)} <span>${escapeHtml(r.headline || "Your progress report")}</span>` +
      (cached && r.generated_at
        ? ` <span class="doc-meta">· generated ${fmtDate(r.generated_at)}</span>` : "");

    els.sw.innerHTML = `
      <div class="rp-sw-card good"><h3>✅ Strengths</h3><ul>
        ${(r.strengths || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("") || "<li>Keep solving to reveal them</li>"}
      </ul></div>
      <div class="rp-sw-card bad"><h3>⚠️ Weak points</h3><ul>
        ${(r.weaknesses || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("") || "<li>None flagged yet</li>"}
      </ul></div>`;

    els.narrative.innerHTML = renderMarkdown(r.narrative_md || "");

    const today = new Date().toISOString().slice(0, 10);
    els.plan.innerHTML = `<div class="md-table-wrap"><table class="rp-table rp-plan-table">
      <thead><tr><th>Day</th><th>Focus</th><th>What to do</th><th>⏱</th></tr></thead>
      <tbody>${(r.plan || []).map((p) => `
        <tr class="${p.date === today ? "today" : ""}">
          <td><span class="rp-day">${p.day}</span><small>${p.date ? fmtDay(p.date) : ""}</small></td>
          <td>${/review|recharge/i.test(p.focus) ? "🌿" : "📚"} ${escapeHtml(p.focus)}</td>
          <td><ul class="rp-tasks">${(p.tasks || []).map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ul></td>
          <td>${p.minutes} min</td>
        </tr>`).join("")}
      </tbody></table></div>`;

    if (!cached) els.report.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---------------- Coach chat ----------------
  function addMsg(roleClass, html) {
    const div = document.createElement("div");
    div.className = `chat-msg ${roleClass}`;
    div.innerHTML = `<div class="markdown">${html}</div>`;
    els.chatMessages.appendChild(div);
    els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
    return div;
  }

  els.chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = els.chatInput.value.trim();
    if (!question) return;

    addMsg("user", escapeHtml(question));
    els.chatInput.value = "";
    els.chatSend.disabled = true;
    const thinking = addMsg("assistant thinking", "Looking at your results…");

    try {
      const data = await api("/api/report/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, history: chatHistory.slice(-6) }),
      });
      thinking.className = "chat-msg assistant";
      thinking.firstElementChild.innerHTML = renderMarkdown(data.content);
      chatHistory.push({ role: "user", content: question },
                       { role: "assistant", content: data.content });
      if (chatHistory.length > 12) chatHistory = chatHistory.slice(-12);
    } catch (err) {
      thinking.className = "chat-msg assistant";
      thinking.firstElementChild.innerHTML =
        `<blockquote>Error: ${escapeHtml(err.message)}</blockquote>`;
    } finally {
      els.chatSend.disabled = false;
      els.chatInput.focus();
    }
  });
})();
