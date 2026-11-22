import json
import os
from decimal import Decimal as D
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError

from payroll_oracle import fica_employee, money

MOCK = Path(__file__).parent / "mock" / "calculator.html"
USE_MOCK = bool(os.getenv("USE_MOCK_CALCULATOR"))
MOCK_BUG = os.getenv("MOCK_BUG", "")


# --------------------------------------------------------------------------- mock self-test ---
def _mock_calc_response(payload: dict) -> tuple[int, str]:
    """Stand-in for POST /tools/paycheck-calculator/<State>. Same JSON shape as the live server.
    Clean behaviour = what a correct calculator should do; MOCK_BUG seeds one known bug class."""
    if MOCK_BUG == "err500":
        return 500, '{"error":"boom"}'
    b = payload["basics"]
    gross = sum(D(str(w["wage"])) * D(str(w["hours"])) for w in b["hourlyWages"])
    if MOCK_BUG == "otdrop":
        gross = D(str(b["hourlyWages"][0]["wage"])) * D(str(b["hourlyWages"][0]["hours"]))
    gross = money(gross)
    if MOCK_BUG == "big" and gross > D("1e15"):            # what the live server does with a 1e308 wage
        return 200, ('{"grossPay":"Inf","takeHomePay":{"amount":"NaN","percentage":NaN},"taxes":{"amount":"0.00",'
                     '"details":[]},"fica":{"amount":"Inf","details":[]},"preTax":{"amount":"0.00","details":[]},'
                     '"postTax":{"amount":"0.00","details":[]}}')
    pre = post = s125 = D(0)
    for d in payload.get("deductions", []):
        amt = D(str(d["amount"])) if d["calculationMethod"] == "FixedAmount" else gross * D(str(d["amount"])) / 100
        if d["name"].startswith("Roth"):
            post += amt
        else:
            pre += amt
            if not d["name"].startswith("Retirement"):
                s125 += amt
    year_base = {2025: D("176100"), 2026: D("184500")}.get(int(b["checkDate"][:4]), D("184500"))
    f = fica_employee(gross - s125, 0, wage_base=year_base)
    ss, med, addl = f.social_security, f.medicare, f.additional_medicare
    if MOCK_BUG == "fica":                                   # flat 7.65%, no wage-base cap
        ss, med = money((gross - s125) * D("0.062")), money((gross - s125) * D("0.0145"))
    ex = set(payload.get("exemptions", []))
    ss, med = (D(0) if "Social Security" in ex else ss), (D(0) if "Medicare Tax" in ex else med)
    fit = D(0) if "Federal Income Tax" in ex else money(max(D(0), gross - pre) * D("0.10"))
    fica = ss + med + addl
    net = gross - fit - fica - pre - post

    def g(amount, details=()):
        return {"amount": f"{amount:,.2f}", "percentage": 0.0,
                "details": [{"amount": f"{a:,.2f}", "label": l, "percentage": 0.0} for l, a in details]}
    body = {"grossPay": f"{gross:,.2f}", "takeHomePay": {"amount": f"{net:,.2f}", "percentage": 0.0},
            "taxes": g(fit, [("Federal Income Tax", fit)]),
            "fica": g(fica, [("Social Security", ss), ("Medicare Tax", med), ("Additional Medicare", addl)]),
            "preTax": g(pre), "postTax": g(post)}
    return 200, json.dumps(body)


def make_context(browser, locale="en-US"):
    """Browser context; under USE_MOCK_CALCULATOR the page and its calculation endpoint are served locally."""
    ctx = browser.new_context(locale=locale, viewport={"width": 1280, "height": 1000})
    if USE_MOCK:
        html = MOCK.read_text().replace("__BUG__", MOCK_BUG)
        ctx.route("https://gusto.com/tools/hourly-paycheck-calculator*",
                  lambda r: r.fulfill(status=200, content_type="text/html", body=html))
        ctx.route("**/tools/paycheck-calculator/*",
                  lambda r: r.fulfill(status=(res := _mock_calc_response(json.loads(r.request.post_data)))[0],
                                      content_type="application/json", body=res[1]))
    return ctx


@pytest.fixture(scope="module")
def _ctx(browser):
    ctx = make_context(browser)
    yield ctx
    ctx.close()


@pytest.fixture
def context_factory(browser):
    made = []

    def _make(locale="en-US"):
        made.append(make_context(browser, locale))
        return made[-1]
    yield _make
    for c in made:
        c.close()


def open_calculator(ctx, setup: bool = False):
    from pages.paycheck_calculator_page import BotChallenge, PaycheckCalculatorPage
    page = ctx.new_page()
    try:
        c = PaycheckCalculatorPage(page, pace_s=0 if USE_MOCK else 3.0).open()
    except BotChallenge as e:
        page.close()
        pytest.skip(f"{e} - headless browsers are blocked by gusto.com")
    except PlaywrightError as e:
        page.close()
        if "ERR_" in str(e):
            pytest.skip(f"gusto.com not reachable from this machine: {str(e).splitlines()[0][:120]}")
        raise
    return c.setup() if setup else c


@pytest.fixture
def calculator_opener():
    return open_calculator


@pytest.fixture(scope="module")
def _shared_calc(_ctx):
    """One loaded + filled-in calculator per module: ~10x fewer page loads against gusto.com."""
    c = open_calculator(_ctx, setup=True)
    yield c
    c.page.close()


@pytest.fixture
def calc(_shared_calc):
    """Shared calculator reset to the baseline ($20 x 40 h, weekly, Alabama, no extras) before each test."""
    _shared_calc.type("rate", 20).type("hours", 40).select("frequency", "Weekly")
    return _shared_calc


@pytest.fixture
def fresh_calc(_ctx):
    """A brand-new page, for tests that add overtime rows, deductions or exemptions."""
    c = open_calculator(_ctx, setup=True)
    yield c
    c.page.close()


@pytest.fixture
def blank_calc(_ctx):
    """A freshly opened page with nothing filled in."""
    c = open_calculator(_ctx, setup=False)
    yield c
    c.page.close()


# ---------------------------------------------------------------------- known product defects ---
def pytest_collection_modifyitems(config, items):
    """@pytest.mark.known_defect("DEF-xx", "...") documents a bug confirmed on live gusto.com.
    Live runs: strict xfail - the suite stays green while the bug exists and turns red (XPASS) the day it is
    fixed, so the marker gets removed. Mock runs: the clean mock has no such bug, so the test must PASS."""
    if USE_MOCK:
        return
    for item in items:
        m = item.get_closest_marker("known_defect")
        if m:
            item.add_marker(pytest.mark.xfail(strict=True, reason=f"{m.args[0]}: {m.args[1] if len(m.args) > 1 else ''}"))
