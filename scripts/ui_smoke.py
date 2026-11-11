"""Browser smoke test: starts the dev server (fake DealPOS) and drives the real page in Chromium,
with a mocked WebUSB printer. Prints 'UI SMOKE OK' or fails with the first broken step.

  uv run python scripts/ui_smoke.py
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pymupdf
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = Path(os.environ.get("LABEL_FONT_DIR", "C:/Windows/Fonts"))
PORT = 8795
URL = f"http://127.0.0.1:{PORT}"

USB_MOCK = """
window.__usb = [];
const device = {
  opened: false, configuration: null,
  async open() { this.opened = true; },
  async selectConfiguration() { this.configuration = { interfaces: [{ interfaceNumber: 0, alternates: [
    { alternateSetting: 0, interfaceClass: 7, endpoints: [{ direction: 'out', type: 'bulk', endpointNumber: 2 }] }] }] }; },
  async claimInterface() {}, async selectAlternateInterface() {},
  async transferOut(ep, data) { window.__usb.push(Array.from(data)); return { status: 'ok' }; },
};
Object.defineProperty(navigator, 'usb', { value: { getDevices: async () => [], requestDevice: async () => device, addEventListener() {} } });
"""


def wait_for_port(port, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError("dev server did not start")


def usb_text(page):
    flat = page.evaluate("window.__usb.flat()")
    return bytes(flat).decode("latin1")


def main():
    server = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "dev_server.py"), str(PORT)], cwd=ROOT)
    try:
        wait_for_port(PORT)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(accept_downloads=True)
            ctx.add_init_script(USB_MOCK)
            page = ctx.new_page()
            page.on("dialog", lambda d: d.accept("CD shelf") if d.type == "prompt" else d.accept())
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))

            page.goto(URL)
            expect(page).to_have_url(URL + "/login")
            page.fill("#password", "wrong")
            page.click("button[type=submit]")
            expect(page.locator("#bad")).to_be_visible()
            page.fill("#password", "devpassword")
            page.click("button[type=submit]")
            expect(page.locator("h1")).to_have_text("MF Label Printer")
            expect(page.locator("#status")).to_contain_text("3 products")
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")          # dark is the default
            expect(page.locator("#empty")).to_be_visible()                               # the empty state teaches the three ways to add labels
            expect(page.locator("#empty .way")).to_have_count(3)
            expect(page.locator("#pdf")).to_be_disabled()                                # nothing to download yet, and the page says why
            expect(page.locator("#actionHint")).to_be_visible()

            page.fill("#codes", "AMEAMET158 NOUPASC001 nope1")
            page.click("#addCodes")
            expect(page.locator("#rows tbody tr")).to_have_count(2)
            expect(page.locator("#msg")).to_contain_text("Not found: nope1")
            expect(page.locator("#empty")).to_be_hidden()
            expect(page.locator("#pdf")).to_be_enabled()
            expect(page.locator("#rows tbody tr").nth(0)).to_have_attribute("aria-current", "true")   # the selected row is announced
            expect(page.locator('#rows tbody tr td[data-col="year"]').first).to_have_attribute("data-label", "Year")  # stacked layout labels
            page.click("#msgClose")                                                      # messages can be dismissed
            expect(page.locator("#msg")).to_be_hidden()
            first = page.locator("#rows tbody tr").first
            expect(first.locator('input[data-field="year"]')).to_have_value("1999")      # filled from the Description
            expect(first.locator('input[data-field="genre"]')).to_have_value("Rock")
            second = page.locator("#rows tbody tr").nth(1)
            expect(second.locator('input[data-field="price"]')).to_have_value("330000")
            expect(second.locator('input[data-field="year"]')).to_have_value("2024")
            expect(second.locator('input[data-field="genre"]')).to_have_value("Soul")
            page.wait_for_function("document.getElementById('previewImg').naturalWidth === 400")

            page.fill("#q", "passionate")
            page.locator("#results li").first.click()
            expect(page.locator("#rows tbody tr")).to_have_count(2)  # NOUPASC001 was already there, NOUPASC002 added
            page.fill("#q", "nourished")
            page.locator("#results li").nth(1).click()
            expect(page.locator("#rows tbody tr")).to_have_count(3)
            third = page.locator("#rows tbody tr").nth(2)
            expect(third.locator('input[data-field="genre"]')).to_have_class("empty")    # amber flag: no genre in DealPOS

            page.locator("#rows tbody tr").first.locator('input[data-field="copies"]').fill("3")
            expect(page.locator("#total")).to_have_text("3 rows, 5 labels")

            with page.expect_download() as dl:
                page.click("#pdf")
            doc = pymupdf.open(dl.value.path())
            assert len(doc) == 5, len(doc)
            with page.expect_download() as dl:
                page.click("#xlsx")
            assert dl.value.suggested_filename == "mf-labels.xlsx"


            # ---- designer: edit, see it in the preview request, save as, print with it, reload, delete
            expect(page.locator("#designSel")).to_have_value("mf-april")
            expect(page.locator("#designDelete")).to_be_disabled()                      # built-in designs cannot be deleted
            expect(page.locator("#designNotes")).to_contain_text("1 dot")               # April design has 1-dot bars
            page.click("#designer summary")
            expect(page.locator("#elList li")).to_have_count(10)
            page.locator("#elList li", has_text="artist").locator("button.elname").click()
            with page.expect_request(lambda r: r.url.endswith("/api/label.png") and '"size_pt":9' in (r.post_data or "")):
                page.fill('#props input[data-key="size_pt"]', "9")
            expect(page.locator("#dirty")).to_be_visible()

            # ---- fonts: filter, pick DM Sans, add a font file, remove it again
            font_select = '#props select[data-key="font"]'
            expect(page.locator(font_select)).to_have_value("arial")
            groups = lambda: page.eval_on_selector_all(font_select + " optgroup", "els => els.map(e => e.label)")
            assert groups() == ["Brand", "Installed"], groups()
            page.fill('#props input[data-role="font-filter"]', "dm")
            expect(page.locator(font_select + " option")).to_have_count(4)                # the three DM Sans weights, and the chosen Arial stays listed
            with page.expect_request(lambda r: r.url.endswith("/api/label.png") and '"font":"dm-sans"' in (r.post_data or "")):
                page.select_option(font_select, label="DM Sans")
            expect(page.locator('#props button[data-role="font-remove"]')).to_be_hidden()  # the brand font cannot be removed
            sample = next((p for p in (FONT_DIR / "tahoma.ttf", FONT_DIR / "verdana.ttf") if p.exists()), None)
            if sample:
                with page.expect_request(lambda r: r.url.endswith("/api/label.png") and '"font":"' + sample.stem + '"' in (r.post_data or "")):
                    page.set_input_files('#props input[data-role="font-file"]', str(sample))
                expect(page.locator("#msg")).to_contain_text("Added the font " + sample.stem.capitalize())
                expect(page.locator(font_select)).to_have_value(sample.stem)
                assert groups() == ["Brand", "Your fonts", "Installed"], groups()
                expect(page.locator('#props button[data-role="font-remove"]')).to_be_visible()
                page.click('#props button[data-role="font-remove"]')                       # confirm dialog is accepted above
                expect(page.locator("#msg")).to_contain_text("Removed the font " + sample.stem.capitalize())
                expect(page.locator('#props button[data-role="font-remove"]')).to_be_hidden()   # the installed copy is still there
                assert groups() == ["Brand", "Installed"], groups()
                with page.expect_request(lambda r: r.url.endswith("/api/label.png") and '"font":"dm-sans"' in (r.post_data or "")):
                    page.select_option(font_select, label="DM Sans")
            with page.expect_request(lambda r: r.url.endswith("/api/label.png") and '"visible":false' in (r.post_data or "")):
                page.locator("#elList li", has_text="logo").locator("input[type=checkbox]").uncheck()
            page.locator("#elList li", has_text="barcode").locator("button.elname").click()
            page.select_option('#props select[data-key="mode"]', "fit")
            expect(page.locator("#designNotes")).to_contain_text("Stretched")           # the warning follows the edit
            page.select_option('#props select[data-key="mode"]', "integer")
            page.click("#designSaveAs")                                                  # prompt answered with "CD shelf"
            expect(page.locator("#designSel")).to_have_value("cd-shelf")
            expect(page.locator("#dirty")).to_be_hidden()
            with page.expect_request(lambda r: r.url.endswith("/api/labels.pdf") and '"name":"CD shelf"' in (r.post_data or "")):
                page.click("#pdf")                                                       # exports with the working design

            page.click("#usb")                       # first print of the session: one label only
            page.wait_for_function("window.__usb.length > 0")
            text = usb_text(page)
            assert text.startswith("SIZE 50 mm,30 mm") and text.count("BITMAP 0,0,50,240,0,") == 1 and text.endswith("PRINT 1,1\r\n"), text[:80]
            page.evaluate("window.__usb.length = 0")
            page.click("#usb")                       # second press prints everything
            page.wait_for_function("window.__usb.length > 0")
            text = usb_text(page)
            assert text.count("BITMAP 0,0,50,240,0,") == 3 and "PRINT 1,3\r\n" in text
            page.evaluate("window.__usb.length = 0")
            page.click("#usbTest")
            page.wait_for_function("window.__usb.length > 0")
            assert usb_text(page).count("BITMAP") == 2           # orientation label + scan-test label
            with page.expect_download() as dl:
                page.click("#testPdf")
            assert len(pymupdf.open(dl.value.path())) == 2

            page.reload()                                                                # saved designs survive a reload
            expect(page.locator("#designSel option")).to_have_count(10)                  # nine built in + the saved one
            page.select_option("#designSel", "cd-shelf")
            expect(page.locator("#designDelete")).to_be_enabled()
            page.click("#designDelete")
            expect(page.locator("#designSel option")).to_have_count(9)
            expect(page.locator("#designSel")).to_have_value("mf-april")

            body = page.inner_text("body")
            assert "undefined" not in body and "null" not in body.lower().replace("nullable", ""), body[:200]

            # ---- theme: dark by default, light on request, remembered across a reload
            page.click("#theme")
            expect(page.locator("html")).to_have_attribute("data-theme", "light")
            expect(page.locator("#theme")).to_have_attribute("aria-pressed", "true")
            page.reload()
            expect(page.locator("html")).to_have_attribute("data-theme", "light")
            expect(page.locator("#theme")).to_have_attribute("aria-pressed", "true")
            page.click("#theme")
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            page.reload()
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")

            assert not errors, errors
            browser.close()
        print("UI SMOKE OK")
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
