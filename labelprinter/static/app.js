"use strict";
const $ = (id) => document.getElementById(id);
const TEXT_FIELDS = ["sku", "artist", "title", "format", "year", "genre"];
const BLANK_OK = ["year", "genre"];   // flagged amber when empty

let rows = [];            // {sku, artist, title, format, year, genre, price, copies}
let selected = -1;
let enrichQueue = [];
let enriching = false;
let previewTimer = null;
let printedThisSession = false;
let design = null;        // the working design (an object): what the preview shows and what prints

function note(text, isError) {
  const el = $("msg");
  el.textContent = text;
  el.classList.toggle("error", !!isError);
  el.hidden = !text;
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

function updateTotal() {
  const labels = rows.reduce((n, r) => n + r.copies, 0);
  $("total").textContent = rows.length ? rows.length + " rows, " + labels + " labels" : "";
  $("empty").hidden = rows.length > 0;
}

function markEmpty(input, field, value) {
  input.classList.toggle("empty", BLANK_OK.includes(field) && !String(value).trim());
}

function buildRow(row, i) {
  const tr = document.createElement("tr");
  tr.dataset.i = i;
  const cell = (field, cls) => {
    const td = document.createElement("td");
    const input = document.createElement("input");
    input.dataset.field = field;
    input.value = row[field];
    if (cls) input.className = cls;
    if (field === "price" || field === "copies") { input.inputMode = "numeric"; input.classList.add("num"); }
    markEmpty(input, field, row[field]);
    input.addEventListener("focus", () => select(i));
    input.addEventListener("input", () => onEdit(i, field, input));
    td.appendChild(input);
    tr.appendChild(td);
  };
  cell("sku", "sku");
  ["artist", "title", "format", "year", "genre", "price", "copies"].forEach((f) => cell(f));
  const td = document.createElement("td");
  const del = document.createElement("button");
  del.type = "button"; del.className = "ghost"; del.textContent = "Remove";
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
    markEmpty(input, field, rows[i][field]);
  });
}

function highlight() {
  document.querySelectorAll("#rows tbody tr").forEach((tr) => tr.classList.toggle("sel", Number(tr.dataset.i) === selected));
}

function onEdit(i, field, input) {
  if (field === "price") rows[i].price = parseInt(input.value.replace(/\D/g, ""), 10) || 0;
  else if (field === "copies") rows[i].copies = Math.max(1, Math.min(200, parseInt(input.value, 10) || 1));
  else if (field === "format") rows[i].format = input.value.toUpperCase();
  else rows[i][field] = input.value;
  markEmpty(input, field, input.value);
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

function schedulePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(loadPreview, 250);
}

async function loadPreview() {
  const img = $("previewImg"), noteEl = $("previewNote"), notes = $("designNotes");
  if (selected < 0 || !rows[selected] || !design) {
    img.hidden = true; noteEl.hidden = false; noteEl.textContent = "Click a row to preview it. The preview is the exact print.";
    notes.hidden = true;
    return;
  }
  try {
    const res = await postJson("/api/label.png", { label: rows[selected], design });
    const blob = await res.blob();
    const old = img.dataset.url;
    img.dataset.url = URL.createObjectURL(blob);
    img.src = img.dataset.url;
    img.hidden = false;
    noteEl.hidden = true;
    const warn = res.headers.get("X-Label-Notes") || "";
    notes.textContent = warn;
    notes.hidden = !warn;
    if (old) URL.revokeObjectURL(old);
  } catch (e) {
    img.hidden = true; noteEl.hidden = false; noteEl.textContent = e.message; notes.hidden = true;
  }
}

function addRows(labels, fromDealpos) {
  let added = 0;
  for (const l of labels) {
    if (rows.some((r) => r.sku.toLowerCase() === l.sku.toLowerCase())) continue;
    const row = { sku: l.sku, artist: l.artist, title: l.title, format: l.format, year: l.year, genre: l.genre, price: l.price, copies: l.copies || 1 };
    rows.push(row);
    if (fromDealpos && (!row.year || !row.genre)) enrichQueue.push(row.sku);
    added++;
  }
  renderRows();
  if (selected < 0 && rows.length) { selected = 0; highlight(); schedulePreview(); }
  runEnrich();
  return added;
}

async function runEnrich() {
  if (enriching) return;
  enriching = true;
  while (enrichQueue.length) {
    const sku = enrichQueue.shift();
    const i = rows.findIndex((r) => r.sku === sku);
    if (i < 0) continue;
    try {
      const res = await (await postJson("/api/enrich", { sku })).json();
      if (res.error) note("Could not read year and genre for " + sku + ": " + res.error, true);
      if (!rows[i].year && res.year) rows[i].year = res.year;
      if (!rows[i].genre && res.genre) rows[i].genre = res.genre;
    } catch (e) { note(e.message, true); }
    refreshRow(i);
    if (i === selected) schedulePreview();
  }
  enriching = false;
}

