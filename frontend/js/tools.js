/* Padhai — a calculator in a floating panel that stays open while you read a
 * question, so working out an answer never means leaving the page.
 *
 * It parses expressions itself (tokeniser → shunting-yard → RPN) rather than
 * calling eval, so nothing typed into it can execute as code. */

"use strict";

(() => {
  const { icon, toast } = window.Padhai;
  const el = (tag, cls, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html !== undefined) n.innerHTML = html;
    return n;
  };

  // =========================================================================
  // Expression evaluator
  // =========================================================================

  const CONSTS = { pi: Math.PI, e: Math.E };
  const rad = (deg) => (deg * Math.PI) / 180;

  let angleMode = "deg";
  const toAngle = (v) => (angleMode === "deg" ? rad(v) : v);
  const fromAngle = (v) => (angleMode === "deg" ? (v * 180) / Math.PI : v);

  const FUNCS = {
    sin: (x) => Math.sin(toAngle(x)),
    cos: (x) => Math.cos(toAngle(x)),
    tan: (x) => Math.tan(toAngle(x)),
    asin: (x) => fromAngle(Math.asin(x)),
    acos: (x) => fromAngle(Math.acos(x)),
    atan: (x) => fromAngle(Math.atan(x)),
    sqrt: Math.sqrt, cbrt: Math.cbrt, abs: Math.abs, exp: Math.exp,
    ln: Math.log, log: Math.log10,
    round: Math.round, floor: Math.floor, ceil: Math.ceil,
  };

  const OP_CHARS = { "×": "*", "÷": "/", "−": "-", "–": "-" };
  const PREC = { neg: 5, "^": 4, "*": 3, "/": 3, "+": 2, "-": 2 };
  const RIGHT_ASSOC = { "^": true, neg: true };

  function tokenize(src) {
    const out = [];
    const prevIsValue = () => {
      const t = out[out.length - 1];
      return !!t && (t.type === "num" || t.type === "const" || t.type === "post" ||
                     (t.type === "paren" && t.value === ")"));
    };

    for (let i = 0; i < src.length; ) {
      const c = src[i];
      if (/\s/.test(c)) { i++; continue; }

      if (/[0-9.]/.test(c)) {
        let j = i;
        while (j < src.length && /[0-9.]/.test(src[j])) j++;
        // Scientific notation: "1e5", "2.4e-3". A bare "2e" stays 2 × Euler's e.
        const sci = /^[eE][+-]?\d+/.exec(src.slice(j));
        if (sci) j += sci[0].length;
        const value = Number(src.slice(i, j));
        if (!Number.isFinite(value)) throw new Error("That number isn't valid");
        if (prevIsValue()) out.push({ type: "op", value: "*" });   // 2(3) → 2*(3)
        out.push({ type: "num", value });
        i = j; continue;
      }

      if (/[a-zA-Z]/.test(c)) {
        let j = i;
        while (j < src.length && /[a-zA-Z]/.test(src[j])) j++;
        const name = src.slice(i, j).toLowerCase();
        if (prevIsValue()) out.push({ type: "op", value: "*" });   // 2pi → 2*pi
        if (name in CONSTS) out.push({ type: "const", value: CONSTS[name] });
        else if (name in FUNCS) out.push({ type: "func", value: name });
        else throw new Error(`I don't know "${name}"`);
        i = j; continue;
      }

      if (c === "(" || c === ")") {
        if (c === "(" && prevIsValue()) out.push({ type: "op", value: "*" });
        out.push({ type: "paren", value: c });
        i++; continue;
      }

      if (c === "%") { out.push({ type: "post", value: "%" }); i++; continue; }

      const op = OP_CHARS[c] || c;
      if ("+-*/^".includes(op)) {
        // A leading +/- is a sign, not an operation
        if ((op === "-" || op === "+") && !prevIsValue()) {
          if (op === "-") out.push({ type: "op", value: "neg" });
        } else {
          out.push({ type: "op", value: op });
        }
        i++; continue;
      }
      throw new Error(`Unexpected "${c}"`);
    }
    return out;
  }

  function toRPN(tokens) {
    const output = [];
    const stack = [];
    for (const t of tokens) {
      if (t.type === "num" || t.type === "const" || t.type === "post") {
        output.push(t);
      } else if (t.type === "func") {
        stack.push(t);
      } else if (t.type === "op") {
        while (stack.length) {
          const top = stack[stack.length - 1];
          if (top.type === "func" ||
              (top.type === "op" &&
               (PREC[top.value] > PREC[t.value] ||
                (PREC[top.value] === PREC[t.value] && !RIGHT_ASSOC[t.value])))) {
            output.push(stack.pop());
          } else break;
        }
        stack.push(t);
      } else if (t.value === "(") {
        stack.push(t);
      } else {
        while (stack.length && stack[stack.length - 1].value !== "(") output.push(stack.pop());
        if (!stack.length) throw new Error("Too many closing brackets");
        stack.pop();
        if (stack.length && stack[stack.length - 1].type === "func") output.push(stack.pop());
      }
    }
    while (stack.length) {
      const t = stack.pop();
      if (t.value === "(") throw new Error("A bracket was never closed");
      output.push(t);
    }
    return output;
  }

  function evalRPN(rpn) {
    const st = [];
    const pop = () => {
      if (!st.length) throw new Error("Something is missing here");
      return st.pop();
    };
    for (const t of rpn) {
      if (t.type === "num" || t.type === "const") st.push(t.value);
      else if (t.type === "post") st.push(pop() / 100);
      else if (t.type === "func") st.push(FUNCS[t.value](pop()));
      else if (t.value === "neg") st.push(-pop());
      else {
        const b = pop(), a = pop();
        if (t.value === "/" && b === 0) throw new Error("Can't divide by zero");
        st.push(t.value === "+" ? a + b : t.value === "-" ? a - b
              : t.value === "*" ? a * b : t.value === "/" ? a / b : a ** b);
      }
    }
    if (st.length !== 1) throw new Error("That expression looks incomplete");
    return st[0];
  }

  function calculate(expr) {
    const value = evalRPN(toRPN(tokenize(expr)));
    if (!Number.isFinite(value)) throw new Error("That has no real answer");
    return value;
  }

  /** Trim floating-point noise: 0.30000000000000004 → 0.3 */
  function formatNumber(n) {
    if (Number.isInteger(n) && Math.abs(n) < 1e15) return String(n);
    const rounded = Number(n.toPrecision(12));
    if (Math.abs(rounded) >= 1e12 || (Math.abs(rounded) < 1e-6 && rounded !== 0)) {
      return rounded.toExponential(6).replace(/\.?0+e/, "e");
    }
    return String(rounded);
  }

  // =========================================================================
  // Calculator UI
  // =========================================================================

  const KEYS = [
    ["√(", "√"], ["(", "("], [")", ")"], ["^2", "x²"], ["^", "xʸ"],
    ["sin(", "sin"], ["cos(", "cos"], ["tan(", "tan"], ["pi", "π"], ["%", "%"],
    ["ln(", "ln"], ["log(", "log"], ["e", "e"], ["clear", "C"], ["back", "⌫"],
    ["7", "7"], ["8", "8"], ["9", "9"], ["÷", "÷"], ["ans", "Ans"],
    ["4", "4"], ["5", "5"], ["6", "6"], ["×", "×"], ["1/(", "1/x"],
    ["1", "1"], ["2", "2"], ["3", "3"], ["−", "−"], ["deg", "DEG"],
    ["0", "0"], [".", "."], ["equals", "="], ["+", "+"], ["abs(", "|x|"],
  ];

  function buildCalculator() {
    const root = el("section", "tool-pane", "");
    const screen = el("div", "calc-screen");
    const inputEl = el("input", "calc-input");
    inputEl.type = "text";
    inputEl.spellcheck = false;
    inputEl.setAttribute("aria-label", "Calculation");
    inputEl.placeholder = "type or tap — e.g. 3(4+5)^2";
    const preview = el("div", "calc-preview", "&nbsp;");
    screen.append(inputEl, preview);

    const pad = el("div", "calc-pad");
    const history = el("div", "calc-history");
    let ans = 0;

    const refresh = () => {
      const src = inputEl.value.trim();
      if (!src) { preview.innerHTML = "&nbsp;"; preview.className = "calc-preview"; return; }
      try {
        preview.textContent = `= ${formatNumber(calculate(src.replace(/\bans\b/gi, `(${ans})`)))}`;
        preview.className = "calc-preview";
      } catch (err) {
        preview.textContent = err.message;
        preview.className = "calc-preview bad";
      }
    };

    const insert = (text) => {
      const start = inputEl.selectionStart ?? inputEl.value.length;
      const end = inputEl.selectionEnd ?? inputEl.value.length;
      inputEl.value = inputEl.value.slice(0, start) + text + inputEl.value.slice(end);
      const caret = start + text.length;
      inputEl.setSelectionRange(caret, caret);
      inputEl.focus();
      refresh();
    };

    const commit = () => {
      const src = inputEl.value.trim();
      if (!src) return;
      try {
        const value = calculate(src.replace(/\bans\b/gi, `(${ans})`));
        ans = value;
        addHistory(src, formatNumber(value));
        inputEl.value = formatNumber(value);
        inputEl.setSelectionRange(inputEl.value.length, inputEl.value.length);
        refresh();
      } catch (err) {
        preview.textContent = err.message;
        preview.className = "calc-preview bad";
      }
    };

    function addHistory(src, out) {
      const row = el("button", "calc-hist-row");
      row.type = "button";
      row.innerHTML = `<span>${src}</span><b>${out}</b>`;
      row.addEventListener("click", () => insert(`(${out})`));
      history.prepend(row);
      while (history.children.length > 6) history.lastElementChild.remove();
    }

    let degBtn = null;
    KEYS.forEach(([action, label]) => {
      const b = el("button", "calc-key");
      b.type = "button";
      b.textContent = label;
      if (/^[0-9.]$/.test(action)) b.classList.add("num");
      if (["÷", "×", "−", "+", "^"].includes(action)) b.classList.add("op");
      if (action === "equals") b.classList.add("eq");
      if (action === "clear" || action === "back") b.classList.add("warn");
      if (action === "deg") { b.classList.add("mode"); degBtn = b; }
      if (action === "%") b.title = "Percent — divides by 100, so 200×15% = 30";
      if (action === "ans") b.title = "The previous answer";

      b.addEventListener("click", () => {
        if (action === "equals") return commit();
        if (action === "clear") { inputEl.value = ""; inputEl.focus(); return refresh(); }
        if (action === "back") {
          const at = inputEl.selectionStart ?? inputEl.value.length;
          if (at > 0) {
            inputEl.value = inputEl.value.slice(0, at - 1) + inputEl.value.slice(inputEl.selectionEnd);
            inputEl.setSelectionRange(at - 1, at - 1);
          }
          inputEl.focus();
          return refresh();
        }
        if (action === "deg") {
          angleMode = angleMode === "deg" ? "rad" : "deg";
          degBtn.textContent = angleMode.toUpperCase();
          return refresh();
        }
        insert(action);
      });
      pad.appendChild(b);
    });

    inputEl.addEventListener("input", refresh);
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); commit(); }
      if (e.key === "Escape") { inputEl.value = ""; refresh(); }
    });

    root.append(screen, pad, history);
    root.addEventListener("tool:show", () => inputEl.focus());
    return root;
  }

  // =========================================================================
  // Floating panel
  // =========================================================================

  function buildPanel() {
    const panel = el("aside", "tools");
    panel.id = "tools-panel";
    panel.hidden = true;

    const head = el("header", "tools-head");
    const tabs = el("div", "tools-tabs");
    const close = el("button", "tools-close", icon("close", 15));
    close.type = "button";
    close.title = "Close (Esc)";
    head.append(el("span", "tools-grip", icon("grip", 14)), tabs, close);

    const body = el("div", "tools-body");
    const panes = {
      calc: { label: "Calculator", icon: "calculator", node: buildCalculator() },
    };

    Object.entries(panes).forEach(([key, def]) => {
      const b = el("button", "tools-tab", `${icon(def.icon, 15)}<span>${def.label}</span>`);
      b.type = "button";
      b.dataset.pane = key;
      b.addEventListener("click", () => show(key));
      tabs.appendChild(b);
      def.node.hidden = true;
      body.appendChild(def.node);
    });

    function show(key) {
      Object.entries(panes).forEach(([k, def]) => {
        def.node.hidden = k !== key;
        if (k === key) def.node.dispatchEvent(new CustomEvent("tool:show"));
      });
      tabs.querySelectorAll(".tools-tab").forEach((b) =>
        b.classList.toggle("current", b.dataset.pane === key)
      );
    }

    panel.append(head, body);
    document.body.appendChild(panel);

    // --- open / close ---
    let opened = false;
    function open(key = "calc") {
      // No calculator while a timed exam is running — that would be cheating.
      if (window.Padhai.examMode) {
        toast("🚫 The calculator is disabled during an exam");
        return;
      }
      panel.hidden = false;
      if (!opened) { opened = true; requestAnimationFrame(() => panel.classList.add("in")); }
      else panel.classList.add("in");
      show(key);
    }
    function hide() {
      panel.classList.remove("in");
      setTimeout(() => { if (!panel.classList.contains("in")) panel.hidden = true; }, 220);
    }
    close.addEventListener("click", hide);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !panel.hidden) hide();
    });

    // --- drag by the header ---
    let drag = null;
    head.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button")) return;
      const r = panel.getBoundingClientRect();
      drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
      panel.classList.add("dragging");
      head.setPointerCapture(e.pointerId);
    });
    head.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const w = panel.offsetWidth, h = panel.offsetHeight;
      const x = Math.min(Math.max(8, e.clientX - drag.dx), window.innerWidth - w - 8);
      const y = Math.min(Math.max(8, e.clientY - drag.dy), window.innerHeight - h - 8);
      panel.style.left = `${x}px`;
      panel.style.top = `${y}px`;
      panel.style.right = "auto";
      panel.style.bottom = "auto";
    });
    const dropPanel = () => { drag = null; panel.classList.remove("dragging"); };
    head.addEventListener("pointerup", dropPanel);
    head.addEventListener("pointercancel", dropPanel);

    return { open, hide, toggle: (k) => (panel.hidden ? open(k) : hide()) };
  }

  window.Padhai.tools = buildPanel();

  // Top-bar shortcut
  const toolsBtn = document.getElementById("tools-btn");
  toolsBtn?.addEventListener("click", () => window.Padhai.tools.toggle("calc"));

  // Exam mode: snap the panel shut and grey out the button until it's over
  document.addEventListener("padhai:exammode", (e) => {
    if (e.detail.on) window.Padhai.tools.hide();
    if (toolsBtn) {
      toolsBtn.classList.toggle("locked", e.detail.on);
      toolsBtn.title = e.detail.on
        ? "Disabled during the exam" : "Calculator";
    }
  });
})();
