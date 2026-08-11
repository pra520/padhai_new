/* Padhai frontend — plain JS, no frameworks.
 * Talks to the Flask API; all state lives in this page (session only). */

"use strict";

// ---------------- State ----------------
const state = {
  documents: [],       // [{id, filename, words, pages, topics}]
  // The document every feature module actually studies. For one pick it is
  // that document; for several it is the combined document the server builds,
  // so nothing downstream needs to know the difference.
  activeDocId: null,
  activeDoc: null,     // its summary dict (filename, members, …)
  activeTab: "summary",
};

// ---------------- DOM helpers ----------------
const $ = (id) => document.getElementById(id);

const els = {
  aiBadge: $("ai-badge"),
  dropzone: $("dropzone"),
  fileInput: $("file-input"),
  uploadStatus: $("upload-status"),
  docList: $("doc-list"),
  docEmpty: $("doc-empty"),
  docTools: $("doc-tools"),
  pickCount: $("pick-count"),
  welcome: $("welcome"),
  workspace: $("workspace"),
  docTitle: $("doc-title"),
  docChips: $("doc-chips"),
  docMeta: $("doc-meta"),
  tabs: $("tabs"),
  panelAnalysis: $("panel-analysis"),
  analysisContent: $("analysis-content"),
  panelChat: $("panel-chat"),
  panelFlashcards: $("panel-flashcards"),
  panelPractice: $("panel-practice"),
  panelExam: $("panel-exam"),
  chatMessages: $("chat-messages"),
  chatForm: $("chat-form"),
  chatInput: $("chat-input"),
  chatSend: $("chat-send"),
  loader: $("loader"),
  loaderText: $("loader-text"),
  warmBar: $("warm-bar"),
  warmFill: $("warm-fill"),
  warmText: $("warm-text"),
  warmCount: $("warm-count"),
};

// ---------------- Tiny markdown renderer ----------------
// Supports: headings, bold, italics, inline code, bullets, blockquotes.
function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderMarkdown(md) {
  const lines = escapeHtml(md).split("\n");
  let html = "", inList = false, listDepth = 0, tableBuf = [];

  const closeList = () => {
    while (listDepth > 0) { html += "</ul>"; listDepth--; }
    inList = false;
  };

  // GFM-style tables: | a | b | rows, optional |---|---| separator after row 1
  const flushTable = () => {
    if (!tableBuf.length) return;
    const rows = tableBuf.map((l) =>
      l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim()));
    tableBuf = [];
    const hasHeader = rows.length > 1 && rows[1].every((c) => /^:?-{2,}:?$/.test(c));
    const head = hasHeader ? rows[0] : null;
    const body = hasHeader ? rows.slice(2) : rows;
    let t = '<div class="md-table-wrap"><table>';
    if (head) t += "<thead><tr>" + head.map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead>";
    t += "<tbody>" + body.map((r) =>
      "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") + "</tbody>";
    html += t + "</table></div>";
  };

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");

    if (/^\s*\|.*\|\s*$/.test(line)) { closeList(); tableBuf.push(line); continue; }
    flushTable();

    const bullet = line.match(/^(\s*)[-*]\s+(.*)/);
    if (bullet) {
      const depth = Math.floor(bullet[1].length / 2) + 1;
      if (!inList) { inList = true; }
      while (listDepth < depth) { html += "<ul>"; listDepth++; }
      while (listDepth > depth) { html += "</ul>"; listDepth--; }
      html += `<li>${inline(bullet[2])}</li>`;
      continue;
    }
    closeList();

    if (/^###\s/.test(line)) html += `<h3>${inline(line.slice(4))}</h3>`;
    else if (/^##\s/.test(line)) html += `<h2>${inline(line.slice(3))}</h2>`;
    else if (/^#\s/.test(line)) html += `<h1>${inline(line.slice(2))}</h1>`;
    else if (/^&gt;\s?/.test(line)) html += `<blockquote>${inline(line.replace(/^&gt;\s?/, ""))}</blockquote>`;
    else if (line.trim() === "") html += "";
    else html += `<p>${inline(line)}</p>`;
  }
  closeList();
  flushTable();
  return html;

  function inline(s) {
    // Maths first, so a LaTeX "*" or "_" is never mistaken for emphasis
    return window.Padhai.formula.prettifyHtml(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
  }
}

// ---------------- API ----------------
async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

// ---------------- AI status badge ----------------
async function loadStatus() {
  try {
    const s = await api("/api/status");
    state.searchProvider = s.search || "";
    const ready = (s.providers || []).filter((p) => p.state === "ready");

    if (ready.length) {
      els.aiBadge.textContent = `AI: ${ready[0].name}`;
      els.aiBadge.className = "badge badge-ok badge-dot";
      els.aiBadge.title =
        "Active provider: " + ready.map((p) => p.name).join(", ") +
        "\n" + (s.providers || [])
          .filter((p) => p.state !== "ready")
          .map((p) => `${p.name}: ${p.state}`).join("\n");
    } else if (s.ai) {
      els.aiBadge.textContent = "AI: reconnecting";
      els.aiBadge.className = "badge badge-warn badge-dot";
      els.aiBadge.title = "Every provider is cooling down — retrying automatically";
    } else {
      els.aiBadge.textContent = "AI: offline mode";
      els.aiBadge.className = "badge badge-warn badge-dot";
      els.aiBadge.title =
        "Add a free key in .env (GEMINI_API_KEY, OPENROUTER_API_KEY, " +
        "GROQ_API_KEY or HF_TOKEN) for full AI answers";
    }
  } catch {
    els.aiBadge.textContent = "server unreachable";
    els.aiBadge.className = "badge badge-warn";
  }
}

// ---------------- Upload ----------------
function setupUpload() {
  els.dropzone.addEventListener("click", () => els.fileInput.click());
  els.dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") els.fileInput.click();
  });
  els.fileInput.addEventListener("change", () => handleFiles(els.fileInput.files));

  ["dragover", "dragenter"].forEach((ev) =>
    els.dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      els.dropzone.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    els.dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      els.dropzone.classList.remove("dragover");
    })
  );
  els.dropzone.addEventListener("drop", (e) => handleFiles(e.dataTransfer.files));
}

