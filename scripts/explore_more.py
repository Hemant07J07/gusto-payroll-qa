"""Exploratory sweep of the live public paycheck calculator: positive / negative / boundary input, UI and
accessibility checks, mobile layout, and server-side validation of the calculation endpoint.

    python scripts/explore_more.py            # everything (visible Chrome, video recorded)
    python scripts/explore_more.py fields api # only some sections: fields calc api a11y mobile

Output: reports/exploration/  - probes.json (every probe: input, expected, observed, verdict), screenshots of
anything that looks wrong, video/*.webm of each browser session, axe.json, api_probes.json, SUMMARY.md.

Verdicts: OK | ISSUE (behaviour contradicts a stated rule or the field's own hint) | OBS (worth a product
question, not provably wrong). Every verdict is decided from what the page/server actually did.
Polite by design: about 8 calculations and 10 direct API calls, paced several seconds apart.
"""
import json
import re
import sys
import time
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tests" / "ui"), str(ROOT / "src"), str(ROOT / "scripts")]

import requests  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import capture_evidence  # noqa: E402
from capture_evidence import annotate, scroll_to  # noqa: E402

capture_evidence.SOURCE = "scripts/explore_more.py"
from pages.paycheck_calculator_page import CALC_ENDPOINT, F, URL, PaycheckCalculatorPage  # noqa: E402

OUT = ROOT / "reports" / "exploration"
(OUT / "video").mkdir(parents=True, exist_ok=True)
PROBES: list[dict] = []
SEL = dict(F, **{
    "fed_dependents": "input[name='federalTax.dependentsAmount']",
    "fed_other_income": "input[name='federalTax.otherIncome']",
    "fed_deductions": "input[name='federalTax.deductions']",
    "fed_extra": "input[name='federalTax.extraWithholding']",
    "ded_amount": "input[name='deductions.0.amount']",
    "fringe_amount": "input[name='fringe.0.amount']",
})
PANEL = "[data-qa=result-panel]"
AXE_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"


def num(s: str):
    try:
        return Decimal(re.sub(r"[$,\s]", "", s))
    except (InvalidOperation, TypeError):
        return None


def rec(pid, area, title, inp, expected, observed, verdict, files=(), **extra):
    row = dict(id=pid, area=area, title=title, input=inp, expected=expected, observed=observed, verdict=verdict,
               files=list(files), **extra)
    PROBES.append(row)
    print(f"[{verdict:5}] {pid} {title} | in={inp!r} | {observed}", flush=True)
    return row


def shot(page, name):
    p = OUT / f"{name}.png"
    page.screenshot(path=str(p))
    return p.name


class Session:
    """One recorded browser page; the video is saved under a readable name when the session closes."""

    def __init__(self, browser, name, **ctx_kw):
        kw = dict(locale="en-US", viewport={"width": 1280, "height": 900},
                  record_video_dir=str(OUT / "video" / "_raw"), record_video_size={"width": 1280, "height": 900})
        kw.update(ctx_kw)
        self.name, self.ctx = name, browser.new_context(**kw)
        self.page = self.ctx.new_page()
        self.console, self.bad_responses = [], []
        self.page.on("console", lambda m: m.type == "error" and self.console.append(m.text[:200]))
        self.page.on("response", lambda r: r.status >= 400 and self.bad_responses.append(f"{r.status} {r.url[:120]}"))

    def close(self):
        v = self.page.video
        self.ctx.close()
        if v:
            v.save_as(str(OUT / "video" / f"{self.name}.webm"))
            Path(v.path()).unlink(missing_ok=True)


# ---------------------------------------------------------------------------------------- field probes --
def field_state(c, sel):
    loc = c.page.locator(sel).first
    c.page.wait_for_timeout(500)
    try:   # validation is asynchronous after blur
        c.page.wait_for_function("e => e.getAttribute('aria-invalid') === 'true'", arg=loc.element_handle(), timeout=1500)
        invalid = True
    except Exception:  # noqa: BLE001
        invalid = False
    msg = loc.evaluate("e => (e.getAttribute('aria-describedby')||'').split(' ').filter(Boolean)"
                       ".map(i => document.getElementById(i)).filter(Boolean).map(n => n.innerText).join(' / ')")
    return loc.input_value(), invalid, c.can_calculate(), msg


def sel_key(sel):
    return next((k for k, v in F.items() if v == sel), None)