async function addCodes() {
  const text = $("codes").value.trim();
  if (!text) return;
  try {
    const data = await (await postJson("/api/resolve", { text })).json();
    const added = addRows(data.labels, true);
    $("codes").value = "";
    note(added + " added." + (data.missing.length ? " Not found: " + data.missing.join(", ") : ""), data.missing.length > 0);
  } catch (e) { note(e.message, true); }
}

let searchTimer = null;
function onSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const q = $("q").value.trim();
    const list = $("results");
    list.replaceChildren();
    if (q.length < 2) return;
    try {
      const data = await (await api("/api/search?q=" + encodeURIComponent(q))).json();
      for (const l of data.labels) {
        const li = document.createElement("li");
        li.tabIndex = 0;
        li.textContent = [l.artist, l.title].filter(Boolean).join(" - ") + "  ·  " + l.format + "  ·  " + l.sku;
        const pick = () => { addRows([l], true); note("Added " + l.sku + "."); };
        li.addEventListener("click", pick);
        li.addEventListener("keydown", (ev) => { if (ev.key === "Enter") pick(); });
        list.appendChild(li);
      }
      if (!data.labels.length) { const li = document.createElement("li"); li.textContent = "No match."; list.appendChild(li); }
    } catch (e) { note(e.message, true); }
  }, 300);
}

async function uploadSheet() {
  const file = $("sheet").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    const data = await (await api("/api/sheet", { method: "POST", body: form })).json();
    const added = addRows(data.labels, false);
    note(added + " rows added from " + data.sheet + ".");
  } catch (e) { note(e.message, true); }
  $("sheet").value = "";
}

function validRows() {
  if (!rows.length) { note("Add at least one label first.", true); return null; }
  return rows;
}

async function download(path, filename) {
  const labels = validRows();
  if (!labels) return;
  try {
    const blob = await (await postJson(path, { labels, design })).blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    note("Downloaded " + filename + ".");
  } catch (e) { note(e.message, true); }
}

async function downloadGet(path, filename) {
  try {
    const blob = await (await api(path)).blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    note("Downloaded " + filename + ". Print it from the iPhone app, then scan labels A, B and C.");
  } catch (e) { note(e.message, true); }
}

async function printUsb() {
  const labels = validRows();
  if (!labels) return;
  const first = !printedThisSession;
  const send = first ? [Object.assign({}, labels[0], { copies: 1 })] : labels;
  const count = send.reduce((n, l) => n + l.copies, 0);
  const ask = first ? "First print of this session: 1 label only, to check size and direction. Print it?" : "Print " + count + " labels?";
  if (!confirm(ask)) return;
  try {
    const bytes = new Uint8Array(await (await postJson("/api/labels.tspl", { labels: send, design })).arrayBuffer());
    await UsbPrinter.send(bytes);
    printedThisSession = true;
    note(first ? "Printed 1 label. Check it, then press Print over USB again for the rest." : "Sent " + count + " labels to the printer.");
  } catch (e) { note(e.message, true); }
}

async function usbTest() {
  if (!confirm("Print the 2 test labels (orientation, then barcode scan test)?")) return;
  try {
    const bytes = new Uint8Array(await (await api("/api/test.tspl")).arrayBuffer());
    await UsbPrinter.send(bytes);
    note("2 test labels sent. On the first, the thick bar must be on the left and the TOP arrow at the top. On the second, scan A, B and C.");
  } catch (e) { note(e.message, true); }
}

async function loadStatus() {
  try {
    const s = await (await api("/api/status")).json();
    $("status").textContent = s.products ? s.products + " products from DealPOS (read " + Math.round(s.age_seconds / 60) + " min ago)" : "DealPOS not read yet";
  } catch (e) { $("status").textContent = e.message; }
}

$("addCodes").addEventListener("click", addCodes);
$("codes").addEventListener("keydown", (ev) => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) addCodes(); });
$("q").addEventListener("input", onSearch);
$("sheet").addEventListener("change", uploadSheet);
$("pdf").addEventListener("click", () => download("/api/labels.pdf", "mf-labels.pdf"));
$("xlsx").addEventListener("click", () => download("/api/labels.xlsx", "mf-labels.xlsx"));
$("testPdf").addEventListener("click", () => downloadGet("/api/test.pdf", "mf-test-labels.pdf"));
$("refresh").addEventListener("click", async () => {
  note("Reading DealPOS…");
  try { await postJson("/api/refresh", {}); await loadStatus(); note("Catalog refreshed."); } catch (e) { note(e.message, true); }
});
if (UsbPrinter.supported()) {
  $("usb").hidden = false; $("usbTest").hidden = false;
  $("usb").addEventListener("click", printUsb);
  $("usbTest").addEventListener("click", usbTest);
}
updateTotal();
loadStatus();
