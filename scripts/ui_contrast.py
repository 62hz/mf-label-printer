"""Contrast check of the real page in both themes (dev server on port 8795 with the fake DealPOS; the real server is never touched).

For each group of visible elements it reads the computed foreground colour and the nearest opaque background (semi-transparent
layers are composited), then checks the WCAG ratio:
  text and placeholders  >= 4.5, or >= 3.0 for large text (18 px and up, or bold 14 px and up)
  control borders, focus rings, the selected-row outline, message icons  >= 3.0 against the surface they sit on
Prints one line per group (the worst element in it) and exits 1 if anything fails or a group matched nothing.

  uv run python scripts/ui_contrast.py
"""
import sys

from playwright.sync_api import expect, sync_playwright

from ui_common import URL, add_rows, dev_server, sign_in, theme_script

LIB = r"""
window.__cx = (() => {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (css) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#ff00ff'; cx.fillStyle = css; cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (t, b) => { const a = t[3] + b[3] * (1 - t[3]); if (a === 0) return [0, 0, 0, 0];
    return [0, 1, 2].map((i) => (t[i] * t[3] + b[i] * b[3] * (1 - t[3])) / a).concat([a]); };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const [hi, lo] = [lum(a), lum(b)].sort((p, q) => q - p); return (hi + 0.05) / (lo + 0.05); };
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const bgOf = (el) => {
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const c = rgba(getComputedStyle(n).backgroundColor);
      if (c[3] > 0) layers.push(c);
      if (c[3] >= 0.999) break;
    }
    let out = [255, 255, 255, 1];
    if (layers.length && layers[layers.length - 1][3] >= 0.999) out = layers.pop();
    for (let i = layers.length - 1; i >= 0; i--) out = over(layers[i], out);
    return out;
  };
  const opacityOf = (el) => { let o = 1; for (let n = el; n; n = n.parentElement) o *= parseFloat(getComputedStyle(n).opacity); return o; };
  const name = (el) => (el.id ? '#' + el.id : el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/)[0] : '')
    + (el.dataset && el.dataset.field ? '[' + el.dataset.field + ']' : '') + (el.dataset && el.dataset.key ? '[' + el.dataset.key + ']' : ''));
  const hex = (c) => '#' + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  const hasText = (el, pseudo) => {
    if (el.matches('input, textarea')) return pseudo ? !el.value && !!el.placeholder : !!el.value;
    if (el.matches('select')) return !pseudo;
    return !pseudo && Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim()) || (!pseudo && !!el.textContent.trim() && el.children.length > 0);
  };

  // text: foreground vs nearest opaque background; pseudo = '::placeholder'
  function text(sel, pseudo) {
    return Array.from(document.querySelectorAll(sel)).filter((el) => visible(el) && hasText(el, pseudo)).map((el) => {
      const cs = getComputedStyle(el, pseudo || null);
      const c = rgba(cs.color); const bg = bgOf(el);
      const fg = over([c[0], c[1], c[2], c[3] * opacityOf(el) * (pseudo ? parseFloat(cs.opacity) : 1)], bg);
      const px = parseFloat(getComputedStyle(el).fontSize), weight = parseInt(getComputedStyle(el).fontWeight, 10);
      const large = px >= 18 || (px >= 14 && weight >= 700);
      return { el: name(el), fg: hex(fg), bg: hex(bg), ratio: ratio(fg, bg), need: large ? 3 : 4.5 };
    });
  }
  // icons and other ink without text: the colour it is drawn in against the surface behind it
  function ink(sel, need, pseudo) {
    return Array.from(document.querySelectorAll(sel)).filter(visible).map((el) => {
      const c = rgba(getComputedStyle(el, pseudo || null).color); const bg = bgOf(el);
      const fg = over([c[0], c[1], c[2], c[3] * opacityOf(el)], bg);
      return { el: name(el), fg: hex(fg), bg: hex(bg), ratio: ratio(fg, bg), need };
    });
  }
  // border of a control against the surface behind it
  function border(sel) {
    return Array.from(document.querySelectorAll(sel)).filter((el) => visible(el) && parseFloat(getComputedStyle(el).borderTopWidth) > 0).map((el) => {
      const c = rgba(getComputedStyle(el).borderTopColor); const bg = bgOf(el.parentElement);
      const fg = over(c, bg);
      return { el: name(el), fg: hex(fg), bg: hex(bg), ratio: ratio(fg, bg), need: 3 };
    });
  }
  // the focus ring of the element that has focus now
  function focusRing() {
    const el = document.activeElement; const cs = getComputedStyle(el);
    if (cs.outlineStyle === 'none' || parseFloat(cs.outlineWidth) < 2) return [{ el: name(el), fg: 'none', bg: '-', ratio: 0, need: 3 }];
    const off = parseFloat(cs.outlineOffset);
    const bg = bgOf(off >= 0 ? el.parentElement : el);
    const fg = over(rgba(cs.outlineColor), bg);
    return [{ el: name(el), fg: hex(fg), bg: hex(bg), ratio: ratio(fg, bg), need: 3 }];
  }
  function outline(sel) {   // selected row outline, message icon colour: a stroke against the fill beside it
    return Array.from(document.querySelectorAll(sel)).filter(visible).map((el) => {
      const cs = getComputedStyle(el);
      const colour = cs.outlineStyle !== 'none' ? cs.outlineColor : cs.color;
      const bg = bgOf(el.matches('.msg-icon') ? el.parentElement : el.parentElement);
      const fg = over(rgba(colour), bg);
      return { el: name(el), fg: hex(fg), bg: hex(bg), ratio: ratio(fg, bg), need: 3 };
    });
  }
  return { text, ink, border, focusRing, outline };
})();
"""