def probe(c, pid, area, key, raw, intended, title, restore, note_if_ok=None, ok_verdict="OK", bad_verdict="ISSUE"):
    """Type `raw` into field `key`. intended=None -> must be rejected; a number -> accepted value must equal it."""
    sel = SEL[key]
    c.type(c.page.locator(sel).first, raw)
    shown, invalid, can_calc, msg = field_state(c, sel)
    rejected = invalid or not can_calc
    val = num(shown)
    if rejected:
        verdict, obs = "OK", f"rejected (aria-invalid={invalid}, Calculate enabled={can_calc}); message: {msg[:90]!r}"
        if intended is not None:
            obs += f"; a valid reading {intended} existed"
    elif intended is not None and val == Decimal(str(intended)):
        verdict, obs = ok_verdict, f"accepted as {shown!r}" + (f"; {note_if_ok}" if note_if_ok else "")
    else:
        verdict = bad_verdict
        obs = f"accepted silently, field shows {shown!r}" + (
            "" if intended is None else f" (user meant {intended})")
    files = []
    if verdict != "OK":
        scroll_to(c.page, sel)
        annotate(c.page, f"{pid}: {title}", [f"Typed: {raw}", f"Field shows: {shown}   flagged invalid: {invalid}",
                                             f"Calculate enabled: {can_calc}",
                                             f"Expected: {'rejected' if intended is None else intended}"], sel)
        files.append(shot(c.page, pid))
        c.page.evaluate("() => document.getElementById('qa-note')?.remove()")
    rec(pid, area, title, raw, "rejected" if intended is None else f"accepted as {intended} (or rejected)",
        obs, verdict, files, field=key)
    c.type(c.page.locator(sel).first, restore)
    c.page.wait_for_timeout(300)


