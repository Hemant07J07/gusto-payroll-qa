"""Log in to Gusto by hand ONCE (2FA / captcha friendly) and store the session for the UI tests.

    python scripts/save_login_state.py            # opens a visible browser; log in; press Enter in the terminal
Use a Gusto demo/trial company. The saved file contains live session cookies - it is git-ignored; never commit it.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(".auth/gusto.json")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto("https://app.gusto.com/login")
    input("Log in in the browser window, wait for the dashboard, then press Enter here... ")
    OUT.parent.mkdir(exist_ok=True)
    ctx.storage_state(path=str(OUT))
    print(f"saved {OUT}")
    browser.close()
