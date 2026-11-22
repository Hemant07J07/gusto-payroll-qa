"""
Logged-in tests of the real "Run payroll" workflow (use a Gusto DEMO/trial company - never real payroll data).

Login is done ONCE by hand (handles 2FA/captcha):  python scripts/save_login_state.py
Then these tests reuse GUSTO_STORAGE_STATE (default .auth/gusto.json).

Selector note: Gusto's app UI is behind a login so I could not inspect its DOM. Locators below use
role/text (resilient to markup changes) and are marked TODO(selector) where the visible wording must be
confirmed on first run - use `playwright codegen --load-storage .auth/gusto.json <url>`.
"""
import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.ui
STATE = Path(os.getenv("GUSTO_STORAGE_STATE", ".auth/gusto.json"))
APP = os.getenv("GUSTO_APP_URL", "https://app.gusto.com")

if not STATE.exists():
    pytest.skip(f"no saved login at {STATE}; run scripts/save_login_state.py", allow_module_level=True)


@pytest.fixture
def browser_context_args(browser_context_args):
    return {**browser_context_args, "storage_state": str(STATE)}


def open_payroll_home(page):
    page.goto(f"{APP}/payroll", wait_until="domcontentloaded")  # TODO(selector): confirm path (Pay > Run payroll)
    assert "login" not in page.url, "saved session expired - re-run save_login_state.py"


@pytest.mark.smoke
def test_payroll_home_shows_deadline_in_pacific_time(page):
    open_payroll_home(page)
    body = page.locator("body").inner_text()
    assert re.search(r"4\s*(:00)?\s*(pm|p\.m\.)\s*(PT|PST|PDT|Pacific)", body, re.I), \
        "payroll deadline should be shown with an explicit Pacific-time cut-off"


def test_deadline_text_is_identical_for_every_browser_timezone(browser):
    """Local-time leakage bug class: a user in India must see the same PT deadline as one in California."""
    seen = {}
    for tz in ("America/Los_Angeles", "Asia/Kolkata", "Pacific/Auckland"):
        ctx = browser.new_context(storage_state=str(STATE), timezone_id=tz, locale="en-US")
        page = ctx.new_page()
        open_payroll_home(page)
        text = page.locator("body").inner_text()
        ctx.close()
        found = re.findall(r"(?:deadline|submit by)[^\n]{0,60}", text, re.I)
        assert found, f"no deadline text for {tz} - TODO(selector)"
        seen[tz] = found[0]
    assert len(set(seen.values())) == 1, seen


def test_cannot_submit_payroll_with_negative_hours(page):
    open_payroll_home(page)
    page.get_by_role("button", name=re.compile(r"run payroll", re.I)).first.click()  # TODO(selector)
    hours = page.get_by_label(re.compile(r"regular hours", re.I)).first               # TODO(selector)
    hours.fill("-8")
    hours.blur()
    assert page.get_by_text(re.compile(r"(invalid|must be|cannot be negative|greater than)", re.I)).count() > 0 \
        or page.get_by_role("button", name=re.compile(r"submit payroll", re.I)).is_disabled()


def test_double_click_submit_does_not_double_submit(page):
    """Idempotency: rapid double click on 'Submit payroll' must create exactly one submission (do NOT run on real data)."""
    pytest.skip("destructive: enable only on a disposable demo company; see data/test_cases.xlsx TC-PAY-042")
