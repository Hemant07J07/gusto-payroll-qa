"""
Page object for Gusto's PUBLIC hourly paycheck calculator (no login needed).

    https://gusto.com/tools/hourly-paycheck-calculator
      -> 301 to https://gusto.com/resources/calculators/payroll/hourly-paycheck-calculator

Calibrated against the live page on 2026-11-21. What the first version got wrong, and how this one differs:
  * Bot protection: headless Chromium gets a Cloudflare "Just a moment..." page (HTTP 403). `open()` raises
    BotChallenge so the run says so, instead of failing 20 times with "No field matched".
  * Locators: fields are found by their stable form `name=` attributes, not by guessing label wording.
  * Required fields: Calculate stays DISABLED until state, wage, hours, frequency, home + work address (picked
    from the autocomplete) and the W-4 selects are set. `setup()` fills them; `calculate()` raises
    CalculateDisabled instead of hanging for 30 s on a disabled button.
  * Results: the panel always shows "Take home pay $0.00" and the intro text also says "take-home pay", so the
    old "first $ after 'take-home'" parser read marketing copy. Results now come from the calculation response
    (`calculate()` returns it) and from the panel rows only.
  * Cookie banner: accepting it RELOADS the page and wipes the form. `open()` waits for that reload.
  * Overtime is a separate field with its own, user-typed overtime rate; the page never applies 1.5x itself.
  * The sticky header covers fields scrolled to the top edge, so clicks are made with 300 px of headroom.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page

URL = "https://gusto.com/tools/hourly-paycheck-calculator"
CALC_ENDPOINT = re.compile(r"/tools/paycheck-calculator/(?!applicable_taxes)[^/?]+$")

F = {
    "state": "select[name='stateName']",
    "rate": "input[name='basics.hourlyPay.wage']",
    "hours": "input[name='basics.hourlyPay.hours']",
    "ot_rate": "input[name='basics.overtime.0.wage']",
    "ot_hours": "input[name='basics.overtime.0.hours']",
    "check_date": "input[name='basics.checkDate']",
    "frequency": "select[name='basics.payFrequency']",
    "fed_status": "select[name='federalTax.filingStatus']",
    "state_status": "select[name='stateTax.filingStatus']",
    "state_dependents": "input[name='stateTax.numberOfDependents']",
    "state_extra": "input[name='stateTax.additionalWithholding']",
    "address": "input[placeholder='Enter address']",
}
ROWS = ("Gross pay", "Income taxes", "FICA taxes", "Pre-tax", "Post-tax", "Take home pay")
MONEY = re.compile(r"(-?)\$\s*(-?[\d,]+(?:\.\d+)?)")
PCT = re.compile(r"(-?[\d.]+)\s*%")


class BotChallenge(RuntimeError):
    """gusto.com answered with a Cloudflare challenge instead of the calculator."""


class CalculateDisabled(AssertionError):
    pass


@dataclass(frozen=True)
class Row:
    pct: Decimal | None
    amount: Decimal | None
    raw: str


@dataclass(frozen=True)
class CalcResponse:
    status: int
    text: str

    @property
    def json(self) -> dict:
        return json.loads(self.text)  # Python accepts bare NaN/Infinity, which the live server emits

    def detail(self, group: str, label: str) -> Decimal | None:
        for d in self.json.get(group, {}).get("details", []):
            if d.get("label") == label:
                return to_dec(d.get("amount"))
        return None


def to_dec(v) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v).replace(",", ""))


class PaycheckCalculatorPage:
    def __init__(self, page: Page, *, pace_s: float = 1.5):
        self.page = page
        self.pace_s = pace_s          # be polite: the live endpoint rate-limits (HTTP 429)
        self.last: CalcResponse | None = None
        self._last_calc_at = 0.0

    # ------------------------------------------------------------------ open --
    def open(self) -> "PaycheckCalculatorPage":
        resp = self.page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        if (resp is not None and resp.status == 403) or "just a moment" in self.page.title().lower():
            raise BotChallenge("Cloudflare bot challenge (HTTP 403 'Just a moment...'); run with --headed")
        self._wait_ready()
        self._settle_cookie_banner()
        return self

    def _wait_ready(self) -> None:
        self.page.locator(F["rate"]).wait_for(state="visible", timeout=45_000)
        self.page.wait_for_load_state("load")

    def _settle_cookie_banner(self) -> None:
        """Accepting cookies reloads the page (console: 'Triggering Page Refresh') - wait for it, otherwise
        whatever is typed next is silently wiped (that is also product defect DEF-09)."""
        btn = self.page.locator("#onetrust-accept-btn-handler")
        try:
            btn.wait_for(state="visible", timeout=6_000)
        except PlaywrightError:
            return
        try:
            with self.page.expect_navigation(timeout=15_000):
                btn.click()
        except PlaywrightError:
            pass
        self._wait_ready()

    # ---------------------------------------------------------------- inputs --
    def field(self, key: str) -> Locator:
        return self.page.locator(F[key]).first

    def _focus(self, loc: Locator) -> None:
        loc.evaluate("e => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 300)")
        loc.click()

    def type(self, key_or_loc, value) -> "PaycheckCalculatorPage":
        """Real key presses: the masked currency inputs ignore programmatic fill()."""
        loc = self.field(key_or_loc) if isinstance(key_or_loc, str) else key_or_loc
        self._focus(loc)
        loc.press("ControlOrMeta+a")
        loc.press("Backspace")
        if str(value) != "":
            self.page.keyboard.type(str(value), delay=15)
        loc.blur()
        return self

    fill = type

    def select(self, key: str, value: str) -> "PaycheckCalculatorPage":
        self.field(key).select_option(value)
        return self

    def value(self, key: str) -> str:
        return self.field(key).input_value()

    def is_invalid(self, key: str, wait_ms: int = 2000) -> bool:
        """Validation runs asynchronously after blur on the live page; poll briefly before answering."""
        loc = self.field(key)
        try:
            loc.page.wait_for_function("e => e.getAttribute('aria-invalid') === 'true'",
                                       arg=loc.element_handle(), timeout=wait_ms)
            return True
        except PlaywrightError:
            return False

    def field_message(self, key_or_loc) -> str:
        loc = self.field(key_or_loc) if isinstance(key_or_loc, str) else key_or_loc
        return loc.evaluate(
            "e => (e.getAttribute('aria-describedby')||'').split(' ').filter(Boolean)"
            ".map(i => document.getElementById(i)).filter(Boolean).map(n => n.innerText).join(' / ')")

    def add_overtime(self, ot_rate, ot_hours) -> "PaycheckCalculatorPage":
        if not self.page.locator(F["ot_rate"]).count():
            self.page.get_by_role("button", name="Add Overtime").click()
        return self.type("ot_rate", ot_rate).type("ot_hours", ot_hours)

    def add_deduction(self, name: str, method: str, amount, *, group: str = "deductions") -> "PaycheckCalculatorPage":
        """name e.g. Retirement401k, Roth401k, MedicalInsurance, HsaIndividual; method FixedAmount | Percentage."""
        self.page.locator(f"select[name='{group}.0.name']").select_option(name)
        self.page.locator(f"select[name='{group}.0.calculationMethod']").select_option(method)
        return self.type(self.page.locator(f"input[name='{group}.0.amount']"), amount)

    def exempt(self, tax: str) -> "PaycheckCalculatorPage":
        """Tick a Special Exemptions box: 'Social Security', 'Federal Income Tax', 'Medicare Tax', ..."""
        boxes = self.page.locator("input[name='exemptions']")
        idx = boxes.evaluate_all(
            "(els, t) => els.findIndex(e => e.labels && e.labels[0] && e.labels[0].innerText.trim() === t)", tax)
        if idx < 0:
            raise AssertionError(f"no exemption checkbox labelled {tax!r}")
        box = boxes.nth(idx)
        box.evaluate("e => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 300)")
        box.check(force=True)
        return self

    def set_check_year(self, year: int) -> "PaycheckCalculatorPage":
        y = self.page.locator("[aria-label='Year (yyyy)']")
        self._focus(y)
        self.page.keyboard.type(str(year), delay=60)
        y.blur()
        return self

    def set_address(self, index: int, query: str) -> str:
        """Type into the address combobox and pick the first suggestion (limited to the selected state)."""
        box = self.page.locator(F["address"]).nth(index)
        self.type(box, query)
        self._focus(box)
        option = self.page.locator(f"#{box.get_attribute('aria-controls')}").get_by_role("option").first
        option.wait_for(state="visible", timeout=10_000)
        option.click()
        return box.input_value()

    def setup(self, *, state="Alabama", rate=20, hours=40, frequency="Weekly",
              address="1000 Main St", fed_status="Single") -> "PaycheckCalculatorPage":
        """Fill every required field with neutral defaults so Calculate becomes enabled."""
        if self.value("state") != state:
            self.select("state", state)
        self.select("frequency", frequency)
        self.type("rate", rate).type("hours", hours)
        self.set_address(0, address)
        self.set_address(1, address)
        self.select("fed_status", fed_status)
        st = self.field("state_status")
        if st.count() and st.is_visible() and not st.input_value():
            opts = [o for o in st.evaluate("s => [...s.options].map(o => o.value)") if o]
            st.select_option("Single" if "Single" in opts else opts[0])
        for key in ("state_dependents", "state_extra"):
            loc = self.field(key)
            if loc.count() and loc.is_visible() and not loc.input_value():
                self.type(key, 0)
        return self

    # --------------------------------------------------------------- results --
    @property
    def calculate_button(self) -> Locator:
        return self.page.locator("button", has_text=re.compile(r"^\s*Calculate\s*$"))

    def can_calculate(self) -> bool:
        self.page.wait_for_timeout(400)  # validation runs asynchronously after blur
        return not self.calculate_button.is_disabled()

    def calculate(self) -> CalcResponse:
        """Click Calculate and return the server's answer (status + raw body). Retries once on HTTP 429."""
        if not self.can_calculate():
            bad = [e.get_attribute("name") for e in self.page.locator("[aria-invalid=true]").all()]
            raise CalculateDisabled(f"Calculate is disabled; invalid fields: {bad}")
        for attempt in range(2):
            wait = self.pace_s - (time.monotonic() - self._last_calc_at)
            if wait > 0:
                time.sleep(wait)
            with self.page.expect_response(lambda r: bool(CALC_ENDPOINT.search(r.url.split("?")[0])),
                                           timeout=30_000) as info:
                self.calculate_button.click()
            self._last_calc_at = time.monotonic()
            r = info.value
            try:
                body = r.text()
            except PlaywrightError:
                body = ""
            self.last = CalcResponse(r.status, body)
            if r.status != 429 or attempt:
                break
            time.sleep(30)
        self.page.wait_for_timeout(300)  # let React paint the panel
        return self.last

    def _panel(self) -> Locator:
        self.page.evaluate(
            """() => { document.querySelectorAll('[data-qa=result-panel]').forEach(e => e.removeAttribute('data-qa'));
                 const hit = [...document.querySelectorAll('div,section,aside,table,dl')].filter(e =>
                     /Gross pay/.test(e.innerText) && /Take home pay/.test(e.innerText)
                     && !e.querySelector('form') && e.innerText.length < 400);
                 hit.sort((a, b) => a.innerText.length - b.innerText.length);
                 if (hit[0]) hit[0].setAttribute('data-qa', 'result-panel'); }""")
        return self.page.locator("[data-qa=result-panel]")

    def panel_text(self) -> str:
        panel = self._panel()
        return panel.inner_text() if panel.count() else ""

    def results(self) -> dict[str, Row]:
        lines = [ln.strip() for ln in self.panel_text().splitlines() if ln.strip()]
        out: dict[str, Row] = {}
        for i, ln in enumerate(lines):
            if ln not in ROWS:
                continue
            chunk = []
            for nxt in lines[i + 1:]:
                if nxt in ROWS:
                    break
                chunk.append(nxt)
            raw = " ".join(chunk)
            m, p = MONEY.search(raw), PCT.search(raw)
            amt = None
            if m:
                amt = Decimal(m.group(2).replace(",", ""))
                amt = -amt if m.group(1) else amt
            out[ln] = Row(Decimal(p.group(1)) if p else None, amt, raw)
        return out

    def amount(self, row: str) -> Decimal | None:
        r = self.results().get(row)
        return r.amount if r else None

    def net_pay(self) -> Decimal | None:
        return self.amount("Take home pay")

    def gross_pay(self) -> Decimal | None:
        return self.amount("Gross pay")

    def visible_error_text(self) -> str:
        """Any user-visible error near the result panel (alerts, toasts, 'something went wrong')."""
        # Only role=alert and explicit failure wording: the live page's aria-live regions hold ordinary form text
        # that changes while typing, which made an earlier version report an error that was never shown.
        alerts = " ".join(t.strip() for t in self.page.locator("[role=alert]").all_inner_texts())
        body = self.page.locator("body").inner_text()
        m = re.search(r"(something went wrong|unable to calculate|could not calculate|please try again)[^\n]{0,80}", body, re.I)
        return (alerts + " " + (m.group(0) if m else "")).strip()