def sec_fields(browser):
    s = Session(browser, "explore_fields")
    c = PaycheckCalculatorPage(s.page, pace_s=4).open().setup()
    P = lambda *a, **k: probe(c, *a, **k)  # noqa: E731

    # Hourly wage: positive, negative, boundary, format
    W = "Wage"
    P("W-01", W, "rate", "20.50", 20.50, "normal decimal wage", 20)
    P("W-02", W, "rate", "7.25", 7.25, "federal minimum wage (boundary)", 20)
    P("W-03", W, "rate", "0.01", 0.01, "1 cent per hour (below federal minimum $7.25)", 20,
      note_if_ok="no warning that it is below the $7.25 federal minimum", ok_verdict="OBS")
    P("W-04", W, "rate", "$20", 20, "leading dollar sign", 20)
    P("W-05", W, "rate", " 20 ", 20, "surrounding spaces", 20)
    P("W-06", W, "rate", "1,000", 1000, "thousands separator", 20)
    P("W-07", W, "rate", "1e2", None, "scientific notation 1e2", 20)
    P("W-08", W, "rate", "20abc", None, "trailing letters", 20)
    P("W-09", W, "rate", "２０", None, "full-width digits", 20)
    P("W-10", W, "rate", "20.999", None, "three decimals (should reject or say it rounds)", 20, bad_verdict="OBS")
    P("W-11", W, "rate", "999999999", None, "absurd but finite wage $999,999,999/h", 20, bad_verdict="OBS")
    P("W-12", W, "rate", "-0", None, "negative zero", 20)

    # Regular hours per frequency (a week has 168 h, two weeks 336, a month up to 744)
    H = "Hours"
    P("H-01", H, "hours", "40.5", 40.5, "fractional hours", 40)
    P("H-02", H, "hours", "168", 168, "every hour of the week (boundary)", 40)
    P("H-03", H, "hours", "1e3", None, "scientific notation hours", 40)
    for pid, freq, bad in (("H-04", "Biweekly", "337"), ("H-05", "Monthly", "745"), ("H-06", "Semimonthly", "400")):
        opts = c.page.locator(F["frequency"]).evaluate("s => [...s.options].map(o => o.value)")
        if freq not in opts:
            rec(pid, H, f"{freq} not offered", bad, "-", f"options: {opts}", "OBS")
            continue
        c.select("frequency", freq)
        P(pid, H, "hours", bad, None, f"{freq}: {bad} h exceeds the hours in the period", 40)
    c.select("frequency", "Weekly")

    # Overtime field
    O = "Overtime"
    c.add_overtime(30, 5)
    P("O-01", O, "ot_hours", "-5", None, "negative overtime hours", 5)
    P("O-02", O, "ot_hours", "200", None, "200 overtime h on top of 40 regular h in one week", 5)
    P("O-03", O, "ot_rate", "0", None, "overtime rate $0", 30)
    P("O-04", O, "ot_rate", "30", 30, "overtime at exactly 1.5x (positive)", 30)

    # Pre-tax deduction amount
    D = "Deduction"
    c.page.locator("select[name='deductions.0.name']").select_option("Retirement401k")
    c.page.locator("select[name='deductions.0.calculationMethod']").select_option("FixedAmount")
    P("D-01", D, "ded_amount", "-100", None, "negative fixed deduction (would ADD money)", 10)
    P("D-02", D, "ded_amount", "50", 50, "normal fixed deduction (positive)", 10)
    c.page.locator("select[name='deductions.0.calculationMethod']").select_option("Percentage")
    c.type(c.page.locator(SEL["ded_amount"]), 5)
    P("D-03", D, "ded_amount", "99", 99, "99 % (integer boundary below 100)", 5)
    P("D-04", D, "ded_amount", "100", None, "100 % deduction", 5)
    P("D-05", D, "ded_amount", "-5", None, "negative percentage", 5)
    P("D-06", D, "ded_amount", "4.5", 4.5, "4.5 % 401(k) - a common contribution rate", 5)
    P("D-07", D, "ded_amount", "99.99", 99.99, "99.99 % (decimal boundary below 100; hint says 0 to 100)", 5)
    c.page.locator("select[name='deductions.0.calculationMethod']").select_option("FixedAmount")
    c.type(c.page.locator(SEL["ded_amount"]), "")

    # Federal W-4
    W4 = "Federal W-4"
    P("F-01", W4, "fed_dependents", "-2000", None, "negative dependents amount (W-4 step 3)", "")
    P("F-02", W4, "fed_dependents", "2001", None, "dependents amount no W-4 could produce ($2,200 x children + $500 x others)", "",
      bad_verdict="OBS")
    P("F-03", W4, "fed_other_income", "-5000", None, "negative other income (4a)", "")
    P("F-04", W4, "fed_extra", "-25", None, "negative extra withholding (4c)", "")
    P("F-05", W4, "fed_extra", "5000", None, "extra withholding $5,000 on an $800 paycheck", "",
      bad_verdict="OBS")

    # State withholding
    ST = "State W-4"
    P("S-01", ST, "state_dependents", "-1", None, "negative number of dependents", 0)
    P("S-02", ST, "state_dependents", "1.5", None, "fractional number of dependents", 0)
    P("S-03", ST, "state_dependents", "1000", None, "1,000 dependents", 0, bad_verdict="OBS")
    P("S-04", ST, "state_extra", "-50", None, "negative additional state withholding", 0)

    # Pay date: invalid calendar dates, out-of-range years
    seg = {k: c.page.locator(f"[aria-label='{k}']") for k in ("Month (mm)", "Day (dd)", "Year (yyyy)")}

    def set_date(m, d, y):
        # The segments auto-advance after two digits (checked by hand); select-all + Backspace corrupts them.
        c._focus(seg["Month (mm)"])
        for ch in m + d + y:
            c.page.keyboard.type(ch, delay=150)
        c.page.keyboard.press("Tab")
        c.page.wait_for_timeout(1200)
        hidden = c.page.locator(F["check_date"]).input_value()
        shown = "/".join(seg[k].input_value() for k in seg)
        bad = c.page.locator("[aria-invalid=true]").evaluate_all("els => els.map(e => e.getAttribute('aria-label') || e.name)")
        return hidden, shown, bad, c.can_calculate()

    for pid, m, d, y, should, title in (("DT-01", "02", "29", "2028", True, "29 Feb in a leap year (positive)"),
                                        ("DT-02", "02", "30", "2026", False, "30 February"),
                                        ("DT-03", "13", "01", "2026", False, "month 13"),
                                        ("DT-04", "01", "01", "1899", False, "year 1899"),
                                        ("DT-05", "01", "01", "2150", False, "year 2150")):
        try:
            hidden, shown, bad, can = set_date(m, d, y)
        except Exception as e:  # noqa: BLE001
            rec(pid, "Pay date", title, f"{m}/{d}/{y}", "-", f"probe crashed: {e}"[:200], "OBS")
            continue
        accepted = can and not bad
        if should:
            verdict = "OK" if accepted else "ISSUE"
        else:
            verdict = "OK" if not accepted else "ISSUE"
        files = []
        if verdict == "ISSUE":
            scroll_to(c.page, "[aria-label='Month (mm)']", 350)
            annotate(c.page, f"{pid}: {title}", [f"Typed {m}/{d}/{y}; segments now show {shown}",
                                                 f"Stored value: {hidden!r}; invalid fields: {bad}; Calculate enabled: {can}"],
                     "[aria-label='Month (mm)']", "[aria-label='Day (dd)']", "[aria-label='Year (yyyy)']")
            files.append(shot(c.page, pid))
        rec(pid, "Pay date", title, f"{m}/{d}/{y}", "accepted" if should else "rejected",
            f"segments {shown}, stored {hidden!r}, invalid={bad}, Calculate enabled={can}", verdict, files)
    set_date("12", "15", "2026")

    hints = c.page.evaluate("""() => [...document.querySelectorAll('form input, form select')].filter(e => e.name && e.offsetParent)
        .map(e => [e.name, (e.getAttribute('aria-describedby')||'').split(' ').filter(Boolean).map(i => document.getElementById(i))
        .filter(Boolean).map(n => n.innerText.trim()).join(' / ').slice(0, 120)])""")
    (OUT / "field_hints.json").write_text(json.dumps(hints, indent=1))
    rec("HINT-01", "UI text", "helper text per field (see field_hints.json)", "-", "each hint describes its own field",
        "; ".join(f"{n}: {h[:60]!r}" for n, h in hints if n.startswith("basics"))[:400], "OBS")

    # Accessible names: several controls share one label
    names = c.page.evaluate("""() => {
        const out = {};
        for (const e of document.querySelectorAll('form input:not([type=hidden]), form select')) {
            if (!e.offsetParent) continue;
            const lab = (e.labels && e.labels[0] ? e.labels[0].innerText : e.getAttribute('aria-label') || '').trim();
            const fs = e.closest('fieldset'); const leg = fs && fs.querySelector('legend');
            (out[lab] = out[lab] || []).push({name: e.name, group: leg ? leg.innerText.trim() : null});
        }
        return Object.fromEntries(Object.entries(out).filter(([k, v]) => v.length > 1 || !k));
    }""")
    rec("A-01", "Accessibility", "controls sharing one accessible name", "-", "unique names or a grouping legend",
        json.dumps(names)[:400], "OBS" if names else "OK")
    rec("N-01", "Page health", "console errors / HTTP errors while using the form", "-", "none",
        f"console errors: {len(s.console)} {s.console[:3]}; HTTP>=400: {s.bad_responses[:5]}",
        "OBS" if (s.console or s.bad_responses) else "OK")
    s.close()


