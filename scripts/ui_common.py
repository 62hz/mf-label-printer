"""Shared bits for the browser scripts (ui_contrast.py, ui_shots.py): start the dev server (fake DealPOS, port 8795,
throwaway designs and fonts), sign in, and fill the table with a few rows.

The real server on port 8797 is never touched. Run the scripts with `uv run python scripts/<name>.py`.
"""
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
PORT = 8795
URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "devpassword"
THEME_KEY = "mf-theme"


def wait_for_port(port, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError("dev server did not start")


@contextmanager
def dev_server():
    server = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "dev_server.py"), str(PORT)], cwd=ROOT)
    try:
        wait_for_port(PORT)
        yield URL
    finally:
        server.terminate()
        server.wait(timeout=10)


def theme_script(theme):
    """Init script: the saved theme, as if the user had picked it with the toggle."""
    return f"try {{ localStorage.setItem('{THEME_KEY}', '{theme}'); }} catch (e) {{}}"


def sign_in(page):
    page.goto(URL)
    expect(page).to_have_url(URL + "/login")
    page.fill("#password", PASSWORD)
    page.click("button[type=submit]")
    expect(page.locator("h1")).to_have_text("MF Label Printer")
    expect(page.locator("#status")).to_contain_text("3 products")


def add_rows(page):
    """Three rows: two pasted SKUs and one found by search; the search one has no genre in DealPOS (an amber cell)."""
    page.fill("#codes", "AMEAMET158 NOUPASC001")
    page.click("#addCodes")
    expect(page.locator("#rows tbody tr")).to_have_count(2)
    page.fill("#q", "nourished")
    page.locator("#results li").nth(1).click()
    expect(page.locator("#rows tbody tr")).to_have_count(3)
    page.wait_for_function("document.getElementById('previewImg').naturalWidth === 400")
    expect(page.locator("#progress")).to_be_hidden()
