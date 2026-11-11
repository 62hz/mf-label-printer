"use strict";
// Design editor: pick a design, change its elements with numbers and dropdowns, save under a name.
// Uses globals from app.js: $, api, postJson, note, design (working design), schedulePreview.

const PROPS = {
  text: [["content", "text"], ["font", "fonts"], ["size_pt", "num"], ["min_size_pt", "num"], ["bold", "bool"], ["italic", "bool"],
         ["reverse", "bool"], ["align", ["left", "center", "right"]], ["valign", ["top", "middle"]]],
  barcode: [["content", "text"], ["mode", ["integer", "fit"]]],
  rect: [],
  image: [],
};
const LABELS = { content: "Text", font: "Font", size_pt: "Size (pt)", min_size_pt: "Smallest (pt)", bold: "Bold", italic: "Italic",
                 reverse: "White on black", align: "Align", valign: "Vertical", mode: "Bars", x: "X (mm)", y: "Y (mm)", w: "Width (mm)", h: "Height (mm)" };
const DEFAULTS = {
  text: { type: "text", content: "{artist}", x: 2, y: 2, w: 20, h: 3, font: "arial", size_pt: 6, min_size_pt: 4, bold: false, italic: false, reverse: false, align: "left", valign: "top" },
  barcode: { type: "barcode", content: "{sku}", x: 2, y: 22, w: 22, h: 5, mode: "integer" },
  rect: { type: "rect", x: 2, y: 16, w: 46, h: 0.25 },
  image: { type: "image", src: "logo", x: 30, y: 16, w: 16, h: 10 },
};

let designList = [];
let fonts = [];
let selEl = 0;
let designDirty = false;
let savedSlug = null;

function markDirty() {
  designDirty = true;
  $("dirty").hidden = false;
  schedulePreview();
}

function field(labelText, control) {
  const wrap = document.createElement("div");
  wrap.className = "prop";
  const label = document.createElement("label");
  label.textContent = labelText;
  wrap.append(label, control);
  return wrap;
}

function control(obj, key, kind, onChange) {
  let input;
  if (kind === "text") {
    input = document.createElement("input");
    input.value = obj[key] ?? "";
    input.addEventListener("input", () => { obj[key] = input.value; onChange(); });
  } else if (kind === "num") {
    input = document.createElement("input");
    input.type = "number"; input.step = "0.1"; input.inputMode = "decimal";
    input.value = obj[key];
    input.addEventListener("input", () => { const v = parseFloat(input.value); if (!Number.isNaN(v)) { obj[key] = v; onChange(); } });
  } else if (kind === "bool") {
    input = document.createElement("input");
    input.type = "checkbox"; input.checked = !!obj[key];
    input.addEventListener("change", () => { obj[key] = input.checked; onChange(); });
  } else {
    input = document.createElement("select");
    const options = kind === "fonts" ? fonts : kind;
    for (const o of options) { const opt = document.createElement("option"); opt.value = o; opt.textContent = o; input.appendChild(opt); }
    input.value = obj[key];
    input.addEventListener("change", () => { obj[key] = input.value; onChange(); });
  }
  input.dataset.key = key;
  return input;
}

function renderLabelProps() {
  const box = $("labelProps");
  box.replaceChildren();
  for (const [key, text, kind] of [["width_mm", "Width (mm)", "num"], ["height_mm", "Height (mm)", "num"], ["gap_mm", "Gap (mm)", "num"], ["direction", "Direction", ["0", "1"]]]) {
    const holder = { [key]: key === "direction" ? String(design[key]) : design[key] };
    const ctl = control(holder, key, kind, () => { design[key] = key === "direction" ? Number(holder[key]) : holder[key]; markDirty(); });
    box.appendChild(field(text, ctl));
  }
}

function renderElList() {
  const list = $("elList");
  list.replaceChildren();
  design.elements.forEach((el, i) => {
    const li = document.createElement("li");
    li.className = i === selEl ? "sel" : "";
    const vis = document.createElement("input");
    vis.type = "checkbox"; vis.checked = el.visible !== false; vis.title = "Show";
    vis.addEventListener("change", () => { el.visible = vis.checked; markDirty(); });
    const name = document.createElement("button");
    name.type = "button"; name.className = "ghost elname"; name.textContent = el.id + " · " + el.type;
    name.addEventListener("click", () => { selEl = i; renderElList(); renderProps(); });
    const up = document.createElement("button");
    up.type = "button"; up.className = "ghost mini"; up.textContent = "↑"; up.title = "Draw earlier";
    up.addEventListener("click", () => { if (i > 0) { [design.elements[i - 1], design.elements[i]] = [design.elements[i], design.elements[i - 1]]; selEl = i - 1; renderElList(); markDirty(); } });
    const down = document.createElement("button");
    down.type = "button"; down.className = "ghost mini"; down.textContent = "↓"; down.title = "Draw later";
    down.addEventListener("click", () => { if (i < design.elements.length - 1) { [design.elements[i + 1], design.elements[i]] = [design.elements[i], design.elements[i + 1]]; selEl = i + 1; renderElList(); markDirty(); } });
    li.append(vis, name, up, down);
    list.appendChild(li);
  });
}