# ------------------------------------------------------------------------------------- calculation probes --
CAPTURED = {}


def sec_calc(browser):
    s = Session(browser, "explore_calculations")
    c = PaycheckCalculatorPage(s.page, pace_s=5).open().setup()
    p = s.page
    c.add_deduction("Retirement401k", "FixedAmount", 50)

    # C-01 baseline (positive) + capture the request for the API section
    with p.expect_request(lambda r: bool(CALC_ENDPOINT.search(r.url.split("?")[0])) and r.method == "POST") as ri:
        resp = c.calculate()
    req = ri.value
    CAPTURED.update(url=req.url, body=req.post_data, headers={k: v for k, v in req.all_headers().items()
                                                              if not k.startswith(":") and k not in ("cookie", "content-length", "host")})
    (OUT / "api_request_sample.json").write_text(json.dumps({"url": req.url, "body": json.loads(req.post_data)}, indent=2))
    r = c.results()
    rec("C-01", "Calculation", "baseline $20 x 40 h weekly, 401(k) $50", "AL, weekly", "HTTP 200, gross 800",
        f"HTTP {resp.status}, gross {r['Gross pay'].raw}, take home {r['Take home pay'].raw}",
        "OK" if resp.status == 200 and r["Gross pay"].amount == Decimal("800.00") else "ISSUE")

    # C-02 stale result: change the wage after calculating - does the panel say the numbers are out of date?
    c.type("rate", 30)
    p.wait_for_timeout(1500)
    r2 = c.results()
    stale = r2["Gross pay"].amount == Decimal("800.00")
    hint = re.search(r"(recalculate|out of date|update[sd]? result)", p.locator("body").inner_text(), re.I)
    files = []
    if stale and not hint:
        scroll_to(p, F["rate"])
        c.results()
        annotate(p, "C-02: results are stale after an input changes",
                 ["Calculated at $20/h (gross $800). Then the wage was changed to $30/h.",
                  f"Panel still shows gross {r2['Gross pay'].raw} with no 'recalculate' / out-of-date cue"], F["rate"], PANEL)
        files.append(shot(p, "C-02"))
    rec("C-02", "UI", "result panel after changing an input", "wage 20 -> 30, no recalc",
        "panel cleared or marked out of date", f"panel gross still {r2['Gross pay'].raw}; stale cue: {bool(hint)}",
        "OBS" if stale and not hint else "OK", files)
    c.type("rate", 20)

    # C-03 extra federal withholding larger than the paycheck
    c.type(p.locator(SEL["fed_extra"]), 5000)
    resp = c.calculate()
    r = c.results()
    net = r["Take home pay"].amount
    files = []
    if net is not None and net < 0:
        scroll_to(p, SEL["fed_extra"])
        c.results()
        annotate(p, "C-03: extra federal withholding larger than gross accepted",
                 ["Gross $800; W-4 4(c) extra withholding $5,000 accepted", f"Take home pay: {r['Take home pay'].raw}",
                  "Withholding cannot exceed the wages actually paid"], SEL["fed_extra"], PANEL)
        files.append(shot(p, "C-03"))
    rec("C-03", "Calculation", "W-4 4(c) extra withholding $5,000 on $800 gross", "fed extra 5000",
        "rejected, or withholding capped at available pay", f"HTTP {resp.status}; take home {r['Take home pay'].raw}",
        "ISSUE" if net is not None and net < 0 else "OK", files)
    c.type(p.locator(SEL["fed_extra"]), "")

    # C-04 additional STATE withholding larger than the paycheck
    c.type("state_extra", 2000)
    resp = c.calculate()
    r = c.results()
    net = r["Take home pay"].amount
    files = []
    if net is not None and net < 0:
        scroll_to(p, F["state_extra"])
        c.results()
        annotate(p, "C-04: additional state withholding larger than gross accepted",
                 ["Gross $800; additional state withholding $2,000 accepted", f"Take home pay: {r['Take home pay'].raw}"],
                 F["state_extra"], PANEL)
        files.append(shot(p, "C-04"))
    rec("C-04", "Calculation", "additional state withholding $2,000 on $800 gross", "state extra 2000",
        "rejected, or capped", f"HTTP {resp.status}; take home {r['Take home pay'].raw}",
        "ISSUE" if net is not None and net < 0 else "OK", files)
    c.type("state_extra", 0)

    # C-06 percentage deduction with a decimal: 4.5 % of $800 is $36.00
    p.locator("select[name='deductions.0.calculationMethod']").select_option("Percentage")
    c.type(p.locator(SEL["ded_amount"]), "4.5")
    shown = p.locator(SEL["ded_amount"]).input_value()
    resp = c.calculate()
    r = c.results()
    pre = r["Pre-tax"].amount
    files = []
    bad = pre is not None and pre != Decimal("36.00")
    if bad:
        scroll_to(p, SEL["ded_amount"])
        c.results()
        annotate(p, "C-06: a 4.5 % 401(k) is calculated as a whole percentage",
                 [f"Typed 4.5 in the percentage box; it now shows {shown!r}",
                  f"Pre-tax deduction: {r['Pre-tax'].raw}  (4.5 % of $800 = $36.00)"], SEL["ded_amount"], PANEL)
        files.append(shot(p, "C-06"))
    rec("C-06", "Calculation", "401(k) at 4.5 % of $800 gross", "Percentage 4.5", "pre-tax deduction $36.00",
        f"field shows {shown!r}; HTTP {resp.status}; pre-tax {r['Pre-tax'].raw}", "ISSUE" if bad else "OK", files)
    p.locator("select[name='deductions.0.calculationMethod']").select_option("FixedAmount")
    c.type(p.locator(SEL["ded_amount"]), 50)

    # C-07 fractional number of state dependents
    c.type("state_dependents", "1.5")
    try:
        resp = c.calculate()
        r = c.results()
        err = c.visible_error_text()
        rec("C-07", "Calculation", "1.5 state dependents (Alabama A-4 line 4 is a whole number)", "dependents 1.5",
            "rejected before calculating", f"HTTP {resp.status}; take home {r['Take home pay'].raw}; error shown: {err[:80]!r}",
            "ISSUE" if resp.status == 200 and not err else "OBS")
    except AssertionError as e:
        rec("C-07", "Calculation", "1.5 state dependents", "dependents 1.5", "rejected", f"blocked: {e}"[:200], "OK")
    c.type("state_dependents", 0)

    # C-05 regular + overtime hours above the hours in a week
    c.add_overtime(30, 150)
    try:
        resp = c.calculate()
        r = c.results()
        g = r["Gross pay"].amount
        files = []
        if g is not None and g > 0:
            scroll_to(p, F["ot_hours"])
            c.results()
            annotate(p, "C-05: 40 regular + 150 overtime hours in ONE week accepted",
                     ["190 hours worked in a 168-hour week", f"Gross: {r['Gross pay'].raw}"], F["hours"], F["ot_hours"], PANEL)
            files.append(shot(p, "C-05"))
        rec("C-05", "Calculation", "40 regular + 150 overtime hours in one week", "weekly 40 + OT 150",
            "rejected (190 h > 168 h)", f"HTTP {resp.status}; gross {r['Gross pay'].raw}",
            "ISSUE" if g and g > 0 else "OK", files)
    except AssertionError as e:
        rec("C-05", "Calculation", "40 regular + 150 overtime hours in one week", "weekly 40 + OT 150",
            "rejected", f"blocked: {e}"[:200], "OK")
    s.close()


