/* Padhai — text-to-speech (Phase 4).
 * Uses the browser's built-in SpeechSynthesis API: free, offline, no server.
 * Any element with class "tts-btn" and a data-tts-target selector (or placed
 * next to a .markdown block) becomes a play/stop toggle. */

"use strict";

(() => {
  const supported = "speechSynthesis" in window;
  let activeBtn = null;

  function stripForSpeech(el) {
    // Read the rendered text, skip blockquote warnings (offline-mode banners)
    const clone = el.cloneNode(true);
    clone.querySelectorAll("blockquote, .tts-btn").forEach((n) => n.remove());
    return clone.textContent.replace(/\s+/g, " ").trim();
  }

  function stop() {
    speechSynthesis.cancel();
    if (activeBtn) {
      activeBtn.classList.remove("speaking");
      activeBtn.textContent = "🔊 Listen";
      activeBtn = null;
    }
  }

  function speak(text, btn) {
    stop();
    if (!text) return;
    const utter = new SpeechSynthesisUtterance(text);
    utter.rate = 1.0;
    utter.onend = stop;
    utter.onerror = stop;
    activeBtn = btn;
    btn.classList.add("speaking");
    btn.textContent = "⏹ Stop";
    speechSynthesis.speak(utter);
  }

  /** Create a listen button for a content element. */
  function makeButton(contentEl) {
    if (!supported) return null;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tts-btn";
    btn.textContent = "🔊 Listen";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (btn === activeBtn) { stop(); return; }
      speak(stripForSpeech(contentEl), btn);
    });
    return btn;
  }

  // Stop speech when the user navigates between tabs/documents
  document.addEventListener("padhai:docchange", stop);
  window.addEventListener("beforeunload", stop);

  window.Padhai.tts = { makeButton, stop, supported };
})();