results = []   # (theme, area, check, worst row or None)
failures = []


def record(theme, area, check, rows):
    if not rows:
        failures.append(f"{theme}: {area} / {check}: matched nothing")
        results.append((theme, area, check, None))
        return
    worst = min(rows, key=lambda r: r["ratio"] - r["need"])
    results.append((theme, area, check, worst))
    if worst["ratio"] < worst["need"]:
        failures.append(f"{theme}: {area} / {check}: {worst['el']} {worst['fg']} on {worst['bg']} = {worst['ratio']:.2f} (needs {worst['need']})")


def text(page, theme, area, check, sel, pseudo=None):
    record(theme, area, check, page.evaluate("([s, p]) => __cx.text(s, p)", [sel, pseudo]))


def ink(page, theme, area, check, sel, need=3, pseudo=None):
    record(theme, area, check, page.evaluate("([s, n, p]) => __cx.ink(s, n, p)", [sel, need, pseudo]))


def border(page, theme, area, check, sel):
    record(theme, area, check, page.evaluate("(s) => __cx.border(s)", sel))


def outline(page, theme, area, check, sel):
    record(theme, area, check, page.evaluate("(s) => __cx.outline(s)", sel))


def ring(page, theme, area, check, sel):
    page.keyboard.press("Tab")           # keyboard modality, so :focus-visible applies
    page.locator(sel).first.focus()
    record(theme, area, check, page.evaluate("() => __cx.focusRing()"))


def inject(page):
    page.evaluate(LIB)


