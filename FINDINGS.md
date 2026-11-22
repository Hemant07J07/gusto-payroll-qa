# Findings: Gusto public hourly paycheck calculator, live gusto.com

First run 2026-11-21. Full re-test, exploratory sweep and re-verification 2026-11-22.

Target: https://gusto.com/tools/hourly-paycheck-calculator (redirects to /resources/calculators/payroll/hourly-paycheck-calculator).
This is the part of Run payroll's logic that can be tested without an account. Logged-in Run payroll and the Gusto API still
need a demo company and token.

## Results (2026-11-22)

| Layer | Result |
| --- | --- |
| Reference model (unit) | 98 passed |
| Framework self-test, clean mock | 38 passed |
| Framework self-test, 15 seeded bug classes | every class caught (`reports/retest_2026-11-22/selftest_seeded_bugs.txt`) |
| Regression suite on live gusto.com (headed Chrome) | 38 tests: 26 passed, 12 expected failures (the 8 known defects); identical to 2026-11-21 |
| Exploratory sweep on live gusto.com (`scripts/explore_more.py`) | 69 probes: 36 OK, 24 issue, 9 observation; 5 new defects |
| Re-verification of every defect (`scripts/capture_evidence.py`) | **13 / 13 reproduced**, annotated screenshot + screen recording each |
| Logged-in app / Gusto API | not run: need a demo company, saved login and API token |

Matrix (`data/test_cases.xlsx`): 115 cases, 55 Pass, 16 Fail, 6 Observation, 38 Not run (the logged-in / API cases).

## Confirmed defects (all re-verified 2026-11-22)

Evidence: [reports/evidence/](reports/evidence/README.md) (screenshots, `video/*.webm`, raw server responses).

| ID | Sev | Defect | Reproduce | Rule it breaks |
| --- | --- | --- | --- | --- |
| DEF-01 | 2 | Fixed-dollar deduction larger than gross accepted; take-home negative | AL, weekly, $20 x 40 h = $800; 401(k) $1,000 -> take home **-$261.20**; Roth $1,000 -> -$347.96; Medical $900 -> -$100.00 | A paycheck can't be negative; payroll systems cap or defer deductions; the page blocks >= 100 % deductions itself |
| DEF-02 | 3 | Wage `1e308` passes validation; server returns HTTP 200 with `"grossPay":"Inf"` and bare `NaN` (invalid JSON); page shows a generic error. The same parser reads `1e2` as $100 and `1e3` hours as 1,000 | Type `1e308` as the wage, Calculate | RFC 8259: Infinity / NaN are not permitted in JSON |
| DEF-04 | 3 | Hours are not limited to the length of the pay period (any frequency, regular + overtime) | Weekly 1,000 h -> $20,000; Biweekly 337 h, Semi-monthly 400 h, Monthly 745 h accepted; weekly 40 h + 150 h overtime -> $5,300 | A week has 168 hours |
| DEF-05 | 2 | `20,5` becomes **$205.00/h** with no warning (10x) | Type `20,5` as the wage | Decimal comma is common in many locales (W3C locale-based forms) |
| DEF-06 | 3 | Pay-date hint says (MM/DD/YYYY); en-GB / en-IN browsers get Day/Month/Year segments | Browser locale en-GB or en-IN | WCAG 3.3.2 / technique G89: the stated format must match the field |
| DEF-07 | 4 | Hourly-wage hint is the overtime rule ("Work more than 8 hours a workday or more than 40 hours per workweek.") | Read the hint under the wage field | WCAG 3.3.2 |
| DEF-08 | 3 | Overtime rate below the regular rate accepted silently | $20 regular, $10 overtime x 12 h -> $920, no warning | FLSA, 29 CFR 778.107: overtime >= 1.5 x regular rate; the field's own hint says "Overtime is a higher hourly wage" |
| DEF-09 | 3 | Accepting the cookie banner reloads the page and wipes input | Type $35, choose Weekly, Accept all cookies -> wage empty, frequency back to Bi-weekly | WCAG 2.2 3.3.7 Redundant Entry |
| **DEF-10** | 2 | **New.** Percentage deductions silently rounded to a whole percent | 401(k) 4.5 % -> box shows **5**, pre-tax **$40.00 instead of $36.00**; 99.99 -> rounded to 100, then "Must be less than 100" although the hint says "0 to 100" | Silent change of a money input; WCAG 3.3.4 error prevention for financial data |
| **DEF-11** | 2 | **New.** Additional federal / state withholding larger than gross accepted; take-home negative | $800 gross; W-4 4(c) $5,000 -> **-$4,315.28**; Alabama additional $2,000 -> **-$1,347.96** | Same as DEF-01; one net-pay floor fixes both |
| **DEF-12** | 3 | **New.** Pay-date year not range-checked: 1899 gives a silent $0.00 paycheck, 2150 is calculated with current tables | Pay date 01/15/1899 -> no message, server HTTP 200 `grossPay 0.00`, panel $0.00 everywhere, no error | WCAG 3.3.1 error identification; a silent $0.00 is a wrong answer, not an error |
| **DEF-13** | 3 | **New.** Calculation endpoint does not validate input server-side | Page's own POST replayed in-page with one field changed: wage -20 -> **HTTP 200, gross -$800**; wage `abc` / missing -> 200, gross $0; 401(k) 150 % -> 200, zeros; hours -40 / 100,000 or frequency `Fortnightly` -> **HTTP 500**. (`{}` / malformed JSON -> 400 and unknown state -> 404 are correct) | OWASP: validate on the server; CWE-602; client errors must be 4xx, not 500 |
| **DEF-14** | 3 | **New.** Fractional dependents (1.5) accepted, then silently treated as 0 | Alabama tax: 0 deps $32.68, 1 dep $31.72, **1.5 deps $32.68**; no message | Form A-4 line 4 is a whole number; the value is dropped and the employee is over-withheld |

