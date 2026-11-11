"use strict";
const $ = (id) => document.getElementById(id);
const BLANK_OK = ["year", "genre"];   // flagged amber when empty
const COLUMN_LABELS = { sku: "SKU", artist: "Artist", title: "Title", format: "Format", year: "Year", genre: "Genre", price: "Price", copies: "Copies" };
const EMPTY_PREVIEW = "Click or tap a row to preview it. The preview is the exact print.";
const SEARCH_IDLE = "Type two or more letters, then pick a result.";
const THEME_KEY = "mf-theme";

let rows = [];            // {sku, artist, title, format, year, genre, price, copies}
let selected = -1;
let enrichQueue = [];
const pending = new Set();   // SKUs whose year and genre are queued or being read
let enriching = false;
let enrichTotal = 0;      // year and genre lookups queued in this run, and how many are finished
let enrichDone = 0;
let previewTimer = null;
let printedThisSession = false;
let design = null;        // the working design (an object): what the preview shows and what prints

// ---- small helpers

function svgIcon(id) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(NS, "use");
  use.setAttribute("href", "#" + id);
  svg.appendChild(use);
  return svg;
}

const plural = (n, word) => n + " " + word + (n === 1 ? "" : "s");

const KIND_ICON = { ok: "i-check", info: "i-info", warn: "i-alert", error: "i-error" };
const KIND_PREFIX = { ok: "", info: "", warn: "Warning: ", error: "Error: " };

// note(text, true) = error; note(text) = done; note(text, "warn" | "info") = the other states.
function note(text, kind) {
  const k = kind === true ? "error" : (kind || "ok");
  const el = $("msg");
  el.hidden = !text;
  if (!text) return;
  el.className = "msg " + k;
  el.querySelector(".msg-icon use").setAttribute("href", "#" + KIND_ICON[k]);
  $("msgKind").textContent = KIND_PREFIX[k];
  $("msgText").textContent = text;
}

async function api(path, options) {
  const res = await fetch(path, options);
  if (res.status === 401) { location.href = "/login"; throw new Error("Signed out"); }
  if (!res.ok) {
    let message = res.statusText;
    try { message = (await res.json()).error || message; } catch (e) { /* not json */ }
    throw new Error(message);
  }
  return res;
}
const postJson = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// Loading state for a button: disabled, its text swapped, restored afterwards.
async function withBusy(button, busyText, work) {
  const label = button.textContent;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = busyText;
  try { return await work(); }
  finally {
    button.textContent = label;
    button.removeAttribute("aria-busy");
    button.disabled = false;
    syncActions();
  }
}

// Downloads and USB print need at least one row; say so instead of leaving them dead.
function syncActions() {
  const none = rows.length === 0;
  for (const id of ["pdf", "xlsx", "usb"]) {
    const button = $(id);
    if (!button.hasAttribute("aria-busy")) button.disabled = none;
  }
  $("actionHint").hidden = !none;
}

function updateTotal() {
  const labels = rows.reduce((n, r) => n + r.copies, 0);
  $("total").textContent = rows.length ? plural(rows.length, "row") + ", " + plural(labels, "label") : "";
  $("empty").hidden = rows.length > 0;
  $("tablePanel").classList.toggle("is-empty", rows.length === 0);
  syncActions();
}

// Amber = missing in DealPOS. A row whose year and genre are still being read is not flagged yet.
function markEmpty(input, field, row) {
  if (!BLANK_OK.includes(field)) return;
  const waiting = pending.has(row.sku);
  input.classList.toggle("empty", !waiting && !String(row[field]).trim());
  input.placeholder = waiting ? "Reading…" : "Missing";
}

// ---- table

function buildRow(row, i) {
  const tr = document.createElement("tr");
  tr.dataset.i = i;
  tr.setAttribute("role", "row");
  const cell = (field, cls) => {
    const td = document.createElement("td");
    td.dataset.col = field;
    td.dataset.label = COLUMN_LABELS[field];
    td.setAttribute("role", "cell");
    const input = document.createElement("input");
    input.dataset.field = field;
    input.value = row[field];
    input.autocomplete = "off";
    input.setAttribute("aria-label", COLUMN_LABELS[field] + ", row " + (i + 1));
    if (cls) input.className = cls;
    if (field === "price" || field === "copies") { input.inputMode = "numeric"; input.classList.add("num"); }
    markEmpty(input, field, row);
    input.addEventListener("focus", () => select(i));
    input.addEventListener("input", () => onEdit(i, field, input));
    td.appendChild(input);
    tr.appendChild(td);
  };
  cell("sku", "sku");
  ["artist", "title", "format", "year", "genre", "price", "copies"].forEach((f) => cell(f));
  const td = document.createElement("td");
  td.dataset.col = "rm";
  td.setAttribute("role", "cell");
  const del = document.createElement("button");
  del.type = "button"; del.className = "ghost iconbtn";
  del.title = "Remove this row";
  del.setAttribute("aria-label", "Remove row " + (i + 1));
  del.appendChild(svgIcon("i-x"));
  del.addEventListener("click", () => removeRow(i));
  td.appendChild(del);
  tr.appendChild(td);
  return tr;
}