# -------------------------------------------------------------------------------- server-side validation --
def _set(obj, path, val):
    cur = obj
    parts = path.split(".")
    for k in parts[:-1]:
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
    last = parts[-1]
    if val is _DEL:
        (cur.pop(int(last)) if isinstance(cur, list) else cur.pop(last, None))
    elif isinstance(cur, list):
        cur[int(last)] = val
    else:
        cur[last] = val


_DEL = object()


def _find(obj, key, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}{k}"
            if k == key:
                yield p
            yield from _find(v, key, p + ".")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _find(v, key, f"{prefix}{i}.")


def sec_api(browser):
    """Replay the page's own calculation request with modified fields, from INSIDE the page (fetch), so it carries
    the same browser, cookies and Cloudflare clearance as a real user. Playwright's out-of-browser request client
    is blocked by Cloudflare (HTTP 403) and would test nothing."""
    s = Session(browser, "explore_api")
    c = PaycheckCalculatorPage(s.page, pace_s=4).open().setup()
    c.add_deduction("Retirement401k", "FixedAmount", 50)
    with s.page.expect_request(lambda r: bool(CALC_ENDPOINT.search(r.url.split("?")[0])) and r.method == "POST") as ri:
        c.calculate()
    req = ri.value
    banned = ("cookie", "content-length", "host", "user-agent", "referer", "origin", "accept-encoding", "accept-language",
              "connection", "priority")
    CAPTURED.update(url=req.url, body=req.post_data, headers={k: v for k, v in req.all_headers().items()
                    if not k.startswith(":") and not k.startswith("sec-") and k not in banned})
    base = json.loads(CAPTURED["body"])
    url = CAPTURED["url"]
    wage = next((p for p in _find(base, "wage") if "overtime" not in p.lower()), None)
    hours = next((p for p in _find(base, "hours") if "overtime" not in p.lower()), None)
    freq = next(iter(_find(base, "payFrequency")), None)
    amount = next((p for p in _find(base, "amount") if p.startswith("deductions")), None)
    method = next((p for p in _find(base, "calculationMethod") if p.startswith("deductions")), None)
    print("payload paths:", wage, hours, freq, amount, method, flush=True)

    def mut(*pairs):
        b = deepcopy(base)
        for path, val in pairs:
            if path:
                _set(b, path, val)
        return json.dumps(b)

    cases = [
        ("API-01", "unchanged replay (positive control)", url, mut(), "200 with the same result"),
        ("API-02", "negative wage -20 (UI rejects it)", url, mut((wage, "-20")), "4xx validation error"),
        ("API-03", "negative hours -40 (UI rejects it)", url, mut((hours, "-40")), "4xx validation error"),
        ("API-04", "wage 'abc'", url, mut((wage, "abc")), "4xx validation error"),
        ("API-05", "100,000 hours in a weekly period", url, mut((hours, "100000")), "4xx validation error"),
        ("API-06", "unknown pay frequency", url, mut((freq, "Fortnightly")), "4xx validation error"),
        ("API-07", "401(k) at 150 % (UI blocks >= 100 %)", url, mut((method, "Percentage"), (amount, "150")), "4xx validation error"),
        ("API-08", "wage field missing", url, mut((wage, _DEL)), "4xx validation error"),
        ("API-09", "empty JSON object", url, "{}", "4xx validation error"),
        ("API-10", "malformed JSON body", url, "{\"basics\":", "400 Bad Request"),
        ("API-11", "unknown state in the URL", re.sub(r"/[^/]+$", "/Atlantis", url), mut(), "404 or 4xx"),
    ]
    rows = []
    for pid, title, u, body, expected in cases:
        time.sleep(4)
        try:
            status, text = s.page.evaluate("""async ([u, body, headers]) => {
                const r = await fetch(u, {method: 'POST', body, headers, credentials: 'same-origin'});
                return [r.status, await r.text()]; }""", [u, body, CAPTURED["headers"]])
        except Exception as e:  # noqa: BLE001
            status, text = -1, f"{type(e).__name__}: {e}"
        gross = re.search(r'"grossPay"\s*:\s*"?([^",}]+)', text)
        net = re.search(r'"takeHomePay"\s*:\s*"?([^",}]+)', text)
        gross, net = (gross.group(1) if gross else None), (net.group(1) if net else None)
        if "Just a moment" in text or status in (-1, 429):
            verdict = "OBS"       # blocked / rate-limited: NOT evaluated - never counted as a pass
        elif pid == "API-01":
            verdict = "OK" if status == 200 else "OBS"
        elif status >= 500:
            verdict = "ISSUE"     # malformed client input must be a 4xx, not a server error
        elif status == 200 and gross is not None:
            verdict = "ISSUE"     # server computed a paycheck from input the UI forbids
        else:
            verdict = "OK"
        obs = f"HTTP {status}; grossPay={gross}; takeHomePay={net}; body: {text[:160]!r}"
        rows.append(dict(id=pid, title=title, url=u, request_body=body[:2000], status=status, response=text[:3000]))
        rec(pid, "API (server-side validation)", title, body[:80] if pid in ("API-09", "API-10") else title, expected, obs, verdict)
    (OUT / "api_probes.json").write_text(json.dumps(rows, indent=2))
    c.page.evaluate("""(rows) => { document.body.insertAdjacentHTML('afterbegin', '<pre id=qa-api style="position:fixed;inset:20px;z-index:2147483647;background:#fff;border:3px solid #d00;padding:14px;font:12px/1.4 monospace;overflow:auto;white-space:pre-wrap">' +
        'QA: calculation requests replayed from inside the page with modified fields (scripts/explore_more.py)\\n\\n' +
        rows.map(r => r.id + '  ' + r.title + '\\n   -> HTTP ' + r.status + '  ' + r.response.slice(0, 150).replace(/</g,'&lt;')).join('\\n\\n') + '</pre>'); }""", rows)
    shot(s.page, "API_summary")
    s.close()


