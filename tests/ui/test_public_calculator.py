"""
UI tests on Gusto's PUBLIC hourly paycheck calculator - runnable by anyone, no account needed.

    pytest tests/ui/test_public_calculator.py --headed        # live (headless is blocked by Cloudflare)
    USE_MOCK_CALCULATOR=1 pytest tests/ui/test_public_calculator.py   # framework self-test, offline

Oracle: src/payroll_oracle.py for everything deterministic (gross, Social Security incl. the wage-base cap,
Medicare, Additional Medicare, pre-/post-tax treatment). Income tax is not predicted - only invariants.

Each test carries @pytest.mark.case("TC-PAY-xxx") (see data/test_cases.xlsx). Tests marked
@pytest.mark.known_defect reproduce a bug confirmed on live gusto.com on 2026-11-21 (see FINDINGS.md);
they are strict-xfail live, so the day Gusto fixes one the suite goes red and the marker must be removed.
"""
import re
from decimal import Decimal as D

import pytest

from payroll_oracle import fica_employee, money, weekly_gross_flsa
from pages.paycheck_calculator_page import CALC_ENDPOINT, PaycheckCalculatorPage, to_dec

pytestmark = pytest.mark.ui
case, known_defect = pytest.mark.case, pytest.mark.known_defect


# ----------------------------------------------------------------------------- helpers --
def parts(resp):
    j = resp.json
    return {
        "gross": to_dec(j["grossPay"]), "net": to_dec(j["takeHomePay"]["amount"]),
        "income": to_dec(j["taxes"]["amount"]), "fica": to_dec(j["fica"]["amount"]),
        "pre": to_dec(j["preTax"]["amount"]), "post": to_dec(j["postTax"]["amount"]),
        "ss": resp.detail("fica", "Social Security") or D(0),
        "medicare": resp.detail("fica", "Medicare Tax") or D(0),
        "addl": resp.detail("fica", "Additional Medicare") or D(0),
    }


def check_paycheck(calc: PaycheckCalculatorPage, resp, *, gross, fica_wages=None):
    """The three checks every calculation gets:
    1. server numbers match the oracle (gross, SS, Medicare, Additional Medicare);
    2. net + every tax + every deduction == gross, to the cent;
    3. the panel shows exactly what the server returned (no display/rounding drift)."""
    assert resp.status == 200, resp.text[:300]
    p = parts(resp)
    f = fica_employee(gross if fica_wages is None else fica_wages)
    assert p["gross"] == money(gross)
    assert (p["ss"], p["medicare"], p["addl"]) == (f.social_security, f.medicare, f.additional_medicare)
    assert p["fica"] == p["ss"] + p["medicare"] + p["addl"]
    assert p["net"] + p["income"] + p["fica"] + p["pre"] + p["post"] == p["gross"], p
    ui = calc.results()
    for row, key in (("Gross pay", "gross"), ("Income taxes", "income"), ("FICA taxes", "fica"),
                     ("Pre-tax", "pre"), ("Post-tax", "post"), ("Take home pay", "net")):
        assert ui[row].amount == p[key], f"panel {row} {ui[row].raw!r} != server {p[key]}"
    return p


# --------------------------------------------------------------------- positive / oracle --
@pytest.mark.smoke
@case("TC-PAY-074")
def test_baseline_weekly_paycheck_matches_oracle(calc):
    """$20 x 40 h weekly: gross $800.00, SS $49.60, Medicare $11.60 (hand-computed)."""
    p = check_paycheck(calc, calc.calculate(), gross=D("800"))
    assert (p["ss"], p["medicare"]) == (D("49.60"), D("11.60"))


@case("TC-PAY-075")
def test_overtime_field_pays_the_premium(fresh_calc):
    """12 h overtime at $30 on top of 40 h at $20 = Gusto OT-article example: $1,160.00."""
    fresh_calc.add_overtime(30, 12)
    p = check_paycheck(fresh_calc, fresh_calc.calculate(), gross=weekly_gross_flsa(20, 52))
    assert p["gross"] == D("1160.00")


@case("TC-PAY-076")
@pytest.mark.parametrize("rate,hours", [(20, "40.01"), (20, "0.001"), ("7.25", 1), (20, 168), (20, 60)])
def test_gross_is_rate_times_regular_hours_and_fica_rounds_per_tax(calc, rate, hours):
    """Boundaries: 0.01 h past 40, sub-cent gross, federal minimum wage x 1 h (SS 0.45 + Medicare 0.11 rounded
    separately = 0.56; one combined 7.65% would give 0.55), and the physical weekly maximum."""
    calc.type("rate", rate).type("hours", hours)
    check_paycheck(calc, calc.calculate(), gross=money(D(str(rate)) * D(str(hours))))