function renderRows() {
  const body = document.querySelector("#rows tbody");
  body.replaceChildren(...rows.map(buildRow));
  highlight();
  updateTotal();
}

function refreshRow(i) {   // update values in place so typing is never interrupted
  const tr = document.querySelector('#rows tbody tr[data-i="' + i + '"]');
  if (!tr) return;
  tr.querySelectorAll("input").forEach((input) => {
    const field = input.dataset.field;
    if (document.activeElement !== input) input.value = rows[i][field];
    markEmpty(input, field, rows[i]);
  });
}

function highlight() {
  document.querySelectorAll("#rows tbody tr").forEach((tr) => {
    const on = Number(tr.dataset.i) === selected;
    tr.classList.toggle("sel", on);
    if (on) tr.setAttribute("aria-current", "true"); else tr.removeAttribute("aria-current");
  });
}

function onEdit(i, field, input) {
  if (field === "price") rows[i].price = parseInt(input.value.replace(/\D/g, ""), 10) || 0;
  else if (field === "copies") rows[i].copies = Math.max(1, Math.min(200, parseInt(input.value, 10) || 1));
  else if (field === "format") rows[i].format = input.value.toUpperCase();
  else rows[i][field] = input.value;
  markEmpty(input, field, rows[i]);
  updateTotal();
  if (i === selected) schedulePreview();
}

function select(i) {
  if (selected === i) return;
  selected = i;
  highlight();
  schedulePreview();
}

function removeRow(i) {
  rows.splice(i, 1);
  selected = rows.length ? Math.min(selected, rows.length - 1) : -1;
  renderRows();
  schedulePreview();
}

// ---- preview: empty -> loading (skeleton, then dimmed image while it reloads) -> ready | error

function setPlate(state) {
  $("plate").dataset.state = state;
  $("plate").setAttribute("aria-busy", state === "loading" ? "true" : "false");
}

function showLoading() {
  setPlate("loading");
  if ($("previewImg").hidden) { $("skeleton").hidden = false; $("previewNote").hidden = true; }
}

function schedulePreview() {
  clearTimeout(previewTimer);
  if (selected >= 0 && rows[selected] && design) showLoading();
  previewTimer = setTimeout(loadPreview, 250);
}

async function loadPreview() {
  const img = $("previewImg"), noteEl = $("previewNote"), notes = $("designNotes"), skeleton = $("skeleton"), caption = $("previewCaption");
  if (selected < 0 || !rows[selected] || !design) {
    img.hidden = true; skeleton.hidden = true; caption.hidden = true;
    noteEl.hidden = false; noteEl.className = "plate-note"; noteEl.textContent = EMPTY_PREVIEW;
    notes.hidden = true;
    setPlate("empty");
    return;
  }
  $("plateFrame").style.setProperty("--ratio", design.width_mm + " / " + design.height_mm);
  showLoading();
  try {
    const res = await postJson("/api/label.png", { label: rows[selected], design });
    const blob = await res.blob();
    const old = img.dataset.url;
    img.dataset.url = URL.createObjectURL(blob);
    img.src = img.dataset.url;
    img.alt = "Preview of the label for " + rows[selected].sku;
    img.hidden = false;
    skeleton.hidden = true;
    noteEl.hidden = true;
    caption.textContent = design.width_mm + " x " + design.height_mm + " mm, actual print size ratio";
    caption.hidden = false;
    const warn = res.headers.get("X-Label-Notes") || "";
    const lines = warn.split(" | ").filter(Boolean);
    $("designNotesText").replaceChildren(...lines.map((line) => {
      const span = document.createElement("span");
      span.className = "note-line";
      span.textContent = line;
      return span;
    }));
    notes.hidden = !lines.length;
    if (old) URL.revokeObjectURL(old);
    setPlate("ready");
  } catch (e) {
    img.hidden = true; skeleton.hidden = true; caption.hidden = true;
    noteEl.hidden = false; noteEl.className = "plate-note error"; noteEl.textContent = e.message;
    notes.hidden = true;
    setPlate("error");
  }
}

