/* Padhai — visual mind maps.
 *
 * The AI returns mind-map notes as a nested markdown bullet list. This module
 * parses that outline into a tree and draws it five different ways — branch
 * tree, flow chart, revision cards, radial wheel and timeline — so the same
 * material can be revised in whichever shape suits it.
 *
 * Formulas are rewritten into readable symbols with a plain-English reading
 * underneath, and the map can be downloaded as PNG, SVG or markdown. */

"use strict";

(() => {
  const { escapeHtml, icon, formula, toast } = window.Padhai;

  // One hue per top-level branch, cycled if there are more than six.
  const HUES = [214, 268, 322, 14, 38, 158];

  // ---------------- Parsing ----------------

  /** Strip markdown emphasis so node labels stay short and clean. */
  function clean(s) {
    return s
      .replace(/\*\*(.+?)\*\*/g, "$1")
      .replace(/\*(.+?)\*/g, "$1")
      .replace(/`(.+?)`/g, "$1")
      .replace(/\s{2,}/g, " ")
      .trim()
      .replace(/^[-–—:]\s*|[.;,]$/g, "")
      .trim();
  }

  const BULLET_RE = /^(\s*)(?:[-*+•]|\d+[.)])\s+(.*)$/;
  const HEADING_RE = /^#{1,6}\s+(.*)$/;

  /**
   * Turn a nested markdown bullet list into {title, children}.
   * Depth comes from the leading indent, so 2-space, 4-space and tab
   * indentation all work.
   */
  function parseOutline(md) {
    const root = { text: "", children: [] };
    const stack = [root];
    const indents = [];
    let title = "";

    for (const raw of String(md || "").split("\n")) {
      const line = raw.replace(/\s+$/, "");
      if (!line.trim()) continue;

      const heading = line.match(HEADING_RE);
      if (heading) {
        if (!title) title = clean(heading[1]);
        continue;
      }

      const bullet = line.match(BULLET_RE);
      if (!bullet) continue;

      const indent = bullet[1].replace(/\t/g, "  ").length;
      const text = clean(bullet[2]);
      if (!text) continue;

      while (indents.length && indent <= indents[indents.length - 1]) {
        indents.pop();
        stack.pop();
      }
      const node = { text, children: [] };
      stack[stack.length - 1].children.push(node);
      indents.push(indent);
      stack.push(node);
    }
    return { title, children: root.children };
  }

  /** Split "Ohm's Law — V = IR" into a label and its supporting detail. */
  const SPLIT_RE = /^(.{2,48}?)\s+(?:[—–]|:)\s+(.{2,})$/;

  /**
   * Work out how a node should be presented:
   *   label   — the bold part
   *   note    — plain supporting text (may be empty)
   *   expr    — a formula in clean symbols (may be empty)
   *   reading — that formula in plain English (may be empty)
   */
  function present(text, allowSplit) {
    // 1. An explicitly delimited formula wins — the prose around it is the label
    const seg = formula.extract(text);
    if (seg) return { label: seg.lead, note: "", expr: seg.expr, reading: seg.reading };

    // 2. "Ohm's Law — V = IR": keep the name, promote the right-hand side
    const m = allowSplit && text.match(SPLIT_RE);
    if (m) {
      const detail = formula.analyse(m[2]);
      return detail
        ? { label: m[1], note: "", ...detail }
        : { label: m[1], note: formula.prettify(m[2]), expr: "", reading: "" };
    }

    // 3. The whole line may be a bare formula
    const whole = formula.analyse(text);
    if (whole) return { label: "", note: "", ...whole };

    return { label: formula.prettify(text), note: "", expr: "", reading: "" };
  }

  function countLeaves(node) {
    if (!node.children.length) return 1;
    return node.children.reduce((n, c) => n + countLeaves(c), 0);
  }

  function flatten(node, depth, out) {
    out.push({ node, depth });
    node.children.forEach((c) => flatten(c, depth + 1, out));
    return out;
  }

  // ---------------- Shared node markup ----------------

  function nodeInner(node, depth) {
    const p = present(node.text, depth >= 2);
    let html = "";
    if (p.label) html += `<span class="mm-label">${escapeHtml(p.label)}</span>`;
    if (p.expr) {
      html += `<span class="mm-formula">${escapeHtml(p.expr)}</span>`;
      if (p.reading) html += `<span class="mm-reading">${escapeHtml(p.reading)}</span>`;
    }
    if (p.note) html += `<span class="mm-note">${escapeHtml(p.note)}</span>`;
    return html || `<span class="mm-label">${escapeHtml(node.text)}</span>`;
  }

  function collapseToggle(node, boxEl) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mm-toggle";
    btn.title = "Collapse / expand";
    btn.innerHTML =
      `<span class="mm-chevron">${icon("chevron", 13)}</span>` +
      `<span class="mm-count">${countLeaves(node)}</span>`;
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      boxEl.parentElement.classList.toggle("collapsed");
    });
    return btn;
  }

  // ---------------- Layout: branch tree ----------------

  function layoutTree(tree, rootTitle) {
    const canvas = el("div", "mm-canvas lay-tree");
    canvas.appendChild(hub(tree, rootTitle));
    canvas.appendChild(treeList(tree.children, 1));
    return canvas;
  }

  function treeList(nodes, depth) {
    const ul = el("ul", "mm-kids");
    nodes.forEach((node, i) => {
      const li = el("li", "mm-item");
      li.style.setProperty("--i", Math.min(i, 14));
      if (depth === 1) li.style.setProperty("--h", HUES[i % HUES.length]);

      const box = el("div", `mm-node mm-l${depth}`);
      box.innerHTML = nodeInner(node, depth);
      if (node.children.length) {
        box.appendChild(collapseToggle(node, box));
        box.addEventListener("click", () => li.classList.toggle("collapsed"));
      }
      li.appendChild(box);
      if (node.children.length) li.appendChild(treeList(node.children, depth + 1));
      ul.appendChild(li);
    });
    return ul;
  }

  // ---------------- Layout: flow chart ----------------

  function layoutFlow(tree, rootTitle) {
    const wrap = el("div", "mm-canvas lay-flow");
    wrap.appendChild(hub(tree, rootTitle));

    tree.children.forEach((branch, i) => {
      const step = el("div", "mm-step");
      step.style.setProperty("--h", HUES[i % HUES.length]);
      step.style.setProperty("--i", Math.min(i, 14));

      const head = el("div", "mm-step-head");
      head.innerHTML =
        `<span class="mm-step-num">${i + 1}</span>` + nodeInner(branch, 1);
      step.appendChild(head);

      if (branch.children.length) {
        const body = el("div", "mm-step-body");
        branch.children.forEach((child) => {
          const chip = el("div", "mm-step-item");
          chip.innerHTML = nodeInner(child, 2);
          if (child.children.length) {
            const subs = el("div", "mm-substack");
            child.children.forEach((g) => {
              const s = el("span", "mm-subchip");
              s.innerHTML = nodeInner(g, 3);
              subs.appendChild(s);
            });
            chip.appendChild(subs);
          }
          body.appendChild(chip);
        });
        step.appendChild(body);
      }
      wrap.appendChild(step);
    });
    return wrap;
  }

  // ---------------- Layout: revision cards ----------------

  function layoutCards(tree, rootTitle) {
    const wrap = el("div", "mm-canvas lay-cards");
    wrap.appendChild(hub(tree, rootTitle));

    const grid = el("div", "mm-grid");
    tree.children.forEach((branch, i) => {
      const card = el("article", "mm-card");
      card.style.setProperty("--h", HUES[i % HUES.length]);
      card.style.setProperty("--i", Math.min(i, 14));

      const head = el("header", "mm-card-head");
      head.innerHTML = nodeInner(branch, 1);
      card.appendChild(head);

      const list = el("ul", "mm-card-list");
      branch.children.forEach((child) => {
        const li = el("li");
        li.innerHTML = nodeInner(child, 2);
        if (child.children.length) {
          const subs = el("div", "mm-substack");
          child.children.forEach((g) => {
            const s = el("span", "mm-subchip");
            s.innerHTML = nodeInner(g, 3);
            subs.appendChild(s);
          });
          li.appendChild(subs);
        }
        list.appendChild(li);
      });
      card.appendChild(list);
      grid.appendChild(card);
    });
    wrap.appendChild(grid);
    return wrap;
  }

  // ---------------- Layout: radial wheel ----------------

  function layoutRadial(tree, rootTitle) {
    const wrap = el("div", "mm-canvas lay-radial");
    const wheel = el("div", "mm-wheel");

    const centre = hub(tree, rootTitle);
    centre.classList.add("mm-wheel-hub");
    wheel.appendChild(centre);

    const detail = el("div", "mm-detail");
    const spokes = [];

    tree.children.forEach((branch, i) => {
      const angle = (-90 + (360 / tree.children.length) * i) * (Math.PI / 180);
      const spoke = el("button", "mm-spoke");
      spoke.type = "button";
      spoke.style.setProperty("--h", HUES[i % HUES.length]);
      spoke.style.setProperty("--x", `calc(var(--wheel-r) * ${Math.cos(angle).toFixed(4)})`);
      spoke.style.setProperty("--y", `calc(var(--wheel-r) * ${Math.sin(angle).toFixed(4)})`);
      spoke.style.setProperty("--i", Math.min(i, 14));
      spoke.innerHTML = nodeInner(branch, 1);
      spoke.addEventListener("click", () => select(i));
      wheel.appendChild(spoke);
      spokes.push(spoke);

      // A line from the hub out to this spoke
      const ray = el("span", "mm-ray");
      ray.style.setProperty("--h", HUES[i % HUES.length]);
      ray.style.setProperty("--deg", `${(-90 + (360 / tree.children.length) * i)}deg`);
      wheel.insertBefore(ray, centre);
    });

    function select(i) {
      spokes.forEach((s, n) => s.classList.toggle("current", n === i));
      const branch = tree.children[i];
      detail.style.setProperty("--h", HUES[i % HUES.length]);
      detail.innerHTML = `<h3 class="mm-detail-head">${nodeInner(branch, 1)}</h3>`;
      const list = el("ul", "mm-card-list");
      branch.children.forEach((child) => {
        const li = el("li");
        li.innerHTML = nodeInner(child, 2);
        if (child.children.length) {
          const subs = el("div", "mm-substack");
          child.children.forEach((g) => {
            const s = el("span", "mm-subchip");
            s.innerHTML = nodeInner(g, 3);
            subs.appendChild(s);
          });
          li.appendChild(subs);
        }
        list.appendChild(li);
      });
      if (!branch.children.length) {
        list.innerHTML = '<li class="empty-hint">No sub-points for this branch.</li>';
      }
      detail.appendChild(list);
    }

    wrap.append(wheel, detail);
    select(0);
    return wrap;
  }

  // ---------------- Layout: timeline ----------------

  function layoutTimeline(tree, rootTitle) {
    const wrap = el("div", "mm-canvas lay-timeline");
    wrap.appendChild(hub(tree, rootTitle));

    const line = el("div", "mm-timeline");
    tree.children.forEach((branch, i) => {
      const row = el("div", `mm-tl-row ${i % 2 ? "right" : "left"}`);
      row.style.setProperty("--h", HUES[i % HUES.length]);
      row.style.setProperty("--i", Math.min(i, 14));

      const card = el("div", "mm-tl-card");
      const head = el("div", "mm-tl-head");
      head.innerHTML = nodeInner(branch, 1);
      card.appendChild(head);

      if (branch.children.length) {
        const list = el("ul", "mm-card-list");
        branch.children.forEach((child) => {
          const li = el("li");
          li.innerHTML = nodeInner(child, 2);
          list.appendChild(li);
        });
        card.appendChild(list);
      }
      row.append(el("span", "mm-tl-dot"), card);
      line.appendChild(row);
    });
    wrap.appendChild(line);
    return wrap;
  }

  // ---------------- Small helpers ----------------

  function el(tag, cls) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    return node;
  }

  function hub(tree, rootTitle) {
    const root = el("div", "mm-root");
    root.innerHTML =
      `<span class="mm-root-label">${escapeHtml(tree.title || rootTitle || "Mind map")}</span>` +
      `<span class="mm-root-sub">${tree.children.length} branches</span>`;
    return root;
  }

  const LAYOUTS = {
    tree: { label: "Branch tree", icon: "mindmap", render: layoutTree },
    flow: { label: "Flow chart", icon: "flow", render: layoutFlow },
    cards: { label: "Cards", icon: "cards", render: layoutCards },
    radial: { label: "Wheel", icon: "compass", render: layoutRadial },
    timeline: { label: "Timeline", icon: "clock", render: layoutTimeline },
  };

  // ---------------- Export ----------------

  const EX = {
    pad: 46, colGap: 48, rowGap: 16, lineGap: 5,
    widths: [230, 235, 250, 250],
    sizes: [18, 16, 14, 13],
    padX: [18, 15, 13, 12],
    padY: [13, 11, 9, 8],
  };

  const at = (arr, d) => arr[Math.min(d, arr.length - 1)];
  const fontFor = (d) => `${d <= 1 ? 700 : 500} ${at(EX.sizes, d)}px "Segoe UI", system-ui, sans-serif`;

  function wrapText(ctx, text, maxWidth) {
    const words = text.split(/\s+/);
    const lines = [];
    let line = "";
    for (const w of words) {
      const attempt = line ? `${line} ${w}` : w;
      if (ctx.measureText(attempt).width <= maxWidth || !line) line = attempt;
      else { lines.push(line); line = w; }
    }
    if (line) lines.push(line);
    return lines.slice(0, 4);
  }

  /** Measure + place every node. Mutates the tree with _x/_y/_w/_h. */
  function layoutForExport(ctx, node, depth) {
    const p = present(node.text, depth >= 2);
    node._text = [p.label, p.expr, p.note].filter(Boolean).join(p.label && p.expr ? "  " : " ")
      || node.text;

    ctx.font = fontFor(depth);
    const maxW = at(EX.widths, depth);
    node._lines = wrapText(ctx, node._text, maxW - at(EX.padX, depth) * 2);
    node._w = Math.min(
      maxW,
      Math.max(...node._lines.map((l) => ctx.measureText(l).width)) + at(EX.padX, depth) * 2
    );
    node._lineH = at(EX.sizes, depth) + EX.lineGap;
    node._h = node._lines.length * node._lineH + at(EX.padY, depth) * 2;

    node.children.forEach((c) => layoutForExport(ctx, c, depth + 1));
    node._childH = node.children.reduce(
      (sum, c, i) => sum + c._blockH + (i ? EX.rowGap : 0), 0
    );
    node._blockH = Math.max(node._h, node._childH);
    return node;
  }

  function placeForExport(node, x, top, depth) {
    node._x = x;
    node._y = top + (node._blockH - node._h) / 2;
    node._depth = depth;
    let y = top + (node._blockH - node._childH) / 2;
    const cx = x + node._w + EX.colGap;
    node.children.forEach((c) => {
      placeForExport(c, cx, y, depth + 1);
      y += c._blockH + EX.rowGap;
    });
  }

  function paintTree(tree, rootTitle) {
    const probe = document.createElement("canvas").getContext("2d");
    const root = { text: tree.title || rootTitle || "Mind map", children: tree.children };
    layoutForExport(probe, root, 0);
    placeForExport(root, EX.pad, EX.pad, 0);

    const all = flatten(root, 0, []);
    const width = Math.max(...all.map((n) => n.node._x + n.node._w)) + EX.pad;
    const height = root._blockH + EX.pad * 2;

    // Branch hue, inherited by every descendant
    root.children.forEach((b, i) => {
      const h = HUES[i % HUES.length];
      flatten(b, 1, []).forEach(({ node }) => (node._hue = h));
    });
    return { root, all, width, height };
  }

  const roundRect = (ctx, x, y, w, h, r) => {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  };

  function drawToCanvas(tree, rootTitle, theme) {
    const { root, all, width, height } = paintTree(tree, rootTitle);
    const dpr = 2;
    const cv = document.createElement("canvas");
    cv.width = width * dpr;
    cv.height = height * dpr;
    const ctx = cv.getContext("2d");
    ctx.scale(dpr, dpr);

    const dark = theme === "dark";
    const paper = dark ? "#12151f" : "#ffffff";
    const ink = dark ? "#e8ebf2" : "#17203a";
    const cardBg = dark ? "#1c212e" : "#f7f9fe";
    const cardLine = dark ? "#2a3040" : "#dde4f2";
    const light = dark ? 62 : 46;

    ctx.fillStyle = paper;
    ctx.fillRect(0, 0, width, height);

    // Connectors first so boxes sit on top
    ctx.lineWidth = 2;
    for (const { node } of all) {
      for (const child of node.children) {
        ctx.strokeStyle = child._hue === undefined
          ? cardLine
          : `hsl(${child._hue} 70% ${light}%)`;
        const x1 = node._x + node._w;
        const y1 = node._y + node._h / 2;
        const x2 = child._x;
        const y2 = child._y + child._h / 2;
        const mid = (x1 + x2) / 2;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.bezierCurveTo(mid, y1, mid, y2, x2, y2);
        ctx.stroke();
      }
    }

    for (const { node, depth } of all) {
      const hue = node._hue;
      const accent = hue === undefined ? null : `hsl(${hue} 70% ${light}%)`;

      if (depth === 0) {
        const grad = ctx.createLinearGradient(node._x, node._y, node._x + node._w, node._y + node._h);
        grad.addColorStop(0, "#5b8cff");
        grad.addColorStop(1, "#7c5bff");
        ctx.fillStyle = grad;
        roundRect(ctx, node._x, node._y, node._w, node._h, node._h / 2);
        ctx.fill();
        ctx.fillStyle = "#ffffff";
      } else if (depth === 1) {
        ctx.fillStyle = accent;
        roundRect(ctx, node._x, node._y, node._w, node._h, node._h / 2);
        ctx.fill();
        ctx.fillStyle = dark ? "#10131c" : "#ffffff";
      } else {
        ctx.fillStyle = cardBg;
        roundRect(ctx, node._x, node._y, node._w, node._h, 10);
        ctx.fill();
        ctx.strokeStyle = cardLine;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.fillStyle = accent;
        roundRect(ctx, node._x, node._y, 3, node._h, 1.5);
        ctx.fill();
        ctx.fillStyle = ink;
      }

      ctx.font = fontFor(depth);
      ctx.textBaseline = "top";
      const tx = node._x + at(EX.padX, depth);
      let ty = node._y + at(EX.padY, depth);
      for (const line of node._lines) {
        ctx.fillText(line, tx, ty);
        ty += node._lineH;
      }
    }
    return cv;
  }

  function drawToSvg(tree, rootTitle, theme) {
    const { all, width, height } = paintTree(tree, rootTitle);
    const dark = theme === "dark";
    const paper = dark ? "#12151f" : "#ffffff";
    const ink = dark ? "#e8ebf2" : "#17203a";
    const cardBg = dark ? "#1c212e" : "#f7f9fe";
    const cardLine = dark ? "#2a3040" : "#dde4f2";
    const light = dark ? 62 : 46;
    const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

    let paths = "";
    let boxes = "";
    for (const { node, depth } of all) {
      for (const child of node.children) {
        const stroke = child._hue === undefined ? cardLine : `hsl(${child._hue} 70% ${light}%)`;
        const x1 = node._x + node._w, y1 = node._y + node._h / 2;
        const x2 = child._x, y2 = child._y + child._h / 2;
        const mid = (x1 + x2) / 2;
        paths += `<path d="M${x1} ${y1} C${mid} ${y1} ${mid} ${y2} ${x2} ${y2}" `
              + `fill="none" stroke="${stroke}" stroke-width="2"/>`;
      }

      const accent = node._hue === undefined ? "#5b8cff" : `hsl(${node._hue} 70% ${light}%)`;
      const r = depth <= 1 ? node._h / 2 : 10;
      let fill = cardBg, textFill = ink, extra = `stroke="${cardLine}"`;
      if (depth === 0) { fill = "url(#hub)"; textFill = "#fff"; extra = ""; }
      else if (depth === 1) { fill = accent; textFill = dark ? "#10131c" : "#fff"; extra = ""; }

      boxes += `<rect x="${node._x}" y="${node._y}" width="${node._w}" height="${node._h}" `
             + `rx="${r}" fill="${fill}" ${extra}/>`;
      if (depth >= 2) {
        boxes += `<rect x="${node._x}" y="${node._y}" width="3" height="${node._h}" rx="1.5" fill="${accent}"/>`;
      }
      let ty = node._y + at(EX.padY, depth) + at(EX.sizes, depth) * 0.85;
      for (const line of node._lines) {
        boxes += `<text x="${node._x + at(EX.padX, depth)}" y="${ty.toFixed(1)}" fill="${textFill}" `
               + `font-family="Segoe UI, system-ui, sans-serif" font-size="${at(EX.sizes, depth)}" `
               + `font-weight="${depth <= 1 ? 700 : 500}">${esc(line)}</text>`;
        ty += node._lineH;
      }
    }

    return `<svg xmlns="http://www.w3.org/2000/svg" width="${Math.round(width)}" `
         + `height="${Math.round(height)}" viewBox="0 0 ${Math.round(width)} ${Math.round(height)}">`
         + `<defs><linearGradient id="hub" x1="0" y1="0" x2="1" y2="1">`
         + `<stop offset="0" stop-color="#5b8cff"/><stop offset="1" stop-color="#7c5bff"/>`
         + `</linearGradient></defs>`
         + `<rect width="100%" height="100%" fill="${paper}"/>${paths}${boxes}</svg>`;
  }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ---------------- Public build ----------------

  function build(markdown, rootTitle) {
    const tree = parseOutline(markdown);
    if (!tree.children.length) return null;

    const safeName = (tree.title || rootTitle || "mind-map")
      .replace(/[\\/:*?"<>|]+/g, " ").trim().replace(/\s+/g, "-").slice(0, 60) || "mind-map";

    const wrap = el("div", "mm-wrap");
    const bar = el("div", "mm-toolbar");

    // Layout picker
    const picker = el("div", "mm-picker");
    let current = "tree";
    const stage = el("div", "mm-stage");

    const draw = (name) => {
      current = name;
      stage.innerHTML = "";
      stage.appendChild(LAYOUTS[name].render(tree, rootTitle));
      picker.querySelectorAll("button").forEach((b) =>
        b.classList.toggle("current", b.dataset.layout === name)
      );
      foldBtns.forEach((b) => (b.disabled = name !== "tree"));
    };

    Object.entries(LAYOUTS).forEach(([name, def]) => {
      const b = el("button", "mm-chip");
      b.type = "button";
      b.dataset.layout = name;
      b.innerHTML = `${icon(def.icon, 15)}<span>${def.label}</span>`;
      b.addEventListener("click", () => draw(name));
      picker.appendChild(b);
    });

    const mkBtn = (iconName, text, cls = "mm-btn") => {
      const b = el("button", cls);
      b.type = "button";
      b.innerHTML = `${icon(iconName, 15)}<span>${text}</span>`;
      return b;
    };

    const expandBtn = mkBtn("expand", "Expand");
    const collapseBtn = mkBtn("collapse", "Collapse");
    const foldBtns = [expandBtn, collapseBtn];

    // Download menu
    const dl = el("div", "mm-dl");
    const dlBtn = mkBtn("download", "Download");
    const menu = el("div", "mm-dl-menu");
    const mkItem = (label, run) => {
      const b = el("button", "mm-dl-item");
      b.type = "button";
      b.textContent = label;
      b.addEventListener("click", () => { menu.classList.remove("open"); run(); });
      return b;
    };
    const theme = () => document.documentElement.getAttribute("data-theme") || "dark";

    menu.append(
      mkItem("PNG image", () => {
        drawToCanvas(tree, rootTitle, theme()).toBlob((blob) => {
          saveBlob(blob, `${safeName}-mindmap.png`);
          toast("🖼 Mind map saved as PNG");
        }, "image/png");
      }),
      mkItem("SVG vector", () => {
        saveBlob(new Blob([drawToSvg(tree, rootTitle, theme())], { type: "image/svg+xml" }),
                 `${safeName}-mindmap.svg`);
        toast("🖼 Mind map saved as SVG");
      }),
      mkItem("Markdown outline", () => {
        saveBlob(new Blob([markdown], { type: "text/markdown" }), `${safeName}-mindmap.md`);
        toast("📄 Outline saved");
      })
    );
    dlBtn.addEventListener("click", (e) => { e.stopPropagation(); menu.classList.toggle("open"); });
    document.addEventListener("click", () => menu.classList.remove("open"));
    dl.append(dlBtn, menu);

    const textBtn = mkBtn("summary", "Outline");
    bar.append(picker, expandBtn, collapseBtn, dl, textBtn);

    const outline = el("div", "markdown mm-outline");
    outline.hidden = true;
    outline.innerHTML = window.Padhai.renderMarkdown(markdown);

    wrap.append(bar, stage, outline);
    draw("tree");

    expandBtn.addEventListener("click", () =>
      stage.querySelectorAll(".mm-item").forEach((li) => li.classList.remove("collapsed"))
    );
    collapseBtn.addEventListener("click", () =>
      // Keep the first ring open so the map never collapses into nothing
      stage.querySelectorAll(".mm-item").forEach((li) => {
        if (li.parentElement.parentElement?.classList.contains("mm-item")) {
          li.classList.add("collapsed");
        }
      })
    );
    textBtn.addEventListener("click", () => {
      const toText = !stage.hidden;
      stage.hidden = toText;
      outline.hidden = !toText;
      picker.querySelectorAll("button").forEach((b) => (b.disabled = toText));
      expandBtn.disabled = collapseBtn.disabled = toText || current !== "tree";
      textBtn.querySelector("span").textContent = toText ? "Map" : "Outline";
    });

    return wrap;
  }

  window.Padhai.mindmap = { build };
})();