Withdrawn: **DEF-03** ("a failed calculation shows a silent $0.00"). The page does show "We could not calculate this paycheck"
when the request fails. (DEF-12 is different: there the request succeeds and the server itself returns zeros.)

## Observations (product questions, not provably wrong)
- OBS-01: 41 regular hours are paid at straight time with no overtime prompt.
- OBS-02: 3-decimal wages are rounded to cents silently (20.999 -> 21.00).
- OBS-03: percentages formatted inconsistently (81.5 % next to 81.51 %).
- OBS-04 / OBS-05: headless browsers get a Cloudflare 403; the endpoint rate-limits (429) after about 40 calculations.
- OBS-06: a wage below the $7.25 federal minimum ($0.01/h) is accepted with no warning.
- OBS-07: no upper bound on wage ($999,999,999/h) or dependents (1,000); W-4 Step 3 accepts $2,001, which no W-4 can
  produce ($2,200 per child + $500 per other dependent).
- OBS-08: after calculating, changing an input leaves the old result on screen with no "out of date" cue.
- OBS-09: pre-tax deduction and fringe-benefit rows use identical labels with no group legend (screen readers can't tell
  them apart). axe-core 4.10 reports **no** WCAG 2.x A/AA violations on the form.
- OBS-10: intermittent console error "Request timed out" (1 of 2 runs).

## Verified correct on live (matches the oracle to the cent)
Gross = rate x hours (40.01 h, 0.001 h, 168 h); Social Security / Medicare rounded separately; Social Security wage-base cap
per check ($184,500 for 2026) and 0.9 % Additional Medicare; 2025 check date uses the 2025 base; 401(k) / Section 125 /
HSA / Roth tax treatment; exemptions; negative / zero / non-numeric wage and hours rejected in the form; negative deductions,
negative W-4 values, $0 overtime rate rejected; 30 Feb and month 13 rejected, 29 Feb 2028 accepted; script payloads not
executed; net + taxes + deductions = gross; panel = server response; error shown when the request fails; no horizontal
scroll or small touch targets at 390 px; empty / malformed request body -> 400, unknown state -> 404.

## How it was tested, and limits
- All runs in a visible Google Chrome (headless is blocked by Cloudflare), paced several seconds per calculation.
- Server-side probes reused the page's own request from inside the page (same browser, cookies and bot clearance as a
  real user): 11 requests in total, functional validation only. No load, fuzzing, or security exploitation was attempted.
- Only Alabama was used for state tax; other states, logged-in Run payroll (R1-R10) and the Gusto API are untested.

## Faults found and fixed in this framework
| # | Fault | Fix |
| --- | --- | --- |
| F1 | Headless run hits Cloudflare 403; 20 tests failed with "No field matched" | `BotChallenge` detection, skip with reason; run headed |
| F2 | Locators were guessed label regexes | Stable `name=` attributes |
| F3 | Calculate is disabled until address + W-4 fields are set; `calculate()` hung 30 s | `setup()` fills required fields; `CalculateDisabled` raised |
| F4 | Net pay parsed from intro text; panel always read $0.00 | Server response + panel rows only |
| F5 | Cookie accept reloads the page and wipes input mid-test | Wait for the reload in `open()` |
| F6 | Default frequency is Bi-weekly; expectations were weekly | Select Weekly |
| F7 | Overtime test assumed automatic 1.5x on hours > 40 | Overtime via the overtime field |
| F8 | `inspect_page.py` waited for `networkidle` and ran headless | domcontentloaded, headed |
| F9 | API `Session.timeout` ignored by requests | Per-request timeout session |
| F10 | API "business day" test never checked business days | Asserts it |
| F11 | Wrong case reference, XSS overclaim, inconsistent test counts | Corrected |
| F12-F14 | (my first redesign) XSS checked too early; error detector read `aria-live`; validation read too early | Wait / svg variant; `role=alert` only; poll 2 s |
| F15 | (exploratory script) typing date segments with select-all + Backspace corrupted them -> 5 false date "bugs" | Type digits continuously (segments auto-advance); re-run |
| F16 | (exploratory script) Playwright's out-of-browser request client is blocked by Cloudflare (403) and was scored "OK" | Replay with `fetch()` inside the page; a block is never a pass |
| F17 | (exploratory script) a probe left a field invalid, so the next probe read a stale `aria-invalid` | Restore a valid value between probes |

## Still open
- R1-R10 in the report (logged-in Run payroll) need a Gusto demo/trial company and `scripts/save_login_state.py`.
- API suite needs `GUSTO_API_TOKEN` / `GUSTO_COMPANY_ID` for the demo host.
- DEF-10..DEF-14 are covered by the exploratory script and the evidence script, not yet by `known_defect` tests in the suite.