@case("TC-PAY-077")
@pytest.mark.parametrize("rate,ss,medicare,addl", [
    (5000, "11439.00", "2900.00", "0.00"),     # $200,000: SS capped at $184,500 x 6.2%; exactly at 200k -> no addl
    (10000, "11439.00", "5800.00", "1800.00"),  # $400,000: 0.9% on the $200,000 above the threshold
])
def test_social_security_wage_base_and_additional_medicare(calc, rate, ss, medicare, addl):
    calc.type("rate", rate)
    p = check_paycheck(calc, calc.calculate(), gross=D(rate) * 40)
    assert (p["ss"], p["medicare"], p["addl"]) == (D(ss), D(medicare), D(addl))


@case("TC-PAY-078")
def test_tax_year_follows_the_check_date(fresh_calc):
    """2025 check date -> 2025 wage base $176,100 -> SS $10,918.20 on a $200,000 check (2026 would be $11,439)."""
    fresh_calc.type("rate", 5000).set_check_year(2025)
    p = parts(fresh_calc.calculate())
    assert p["ss"] == money(D("176100") * D("0.062")) == D("10918.20")


@case("TC-PAY-079")
@pytest.mark.parametrize("name,fica_exempt,pre,post", [
    ("Retirement401k", False, "100.00", "0.00"),   # traditional 401(k): lowers income-tax wages only
    ("MedicalInsurance", True, "100.00", "0.00"),  # Section 125: lowers FICA wages too
    ("HsaIndividual", True, "100.00", "0.00"),
    ("Roth401k", False, "0.00", "100.00"),          # post-tax: changes nothing but net
])
def test_deduction_tax_treatment(fresh_calc, name, fica_exempt, pre, post):
    base = parts(fresh_calc.calculate())
    fresh_calc.add_deduction(name, "FixedAmount", 100)
    p = check_paycheck(fresh_calc, fresh_calc.calculate(), gross=D(800), fica_wages=D(700) if fica_exempt else D(800))
    assert (p["pre"], p["post"]) == (D(pre), D(post))
    if D(pre):
        assert p["income"] < base["income"], "pre-tax deduction must lower income tax"
    else:
        assert p["income"] == base["income"], "post-tax deduction must not change income tax"


@case("TC-PAY-080")
@pytest.mark.parametrize("tax,ss,medicare", [("Social Security", "0.00", "11.60"), ("Medicare Tax", "49.60", "0.00")])
def test_fica_exemptions(fresh_calc, tax, ss, medicare):
    fresh_calc.exempt(tax)
    p = parts(fresh_calc.calculate())
    assert (p["ss"], p["medicare"]) == (D(ss), D(medicare))
    assert p["net"] + p["income"] + p["fica"] == p["gross"]


@case("TC-PAY-081")
def test_more_hours_always_increase_net_pay(calc):
    last = D(-1)
    for h in (1, 10, 39, 40, 41, 60):
        calc.type("hours", h)
        net = parts(calc.calculate())["net"]
        assert net > last, f"net pay did not increase at {h}h: {net} <= {last}"
        last = net


# ------------------------------------------------------------------- negative / security --
@case("TC-PAY-082")
@pytest.mark.parametrize("field,value", [("rate", -20), ("rate", 0), ("rate", "abc"), ("hours", -5), ("hours", 0), ("hours", "xyz")])
def test_invalid_input_is_flagged_and_blocks_calculate(calc, field, value):
    calc.type(field, value)
    assert calc.is_invalid(field), f"{field}={value!r} accepted"
    assert not calc.can_calculate(), "Calculate must stay disabled while an input is invalid"


@case("TC-PAY-083")
@pytest.mark.parametrize("payload", ["<img src=x onerror=window.__pwned=1>", "<svg onload=window.__pwned=1>"])
def test_script_in_numeric_field_is_not_executed(calc, payload):
    """onerror/onload handlers fire asynchronously (after the failed image request), so give them time.
    The first version checked immediately and missed a seeded XSS bug in the self-test."""
    calc.type("rate", payload)
    calc.page.wait_for_timeout(1500)
    assert calc.page.evaluate("() => window.__pwned") is None, "payload executed"
    assert calc.is_invalid("rate")


# --------------------------------------------------------------- confirmed product defects --
@case("TC-PAY-084")
@known_defect("DEF-01", "fixed-dollar deduction larger than gross is accepted; take-home goes negative")
@pytest.mark.parametrize("name,amount", [("Retirement401k", 1000), ("Roth401k", 1000), ("MedicalInsurance", 900)])
def test_deduction_larger_than_gross_never_gives_negative_take_home(fresh_calc, name, amount):
    """$800 gross. Percent deductions >= 100% are blocked; fixed-dollar ones are not, and the live page shows
    e.g. 'Take home pay -32.65% -$261.20'. Expected: blocked, or capped so that net is never negative."""
    fresh_calc.add_deduction(name, "FixedAmount", amount)
    if fresh_calc.can_calculate():
        p = parts(fresh_calc.calculate())
        assert p["net"] >= 0, f"take-home {p['net']} with a ${amount} {name} on ${p['gross']} gross"


