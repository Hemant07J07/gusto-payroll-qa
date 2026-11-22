"""Print every form control on a page - the fastest way to calibrate page-object locators.

    python scripts/inspect_page.py [url] [--headless]

Fixed 2026-11-21: the first version waited for "networkidle", which never happens on gusto.com (analytics keep
polling), and ran headless, which Cloudflare blocks with a 403 "Just a moment..." page. It now opens a visible
browser, waits for the DOM plus a few seconds, and prints the stable `name=` attribute of each control.
"""
import sys

from playwright.sync_api import sync_playwright

args = [a for a in sys.argv[1:] if not a.startswith("--")]
url = args[0] if args else "https://gusto.com/tools/hourly-paycheck-calculator"
with sync_playwright() as p:
    b = p.chromium.launch(headless="--headless" in sys.argv)
    page = b.new_page()
    resp = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(6_000)
    print(f"HTTP {resp.status if resp else '?'}  {page.url}  title={page.title()!r}")
    if "just a moment" in page.title().lower():
        print("Cloudflare challenge page - rerun without --headless")
    for c in page.locator("input:not([type=hidden]), select, textarea").all():
        info = c.evaluate("""e => ({tag: e.tagName.toLowerCase(), type: e.type, name: e.name,
            label: (e.labels && e.labels[0] ? e.labels[0].innerText : e.getAttribute('aria-label') || e.placeholder || '').trim(),
            visible: !!(e.offsetWidth || e.offsetHeight)})""")
        if info["visible"]:
            print(f"{info['tag']:8} {info['type'] or '':10} name={info['name']!r:42} label={info['label'][:70]!r}")
    b.close()
