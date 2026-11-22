"""Re-test each confirmed defect on live gusto.com in a visible Google Chrome window and save annotated screenshots.

    python scripts/capture_evidence.py              # all defects
    python scripts/capture_evidence.py DEF-01 DEF-05

Screenshots go to reports/evidence/<DEF-id>*.png, a screen recording of each check to reports/evidence/video/*.webm,
with a summary in reports/evidence/README.md.
The red outlines and the yellow box are QA annotations injected by this script for the screenshot; they are not
part of Gusto's page. Each check prints REPRODUCED or NOT REPRODUCED from what the page/server actually did.
Paced on purpose (the calculation endpoint rate-limits): about 14 page loads, 14 calculations and 4 replayed requests.
"""
import json
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tests" / "ui"), str(ROOT / "src")]

from playwright.sync_api import sync_playwright  # noqa: E402

from pages.paycheck_calculator_page import F, URL, PaycheckCalculatorPage  # noqa: E402

OUT = ROOT / "reports" / "evidence"
OUT.mkdir(parents=True, exist_ok=True)
RESULTS = []
SOURCE = "scripts/capture_evidence.py"   # shown in the annotation footer
VIDEO = dict(record_video_dir=str(OUT / "video" / "_raw"), record_video_size={"width": 1280, "height": 1000})


def save_video(page, name: str) -> str:
    """Call after the page (or its context) is closed; returns the video's path relative to OUT."""
    v = page.video
    if not v:
        return ""
    dest = OUT / "video" / f"{name}.webm"
    v.save_as(str(dest))
    Path(v.path()).unlink(missing_ok=True)
    return f"video/{dest.name}"


def annotate(page, title: str, lines: list[str], *selectors: str):
    """Outline the elements involved and pin a labelled note to the bottom-left of the viewport."""
    page.evaluate(
        """([title, lines, sels, src]) => {
            document.querySelectorAll('[data-qa-hl]').forEach(e => { e.style.outline = ''; e.removeAttribute('data-qa-hl'); });
            for (const s of sels) for (const e of document.querySelectorAll(s)) {
                e.style.outline = '4px solid #d00'; e.style.outlineOffset = '2px'; e.setAttribute('data-qa-hl', '1'); }
            let n = document.getElementById('qa-note');
            if (!n) { n = document.createElement('div'); n.id = 'qa-note'; document.body.appendChild(n); }
            n.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:2147483647;max-width:560px;background:#fff7c2;' +
                'border:3px solid #d00;padding:10px 14px;font:13px/1.45 -apple-system,Segoe UI,sans-serif;color:#111;' +
                'box-shadow:0 4px 18px rgba(0,0,0,.25)';
            n.innerHTML = '<div style="font-weight:700;font-size:14px;margin-bottom:4px">' + title + '</div>' +
                lines.map(l => '<div>' + l.replace(/</g, '&lt;') + '</div>').join('') +
                '<div style="margin-top:6px;color:#666;font-size:11px">QA annotation added by ' + src + ' - ' +
                new Date().toISOString().slice(0, 16).replace('T', ' ') + ' UTC</div>';
        }""",
        [title, lines, list(selectors), SOURCE],
    )


def scroll_to(page, selector: str, headroom: int = 300):
    page.locator(selector).first.evaluate(f"e => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - {headroom})")
    page.wait_for_timeout(400)


def shot(page, name: str) -> str:
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path))
    return path.name


def record(defect, reproduced: bool, observed: str, files: list[str]):
    RESULTS.append((defect, reproduced, observed, files))  # files list is extended with the video afterwards
    print(f"{defect}: {'REPRODUCED' if reproduced else 'NOT REPRODUCED'} - {observed}  -> {', '.join(files)}", flush=True)


PANEL = "[data-qa=result-panel]"


# ------------------------------------------------------------------------------------------- checks --
def def01(ctx):
    c = PaycheckCalculatorPage(ctx.new_page(), pace_s=3).open().setup()
    c.add_deduction("Retirement401k", "FixedAmount", 1000)
    c.calculate()
    r = c.results()
    net, gross = r["Take home pay"].amount, r["Gross pay"].amount
    scroll_to(c.page, "input[name='deductions.0.amount']")
    c.results()  # re-tags the panel
    annotate(c.page, "DEF-01 (Sev 2): deduction larger than gross accepted",
             [f"Gross ${gross}; 401(k) fixed amount $1,000 accepted, no error",
              f"Take home pay shown: {r['Take home pay'].raw}",
              "A percentage deduction >= 100% IS blocked; a fixed dollar amount is not"],
             "input[name='deductions.0.amount']", "select[name='deductions.0.name']", PANEL)
    f = shot(c.page, "DEF-01_negative_take_home")
    c.page.close()
    record("DEF-01", net is not None and net < 0, f"gross {gross}, take-home {net}", [f, save_video(c.page, "DEF-01")])