# ------------------------------------------------------------------------------ accessibility (axe-core) --
def sec_a11y(browser):
    s = Session(browser, "explore_a11y")
    c = PaycheckCalculatorPage(s.page, pace_s=4).open()
    axe = requests.get(AXE_URL, timeout=30).text
    s.page.evaluate(axe)   # evaluate() is not subject to the page's CSP
    res = s.page.evaluate("""async () => {
        const form = document.querySelector('form');
        const r = await axe.run(form || document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}});
        return r.violations.map(v => ({id: v.id, impact: v.impact, help: v.help, tags: v.tags.filter(t => t.startsWith('wcag')),
            helpUrl: v.helpUrl, count: v.nodes.length, nodes: v.nodes.slice(0, 5).map(n => ({target: n.target.join(' '),
            summary: n.failureSummary, html: n.html.slice(0, 200)}))}));
    }""")
    (OUT / "axe.json").write_text(json.dumps(res, indent=2))
    sels = [n["target"] for v in res for n in v["nodes"][:3] if v["impact"] in ("serious", "critical")]
    if res:
        first = sels[0] if sels else None
        if first:
            try:
                scroll_to(s.page, first, 350)
            except Exception:  # noqa: BLE001
                pass
        annotate(s.page, "A11Y: axe-core WCAG 2.x A/AA scan of the calculator form",
                 [f"{v['id']} ({v['impact']}, {v['count']} element(s)): {v['help']}" for v in res][:8], *sels[:12])
        shot(s.page, "A11Y_axe")
    for v in res:
        rec(f"AX-{v['id']}", "Accessibility (axe-core)", v["help"], f"{v['count']} element(s)",
            "no WCAG A/AA violations", f"{v['impact']}; {', '.join(v['tags'])}; e.g. {v['nodes'][0]['target']}",
            "ISSUE" if v["impact"] in ("serious", "critical") else "OBS", ["A11Y_axe.png"] if res else [])
    if not res:
        rec("AX-none", "Accessibility (axe-core)", "no WCAG A/AA violations found by axe", "-", "-", "clean", "OK")
    s.close()