async function handleFiles(fileList) {
  const files = [...fileList];
  if (!files.length) return;

  let added = 0, split = 0, failed = 0;

  // Upload everything first, then rebuild the study context ONCE. Refreshing
  // per file would re-combine and re-warm the whole set on every arrival.
  for (const [i, file] of files.entries()) {
    showUploadStatus(files.length > 1
      ? `Uploading ${i + 1} of ${files.length} — ${file.name}…`
      : `Uploading ${file.name}…`);

    const form = new FormData();
    form.append("file", file);
    try {
      const data = await api("/api/upload", { method: "POST", body: form });
      // A file containing horizontal rules arrives back as several documents
      const docs = data.documents || [data.document];
      state.documents.push(...docs);
      added += docs.length;
      if (docs.length > 1) split++;
      renderDocList();
    } catch (err) {
      failed++;
      showUploadStatus(`✗ ${file.name}: ${err.message}`, true);
    }
  }

  els.fileInput.value = "";
  if (!added) return;

  showUploadStatus(
    `✓ ${added} document${added === 1 ? "" : "s"} added` +
    (split ? ` — ${split} file${split === 1 ? " was" : "s were"} split at its ` +
             "horizontal rules" : "") +
    (failed ? ` · ${failed} failed` : "")
  );
  await refreshContext();
  document.dispatchEvent(new CustomEvent("padhai:action", { detail: { type: "upload" } }));
}

// ---------------- Import from web link ----------------
function setupUrlImport() {
  const form = $("url-form");
  const input = $("url-input");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = input.value.trim();
    if (!url) return;

    showUploadStatus("🌐 Fetching page text…");
    form.querySelector("button").disabled = true;
    try {
      const data = await api("/api/import-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const docs = data.documents || [data.document];
      state.documents.push(...docs);
      input.value = "";
      showUploadStatus(docs.length > 1
        ? `✓ Imported and split into ${docs.length} documents`
        : `✓ ${docs[0].filename} ready`);
      renderDocList();
      await refreshContext();
      document.dispatchEvent(new CustomEvent("padhai:action", { detail: { type: "upload" } }));
    } catch (err) {
      showUploadStatus(`✗ ${err.message}`, true);
    } finally {
      form.querySelector("button").disabled = false;
    }
  });
}

function showUploadStatus(msg, isError = false) {
  els.uploadStatus.hidden = false;
  els.uploadStatus.textContent = msg;
  els.uploadStatus.classList.toggle("error", isError);
  if (!isError) setTimeout(() => (els.uploadStatus.hidden = true), 4000);
}