def def05_04_07(ctx):
    """Three defects on one page: wage hint (DEF-07), '20,5' (DEF-05), 1,000 weekly hours (DEF-04)."""
    c = PaycheckCalculatorPage(ctx.new_page(), pace_s=3).open().setup()
    p = c.page
    # DEF-07 - wage hint text
    hint = c.field_message("rate")
    scroll_to(p, F["rate"])
    annotate(p, "DEF-07 (Sev 4): wrong hint under the hourly wage field",
             [f"Hint reads: \"{hint.split(' / ')[0]}\"", "That is the overtime definition, not a description of the wage"],
             F["rate"])
    p.evaluate("""() => { const e = document.querySelector("input[name='basics.hourlyPay.wage']");
                          const id = (e.getAttribute('aria-describedby')||'').split(' ')[0];
                          const h = id && document.getElementById(id); if (h) { h.style.outline='4px solid #d00'; h.setAttribute('data-qa-hl','1'); } }""")
    record("DEF-07", "40 hours per workweek" in hint, f"hint = {hint.split(' / ')[0]!r}", [shot(p, "DEF-07_wage_hint")])

    # DEF-05 - decimal comma
    c.type("rate", "20,5")
    p.wait_for_timeout(600)
    shown = c.value("rate")
    c.calculate()
    r = c.results()
    scroll_to(p, F["rate"])
    c.results()
    annotate(p, "DEF-05 (Sev 2): '20,5' silently becomes $205.00/h",
             ["Typed: 20,5  (decimal comma, as used in much of Europe/LatAm)", f"Field now shows: {shown}  - no warning",
              f"Gross for 40 h: {r['Gross pay'].raw}  (expected $820.00 or a validation error)"],
             F["rate"], PANEL)
    record("DEF-05", shown.replace(",", "") in ("205", "205.00"), f"'20,5' -> {shown}, gross {r['Gross pay'].amount}",
           [shot(p, "DEF-05_decimal_comma")])

    # DEF-04 - 1,000 hours in one week
    c.type("rate", 20).type("hours", 1000)
    p.wait_for_timeout(600)
    invalid = c.is_invalid("hours", wait_ms=1000)
    c.calculate()
    r = c.results()
    scroll_to(p, F["hours"])
    c.results()
    annotate(p, "DEF-04 (Sev 3): 1,000 regular hours accepted for ONE week",
             ["Pay frequency: Weekly (a week has 168 hours)", f"Hours field: {c.value('hours')}  - flagged invalid: {invalid}",
              f"Gross: {r['Gross pay'].raw}"],
             F["hours"], F["frequency"], PANEL)
    record("DEF-04", not invalid and r["Gross pay"].amount == Decimal("20000.00"),
           f"1000 h weekly -> gross {r['Gross pay'].amount}", [shot(p, "DEF-04_1000_hours_weekly")])
    p.close()
    vid = save_video(p, "DEF-07_DEF-05_DEF-04")
    for row in RESULTS[-3:]:
        row[3].append(vid)


def def02(ctx):
    c = PaycheckCalculatorPage(ctx.new_page(), pace_s=3).open().setup(rate="1e308")
    p = c.page
    invalid = c.is_invalid("rate", wait_ms=1000)
    resp = c.calculate()
    p.wait_for_timeout(1500)
    (OUT / "DEF-02_server_response.json.txt").write_text(f"HTTP {resp.status}\n{resp.text}\n")
    non_finite = bool(re.search(r"\b(Inf|NaN)\b", resp.text))
    try:
        json.loads(resp.text, parse_constant=lambda c_: (_ for _ in ()).throw(ValueError(c_)))
        strict_json = True
    except ValueError:
        strict_json = False
    scroll_to(p, F["rate"])
    c.results()
    annotate(p, "DEF-02 (Sev 3): wage 1e308 passes validation",
             [f"Wage field accepted the value (flagged invalid: {invalid}): {c.value('rate')[:38]}...",
              f"Server: HTTP {resp.status}, body starts {resp.text[:70]}",
              f"Valid JSON: {strict_json} (bare NaN is not JSON).  Page: generic 'something went wrong' instead of a validation message"],
             F["rate"], PANEL)
    record("DEF-02", (not invalid) and resp.status == 200 and non_finite,
           f"HTTP {resp.status}, Inf/NaN in body: {non_finite}, strict JSON: {strict_json}",
           [shot(p, "DEF-02_huge_wage"), "DEF-02_server_response.json.txt"])
    p.close()
    RESULTS[-1][3].append(save_video(p, "DEF-02"))