// ---- adding labels

function addRows(labels, fromDealpos) {
  let added = 0;
  for (const l of labels) {
    if (rows.some((r) => r.sku.toLowerCase() === l.sku.toLowerCase())) continue;
    const row = { sku: l.sku, artist: l.artist, title: l.title, format: l.format, year: l.year, genre: l.genre, price: l.price, copies: l.copies || 1 };
    rows.push(row);
    if (fromDealpos && (!row.year || !row.genre)) { enrichQueue.push(row.sku); pending.add(row.sku); enrichTotal++; }
    added++;
  }
  renderRows();
  if (selected < 0 && rows.length) { selected = 0; highlight(); schedulePreview(); }
  runEnrich();
  return added;
}

function showProgress() {
  $("progress").hidden = enrichTotal === 0;
  if (!enrichTotal) return;
  const current = Math.min(enrichDone + 1, enrichTotal);
  $("progressText").textContent = "Reading year and genre: " + current + " of " + enrichTotal;
  $("progressBar").max = enrichTotal;
  $("progressBar").value = enrichDone;
}

async function runEnrich() {
  if (enriching) return;
  enriching = true;
  while (enrichQueue.length) {
    showProgress();
    const sku = enrichQueue.shift();
    const i = rows.findIndex((r) => r.sku === sku);
    if (i < 0) { pending.delete(sku); enrichDone++; continue; }
    try {
      const res = await (await postJson("/api/enrich", { sku })).json();
      if (res.error) note("Could not read year and genre for " + sku + ": " + res.error, true);
      if (!rows[i].year && res.year) rows[i].year = res.year;
      if (!rows[i].genre && res.genre) rows[i].genre = res.genre;
    } catch (e) { note(e.message, true); }
    pending.delete(sku);
    enrichDone++;
    refreshRow(i);
    if (i === selected) schedulePreview();
  }
  enriching = false;
  enrichTotal = 0; enrichDone = 0;
  showProgress();
}

async function addCodes() {
  const text = $("codes").value.trim();
  if (!text) return;
  await withBusy($("addCodes"), "Adding…", async () => {
    try {
      const data = await (await postJson("/api/resolve", { text })).json();
      const added = addRows(data.labels, true);
      $("codes").value = "";
      note(added + " added." + (data.missing.length ? " Not found: " + data.missing.join(", ") : ""), data.missing.length ? "warn" : "ok");
    } catch (e) { note(e.message, true); }
  });
}

let searchTimer = null;
function onSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const q = $("q").value.trim();
    const list = $("results"), state = $("searchState");
    list.replaceChildren();
    if (q.length < 2) { state.textContent = SEARCH_IDLE; return; }
    state.textContent = "Searching…";
    list.setAttribute("aria-busy", "true");
    try {
      const data = await (await api("/api/search?q=" + encodeURIComponent(q))).json();
      for (const l of data.labels) {
        const li = document.createElement("li");
        const pick = document.createElement("button");
        pick.type = "button"; pick.className = "pick";
        pick.append([l.artist, l.title].filter(Boolean).join(" - "));
        const detail = document.createElement("small");
        detail.textContent = l.format + "  ·  " + l.sku;
        pick.appendChild(detail);
        pick.addEventListener("click", () => { addRows([l], true); note("Added " + l.sku + "."); });
        li.appendChild(pick);
        list.appendChild(li);
      }
      if (!data.labels.length) { const li = document.createElement("li"); li.className = "none"; li.textContent = "No match."; list.appendChild(li); }
      const n = data.labels.length;
      state.textContent = n ? (n === 1 ? "1 match" : n + " matches") + ". Pick one to add it." : "Nothing matches. Try fewer letters.";
    } catch (e) { state.textContent = SEARCH_IDLE; note(e.message, true); }
    list.removeAttribute("aria-busy");
  }, 300);
}

async function uploadSheet() {
  const file = $("sheet").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  note("Reading " + file.name + "…", "info");
  try {
    const data = await (await api("/api/sheet", { method: "POST", body: form })).json();
    const added = addRows(data.labels, false);
    note(added + " rows added from " + data.sheet + ".");
  } catch (e) { note(e.message, true); }
  $("sheet").value = "";
}

// ---- downloads and printing