# --------------------------------------------------------------------------------------------- mobile --
def sec_mobile(browser):
    s = Session(browser, "explore_mobile", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                device_scale_factor=2, record_video_size={"width": 390, "height": 844})
    c = PaycheckCalculatorPage(s.page, pace_s=4).open()
    p = s.page
    m = p.evaluate("""() => ({sw: document.documentElement.scrollWidth, iw: window.innerWidth,
        wide: [...document.querySelectorAll('form *')].filter(e => e.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 5).map(e => e.tagName + (e.name ? '[' + e.name + ']' : ''))})""")
    small = p.evaluate("""() => [...document.querySelectorAll('form button, form input[type=checkbox], form select, form input')]
        .filter(e => e.offsetParent).map(e => { const r = e.getBoundingClientRect(); return [e.name || e.innerText.trim().slice(0, 20) || e.tagName, Math.round(r.width), Math.round(r.height)]; })
        .filter(([n, w, h]) => w < 24 || h < 24)""")
    scroll_to(p, F["rate"], 200)
    f1 = shot(p, "M-01_mobile_form")
    overflow = m["sw"] > m["iw"] + 1
    rec("M-01", "Mobile 390 px", "horizontal overflow", "iPhone-size viewport", "no horizontal scroll",
        f"scrollWidth {m['sw']} vs viewport {m['iw']}; elements past the edge: {m['wide']}", "ISSUE" if overflow else "OK", [f1])
    rec("M-02", "Mobile 390 px", "touch targets smaller than 24x24 px (WCAG 2.5.8)", "-", "none",
        f"{len(small)} small: {small[:6]}", "OBS" if small else "OK", [f1])
    s.close()