// ---------------- Document list ----------------
// Every uploaded document is part of the working context automatically. There
// is nothing to tick: upload, then generate. Removing a document takes it out
// of the context immediately.
function renderDocList() {
  els.docList.innerHTML = "";
  els.docEmpty.hidden = state.documents.length > 0;
  els.docTools.hidden = state.documents.length === 0;

  state.documents.forEach((doc, i) => {
    const li = document.createElement("li");
    li.className = "doc-item in-context";
    li.style.setProperty("--i", Math.min(i, 12));

    const info = [
      doc.pages ? `${doc.pages} pages` : null,
      `${doc.words.toLocaleString()} words`,
    ].filter(Boolean).join(" · ");

    li.innerHTML = `
      <span class="doc-tick" title="Included in every answer" aria-hidden="true">
        ${window.Padhai.icon ? window.Padhai.icon("check", 13) : "✓"}
      </span>
      <div class="doc-item-main">
        <div class="doc-item-name" title="${escapeHtml(doc.filename)}">${escapeHtml(doc.filename)}</div>
        <div class="doc-item-info">${info}</div>
      </div>
      <button class="doc-delete" title="Remove ${escapeHtml(doc.filename)}"
              aria-label="Remove ${escapeHtml(doc.filename)}">✕</button>`;

    li.querySelector(".doc-delete").addEventListener("click", (e) => {
      e.stopPropagation();
      deleteDocument(doc.id, doc.filename);
    });
    els.docList.appendChild(li);
  });

  const n = state.documents.length;
  els.pickCount.textContent = n === 1
    ? "1 document in context"
    : `All ${n} documents in context`;
}

async function deleteDocument(id, name = "this document") {
  const ok = await window.Padhai.confirm({
    title: "Remove document?",
    body: `“${name}” and everything generated from it will be removed.`,
    confirmText: "Remove",
    danger: true,
  });
  if (!ok) return;

  try { await api(`/api/documents/${id}`, { method: "DELETE" }); } catch {}
  state.documents = state.documents.filter((d) => d.id !== id);
  renderDocList();
  await refreshContext();          // the AI stops seeing it immediately
  window.Padhai.toast(`Removed ${name}`);
}

// ---------------- Working context ----------------
/** Rebuild the study context from every uploaded document.
 *
 * One document is studied directly; several are merged server-side into a
 * single combined document, so every feature (summary, chat, exam, viva…)
 * sees one id and needs no knowledge of how many files are behind it.
 */
let contextRun = 0;
async function refreshContext({ silent = false } = {}) {
  const ids = state.documents.map((d) => d.id);
  if (!ids.length) {
    state.activeDocId = null;
    state.activeDoc = null;
    showDefaultView();
    return;
  }

  const run = ++contextRun;    // a slower earlier request must not win
  let doc;

  if (ids.length === 1) {
    doc = state.documents[0];
  } else {
    if (!silent) showLoader(`Reading all ${ids.length} documents…`);
    try {
      doc = (await api("/api/documents/combine", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      })).document;
    } catch (err) {
      window.Padhai.toast(`⚠ ${err.message}`, "error");
      return;
    } finally {
      if (!silent) hideLoader();
    }
  }
  if (!doc || run !== contextRun) return;

  state.activeDocId = doc.id;
  state.activeDoc = doc;
  openWorkspace(doc);
  watchWarmUp(doc.id);
}

// ---------------- Workspace ----------------
function openWorkspace(doc) {
  document.querySelectorAll(".study-view").forEach((v) => (v.hidden = true));
  els.workspace.hidden = false;

  const members = doc.members || [];
  els.docTitle.textContent = doc.filename;
  els.docTitle.title = members.length
    ? members.map((m) => m.filename).join(" · ")
    : doc.filename;

  // Chapter chips make it obvious what is being studied together
  els.docChips.innerHTML = members.length
    ? members.map((m) =>
        `<span class="doc-chip" title="${escapeHtml(m.filename)}">${escapeHtml(m.filename)}</span>`
      ).join("")
    : "";
  els.docChips.hidden = !members.length;

  const bits = [];
  if (members.length) bits.push(`${members.length} documents combined`);
  if (doc.words) bits.push(`${doc.words.toLocaleString()} words`);
  if (doc.topics?.length) bits.push("Topics: " + doc.topics.slice(0, 4).join(", "));
  els.docMeta.textContent = bits.join(" · ");

  // Name the browser tab after what is being studied
  document.title = `${doc.filename} — Padhai`;

  const scope = members.length ? "these documents" : "this document";
  els.chatMessages.innerHTML =
    '<div class="chat-msg assistant"><div class="markdown">' +
    `Ask me anything about ${scope} — I'll answer only from what's in ${members.length ? "them" : "it"}.` +
    "</div></div>";
  els.chatInput.placeholder = members.length
    ? "Ask across all the selected chapters…"
    : "e.g. Explain the main idea of chapter 2…";

  // Feature modules (flashcards/practice/exam/viva) reset on this
  document.dispatchEvent(new CustomEvent("padhai:docchange", { detail: { id: doc.id } }));
  const perDocTabs = ["chat", "flashcards", "practice", "exam", "viva"];
  switchTab(perDocTabs.includes(state.activeTab) ? "summary" : state.activeTab);
}

