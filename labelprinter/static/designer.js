"use strict";
// Design editor: pick a design, change its elements with numbers and dropdowns, save under a name.
// Uses globals from app.js: $, api, postJson, note, design (working design), schedulePreview.

const PROPS = {
  text: [["content", "text"], ["size_pt", "num"], ["min_size_pt", "num"], ["font", "fonts"], ["align", ["left", "center", "right"]], ["valign", ["top", "middle", "baseline"]],
         ["bold", "bool"], ["italic", "bool"], ["reverse", "bool"], ["upper", "bool"], ["lines", ["1", "2", "3"]]],
  barcode: [["content", "text"], ["mode", ["integer", "fit"]], ["rotate", ["0", "90"]]],
  rect: [],
  image: [["src", ["logo", "symbol", "screen-logo"]], ["gives_way", "bool"]],
};
const LABELS = { content: "Text", font: "Font", size_pt: "Size (pt)", min_size_pt: "Smallest (pt)", bold: "Bold", italic: "Italic",
                 reverse: "White on black", upper: "Uppercase", lines: "Lines (wrap)", rotate: "Turn (degrees)", src: "Logo file", gives_way: "Hide if the barcode needs the room", align: "Align", valign: "Vertical", mode: "Bars", x: "X (mm)", y: "Y (mm)", w: "Width (mm)", h: "Height (mm)" };
const DEFAULTS = {
  text: { type: "text", content: "{artist}", x: 2, y: 2, w: 20, h: 3, font: "arial", size_pt: 6, min_size_pt: 4, bold: false, italic: false, reverse: false, upper: false, align: "left", valign: "top" },
  barcode: { type: "barcode", content: "{sku}", x: 2, y: 22, w: 22, h: 5, mode: "integer" },
  rect: { type: "rect", x: 2, y: 16, w: 46, h: 0.25 },
  image: { type: "image", src: "symbol", x: 38, y: 17, w: 9.4, h: 10.4 },
};

let designList = [];
let fonts = [];           // font families from /api/fonts: {key, name, source: bundled|custom|system, styles}
let fontsLoaded = false;
let selEl = 0;
let designDirty = false;
let savedSlug = null;

function markDirty() {
  designDirty = true;
  $("dirty").hidden = false;
  schedulePreview();
}

let fieldSeq = 0;
function field(labelText, control) {   // a label tied to its control (a select for the font picker); a checkbox sits beside its label
  const wrap = document.createElement("div");
  wrap.className = "prop";
  const label = document.createElement("label");
  if (control.matches('input[type="checkbox"]')) {   // the whole label is the click target, at least 44 px tall on touch
    const text = document.createElement("span");
    text.textContent = labelText;
    label.append(control, text);
    wrap.classList.add("prop-check");
    wrap.appendChild(label);
    return wrap;
  }
  label.textContent = labelText;
  const target = control.matches("input, select, textarea") ? control : (control.querySelector("select") || control.querySelector("input"));
  if (target) { target.id = target.id || "prop-" + (++fieldSeq); label.htmlFor = target.id; }
  wrap.append(label, control);
  return wrap;
}

// ---- font picker: a filter box, a select grouped Brand / Your fonts / Installed, add a font file, remove an added one

const FONT_GROUPS = [["bundled", "Brand"], ["custom", "Your fonts"], ["system", "Installed"]];

function fontOption(value, text) {
  const opt = document.createElement("option");
  opt.value = value; opt.textContent = text;
  return opt;
}

function fontMatches(f, query) {
  return !query || f.name.toLowerCase().includes(query) || f.key.includes(query);
}

function fillFontSelect(select, filterText, current) {
  const query = filterText.trim().toLowerCase();
  select.replaceChildren();
  if (!fonts.some((f) => f.key === current)) {   // the design names a font this PC does not have: say so instead of showing another one
    if (fontsLoaded) {
      const group = document.createElement("optgroup");
      group.label = "Not installed here";
      group.appendChild(fontOption(current, current));
      select.appendChild(group);
    } else {
      select.appendChild(fontOption(current, current));
    }
  }
  for (const [source, title] of FONT_GROUPS) {
    const list = fonts.filter((f) => f.source === source && (f.key === current || fontMatches(f, query)));  // the chosen font always stays listed
    if (!list.length) continue;
    const group = document.createElement("optgroup");
    group.label = title;
    for (const f of list) group.appendChild(fontOption(f.key, f.name));
    select.appendChild(group);
  }
  select.value = current;
}

async function loadFonts() {
  fonts = (await (await api("/api/fonts")).json()).fonts;
  fontsLoaded = true;
}