def def08(ctx):
    c = PaycheckCalculatorPage(ctx.new_page(), pace_s=3).open().setup()
    c.add_overtime(10, 12)
    p = c.page
    invalid = c.is_invalid("ot_rate", wait_ms=1000)
    msg = c.field_message("ot_rate")
    c.calculate()
    r = c.results()
    scroll_to(p, F["ot_rate"])
    c.results()
    annotate(p, "DEF-08 (Sev 3): overtime rate below the regular rate accepted",
             ["Regular rate $20.00; overtime rate typed $10.00 x 12 h", f"Flagged invalid: {invalid}; the field's own hint: \"{msg.split(' / ')[0][:70]}...\"",
              f"Gross: {r['Gross pay'].raw}  (FLSA overtime is at least 1.5 x $20 = $30/h)"],
             F["rate"], F["ot_rate"], F["ot_hours"], PANEL)
    record("DEF-08", not invalid and r["Gross pay"].amount == Decimal("920.00"), f"OT $10 x 12 -> gross {r['Gross pay'].amount}",
           [shot(p, "DEF-08_overtime_below_regular")])
    p.close()
    RESULTS[-1][3].append(save_video(p, "DEF-08"))


def def06(browser):
    files, mismatch = [], []
    for loc in ("en-GB", "en-IN"):
        ctx = browser.new_context(locale=loc, viewport={"width": 1280, "height": 1000}, **VIDEO)
        c = PaycheckCalculatorPage(ctx.new_page(), pace_s=3).open()
        p = c.page
        label = p.get_by_text(re.compile("When will your employee be paid")).first.inner_text()
        order = p.locator("[aria-label='Day (dd)'], [aria-label='Month (mm)'], [aria-label='Year (yyyy)']").evaluate_all(
            "els => els.map(e => e.getAttribute('aria-label'))")
        scroll_to(p, F["check_date"], 350)
        p.get_by_text(re.compile("When will your employee be paid")).first.evaluate(
            "e => { e.style.outline='4px solid #d00'; e.setAttribute('data-qa-hl','1'); }")
        annotate(p, f"DEF-06 (Sev 3): date hint vs field order, browser locale {loc}",
                 [f"Label: \"{label.strip()}\"", f"Field segments in order: {', '.join(order)}",
                  "Typing per the hint (11/12/2026 = 12 Nov) gives 11 Dec: wrong pay date and possibly wrong tax year"],
                 "[aria-label='Day (dd)']", "[aria-label='Month (mm)']")
        files.append(shot(p, f"DEF-06_date_hint_{loc}"))
        if "MM/DD/YYYY" in label and order and order[0].startswith("Day"):
            mismatch.append(loc)
        ctx.close()
        files.append(save_video(p, f"DEF-06_{loc}"))
    record("DEF-06", len(mismatch) == 2, f"hint MM/DD/YYYY with Day-first fields in {mismatch}", files)


def def09(browser):
    ctx = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 1000}, **VIDEO)
    p = ctx.new_page()
    c = PaycheckCalculatorPage(p)
    p.goto(URL, wait_until="domcontentloaded", timeout=60_000)
    c._wait_ready()
    btn = p.locator("#onetrust-accept-btn-handler")
    btn.wait_for(state="visible", timeout=15_000)
    c.type("rate", 35)
    c.select("frequency", "Weekly")
    before = (c.value("rate"), c.value("frequency"))
    scroll_to(p, F["rate"])
    annotate(p, "DEF-09 (Sev 3) - step 1: user has typed, cookie banner still open",
             [f"Wage: {before[0]}   Pay frequency: {before[1]}", "Next: click 'Accept all cookies'"],
             F["rate"], F["frequency"], "#onetrust-accept-btn-handler")
    f1 = shot(p, "DEF-09_step1_before_accepting_cookies")
    p.evaluate("() => document.getElementById('qa-note')?.remove()")
    btn.click()
    p.wait_for_timeout(6_000)
    c._wait_ready()
    after = (c.value("rate"), c.value("frequency"))
    scroll_to(p, F["rate"])
    annotate(p, "DEF-09 (Sev 3) - step 2: after 'Accept all cookies'",
             [f"Wage: '{after[0]}' (was {before[0]})   Pay frequency: {after[1]} (was {before[1]})",
              "The banner reloaded the page and discarded the user's input"],
             F["rate"], F["frequency"])
    f2 = shot(p, "DEF-09_step2_after_accepting_cookies")
    ctx.close()
    record("DEF-09", after[0] in ("", "0.00") and after != before, f"before {before} -> after {after}",
           [f1, f2, save_video(p, "DEF-09")])