function setupTabs() {
  els.tabs.addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (btn) switchTab(btn.dataset.tab);
  });
}

function switchTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t.dataset.tab === tab;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
    t.setAttribute("role", "tab");
  });
  // Lets ui.js slide the tab indicator and highlight the radial dock
  document.dispatchEvent(new CustomEvent("padhai:tab", { detail: { tab } }));

  const moduleTabs = ["chat", "flashcards", "practice", "exam", "viva"];
  els.panelChat.hidden = tab !== "chat";
  els.panelFlashcards.hidden = tab !== "flashcards";
  els.panelPractice.hidden = tab !== "practice";
  els.panelExam.hidden = tab !== "exam";
  $("panel-viva").hidden = tab !== "viva";
  els.panelAnalysis.hidden = moduleTabs.includes(tab);

  if (tab === "chat") { els.chatInput.focus(); return; }
  if (moduleTabs.includes(tab)) return; // managed by their modules
  loadAnalysis(tab);
}

const LOADER_MESSAGES = {
  summary: "Summarising your material…",
  keypoints: "Extracting key points…",
  definitions: "Collecting definitions…",
  mindmap: "Building mind-map notes…",
};

/** A small "built offline / rebuild this" control above each analysis. */
function regenerateBar(kind, source) {
  const bar = document.createElement("div");
  bar.className = "regen-bar" + (source === "local" ? " regen-offline" : "");

  const label = document.createElement("span");
  label.className = "regen-label";
  label.textContent = source === "local"
    ? "Built from your document without AI"
    : "Written by AI";

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "regen-btn";
  btn.textContent = source === "local" ? "Rebuild with AI" : "Regenerate";
  btn.addEventListener("click", () => loadAnalysis(kind, { refresh: true }));

  bar.append(label, btn);
  return bar;
}

async function loadAnalysis(kind, { refresh = false } = {}) {
  if (!state.activeDocId) return;
  // These calls take seconds. Remember what the student was looking at so a
  // slow reply for an abandoned tab never overwrites the one they moved to.
  const docId = state.activeDocId;
  const stale = () => state.activeTab !== kind || state.activeDocId !== docId;

  showLoader(refresh ? "Rebuilding with the AI…" : (LOADER_MESSAGES[kind] || "Working…"));
  try {
    const data = await api(
      `/api/analyze/${docId}/${kind}${refresh ? "?refresh=1" : ""}`);
    if (stale()) return;

    // The mind map is drawn as a real diagram; everything else is markdown.
    // build() returns null when the notes have no usable outline, in which
    // case we fall back to the plain text view.
    const doc = state.documents.find((d) => d.id === docId);
    const map = kind === "mindmap"
      ? window.Padhai.mindmap?.build(data.content, doc?.filename.replace(/\.[^.]+$/, ""))
      : null;

    els.analysisContent.innerHTML = map ? "" : renderMarkdown(data.content);
    if (map) els.analysisContent.appendChild(map);

    els.analysisContent.prepend(regenerateBar(kind, data.source));
    const ttsBtn = window.Padhai.tts?.makeButton(els.analysisContent);
    if (ttsBtn) els.analysisContent.prepend(ttsBtn);
    document.dispatchEvent(new CustomEvent("padhai:action", { detail: { type: "analysis", kind } }));
  } catch (err) {
    if (stale()) return;
    els.analysisContent.innerHTML =
      `<blockquote>Could not generate this view: ${escapeHtml(err.message)}</blockquote>`;
  } finally {
    if (!stale()) hideLoader();
  }
}

