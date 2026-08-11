/* Padhai — UI layer: icon set, light/dark theme, the animated radial
 * navigation dock, the sliding tab indicator and small motion touches.
 * Loads right after app.js so every other module can use window.Padhai.icon(). */

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
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------------- Icon set (inline SVG, inherits currentColor) ----------------
  const ICONS = {
    summary: '<path d="M4 6h16M4 11h16M4 16h10"/>',
    keypoints: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.2"/>',
    definitions: '<path d="M4 5a2 2 0 0 1 2-2h6v18H6a2 2 0 0 1-2-2z"/><path d="M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6"/>',
    mindmap: '<circle cx="12" cy="5.5" r="2.8"/><circle cx="5" cy="18.5" r="2.8"/><circle cx="19" cy="18.5" r="2.8"/><path d="M12 8.3v3.4M12 11.7l-5.2 4.2M12 11.7l5.2 4.2"/>',
    flashcards: '<rect x="3" y="7" width="13" height="12" rx="2"/><path d="M7.5 4h11A2.5 2.5 0 0 1 21 6.5V16"/>',
    practice: '<path d="M4 20.5l4.2-1.1L19 8.6a2 2 0 0 0 0-2.8l-.8-.8a2 2 0 0 0-2.8 0L4.9 15.9z"/><path d="M14.5 7.5l2.8 2.8"/>',
    exam: '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
    chat: '<path d="M21 11.8a8 8 0 0 1-11.7 7.2L4 20.6l1.6-5A8 8 0 1 1 21 11.8z"/>',
    papers: '<path d="M8 3h7l4 4v14H8z"/><path d="M15 3v4h4"/><path d="M5 7v14h11"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4.1-4.1"/>',
    upload: '<path d="M12 16.5V4.2"/><path d="M7 9.2l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    audio: '<path d="M12 3v12"/><path d="M9 6.5l6-2.2"/><circle cx="8" cy="17" r="3"/><path d="M11 17V7"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18z"/>',
    pdf: '<path d="M8 3h7l4 4v14H8z"/><path d="M15 3v4h4"/><path d="M11 12h1.5a1.5 1.5 0 0 1 0 3H11v-3zM11 15v2.5"/>',
    trophy: '<path d="M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M7 6H4v1a3 3 0 0 0 3 3M17 6h3v1a3 3 0 0 1-3 3"/><path d="M12 14v4M9 21h6"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.2l3.2 2"/>',
    shield: '<path d="M12 3l7 3v6c0 4.4-2.9 7.9-7 9-4.1-1.1-7-4.6-7-9V6z"/>',
    sun: '<circle cx="12" cy="12" r="4.4"/><path d="M12 2.2v2M12 19.8v2M2.2 12h2M19.8 12h2M5.1 5.1l1.4 1.4M17.5 17.5l1.4 1.4M18.9 5.1l-1.4 1.4M6.5 17.5l-1.4 1.4"/>',
    moon: '<path d="M20.5 14.8A8.6 8.6 0 1 1 9.2 3.5a6.9 6.9 0 0 0 11.3 11.3z"/>',
    compass: '<circle cx="12" cy="12" r="9"/><path d="M15.6 8.4l-2.1 5.1-5.1 2.1 2.1-5.1z"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    chevron: '<path d="M9 6l6 6-6 6"/>',
    check: '<path d="M4.5 12.5l5 5 10-11"/>',
    flow: '<rect x="8" y="3" width="8" height="5" rx="1.5"/><rect x="3" y="16" width="8" height="5" rx="1.5"/><rect x="14" y="16" width="7" height="5" rx="1.5"/><path d="M12 8v4M7 16v-4h10v4"/>',
    cards: '<rect x="3" y="4" width="8" height="7" rx="1.5"/><rect x="13" y="4" width="8" height="7" rx="1.5"/><rect x="3" y="13" width="8" height="7" rx="1.5"/><rect x="13" y="13" width="8" height="7" rx="1.5"/>',
    download: '<path d="M12 3v12"/><path d="M7.5 10.5L12 15l4.5-4.5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    calculator: '<rect x="4" y="2.5" width="16" height="19" rx="2.5"/><path d="M7.5 7h9"/><path d="M8 12h.01M12 12h.01M16 12h.01M8 16.5h.01M12 16.5h.01M16 16.5h.01"/>',
    board: '<rect x="2.5" y="4" width="19" height="12.5" rx="2"/><path d="M12 16.5v4M8.5 20.5h7"/><path d="M6.5 12l3-3 2.5 2.5 3.5-4"/>',
    marker: '<path d="M4 19.5h4l10-10a2.5 2.5 0 0 0-3.5-3.5l-10 10z"/><path d="M3 21.5h7"/>',
    eraser: '<path d="M8 20.5h12"/><path d="M15.5 4.2l4.3 4.3a2 2 0 0 1 0 2.8l-8 8H7.6l-3.4-3.4a2 2 0 0 1 0-2.8l8.5-8.9a2 2 0 0 1 2.8 0z"/>',
    undo: '<path d="M4 9h10a5.5 5.5 0 0 1 0 11H8"/><path d="M8 4.5L3.5 9 8 13.5"/>',
    grid: '<path d="M6 6h.01M12 6h.01M18 6h.01M6 12h.01M12 12h.01M18 12h.01M6 18h.01M12 18h.01M18 18h.01"/>',
    trash: '<path d="M4 6.5h16"/><path d="M9.5 6.5V4.5h5v2"/><path d="M6.5 6.5l1 13.5h9l1-13.5"/>',
    grip: '<path d="M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01"/>',
    sticky: '<path d="M4 4h16v10l-6 6H4z"/><path d="M20 14h-6v6"/><path d="M8 9h8M8 12.5h4"/>',
    user: '<circle cx="12" cy="8" r="3.6"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>',
    viva: '<path d="M12 3a4 4 0 0 1 4 4v4a4 4 0 0 1-8 0V7a4 4 0 0 1 4-4z"/><path d="M6 11a6 6 0 0 0 12 0"/><path d="M12 17v3M9 20.5h6"/>',
    report: '<path d="M4 20h16"/><path d="M6.5 20v-6.5M12 20V9M17.5 20V4.5"/><path d="M4.5 8.5l5-3 4 2.5 5.5-4"/>',
    calendar: '<rect x="3.5" y="5" width="17" height="16" rx="2"/><path d="M8 3v4M16 3v4M3.5 10.5h17"/>',
    expand: '<path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3"/>',
    collapse: '<path d="M4 8h4V4M20 8h-4V4M4 16h4v4M20 16h-4v4"/>',
  };

  /** Build an inline SVG icon. Falls back to an empty box for unknown names. */
  function icon(name, size = 20, cls = "") {
    return (
      `<svg class="ic ${cls}" viewBox="0 0 24 24" width="${size}" height="${size}" ` +
      'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" ' +
      `stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`
    );
  }

  /** Fill every <span data-icon="name"> in the markup with its SVG. */
  function paintStaticIcons(root = document) {
    root.querySelectorAll("[data-icon]").forEach((el) => {
      el.innerHTML = icon(el.dataset.icon, Number(el.dataset.size) || 20);
    });
  }

  // ---------------- Theme ----------------
  const THEME_KEY = "padhai_theme";

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    const btn = $("theme-toggle");
    if (btn) {
      btn.setAttribute("aria-label", theme === "light" ? "Switch to dark theme" : "Switch to light theme");
      btn.title = theme === "light" ? "Dark theme" : "Light theme";
    }
    // The whiteboard paints its own grid, so it needs to know
    document.dispatchEvent(new CustomEvent("padhai:theme", { detail: { theme } }));
  }

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") || "dark";
  }

  function setupTheme() {
    const btn = $("theme-toggle");
    if (!btn) return;
    btn.innerHTML = icon("sun", 19, "ic-sun") + icon("moon", 19, "ic-moon");
    applyTheme(currentTheme());

    btn.addEventListener("click", () => {
      const next = currentTheme() === "light" ? "dark" : "light";
      applyTheme(next);
      try { localStorage.setItem(THEME_KEY, next); } catch { /* private mode */ }
      toast(next === "light" ? "☀ Light theme" : "🌙 Dark theme");
    });

    // Follow the OS only while the student hasn't picked a theme themselves
    window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", (e) => {
      let stored = null;
      try { stored = localStorage.getItem(THEME_KEY); } catch { /* ignore */ }
      if (!stored) applyTheme(e.matches ? "light" : "dark");
    });
  }

  // ---------------- Toasts ----------------
  function toast(text, kind = "xp") {
    const stack = $("toast-stack");
    if (!stack) return;
    const div = document.createElement("div");
    div.className = `toast toast-${kind}`;
    div.textContent = text;
    stack.appendChild(div);
    requestAnimationFrame(() => div.classList.add("show"));
    setTimeout(() => {
      div.classList.remove("show");
      setTimeout(() => div.remove(), 350);
    }, kind === "badge" ? 4000 : 1900);
  }

  // ---------------- Confirm dialog ----------------
  // A styled, promise-based stand-in for window.confirm(), so destructive
  // actions look like the rest of the app and can be dismissed with Escape.
  function confirmDialog({ title, body = "", confirmText = "Confirm",
                           cancelText = "Cancel", danger = false } = {}) {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "modal confirm-modal";
      overlay.innerHTML =
        `<div class="modal-card confirm-card" role="alertdialog" aria-modal="true">
           <h2>${escapeHtml(title)}</h2>
           ${body ? `<p class="confirm-body">${escapeHtml(body)}</p>` : ""}
           <div class="confirm-actions">
             <button type="button" class="btn-secondary" data-act="cancel">${escapeHtml(cancelText)}</button>
             <button type="button" class="btn-primary ${danger ? "btn-danger" : ""}"
                     data-act="ok">${escapeHtml(confirmText)}</button>
           </div>
         </div>`;
      document.body.appendChild(overlay);
      requestAnimationFrame(() => overlay.classList.add("in"));

      const previouslyFocused = document.activeElement;
      const okBtn = overlay.querySelector('[data-act="ok"]');
      okBtn.focus();

      const done = (value) => {
        overlay.classList.remove("in");
        document.removeEventListener("keydown", onKey, true);
        setTimeout(() => overlay.remove(), 180);
        previouslyFocused?.focus?.();
        resolve(value);
      };
      const onKey = (e) => {
        if (e.key === "Escape") { e.stopPropagation(); done(false); }
        if (e.key === "Enter" && document.activeElement === okBtn) done(true);
        // Keep focus inside the dialog while it is open
        if (e.key === "Tab") {
          const focusables = overlay.querySelectorAll("button");
          const first = focusables[0], last = focusables[focusables.length - 1];
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
      };
      document.addEventListener("keydown", onKey, true);
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) done(false);
        const act = e.target.closest("[data-act]")?.dataset.act;
        if (act) done(act === "ok");
      });
    });
  }

  const escapeHtml = (s) =>
    String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  // ---------------- Tabs: icons + sliding glider ----------------
  const TAB_ICONS = {
    summary: "summary", keypoints: "keypoints", definitions: "definitions",
    mindmap: "mindmap", flashcards: "flashcards", practice: "practice",
    exam: "exam", viva: "viva", chat: "chat",
  };

  function setupTabs() {
    const tabs = $("tabs");
    if (!tabs) return;

    tabs.querySelectorAll(".tab").forEach((btn) => {
      const name = TAB_ICONS[btn.dataset.tab];
      if (name) btn.insertAdjacentHTML("afterbegin", icon(name, 17));
    });

    const glider = document.createElement("span");
    glider.className = "tab-glider";
    tabs.prepend(glider);

    // The glider tracks the active pill's exact box, so it follows correctly
    // even when the bar wraps onto several rows.
    const moveGlider = () => {
      const active = tabs.querySelector(".tab.active");
      if (!active || !active.offsetWidth) return;
      glider.style.width = `${active.offsetWidth}px`;
      glider.style.height = `${active.offsetHeight}px`;
      glider.style.transform = `translate(${active.offsetLeft}px, ${active.offsetTop}px)`;
      glider.classList.add("ready");
    };

    document.addEventListener("padhai:tab", moveGlider);
    window.addEventListener("resize", moveGlider);
    // The tab bar lives inside a hidden workspace at boot — measure once shown
    new MutationObserver(moveGlider).observe($("workspace"), {
      attributes: true, attributeFilter: ["hidden"],
    });
    moveGlider();
  }

  // ---------------- Radial navigation dock ----------------
  const NAV_ITEMS = [
    { tab: "summary", icon: "summary", label: "Summary" },
    { tab: "keypoints", icon: "keypoints", label: "Key points" },
    { tab: "definitions", icon: "definitions", label: "Definitions" },
    { tab: "mindmap", icon: "mindmap", label: "Mind map" },
    { tab: "flashcards", icon: "flashcards", label: "Flashcards" },
    { tab: "practice", icon: "practice", label: "Practice" },
    { tab: "exam", icon: "exam", label: "Exam" },
    { tab: "viva", icon: "viva", label: "Viva" },
    { tab: "chat", icon: "chat", label: "Chat" },
    { action: "report", icon: "report", label: "My report" },
    { action: "notes", icon: "sticky", label: "Sticky notes" },
    { action: "calc", icon: "calculator", label: "Calculator" },
    { action: "upload", icon: "upload", label: "Upload" },
  ];

  function setupRadial() {
    const root = $("radial-nav");
    const core = $("radial-toggle");
    const holder = $("radial-items");
    if (!root || !core || !holder) return;

    const scrim = document.createElement("div");
    scrim.className = "radial-scrim";
    document.body.appendChild(scrim);

    core.innerHTML =
      '<span class="radial-core-ring"></span>' + icon("compass", 26);

    // Positions are expressed against the CSS --nav-r variable so the ring
    // resizes with the viewport without rebuilding the dock.
    const step = 360 / NAV_ITEMS.length;

    NAV_ITEMS.forEach((item, i) => {
      const angle = ((-90 + i * step) * Math.PI) / 180;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "radial-item";
      btn.dataset.label = item.label;
      if (item.tab) btn.dataset.tab = item.tab;
      btn.setAttribute("aria-label", item.label);
      btn.style.setProperty("--x", `calc(var(--nav-r) * ${Math.cos(angle).toFixed(4)})`);
      btn.style.setProperty("--y", `calc(var(--nav-r) * ${Math.sin(angle).toFixed(4)})`);
      btn.style.setProperty("--d", `${reduceMotion ? 0 : i * 32}ms`);
      btn.innerHTML = icon(item.icon, 21);
      btn.addEventListener("click", () => { navigate(item); close(); });
      holder.appendChild(btn);
    });

    const track = document.createElement("span");
    track.className = "radial-track";
    root.insertBefore(track, holder);

    const isOpen = () => root.classList.contains("open");

    /** Distance from the button's resting corner to the viewport centre. */
    function centreOffset() {
      const r = root.getBoundingClientRect();
      // Measure the closed position even when called while open.
      const restX = isOpen() ? r.left - parseFloat(root.style.getPropertyValue("--to-x") || 0) : r.left;
      const restY = isOpen() ? r.top - parseFloat(root.style.getPropertyValue("--to-y") || 0) : r.top;
      return {
        x: window.innerWidth / 2 - (restX + r.width / 2),
        y: window.innerHeight / 2 - (restY + r.height / 2),
      };
    }

    function open() {
      const { x, y } = centreOffset();
      root.style.setProperty("--to-x", `${x.toFixed(1)}px`);
      root.style.setProperty("--to-y", `${y.toFixed(1)}px`);
      root.classList.add("open");
      scrim.classList.add("show");
      core.setAttribute("aria-expanded", "true");
      markCurrent();
    }

    // Keep the dial centred if the window is resized while it is open
    window.addEventListener("resize", () => {
      if (!isOpen()) return;
      const { x, y } = centreOffset();
      root.style.setProperty("--to-x", `${x.toFixed(1)}px`);
      root.style.setProperty("--to-y", `${y.toFixed(1)}px`);
    });
    function close() {
      root.classList.remove("open");
      scrim.classList.remove("show");
      core.setAttribute("aria-expanded", "false");
    }

    core.addEventListener("click", () => (isOpen() ? close() : open()));
    scrim.addEventListener("click", close);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && isOpen()) close();
      // "n" opens the dial, unless the student is typing or a dialog is up
      if ((e.key === "n" || e.key === "N") && !isTyping() &&
          !e.ctrlKey && !e.metaKey && !document.querySelector(".modal")) {
        isOpen() ? close() : open();
      }
    });

    function markCurrent() {
      const active = window.Padhai.state.activeTab;
      holder.querySelectorAll(".radial-item").forEach((b) =>
        b.classList.toggle("current", b.dataset.tab === active)
      );
    }
    document.addEventListener("padhai:tab", markCurrent);
  }

  function navigate(item) {
    const S = window.Padhai;
    if (item.action === "report") return S.openReport?.();
    if (item.action === "notes") return S.openNotes?.();
    if (item.action === "calc") return S.tools?.open("calc");
    if (item.action === "upload") {
      S.showDefaultView?.();
      $("dropzone")?.scrollIntoView({ block: "center" });
      $("file-input")?.click();
      return;
    }
    if (!S.state.activeDocId) {
      toast("📄 Upload something to study first");
      $("dropzone")?.scrollIntoView({ block: "center" });
      return;
    }
    S.showDefaultView?.();
    S.switchTab(item.tab);
    document.querySelector(".tabs")?.scrollIntoView({ block: "nearest" });
  }

  // ---------------- Welcome-screen orbit ----------------
  const ORBIT = [
    { ring: 1, icons: ["summary", "flashcards", "exam", "chat"] },
    { ring: 2, icons: ["report", "mindmap", "audio", "trophy", "practice", "globe"] },
  ];

  function setupOrbit() {
    const host = $("orbit");
    if (!host) return;
    host.innerHTML =
      '<span class="orbit-track orbit-track-1"></span>' +
      '<span class="orbit-track orbit-track-2"></span>' +
      ORBIT.map((r) => {
        const radius = r.ring === 1 ? 90 : 134;
        const step = 360 / r.icons.length;
        const chips = r.icons
          .map((name, i) =>
            `<span class="orbit-chip" style="--a:${(i * step).toFixed(1)}deg;--r:${radius}px">` +
            `<span>${icon(name, 21)}</span></span>`
          )
          .join("");
        return `<span class="orbit-ring orbit-ring-${r.ring}">${chips}</span>`;
      }).join("") +
      '<span class="orbit-core">SA</span>';
  }

  // ---------------- Small motion touches ----------------
  function setupRipples() {
    if (reduceMotion) return;
    document.addEventListener("pointerdown", (e) => {
      const btn = e.target.closest(".btn-primary, .btn-secondary");
      if (!btn || btn.disabled) return;
      const rect = btn.getBoundingClientRect();
      const span = document.createElement("span");
      span.className = "ripple";
      const size = Math.max(rect.width, rect.height);
      span.style.cssText =
        `width:${size}px;height:${size}px;left:${e.clientX - rect.left}px;top:${e.clientY - rect.top}px`;
      btn.appendChild(span);
      setTimeout(() => span.remove(), 600);
    });
  }

  function setupDropzoneGlow() {
    const dz = $("dropzone");
    if (!dz || reduceMotion) return;
    dz.addEventListener("pointermove", (e) => {
      const r = dz.getBoundingClientRect();
      dz.style.setProperty("--mx", `${e.clientX - r.left}px`);
      dz.style.setProperty("--my", `${e.clientY - r.top}px`);
    });
  }

  // ---------------- Keyboard shortcuts ----------------
  const TAB_ORDER = ["summary", "keypoints", "definitions", "mindmap",
                     "flashcards", "practice", "exam", "viva", "chat"];

  const SHORTCUTS = [
    { keys: ["1", "…", "9"], label: "Jump to a study tab" },
    { keys: ["N"], label: "Open the quick-navigation dial" },
    { keys: ["U"], label: "Upload a document" },
    { keys: ["/"], label: "Ask a question in Chat" },
    { keys: ["T"], label: "Switch light / dark theme" },
    { keys: ["C"], label: "Open the calculator" },
    { keys: ["S"], label: "Open sticky notes" },
    { keys: ["?"], label: "Show this list" },
    { keys: ["Esc"], label: "Close whatever is open" },
  ];

  /** True while the student is typing, so letters stay letters. */
  function isTyping() {
    const el = document.activeElement;
    return !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
  }

  function setupShortcuts() {
    document.addEventListener("keydown", (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping()) return;
      // Never hijack keys while a dialog is asking something
      if (document.querySelector(".confirm-modal")) return;
      const S = window.Padhai;

      if (e.key === "?") { e.preventDefault(); toggleShortcutHelp(); return; }

      // Number keys pick a tab, but only when a document is open
      if (/^[1-9]$/.test(e.key) && S.state.activeDocId) {
        const tab = TAB_ORDER[Number(e.key) - 1];
        if (tab) {
          e.preventDefault();
          S.showDefaultView?.();
          S.switchTab(tab);
        }
        return;
      }

      switch (e.key.toLowerCase()) {
        case "u": e.preventDefault(); $("file-input")?.click(); break;
        case "t": e.preventDefault(); $("theme-toggle")?.click(); break;
        case "c": e.preventDefault(); S.tools?.open("calc"); break;
        case "s": e.preventDefault(); S.openNotes?.(); break;
        case "/":
          if (S.state.activeDocId) {
            e.preventDefault();
            S.showDefaultView?.();
            S.switchTab("chat");
          }
          break;
      }
    });
  }

  function toggleShortcutHelp() {
    const open = document.getElementById("shortcut-help");
    if (open) { open.classList.remove("in"); setTimeout(() => open.remove(), 180); return; }

    const overlay = document.createElement("div");
    overlay.id = "shortcut-help";
    overlay.className = "modal";
    overlay.innerHTML =
      `<div class="modal-card shortcut-card" role="dialog" aria-modal="true"
            aria-label="Keyboard shortcuts">
         <button class="modal-close" type="button" aria-label="Close">✕</button>
         <h2>Keyboard shortcuts</h2>
         <dl class="shortcut-list">` +
        SHORTCUTS.map((s) =>
          `<div><dt>${s.keys.map((k) =>
             k === "…" ? "<span class='kbd-sep'>…</span>" : `<kbd>${k}</kbd>`).join("")}</dt>` +
          `<dd>${s.label}</dd></div>`).join("") +
      `</dl></div>`;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add("in"));
    overlay.querySelector(".modal-close").focus();
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay || e.target.closest(".modal-close")) toggleShortcutHelp();
    });
    document.addEventListener("keydown", function esc(e) {
      if (e.key === "Escape" && document.getElementById("shortcut-help")) {
        toggleShortcutHelp();
        document.removeEventListener("keydown", esc);
      }
    });
  }

  // ---------------- Top-bar "Menu" dropdown ----------------
  // The feature buttons used to crowd the bar and overflow off-screen. They now
  // live in one dropdown; each still has its original id, so the modules that
  // bind to #report-btn / #notes-btn / #tools-btn keep working unchanged.
  function setupAppsMenu() {
    const btn = $("apps-btn");
    const menu = $("apps-menu");
    if (!btn || !menu) return;

    const close = () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); };
    const open = () => { menu.hidden = false; btn.setAttribute("aria-expanded", "true"); };

    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      menu.hidden ? open() : close();
    });
    // Any choice inside the menu closes it
    menu.addEventListener("click", (e) => { if (e.target.closest("button")) close(); });
    document.addEventListener("click", (e) => {
      if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) close();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });

    // Mirror the AI status line into the menu so nothing is lost off the bar
    const badge = $("ai-badge");
    const mirror = $("ai-badge-menu");
    if (badge && mirror) {
      const sync = () => {
        mirror.textContent = badge.textContent;
        mirror.className = "apps-status " + (badge.classList.contains("badge-ok") ? "ok"
          : badge.classList.contains("badge-warn") ? "warn" : "");
      };
      sync();
      new MutationObserver(sync).observe(badge, {
        childList: true, characterData: true, subtree: true, attributes: true,
      });
    }
  }

  // ---------------- Export + init ----------------
  Object.assign(window.Padhai, { icon, toast, confirm: confirmDialog });

  paintStaticIcons();
  setupTheme();
  setupTabs();
  setupRadial();
  setupOrbit();
  setupAppsMenu();
  setupShortcuts();
  setupRipples();
  setupDropzoneGlow();
})();
