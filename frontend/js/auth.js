/* Padhai — optional accounts.
 *
 * The app works fully as a guest. Signing in only changes where your work
 * lives: uploaded material, generated summaries/mind maps and sticky notes
 * move into the database so they are still there tomorrow.
 *
 * Anything created while browsing as a guest is offered up to the account on
 * the way in, so nothing is lost by signing up late.
 *
 * The session token is set by the server as an HttpOnly cookie — this file
 * never sees it, and neither would an injected script. */

"use strict";

(() => {
  const { api, icon, toast, escapeHtml } = window.Padhai;
  const $ = (id) => document.getElementById(id);

  const els = {
    chip: $("auth-chip"),
    modal: $("auth-modal"),
    form: $("auth-form"),
    title: $("auth-title"),
    name: $("auth-name"),
    nameRow: $("auth-name-row"),
    email: $("auth-email"),
    password: $("auth-password"),
    submit: $("auth-submit"),
    error: $("auth-error"),
    swap: $("auth-swap"),
    close: $("auth-close"),
    menu: $("auth-menu"),
  };

  let mode = "login";

  // ---------------- Chip + menu ----------------

  function paintChip() {
    const user = window.Padhai.user;
    if (user) {
      const initial = (user.name || user.email)[0].toUpperCase();
      els.chip.innerHTML =
        `<span class="auth-avatar">${escapeHtml(initial)}</span>` +
        `<span class="auth-who">${escapeHtml(user.name || user.email)}</span>`;
      els.chip.title = `Signed in as ${user.email}`;
      els.chip.classList.add("in");
    } else {
      els.chip.innerHTML = `${icon("user", 15)}<span>Sign in</span>`;
      els.chip.title = "Sign in to save your work";
      els.chip.classList.remove("in");
    }
    els.menu.hidden = true;
  }

  els.chip.addEventListener("click", (e) => {
    e.stopPropagation();
    if (window.Padhai.user) els.menu.hidden = !els.menu.hidden;
    else open("login");
  });
  document.addEventListener("click", () => (els.menu.hidden = true));

  $("auth-logout").addEventListener("click", async () => {
    try { await api("/api/auth/logout", { method: "POST" }); } catch { /* already out */ }
    setUser(null);
    toast("👋 Signed out");
  });

  // ---------------- Modal ----------------

  function open(next) {
    mode = next;
    els.title.textContent = mode === "login" ? "Welcome back" : "Create your account";
    els.submit.textContent = mode === "login" ? "Sign in" : "Create account";
    els.swap.innerHTML = mode === "login"
      ? 'New here? <button type="button" class="linkish">Create an account</button>'
      : 'Already have one? <button type="button" class="linkish">Sign in</button>';
    els.swap.querySelector("button").addEventListener("click", () =>
      open(mode === "login" ? "signup" : "login")
    );
    els.nameRow.hidden = mode === "login";
    els.error.hidden = true;
    els.modal.hidden = false;
    requestAnimationFrame(() => els.modal.classList.add("in"));
    setTimeout(() => els.email.focus(), 60);
  }

  function close() {
    els.modal.classList.remove("in");
    setTimeout(() => { els.modal.hidden = true; }, 200);
  }

  els.close.addEventListener("click", close);
  els.modal.addEventListener("click", (e) => { if (e.target === els.modal) close(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !els.modal.hidden) close();
  });

  function fail(message) {
    els.error.textContent = message;
    els.error.hidden = false;
    els.submit.disabled = false;
    els.submit.textContent = mode === "login" ? "Sign in" : "Create account";
  }

  els.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    els.error.hidden = true;
    els.submit.disabled = true;
    els.submit.textContent = "Just a moment…";

    // Hand over whatever this browser made before signing in
    const body = {
      email: els.email.value.trim(),
      password: els.password.value,
      name: els.name.value.trim(),
      claim_documents: window.Padhai.state.documents.map((d) => d.id),
      claim_notes: window.Padhai.guestNotes?.() || [],
    };

    try {
      const data = await api(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (body.claim_notes.length) window.Padhai.clearGuestNotes?.();
      close();
      els.form.reset();
      setUser(data.user);
      toast(`✓ Signed in as ${data.user.name}`);
      if (data.imported_notes) toast(`📌 ${data.imported_notes} notes saved to your account`);
    } catch (err) {
      fail(err.message);
    }
  });

  // ---------------- Session ----------------

  function setUser(user) {
    window.Padhai.user = user;
    paintChip();
    document.dispatchEvent(new CustomEvent("padhai:user", { detail: { user } }));
  }

  async function boot() {
    try {
      const { user } = await api("/api/auth/me");
      setUser(user);
    } catch {
      setUser(null);
    }
  }

  Object.assign(window.Padhai, { openAuth: open, user: null });
  boot();
})();