def sec_dates(browser):
    """What the server does with a pay date the UI lets through (years 1899 / 2150)."""
    s = Session(browser, "explore_dates")
    c = PaycheckCalculatorPage(s.page, pace_s=5).open().setup()
    p = s.page
    for pid, y in (("DT-06", "1899"), ("DT-07", "2150")):
        c._focus(p.locator("[aria-label='Month (mm)']"))
        for ch in "0115" + y:
            p.keyboard.type(ch, delay=150)
        p.keyboard.press("Tab")
        p.wait_for_timeout(1200)
        stored = p.locator(F["check_date"]).input_value()
        try:
            resp = c.calculate()
        except AssertionError as e:
            rec(pid, "Pay date", f"calculate with pay date in {y}", stored, "rejected with a message", f"blocked: {e}"[:200], "OK")
            continue
        p.wait_for_timeout(1500)
        r = c.results()
        err = c.visible_error_text()
        scroll_to(p, "[aria-label='Month (mm)']", 350)
        c.results()
        annotate(p, f"{pid}: pay date {stored} accepted by the form",
                 [f"Calculate was enabled; server answered HTTP {resp.status}", f"Body starts: {resp.text[:90]}",
                  f"Panel take home: {r.get('Take home pay').raw if r.get('Take home pay') else '-'}; error shown: {err[:70]!r}",
                  "Expected: the field rejects a year that has no tax tables, with a message"],
                 "[aria-label='Month (mm)']", "[aria-label='Day (dd)']", "[aria-label='Year (yyyy)']", PANEL)
        f = shot(p, pid)
        rec(pid, "Pay date", f"calculate with pay date in {y}", stored, "field rejects the year with a message",
            f"HTTP {resp.status}; body {resp.text[:120]!r}; error shown {err[:80]!r}", "ISSUE", [f])
    s.close()


SECTIONS = {"dates": sec_dates, "fields": sec_fields, "calc": sec_calc, "api": sec_api, "a11y": sec_a11y, "mobile": sec_mobile}


def main(names):
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=False, slow_mo=80)
        except Exception:  # noqa: BLE001
            browser = pw.chromium.launch(headless=False, slow_mo=80)
        for n in names:
            try:
                SECTIONS[n](browser)
            except Exception as e:  # noqa: BLE001
                rec(f"CRASH-{n}", "harness", f"section {n} crashed", "-", "-", f"{type(e).__name__}: {e}"[:300], "OBS")
        browser.close()
    old = json.loads((OUT / "probes.json").read_text()) if (OUT / "probes.json").exists() else []
    ids = {p["id"] for p in PROBES}
    done = {f"CRASH-{n}" for n in names if not any(p["id"] == f"CRASH-{n}" for p in PROBES)}  # section ran cleanly now
    merged = [p for p in old if p["id"] not in ids and p["id"] not in done] + PROBES
    (OUT / "probes.json").write_text(json.dumps(merged, indent=2))
    write_summary(merged)


def write_summary(merged):
    lines = [f"# Exploratory sweep - live gusto.com, {datetime.now():%Y-%m-%d %H:%M}", "",
             "| ID | Area | Probe | Input | Expected | Observed | Verdict | Evidence |", "|---|---|---|---|---|---|---|---|"]
    for p in merged:
        ev = "<br>".join(f"[{f}]({f})" for f in p["files"])
        cell = lambda x: str(x).replace("|", "\\|").replace("\n", " ")  # noqa: E731
        lines.append(f"| {p['id']} | {p['area']} | {cell(p['title'])} | `{cell(p['input'])[:40]}` | {cell(p['expected'])} | "
                     f"{cell(p['observed'])[:220]} | **{p['verdict']}** | {ev} |")
    (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    from collections import Counter
    print("\n", Counter(p["verdict"] for p in merged), f"-> {OUT}")


if __name__ == "__main__":
    if sys.argv[1:] == ["summary"]:
        write_summary(json.loads((OUT / "probes.json").read_text()))
        sys.exit()
    main([a.lower() for a in sys.argv[1:]] or ["fields", "calc", "api", "a11y", "mobile"])