@case("TC-PAY-085")
@known_defect("DEF-02", "wage 1e308 passes validation; server answers HTTP 200 with Inf/NaN (invalid JSON); user gets a generic 'something went wrong' instead of a validation message")
def test_absurd_wage_is_rejected_not_rendered_as_zero(calc):
    calc.type("rate", "1e308")
    if not calc.can_calculate():
        return  # rejected up front: correct
    resp = calc.calculate()
    assert not re.search(r"\b(Inf|Infinity|NaN)\b", resp.text), f"server returned non-finite money: {resp.text[:200]}"
    assert calc.gross_pay() not in (None, D(0)), "valid-looking input produced a silent $0.00 paycheck"


@case("TC-PAY-086")
def test_failed_calculation_is_reported_to_the_user(fresh_calc):
    """Fault injection: the calculation endpoint answers 500 (the live site also returns 429/422 under load).
    Live gusto.com PASSES this: it shows 'We could not calculate this paycheck'. DEF-03 ('silent $0.00') was
    raised from a manual probe that only read the result panel, and was withdrawn when this test XPASSed."""
    page = fresh_calc.page
    before = fresh_calc.visible_error_text()
    page.route(CALC_ENDPOINT, lambda r: r.fulfill(status=500, content_type="application/json", body='{"error":"x"}'))
    resp = fresh_calc.calculate()
    assert resp.status == 500
    after = fresh_calc.visible_error_text()
    shows_zero = fresh_calc.net_pay() == D(0)
    assert after != before or not shows_zero, "request failed, but the page shows 'Take home pay $0.00' and no error"


@case("TC-PAY-087")
@known_defect("DEF-04", "a WEEKLY pay period accepts more than 168 regular hours")
@pytest.mark.parametrize("hours", [169, 1000])
def test_weekly_hours_cannot_exceed_hours_in_a_week(calc, hours):
    calc.type("hours", hours)
    assert calc.is_invalid("hours") or not calc.can_calculate(), f"{hours} h accepted for one week"


@case("TC-PAY-088")
@known_defect("DEF-05", "'20,5' is read as $205.00/h (comma dropped) without any warning")
def test_decimal_comma_is_not_silently_multiplied_by_ten(calc):
    calc.type("rate", "20,5")
    shown = D(calc.value("rate").replace(",", "") or "0")
    assert calc.is_invalid("rate") or shown in (D("20.5"), D("20.50")), f"'20,5' became {calc.value('rate')}"


@case("TC-PAY-089")
@known_defect("DEF-06", "date hint says MM/DD/YYYY but en-GB / en-IN browsers get the field in DD/MM/YYYY order")
@pytest.mark.parametrize("locale", ["en-GB", "en-IN"])
def test_date_format_hint_matches_the_field_for_every_locale(context_factory, calculator_opener, locale):
    c = calculator_opener(context_factory(locale))
    hint = re.search(r"\((MM|DD)/(DD|MM)/YYYY\)", c.page.get_by_text(re.compile("When will your employee be paid")).first.inner_text())
    order = c.page.locator("[aria-label='Day (dd)'], [aria-label='Month (mm)']").evaluate_all(
        "els => els.map(e => e.getAttribute('aria-label').slice(0, 1) === 'D' ? 'DD' : 'MM')")
    if hint:
        assert [hint.group(1), hint.group(2)] == order[:2], f"hint {hint.group(0)} but field order {order}"


@case("TC-PAY-090")
@known_defect("DEF-07", "hourly-wage helper text shows the overtime definition")
def test_wage_helper_text_describes_the_wage(blank_calc):
    assert "40 hours per workweek" not in blank_calc.field_message("rate")


@case("TC-PAY-091")
@known_defect("DEF-08", "an overtime rate below the regular rate is accepted silently")
def test_overtime_rate_below_regular_rate_is_flagged(fresh_calc):
    fresh_calc.add_overtime(10, 12)  # regular rate is $20; FLSA needs >= $30
    assert fresh_calc.is_invalid("ot_rate") or re.search(r"(lower|less|at least|1\.5)", fresh_calc.field_message("ot_rate"), re.I)


@case("TC-PAY-092")
@known_defect("DEF-09", "accepting the cookie banner reloads the page and wipes everything already typed")
def test_accepting_cookies_keeps_what_the_user_typed(context_factory):
    page = context_factory().new_page()
    c = PaycheckCalculatorPage(page)
    page.goto("https://gusto.com/tools/hourly-paycheck-calculator", wait_until="domcontentloaded")
    if "just a moment" in page.title().lower():
        pytest.skip("Cloudflare challenge; run with --headed")
    c._wait_ready()
    btn = page.locator("#onetrust-accept-btn-handler")
    btn.wait_for(state="visible", timeout=15_000)
    c.type("rate", 35)
    btn.click()
    page.wait_for_timeout(5_000)
    c._wait_ready()
    assert c.value("rate").replace(",", "") in ("35", "35.00"), f"wage after accepting cookies: {c.value('rate')!r}"