def def10(ctx):
    """Percentage deductions are rounded to a whole percent: 4.5 % -> 5 %."""
    c = PaycheckCalculatorPage(ctx.new_page(), pace_s=3).open().setup()
    p = c.page
    amt = "input[name='deductions.0.amount']"
    c.add_deduction("Retirement401k", "Percentage", "4.5")
    p.wait_for_timeout(600)
    shown = p.locator(amt).input_value()
    c.calculate()
    r = c.results()
    scroll_to(p, amt)
    c.results()
    annotate(p, "DEF-10 (Sev 2): percentage deduction silently rounded to a whole number",
             ["Typed 4.5 into the 401(k) percentage box (a common contribution rate)", f"Box now shows: {shown}",
              f"Pre-tax deducted: {r['Pre-tax'].raw}   (4.5 % of $800 = $36.00)",
              "Also: 99.99 is rounded to 100 and then rejected with 'Must be less than 100'"],
             amt, PANEL)
    f = shot(p, "DEF-10_percentage_rounded")
    p.close()
    record("DEF-10", shown == "5" and r["Pre-tax"].amount == Decimal("40.00"),
           f"4.5 % -> box shows {shown!r}, pre-tax {r['Pre-tax'].amount}", [f, save_video(p, "DEF-10")])


def def11(ctx):
    """Additional federal / state withholding larger than gross: take-home goes negative."""
    c = PaycheckCalculatorPage(ctx.new_page(), pace_s=3).open().setup()
    p = c.page
    fed = "input[name='federalTax.extraWithholding']"
    c.type(p.locator(fed), 5000)
    c.calculate()
    r1 = c.results()
    scroll_to(p, fed)
    c.results()
    annotate(p, "DEF-11 (Sev 2): extra federal withholding larger than gross accepted",
             ["Gross $800; W-4 line 4(c) extra withholding $5,000 accepted with no message",
              f"Take home pay: {r1['Take home pay'].raw}"], fed, PANEL)
    f1 = shot(p, "DEF-11_federal_extra_withholding")
    c.type(p.locator(fed), "")
    c.type("state_extra", 2000)
    c.calculate()
    r2 = c.results()
    scroll_to(p, F["state_extra"])
    c.results()
    annotate(p, "DEF-11 (Sev 2): additional state withholding larger than gross accepted",
             ["Gross $800; Alabama additional withholding $2,000 accepted with no message",
              f"Take home pay: {r2['Take home pay'].raw}"], F["state_extra"], PANEL)
    f2 = shot(p, "DEF-11_state_extra_withholding")
    p.close()
    n1, n2 = r1["Take home pay"].amount, r2["Take home pay"].amount
    record("DEF-11", n1 is not None and n2 is not None and n1 < 0 and n2 < 0,
           f"federal extra $5,000 -> take-home {n1}; state extra $2,000 -> take-home {n2}", [f1, f2, save_video(p, "DEF-11")])


def _type_date(p, mmddyyyy: str):
    p.locator("[aria-label='Month (mm)']").evaluate("e => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 300)")
    p.locator("[aria-label='Month (mm)']").click()
    for ch in mmddyyyy:            # the segments auto-advance after two digits
        p.keyboard.type(ch, delay=150)
    p.keyboard.press("Tab")
    p.wait_for_timeout(1200)