def run_theme(browser, theme):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script(theme_script(theme))
    page = ctx.new_page()
    page.on("dialog", lambda d: d.accept())

    # ---- sign-in page, with and without the error
    page.goto(URL + "/login?bad=1")
    inject(page)
    expect(page.locator("html")).to_have_attribute("data-theme", theme)
    text(page, theme, "sign-in", "title", "h1")
    text(page, theme, "sign-in", "label", "label")
    page.fill("#password", "x")
    text(page, theme, "sign-in", "input text (typed)", "#password")
    border(page, theme, "sign-in", "input border", "#password")
    text(page, theme, "sign-in", "primary button", "button[type=submit]")
    text(page, theme, "sign-in", "error message", "#bad .msg-body")
    outline(page, theme, "sign-in", "error icon", "#bad .msg-icon")
    ring(page, theme, "sign-in", "focus ring", "#password")

    # ---- empty state
    sign_in(page)
    inject(page)
    text(page, theme, "empty", "title", "h1")
    text(page, theme, "empty", "status (muted)", "#status")
    text(page, theme, "empty", "field label", ".addblock label")
    text(page, theme, "empty", "hint (muted)", ".addblock .hint")
    text(page, theme, "empty", "textarea placeholder", "#codes", "::placeholder")
    text(page, theme, "empty", "search placeholder", "#q", "::placeholder")
    text(page, theme, "empty", "primary button (Add)", "#addCodes")
    text(page, theme, "empty", "ghost buttons", ".top-tools button.ghost")
    ink(page, theme, "empty", "file input text", "#sheet", 4.5)
    ink(page, theme, "empty", "file input button text", "#sheet", 4.5, "::file-selector-button")
    border(page, theme, "empty", "input borders", "#codes, #q, #sheet")
    border(page, theme, "empty", "ghost button borders", ".top-tools button.ghost")
    text(page, theme, "empty", "empty-state heading", ".teach h2")
    text(page, theme, "empty", "empty-state text", ".teach p")
    text(page, theme, "empty", "empty-state ways (title)", ".way strong")
    text(page, theme, "empty", "empty-state ways (example)", ".way span")
    text(page, theme, "empty", "preview note", "#previewNote")
    text(page, theme, "empty", "action hint", "#actionHint")
    text(page, theme, "empty", "design select", "#designSel")
    border(page, theme, "empty", "design select border", "#designSel")
    text(page, theme, "empty", "design buttons (enabled)", ".designbtns button.ghost:not(:disabled)")
    text(page, theme, "empty", "enabled ghost button (test labels)", "#testPdf")
    ring(page, theme, "empty", "focus ring (button)", "#addCodes")
    ring(page, theme, "empty", "focus ring (textarea)", "#codes")
    ring(page, theme, "empty", "focus ring (empty-state action)", ".way")

    # ---- table with rows, one selected, one amber cell
    add_rows(page)
    page.locator("#rows tbody tr").nth(1).locator('input[data-field="artist"]').click()
    expect(page.locator("#rows tbody tr").nth(1)).to_have_attribute("aria-current", "true")
    page.wait_for_function("document.getElementById('previewImg').naturalWidth === 400")
    page.wait_for_timeout(300)
    page.fill("#codes", "AMEAMET158")
    inject(page)
    text(page, theme, "table", "typed text in textarea", "#codes")
    text(page, theme, "table", "typed text in search", "#q")
    text(page, theme, "table", "search result text", ".results .pick")
    text(page, theme, "table", "search result detail", ".results .pick small")
    text(page, theme, "table", "total", "#total")
    text(page, theme, "table", "legend", ".legend")
    text(page, theme, "table", "table header", "th")
    text(page, theme, "table", "cell text", "tbody tr:not(.sel) td input:not(.empty)")
    text(page, theme, "table", "selected row text", "tbody tr.sel td input")
    text(page, theme, "table", "amber cell placeholder", "td input.empty", "::placeholder")
    border(page, theme, "table", "cell borders", "tbody tr:not(.sel) td input:not(.empty)")
    border(page, theme, "table", "cell borders (selected row)", "tbody tr.sel td input")
    border(page, theme, "table", "amber cell border", "td input.empty")
    outline(page, theme, "table", "selected row outline", "tbody tr.sel")
    ink(page, theme, "table", "remove row icon", "td[data-col=rm] button")
    text(page, theme, "table", "primary button (Download PDF)", "#pdf")
    text(page, theme, "table", "ghost buttons in the action bar", ".actions button.ghost")
    border(page, theme, "table", "action bar ghost borders", ".actions button.ghost")
    text(page, theme, "table", "preview caption", "#previewCaption")
    text(page, theme, "table", "design notes (warning)", "#designNotes .msg-body")
    outline(page, theme, "table", "warning icon", "#designNotes .msg-icon")
    ring(page, theme, "table", "focus ring (table cell)", "tbody tr:not(.sel) td input")
    ring(page, theme, "table", "focus ring (remove row)", "td[data-col=rm] button")
    ring(page, theme, "table", "focus ring (primary button)", "#pdf")

    # ---- every message state
    for kind, call in (("ok", "note('Saved design CD shelf.')"), ("info", "note('Reading DealPOS…', 'info')"),
                       ("warn", "note('2 added. Not found: nope1', 'warn')"), ("error", "note('DealPOS: request failed', true)")):
        page.evaluate(call)
        text(page, theme, "message " + kind, "text", "#msg .msg-body")
        outline(page, theme, "message " + kind, "icon", "#msg .msg-icon")
    page.evaluate("note('')")

    # ---- design editor open, an element selected, an unsaved change
    page.click("#designer summary")
    page.locator("#elList li", has_text="artist").locator("button.elname").click()
    page.fill('#props input[data-key="size_pt"]', "7")
    expect(page.locator("#dirty")).to_be_visible()
    page.wait_for_timeout(400)
    inject(page)
    text(page, theme, "editor", "unsaved note", "#dirty")
    text(page, theme, "editor", "summary", "#designer summary")
    text(page, theme, "editor", "headings", ".dgrid h2")
    text(page, theme, "editor", "property labels", ".prop label")
    text(page, theme, "editor", "property inputs", ".prop input:not([type=checkbox]):not([type=search])")
    text(page, theme, "editor", "font filter placeholder", '[data-role="font-filter"]', "::placeholder")
    text(page, theme, "editor", "selects", ".prop select, #addType")
    border(page, theme, "editor", "input and select borders", ".prop input:not([type=checkbox]), .prop select, #addType")
    text(page, theme, "editor", "element names", ".ellist li:not(.sel) .elname")
    text(page, theme, "editor", "selected element name", ".ellist li.sel .elname")
    ink(page, theme, "editor", "element move icons", ".ellist .mini")
    text(page, theme, "editor", "editor buttons", ".eladd button, .fontpick button")
    border(page, theme, "editor", "editor button borders", ".eladd button, .fontpick button")
    text(page, theme, "editor", "editor hint", ".dright .hint")
    ring(page, theme, "editor", "focus ring (summary)", "#designer summary")
    ring(page, theme, "editor", "focus ring (element name)", ".ellist .elname")
    ring(page, theme, "editor", "focus ring (property input)", '#props input[data-key="size_pt"]')
    ctx.close()