function validRows() {
  if (!rows.length) { note("Add at least one label first.", true); return null; }
  return rows;
}

function saveBlob(blob, filename) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}

async function download(button, path, filename) {
  const labels = validRows();
  if (!labels) return;
  await withBusy(button, "Preparing…", async () => {
    try {
      const blob = await (await postJson(path, { labels, design })).blob();
      saveBlob(blob, filename);
      note("Downloaded " + filename + ".");
    } catch (e) { note(e.message, true); }
  });
}

async function downloadGet(button, path, filename) {
  await withBusy(button, "Preparing…", async () => {
    try {
      const blob = await (await api(path)).blob();
      saveBlob(blob, filename);
      note("Downloaded " + filename + ". Print it from the iPhone app, then scan labels A, B and C.");
    } catch (e) { note(e.message, true); }
  });
}

async function printUsb() {
  const labels = validRows();
  if (!labels) return;
  const first = !printedThisSession;
  const send = first ? [Object.assign({}, labels[0], { copies: 1 })] : labels;
  const count = send.reduce((n, l) => n + l.copies, 0);
  const ask = first ? "First print of this session: 1 label only, to check size and direction. Print it?" : "Print " + count + " labels?";
  if (!confirm(ask)) return;
  await withBusy($("usb"), "Printing…", async () => {
    try {
      const bytes = new Uint8Array(await (await postJson("/api/labels.tspl", { labels: send, design })).arrayBuffer());
      await UsbPrinter.send(bytes);
      printedThisSession = true;
      note(first ? "Printed 1 label. Check it, then press Print over USB again for the rest." : "Sent " + count + " labels to the printer.");
    } catch (e) { note(e.message, true); }
  });
}

async function usbTest() {
  if (!confirm("Print the 2 test labels (orientation, then barcode scan test)?")) return;
  await withBusy($("usbTest"), "Printing…", async () => {
    try {
      const bytes = new Uint8Array(await (await api("/api/test.tspl")).arrayBuffer());
      await UsbPrinter.send(bytes);
      note("2 test labels sent. On the first, the thick bar must be on the left and the TOP arrow at the top. On the second, scan A, B and C.");
    } catch (e) { note(e.message, true); }
  });
}

async function loadStatus() {
  try {
    const s = await (await api("/api/status")).json();
    $("status").textContent = s.products ? s.products + " products from DealPOS (read " + Math.round(s.age_seconds / 60) + " min ago)" : "DealPOS not read yet";
  } catch (e) { $("status").textContent = e.message; }
}

// ---- theme: dark by default, light on request; the head script applies the saved choice before first paint

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  $("theme").setAttribute("aria-pressed", String(theme === "light"));
}

// ---- wiring

$("addCodes").addEventListener("click", addCodes);
$("codes").addEventListener("keydown", (ev) => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) addCodes(); });
$("q").addEventListener("input", onSearch);
$("sheet").addEventListener("change", uploadSheet);
$("pdf").addEventListener("click", () => download($("pdf"), "/api/labels.pdf", "mf-labels.pdf"));
$("xlsx").addEventListener("click", () => download($("xlsx"), "/api/labels.xlsx", "mf-labels.xlsx"));
$("testPdf").addEventListener("click", () => downloadGet($("testPdf"), "/api/test.pdf", "mf-test-labels.pdf"));
$("refresh").addEventListener("click", () => withBusy($("refresh"), "Refreshing…", async () => {
  note("Reading DealPOS…", "info");
  try { const r = await (await postJson("/api/refresh", {})).json(); await loadStatus(); note(r.refreshed ? "Catalog refreshed." : "Catalog was read less than a minute ago."); } catch (e) { note(e.message, true); }
}));
$("msgClose").addEventListener("click", () => note(""));
$("theme").addEventListener("click", () => {
  const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
  applyTheme(next);
  try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* storage blocked: the choice lasts until reload */ }
});
document.querySelectorAll("#empty .way").forEach((button) => button.addEventListener("click", () => {
  const way = button.dataset.way;
  if (way === "codes") $("codes").focus();
  else if (way === "search") $("q").focus();
  else $("sheet").click();
}));
if (UsbPrinter.supported()) {
  $("usb").hidden = false; $("usbTest").hidden = false;
  $("usb").addEventListener("click", printUsb);
  $("usbTest").addEventListener("click", usbTest);
} else {
  $("actionHint").textContent = "Add a label to turn on the downloads.";
}
applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark");
updateTotal();
loadStatus();