def def12(ctx):
    """A pay date in 1899 is accepted; the server returns all-zero results and the page shows $0.00, no error."""
    c = PaycheckCalculatorPage(ctx.new_page(), pace_s=3).open().setup()
    p = c.page
    _type_date(p, "01151899")
    stored = p.locator(F["check_date"]).input_value()
    resp = c.calculate()
    p.wait_for_timeout(1500)
    r = c.results()
    err = c.visible_error_text()
    scroll_to(p, "[aria-label='Month (mm)']", 350)
    c.results()
    annotate(p, "DEF-12 (Sev 3): pay date in 1899 accepted; result is a silent $0.00",
             [f"Pay date typed 01/15/1899 (stored {stored}); no validation message, Calculate enabled",
              f"Server: HTTP {resp.status}, {resp.text[:60]}...", f"Panel: Gross {r['Gross pay'].raw}, Take home {r['Take home pay'].raw}; error shown: {bool(err)}",
              "A year in 2150 is also accepted and silently calculated with current tax tables"],
             "[aria-label='Month (mm)']", "[aria-label='Day (dd)']", "[aria-label='Year (yyyy)']", PANEL)
    f = shot(p, "DEF-12_pay_year_1899")
    p.close()
    record("DEF-12", resp.status == 200 and r["Gross pay"].amount == Decimal("0.00") and not err,
           f"pay date {stored}: HTTP {resp.status}, gross {r['Gross pay'].amount}, error shown {bool(err)}", [f, save_video(p, "DEF-12")])


def def13(ctx):
    """The calculation endpoint does not validate input server-side. Requests are the page's own request, replayed
    from inside the page with one field changed (same browser, cookies and Cloudflare clearance as the user)."""
    from pages.paycheck_calculator_page import CALC_ENDPOINT
    c = PaycheckCalculatorPage(ctx.new_page(), pace_s=3).open().setup()
    p = c.page
    with p.expect_request(lambda r: bool(CALC_ENDPOINT.search(r.url.split("?")[0])) and r.method == "POST") as ri:
        c.calculate()
    req = ri.value
    banned = ("cookie", "content-length", "host", "user-agent", "referer", "origin", "accept-encoding", "accept-language",
              "connection", "priority")
    headers = {k: v for k, v in req.all_headers().items() if not k.startswith((":", "sec-")) and k not in banned}
    base = json.loads(req.post_data)

    def body(path, val):
        b = json.loads(json.dumps(base))
        cur = b
        keys = path.split(".")
        for k in keys[:-1]:
            cur = cur[int(k)] if isinstance(cur, list) else cur[k]
        cur[keys[-1]] = val
        return json.dumps(b)

    cases = [("negative wage -20", body("basics.hourlyWages.0.wage", "-20")),
             ("wage 'abc'", body("basics.hourlyWages.0.wage", "abc")),
             ("negative hours -40", body("basics.hourlyWages.0.hours", "-40")),
             ("unknown pay frequency 'Fortnightly'", body("basics.payFrequency", "Fortnightly"))]
    rows = []
    for title, b in cases:
        p.wait_for_timeout(3500)
        status, text = p.evaluate("""async ([u, body, headers]) => { const r = await fetch(u, {method: 'POST', body, headers,
            credentials: 'same-origin'}); return [r.status, await r.text()]; }""", [req.url, b, headers])
        t = re.search(r"<title>([^<]+)</title>", text)
        rows.append({"probe": title, "status": status, "summary": (t.group(1) if t else text[:110])})
    (OUT / "DEF-13_server_validation.json.txt").write_text(json.dumps({"endpoint": req.url, "baseline_request": base, "probes": rows}, indent=2))
    p.evaluate("""(rows) => { const n = document.createElement('div'); n.id = 'qa-api';
        n.style.cssText = 'position:fixed;left:20px;right:20px;top:110px;z-index:2147483646;background:#fff;border:3px solid #d00;padding:14px 18px;font:13px/1.5 ui-monospace,Menlo,monospace;color:#111;box-shadow:0 4px 18px rgba(0,0,0,.25)';
        n.innerHTML = '<b>Calculation request replayed from inside this page, one field changed (the form blocks every one of these values)</b><br><br>' +
          rows.map(r => '<div style="margin-bottom:8px"><b>' + r.probe + '</b><br>&rarr; HTTP ' + r.status + ' &nbsp; ' +
                   r.summary.replace(/</g, '&lt;') + '</div>').join('');
        document.body.appendChild(n); }""", rows)
    annotate(p, "DEF-13 (Sev 3): calculation endpoint does not validate input on the server",
             ["Negative / non-numeric wage -> HTTP 200 with a computed (negative or $0) paycheck",
              "Negative hours / unknown pay frequency -> HTTP 500 server error instead of a 4xx validation error",
              "Full requests and responses: DEF-13_server_validation.json.txt"])
    f = shot(p, "DEF-13_server_side_validation")
    p.close()
    ok200 = rows[0]["status"] == 200 and rows[1]["status"] == 200
    has500 = any(r["status"] >= 500 for r in rows)
    record("DEF-13", ok200 and has500, "; ".join(f"{r['probe']} -> HTTP {r['status']}" for r in rows),
           [f, "DEF-13_server_validation.json.txt", save_video(p, "DEF-13")])