// ---------------- Chat ----------------
function setupChat() {
  els.chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = els.chatInput.value.trim();
    if (!question || !state.activeDocId) return;

    addChatMessage("user", question);
    els.chatInput.value = "";
    els.chatSend.disabled = true;

    const thinking = addChatMessage("assistant thinking", "Thinking…");
    try {
      const data = await api(`/api/chat/${state.activeDocId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      thinking.className = "chat-msg assistant";
      thinking.firstElementChild.innerHTML = renderMarkdown(data.content);
      // Show exactly which parts of the material the answer came from
      if (data.sources?.length) {
        const cite = document.createElement("div");
        cite.className = "chat-sources";
        cite.innerHTML =
          `<span class="chat-sources-label">From your material:</span>` +
          data.sources.map((s, i) =>
            `<span class="chat-source" title="${escapeHtml(s)}">` +
            `<b>${i + 1}</b> ${escapeHtml(s)}</span>`).join("");
        thinking.appendChild(cite);
      }
      const ttsBtn = window.Padhai.tts?.makeButton(thinking.firstElementChild);
      if (ttsBtn) thinking.appendChild(ttsBtn);
      document.dispatchEvent(new CustomEvent("padhai:action", { detail: { type: "chat" } }));
    } catch (err) {
      thinking.className = "chat-msg assistant";
      thinking.firstElementChild.innerHTML =
        `<blockquote>Error: ${escapeHtml(err.message)}</blockquote>`;
    } finally {
      els.chatSend.disabled = false;
      els.chatInput.focus();
    }
  });
}

function addChatMessage(roleClass, text) {
  const div = document.createElement("div");
  div.className = `chat-msg ${roleClass}`;
  const inner = document.createElement("div");
  inner.className = "markdown";
  inner.textContent = text;
  div.appendChild(inner);
  els.chatMessages.appendChild(div);
  els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
  return div;
}

// ---------------- Warm-up ----------------
// The server builds every view in parallel the moment a file lands. This just
// reports how far along it is, so the student can watch it fill in instead of
// waiting on a spinner the first time they open each tab.
const WARM_LABELS = {
  summary: "Summary", keypoints: "Key points", definitions: "Definitions",
  mindmap: "Mind map", flashcards: "Flashcards",
};

function watchWarmUp(docId) {
  const bar = els.warmBar;
  const poll = async () => {
    if (state.activeDocId !== docId) return hideWarm();
    let s;
    try { s = await api(`/api/documents/${docId}/status`); } catch { return hideWarm(); }

    const doc = state.documents.find((d) => d.id === docId);
    if (doc) doc.ready = s.ready;

    bar.hidden = false;
    els.warmFill.style.width = `${Math.round(s.progress * 100)}%`;
    els.warmText.textContent = s.complete
      ? "Everything is ready — every tab opens instantly"
      : `Preparing ${s.pending.map((k) => WARM_LABELS[k] || k).join(", ")}…`;
    els.warmCount.textContent = `${s.ready.length}/${s.total}`;

    if (s.complete) return setTimeout(hideWarm, 2600);
    setTimeout(poll, 1500);
  };
  poll();
}

function hideWarm() { els.warmBar.hidden = true; }

// ---------------- Views ----------------
/** Show the workspace (or the welcome screen) and hide every other view. */
function showDefaultView() {
  document.querySelectorAll(".study-view").forEach((v) => (v.hidden = true));
  if (state.activeDocId) els.workspace.hidden = false;
  else {
    els.welcome.hidden = false;
    document.title = "Padhai — your AI study workspace";
  }
}

// ---------------- Loader ----------------
function showLoader(text) {
  els.loaderText.textContent = text;
  els.loader.hidden = false;
}
function hideLoader() { els.loader.hidden = true; }

// ---------------- Shared API for feature modules ----------------
// formula.js already created the namespace — extend it, never replace it.
Object.assign(window.Padhai, {
  api, renderMarkdown, escapeHtml, state, showLoader, hideLoader, switchTab,
  showDefaultView, loadDocuments, refreshContext,
});


// ---------------- Documents belonging to the account ----------------
async function loadDocuments() {
  try {
    const { documents } = await api("/api/documents");
    // Combined documents are derived, not library items — they'd clutter the
    // list and can always be rebuilt by re-picking their members.
    state.documents = documents.filter((d) => !d.combined);
    renderDocList();
    await refreshContext({ silent: true });
  } catch { /* guest, or offline — keep whatever is on screen */ }
}

// Signing in or out swaps which library is on screen
document.addEventListener("padhai:user", (e) => {
  if (e.detail.user) {
    loadDocuments();
  } else {
    state.documents = [];
    state.activeDocId = null;
    state.activeDoc = null;
    renderDocList();
    showDefaultView();
  }
});

// ---------------- Init ----------------
loadStatus();
setupUpload();
setupUrlImport();
setupTabs();
setupChat();
