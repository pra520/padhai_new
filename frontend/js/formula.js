/* Padhai — formula readability.
 *
 * Models often answer with LaTeX ("$H \propto I^2 R t$"), which is noise to a
 * student revising. This turns it into clean symbols (H ∝ I² R t) and, where
 * it can, a plain-English reading ("H is proportional to I squared times R
 * times t") so the formula can be read out loud.
 *
 * Loaded before app.js — everything else picks it up from window.Padhai. */

"use strict";

(() => {
  const SUPER = { "0": "⁰", 1: "¹", 2: "²", 3: "³", 4: "⁴", 5: "⁵", 6: "⁶",
                  7: "⁷", 8: "⁸", 9: "⁹", "+": "⁺", "-": "⁻", n: "ⁿ", i: "ⁱ" };
  const SUB = { "0": "₀", 1: "₁", 2: "₂", 3: "₃", 4: "₄", 5: "₅", 6: "₆",
                7: "₇", 8: "₈", 9: "₉", "+": "₊", "-": "₋" };

  const GREEK = {
    alpha: "α", beta: "β", gamma: "γ", delta: "δ", Delta: "Δ", epsilon: "ε",
    theta: "θ", lambda: "λ", mu: "μ", nu: "ν", pi: "π", rho: "ρ", sigma: "σ",
    Sigma: "Σ", tau: "τ", phi: "φ", omega: "ω", Omega: "Ω",
  };

  // Only bracket a term when it is compound — "(1) / (2)" reads worse than "1/2".
  const atom = (s) => {
    const t = String(s).trim();
    return /^[\w.^_]+$/.test(t) ? t : `(${t})`;
  };

  const COMMANDS = [
    [/\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}/g, (m, a, b) => `${atom(a)}/${atom(b)}`],
    [/\\sqrt\s*\{([^{}]+)\}/g, (m, a) => `√${atom(a)}`],
    [/\\sqrt\s*([A-Za-z0-9]+)/g, "√$1"],
    [/\\(?:text|mathrm|mathit|mathbf|operatorname)\s*\{([^{}]*)\}/g, "$1"],
    [/\\propto/g, " ∝ "],
    [/\\times/g, " × "],
    [/\\cdot/g, " · "],
    [/\\div/g, " ÷ "],
    [/\\p[mh]\b/g, " ± "],
    [/\\leq?\b/g, " ≤ "],
    [/\\geq?\b/g, " ≥ "],
    [/\\neq\b/g, " ≠ "],
    [/\\approx/g, " ≈ "],
    [/\\infty/g, "∞"],
    [/\\(?:rightarrow|to|implies)\b/g, " → "],
    [/\\degree|\^\\circ|\\circ/g, "°"],
    [/\\left|\\right/g, ""],
    [/\\[,;!:> ]/g, " "],
  ];

  const script = (chars, map) => {
    const out = [...chars].map((c) => map[c]);
    return out.every(Boolean) ? out.join("") : null;
  };

  /** LaTeX-ish maths → readable unicode symbols. */
  function toSymbols(input) {
    let t = String(input);
    for (const [re, rep] of COMMANDS) t = t.replace(re, rep);
    for (const [name, ch] of Object.entries(GREEK)) {
      t = t.replace(new RegExp(`\\\\${name}\\b`, "g"), ch);
    }
    // Exponents and indices, braced form first
    t = t.replace(/\^\{([^{}]+)\}/g, (m, g) => script(g, SUPER) ?? `^(${g})`);
    t = t.replace(/\^(-?[0-9A-Za-z])/g, (m, g) => script(g, SUPER) ?? `^${g}`);
    t = t.replace(/_\{([^{}]+)\}/g, (m, g) => script(g, SUB) ?? `_${g}`);
    t = t.replace(/_(-?[0-9A-Za-z])/g, (m, g) => script(g, SUB) ?? `_${g}`);

    return t
      .replace(/\\/g, "")
      .replace(/[{}$]/g, "")          // $ only ever delimits maths — never output it
      .replace(/\s{2,}/g, " ")
      .trim();
  }

  const WORDS = [
    ["∝", " is proportional to "],
    ["≈", " is about "],
    ["≤", " is at most "],
    ["≥", " is at least "],
    ["≠", " is not "],
    ["→", " gives "],
    ["=", " equals "],
    ["×", " times "],
    ["·", " times "],
    ["*", " times "],
    ["÷", " divided by "],
    ["/", " divided by "],
    ["+", " plus "],
    ["±", " plus or minus "],
    ["−", " minus "],
    ["²", " squared "],
    ["³", " cubed "],
    ["√", " the square root of "],
    ["π", " pi "],
    ["∞", " infinity "],
  ];

  /** Symbols → a sentence a student can read aloud. */
  function toWords(symbols) {
    let t = ` ${symbols} `;
    for (const [sym, word] of WORDS) t = t.split(sym).join(word);
    // A lone hyphen between terms is a minus; hyphens inside words are not.
    t = t.replace(/(\s)-(\s*)/g, "$1minus ");
    return t.replace(/\s{2,}/g, " ").trim();
  }

  // A formula worth highlighting: has a relational operator and is short.
  const REL = /[=∝≈≤≥≠]|\\propto|\\leq|\\geq|\\approx/;

  function looksLikeFormula(text) {
    const t = String(text);
    return REL.test(t) && t.length <= 90 && t.split(/\s+/).length <= 18;
  }

  /**
   * Analyse one piece of text.
   * Returns {expr, reading} when it reads as a formula, otherwise null.
   * `reading` is omitted when it would just repeat the symbols.
   */
  function analyse(text) {
    const raw = String(text).replace(/^\$+|\$+$/g, "").trim();
    if (!raw || !looksLikeFormula(raw)) return null;
    const expr = toSymbols(raw);
    if (!expr) return null;
    const reading = toWords(expr);
    return { expr, reading: reading && reading !== expr ? reading : "" };
  }

  // $…$, \(…\) and \[…\] segments inside a longer sentence.
  const MATH_SEGMENT = /\$([^$]{1,120})\$|\\\(([^)]{1,120})\\\)|\\\[([^\]]{1,120})\\\]/g;

  /**
   * Pull an explicit maths segment out of a sentence.
   * "Joule's law: $H \propto I^2Rt$" → {lead: "Joule's law", expr: "H ∝ I²Rt"}
   * Returns null when the text has no delimited maths.
   */
  function extract(text) {
    const re = new RegExp(MATH_SEGMENT.source);
    const m = re.exec(String(text));
    if (!m) return null;
    const expr = toSymbols(m[1] || m[2] || m[3]);
    if (!expr) return null;
    const lead = (text.slice(0, m.index) + " " + text.slice(m.index + m[0].length))
      .replace(/\(\s*\)/g, " ")
      .replace(/\s{2,}/g, " ")
      .trim()
      .replace(/[:\-–—(,]\s*$/, "")
      .trim();
    const reading = toWords(expr);
    return { lead, expr, reading: reading && reading !== expr ? reading : "" };
  }

  /** Replace maths segments in running text with their symbol form. */
  function prettify(text) {
    let t = String(text).replace(MATH_SEGMENT, (m, a, b, c) => toSymbols(a || b || c));
    // Bare LaTeX commands that were never wrapped in delimiters
    if (/\\[a-zA-Z]{2,}/.test(t)) t = toSymbols(t);
    return t;
  }

  /**
   * Same as prettify(), but wraps each maths segment in a styled span.
   * Input must already be HTML-escaped; only quotes are re-escaped here.
   */
  function prettifyHtml(escaped) {
    return String(escaped).replace(MATH_SEGMENT, (m, a, b, c) => {
      const expr = toSymbols(a || b || c);
      const reading = toWords(expr);
      const title = reading && reading !== expr
        ? ` title="${reading.replace(/"/g, "&quot;")}"`
        : "";
      return `<span class="fx"${title}>${expr}</span>`;
    });
  }

  window.Padhai = window.Padhai || {};
  window.Padhai.formula = {
    toSymbols, toWords, analyse, extract, prettify, prettifyHtml, looksLikeFormula,
  };
})();