def def14(ctx):
    """1.5 dependents is accepted, then silently treated as 0 (same state tax as 0 dependents)."""
    c = PaycheckCalculatorPage(ctx.new_page(), pace_s=3).open().setup()
    p = c.page
    tax = {}
    for d in ("0", "1", "1.5"):
        c.type("state_dependents", d)
        resp = c.calculate()
        tax[d] = c.last.detail("taxes", "Alabama State Tax")
    invalid = c.is_invalid("state_dependents", wait_ms=1500)
    r = c.results()
    err = c.visible_error_text()
    scroll_to(p, F["state_dependents"])
    c.results()
    annotate(p, "DEF-14 (Sev 3): 1.5 dependents accepted, then silently treated as 0",
             [f"Dependents typed: 1.5 - flagged invalid: {invalid}; server HTTP {resp.status}; error shown: {bool(err)}",
              f"Alabama state tax: 0 dependents ${tax['0']} | 1 dependent ${tax['1']} | 1.5 dependents ${tax['1.5']}",
              "The value is dropped without a message, so the employee is over-withheld (form A-4 line 4 is a whole number)"],
             F["state_dependents"], PANEL)
    f = shot(p, "DEF-14_fractional_dependents")
    p.close()
    record("DEF-14", not invalid and resp.status == 200 and not err and tax["1.5"] == tax["0"] != tax["1"],
           f"state tax 0 deps {tax['0']}, 1 dep {tax['1']}, 1.5 deps {tax['1.5']} (treated as 0), no message",
           [f, save_video(p, "DEF-14")])


CHECKS = {"DEF-10": def10, "DEF-11": def11, "DEF-12": def12, "DEF-13": def13, "DEF-14": def14,
          "DEF-01": def01, "DEF-05": def05_04_07, "DEF-04": def05_04_07, "DEF-07": def05_04_07,
          "DEF-02": def02, "DEF-08": def08, "DEF-06": def06, "DEF-09": def09}
NEEDS_BROWSER = {def06, def09}


def main(wanted):
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=False, slow_mo=120)
        except Exception:
            browser = pw.chromium.launch(headless=False, slow_mo=120)  # Playwright's Chromium if Chrome is missing
        ctx = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 1000}, **VIDEO)
        done = set()
        for d in wanted:
            fn = CHECKS[d]
            if fn in done:
                continue
            done.add(fn)
            try:
                fn(browser) if fn in NEEDS_BROWSER else fn(ctx)
            except Exception as e:  # keep going; a crash is reported, not hidden
                record(d, False, f"check crashed: {type(e).__name__}: {str(e)[:160]}", [])
        browser.close()
    store = OUT / "results.json"
    merged = {r[0]: r for r in (json.loads(store.read_text()) if store.exists() else [])}
    stamp = f"{datetime.now():%Y-%m-%d %H:%M}"
    for d, ok, obs, files in RESULTS:
        merged[d] = [d, ok, obs, [f for f in files if f], stamp]
    store.write_text(json.dumps(sorted(merged.values()), indent=1))
    lines = [f"# Defect evidence - live gusto.com (last run {stamp})", "",
             "Red outlines and the yellow note are annotations added by `scripts/capture_evidence.py`.", "",
             "| Defect | Re-test | Observed | Evidence | Checked |", "| --- | --- | --- | --- | --- |"]
    for d, ok, obs, files, when in sorted(merged.values()):
        lines.append(f"| {d} | {'REPRODUCED' if ok else 'NOT REPRODUCED'} | {obs} | " + "<br>".join(f"[{f}]({f})" for f in files) + f" | {when} |")
    (OUT / "README.md").write_text("\n".join(lines) + "\n")
    print(f"\n{sum(r[1] for r in RESULTS)}/{len(RESULTS)} reproduced; evidence in {OUT}")


if __name__ == "__main__":
    args = [a.upper() for a in sys.argv[1:]] or ["DEF-01", "DEF-05", "DEF-04", "DEF-07", "DEF-02", "DEF-08", "DEF-06", "DEF-09",
                                                 "DEF-10", "DEF-11", "DEF-12", "DEF-13", "DEF-14"]
    main(args)