function fontControl(obj, key, onChange) {
  const wrap = document.createElement("div");
  wrap.className = "fontpick";
  const filter = document.createElement("input");
  filter.type = "search"; filter.placeholder = "Filter fonts"; filter.autocomplete = "off";
  filter.setAttribute("aria-label", "Filter fonts"); filter.dataset.role = "font-filter";
  const select = document.createElement("select");
  select.setAttribute("aria-label", "Font"); select.dataset.key = key;
  const remove = document.createElement("button");
  remove.type = "button"; remove.className = "ghost"; remove.textContent = "Remove"; remove.dataset.role = "font-remove";
  remove.title = "Remove this added font";
  const row = document.createElement("div");
  row.className = "fontrow";
  row.append(select, remove);
  const add = document.createElement("button");
  add.type = "button"; add.className = "ghost"; add.textContent = "Add a font file"; add.dataset.role = "font-add";
  const file = document.createElement("input");
  file.type = "file"; file.accept = ".ttf,.otf"; file.hidden = true; file.dataset.role = "font-file";
  const current = () => fonts.find((f) => f.key === obj[key]);
  const sync = () => { remove.hidden = current()?.source !== "custom"; };
  fillFontSelect(select, "", obj[key]);
  sync();

  filter.addEventListener("input", () => fillFontSelect(select, filter.value, obj[key]));
  filter.addEventListener("keydown", (ev) => {      // Enter takes the first match
    if (ev.key !== "Enter") return;
    ev.preventDefault();
    const query = filter.value.trim().toLowerCase();
    const hit = FONT_GROUPS.flatMap(([source]) => fonts.filter((f) => f.source === source && fontMatches(f, query)))[0];
    if (!hit) return;
    obj[key] = hit.key;
    fillFontSelect(select, filter.value, obj[key]);
    sync(); onChange();
  });
  select.addEventListener("change", () => { obj[key] = select.value; sync(); onChange(); });
  add.addEventListener("click", () => file.click());
  file.addEventListener("change", async () => {
    const chosen = file.files[0];
    if (!chosen) return;
    const form = new FormData();
    form.append("file", chosen);
    try {
      const res = await (await api("/api/fonts", { method: "POST", body: form })).json();
      fonts = res.fonts; obj[key] = res.key;
      note("Added the font " + (current()?.name ?? res.key) + ".");
      renderProps(); markDirty();
    } catch (e) { note(e.message, true); }
    file.value = "";
  });
  remove.addEventListener("click", async () => {
    const font = current();
    if (!font || !confirm("Remove the font " + font.name + "? Labels that use it print in Arial until you pick another.")) return;
    try {
      fonts = (await (await api("/api/fonts/" + encodeURIComponent(font.key), { method: "DELETE" })).json()).fonts;
      note("Removed the font " + font.name + ".");
      renderProps(); schedulePreview();
    } catch (e) { note(e.message, true); }
  });
  wrap.append(filter, row, add, file);
  return wrap;
}

function control(obj, key, kind, onChange) {
  let input;
  if (kind === "fonts") return fontControl(obj, key, onChange);
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
    for (const o of kind) { const opt = document.createElement("option"); opt.value = o; opt.textContent = o; input.appendChild(opt); }
    input.value = obj[key];
    input.addEventListener("change", () => { obj[key] = input.value; onChange(); });
  }
  input.dataset.key = key;
  return input;
}

function renderLabelProps() {
  const box = $("labelProps");
  box.replaceChildren();
  for (const [key, text, kind] of [["width_mm", "Width (mm)", "num"], ["height_mm", "Height (mm)", "num"], ["gap_mm", "Gap (mm)", "num"], ["direction", "Direction", ["0", "1"]], ["smooth_text", "Smooth text", "bool"]]) {
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
    vis.type = "checkbox"; vis.checked = el.visible !== false;
    vis.setAttribute("aria-label", "Show " + el.id);
    vis.addEventListener("change", () => { el.visible = vis.checked; markDirty(); });
    const check = document.createElement("label");   // the whole 44 px square toggles the checkbox
    check.className = "check"; check.title = "Show";
    check.appendChild(vis);
    const name = document.createElement("button");
    name.type = "button"; name.className = "ghost elname"; name.textContent = el.id + " · " + el.type;
    if (i === selEl) name.setAttribute("aria-current", "true");
    name.addEventListener("click", () => { selEl = i; renderElList(); renderProps(); });
    const mover = (label, icon, to) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "ghost mini iconbtn"; b.title = label; b.setAttribute("aria-label", label + ": " + el.id);
      b.appendChild(svgIcon(icon));
      b.addEventListener("click", () => {
        if (to < 0 || to >= design.elements.length) return;
        [design.elements[to], design.elements[i]] = [design.elements[i], design.elements[to]];
        selEl = to; renderElList(); markDirty();
      });
      return b;
    };
    li.append(check, name, mover("Draw earlier", "i-up", i - 1), mover("Draw later", "i-down", i + 1));
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
  for (const [key, kind] of PROPS[el.type]) {
    const wrap = field(LABELS[key], control(el, key, kind, onChange));
    if (key === "content" || kind === "fonts") wrap.classList.add("wide");
    box.appendChild(wrap);
  }
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
  designList = data.designs;
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
loadFonts().then(() => { if (design) renderProps(); }).catch((e) => note(e.message, true));   // the list arrives once; again only after an upload or a removal