def main():
    with dev_server(), sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ("dark", "light"):
            run_theme(browser, theme)
        browser.close()

    width = max(len(r[2]) for r in results)
    print(f"{'theme':5}  {'area':14}  {'check':{width}}  {'worst element':28}  {'fg':7}  {'bg':7}  {'ratio':>6}  {'need':>4}  result")
    for theme, area, check, w in results:
        if w is None:
            print(f"{theme:5}  {area:14}  {check:{width}}  {'(nothing matched)':28}  {'':7}  {'':7}  {'':>6}  {'':>4}  FAIL")
            continue
        ok = "ok" if w["ratio"] >= w["need"] else "FAIL"
        print(f"{theme:5}  {area:14}  {check:{width}}  {w['el'][:28]:28}  {w['fg']:7}  {w['bg']:7}  {w['ratio']:6.2f}  {w['need']:4}  {ok}")
    for theme in ("dark", "light"):
        lows = [(w["ratio"] / w["need"], w, c) for t, a, c, w in results if t == theme and w]
        low = min(lows, key=lambda x: x[0])
        print(f"{theme}: lowest ratio {min(w['ratio'] for _, w, _ in lows):.2f} (tightest margin: {low[2]}, {low[1]['ratio']:.2f} vs {low[1]['need']})")
    if failures:
        print("\nFAILED:")
        for line in failures:
            print(" -", line)
        sys.exit(1)
    print("\nUI CONTRAST OK")


if __name__ == "__main__":
    main()