function renderProps() {
  const box = $("props");
  box.replaceChildren();
  const el = design.elements[selEl];
  $("propsTitle").textContent = el ? el.id + " (" + el.type + ")" : "No element";
  if (!el) return;
  const onChange = () => markDirty();
  for (const key of ["x", "y", "w", "h"]) box.appendChild(field(LABELS[key], control(el, key, "num", onChange)));
  for (const [key, kind] of PROPS[el.type]) box.appendChild(field(LABELS[key], control(el, key, kind, onChange)));
}

function renderAll() {
  if (selEl >= design.elements.length) selEl = Math.max(0, design.elements.length - 1);
  renderLabelProps(); renderElList(); renderProps();
  $("designDelete").disabled = designList.find((d) => d.slug === savedSlug)?.builtin !== false;
}

function renderSelect() {
  const sel = $("designSel");
  sel.replaceChildren();
  for (const d of designList) {
    const opt = document.createElement("option");
    opt.value = d.slug; opt.textContent = d.name + (d.builtin ? " (built in)" : "");
    sel.appendChild(opt);
  }
  sel.value = savedSlug;
}

async function openDesign(slug) {
  design = await (await api("/api/designs/" + encodeURIComponent(slug))).json();
  savedSlug = slug; designDirty = false; selEl = 0;
  $("dirty").hidden = true;
  renderSelect(); renderAll(); schedulePreview();
}

async function loadDesigns(pick) {
  const data = await (await api("/api/designs")).json();
  designList = data.designs; fonts = data.fonts;
  const slug = [pick, savedSlug, data.default].find((s) => s && designList.some((d) => d.slug === s));
  await openDesign(slug);
}

async function saveDesign(asNew) {
  let name = design.name;
  if (asNew || designList.find((d) => d.slug === savedSlug)?.builtin) {
    name = prompt(asNew ? "Name for the new design:" : "Built-in designs are read-only. Save as:", asNew ? design.name + " copy" : design.name + " copy");
    if (!name) return;
  }
  try {
    const res = await (await postJson("/api/designs", Object.assign({}, design, { name }))).json();
    note("Saved design " + name + ".");
    await loadDesigns(res.slug);
  } catch (e) { note(e.message, true); }
}

$("designSel").addEventListener("change", async (ev) => {
  if (designDirty && !confirm("Discard your unsaved design changes?")) { ev.target.value = savedSlug; return; }
  try { await openDesign(ev.target.value); } catch (e) { note(e.message, true); }
});
$("designSave").addEventListener("click", () => saveDesign(false));
$("designSaveAs").addEventListener("click", () => saveDesign(true));
$("designDelete").addEventListener("click", async () => {
  if (!confirm("Delete the design " + design.name + "?")) return;
  try { await api("/api/designs/" + encodeURIComponent(savedSlug), { method: "DELETE" }); note("Deleted."); await loadDesigns(); } catch (e) { note(e.message, true); }
});
$("elAdd").addEventListener("click", () => {
  const type = $("addType").value;
  let n = design.elements.length + 1;
  while (design.elements.some((e) => e.id === type + "-" + n)) n++;
  design.elements.push(Object.assign({ id: type + "-" + n, visible: true }, DEFAULTS[type]));
  selEl = design.elements.length - 1;
  renderElList(); renderProps(); markDirty();
});
$("elDup").addEventListener("click", () => {
  const el = design.elements[selEl];
  if (!el) return;
  let n = design.elements.length + 1;
  while (design.elements.some((e) => e.id === el.type + "-" + n)) n++;
  design.elements.push(Object.assign(JSON.parse(JSON.stringify(el)), { id: el.type + "-" + n, y: Math.round((el.y + 1) * 100) / 100 }));
  selEl = design.elements.length - 1;
  renderElList(); renderProps(); markDirty();
});
$("elDel").addEventListener("click", () => {
  if (!design.elements.length) return;
  design.elements.splice(selEl, 1);
  selEl = Math.max(0, selEl - 1);
  renderElList(); renderProps(); markDirty();
});

loadDesigns().catch((e) => note(e.message, true));
