"""Screenshots of the page for design review: 1280, 768 and 390 px wide, dark and light, in four states
(empty, table with a selected row, design editor open, plus the sign-in page). Saved to samples/ui/ (gitignored).
Also prints any page that scrolls sideways, which would be a layout bug.

  uv run python scripts/ui_shots.py [--out samples/ui] [--only 390]
"""
import argparse
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from ui_common import ROOT, URL, add_rows, dev_server, sign_in, theme_script

SIZES = [(1280, 800, False), (768, 1024, True), (390, 844, True)]   # width, height, touch device
THEMES = ["dark", "light"]


def sideways(page):
    return page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")


def full_shot(page, path, width, height):
    """Whole page in one image: grow the viewport to the page height first, so the sticky action bar lands at the bottom."""
    page.set_viewport_size({"width": width, "height": page.evaluate("document.documentElement.scrollHeight")})
    page.wait_for_timeout(200)
    page.screenshot(path=str(path))
    page.set_viewport_size({"width": width, "height": height})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "samples" / "ui"))
    ap.add_argument("--only", type=int, help="only this width")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    problems = []
    with dev_server(), sync_playwright() as p:
        browser = p.chromium.launch()
        for width, height, touch in SIZES:
            if args.only and width != args.only:
                continue
            for theme in THEMES:
                ctx = browser.new_context(viewport={"width": width, "height": height}, has_touch=touch, is_mobile=touch, device_scale_factor=1)
                ctx.add_init_script(theme_script(theme))
                page = ctx.new_page()
                page.on("dialog", lambda d: d.accept())
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                tag = f"{width}-{theme}"

                page.goto(URL + "/login")
                page.screenshot(path=str(out / f"login-{tag}.png"))

                sign_in(page)
                expect(page.locator("html")).to_have_attribute("data-theme", theme)
                full_shot(page, out / f"empty-{tag}.png", width, height)
                if sideways(page) > 0:
                    problems.append(f"empty {tag}: scrolls sideways by {sideways(page)} px")

                add_rows(page)
                page.locator("#rows tbody tr").nth(1).locator('input[data-field="artist"]').click()
                expect(page.locator("#rows tbody tr").nth(1)).to_have_attribute("aria-current", "true")
                page.wait_for_function("document.getElementById('previewImg').naturalWidth === 400")
                page.wait_for_timeout(400)
                full_shot(page, out / f"table-{tag}.png", width, height)
                if sideways(page) > 0:
                    problems.append(f"table {tag}: scrolls sideways by {sideways(page)} px")
                if width == 1280:   # sticky header and sticky preview: look at it part-way down a long page
                    page.evaluate("window.scrollTo(0, 260)")
                    page.screenshot(path=str(out / f"table-scrolled-{tag}.png"))
                    page.evaluate("window.scrollTo(0, 0)")

                page.click("#designer summary")
                page.locator("#elList li", has_text="artist").locator("button.elname").click()
                page.wait_for_timeout(500)
                full_shot(page, out / f"editor-{tag}.png", width, height)
                if sideways(page) > 0:
                    problems.append(f"editor {tag}: scrolls sideways by {sideways(page)} px")
                if errors:
                    problems.append(f"{tag}: page errors {errors}")
                ctx.close()
        browser.close()
    for line in problems:
        print("PROBLEM", line)
    print("shots in", out, "-", "problems found" if problems else "no sideways scroll, no page errors")


if __name__ == "__main__":
    main()
