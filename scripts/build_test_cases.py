"""Single source of truth for the manual/automated test-case matrix.
    python scripts/build_test_cases.py   ->  data/test_cases.xlsx + data/test_cases.csv
Columns: ID | Area | Type | Priority | Scenario | Data / steps | Expected result | Automation | Basis
Basis = where the expected result comes from. 'ASSUMPTION' rows are questions to put to the product owner."""
import csv
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

P, N, B, E, S, I = "Positive", "Negative", "Boundary", "Edge", "Security", "Integration"
U, A, W, M = "Unit (oracle)", "API", "UI", "Manual"
DOC = "Gusto docs"

C = []
PROBES: dict = {}


def add(area, typ, pri, scenario, data, expected, auto, basis=DOC):
    C.append((f"TC-PAY-{len(C) + 1:03d}", area, typ, pri, scenario, data, expected, auto, basis))


# ---------------------------------------------------------------- Gross pay & overtime
a = "Gross pay / overtime"
add(a, P, "P0", "Hourly employee, exactly 40h", "$20/h, 40h, 1 state, no bonus", "Gross $800.00, no overtime line", U + " + " + W)
add(a, P, "P0", "Hourly employee with 12h overtime", "$20/h, 52h", "Gross $1,160.00 (40*20 + 12*30); OT premium $120.00", U + " + " + W, "Gusto OT article example")
add(a, B, "P0", "One hundredth of an hour past threshold", "$20/h, 40.01h", "Gross $800.30 (premium $0.10 applied to 0.01h)", U)
add(a, B, "P1", "One hundredth under threshold", "$20/h, 39.99h", "Gross $799.80, no OT", U)
add(a, B, "P2", "Zero hours on regular payroll", "Hourly employee, 0h", "Gross $0.00; payroll can still be submitted; no negative or NaN rows", U + " + " + W)
add(a, B, "P1", "Maximum hours in a week", "168h in one workweek", "Calculated correctly or blocked with a clear message (168 is the physical limit)", U)
add(a, N, "P1", "Negative hours", "-8h in the hours field", "Rejected inline; Submit disabled or blocked; nothing saved", U + " + " + W)
add(a, N, "P1", "More than 24h in a single day", "Time sheet entry of 25h on one day", "Rejected; day cannot exceed 24h", W + " + " + M)
add(a, N, "P2", "Non-numeric hours", "'abc', '8h', '1e3', '8,5'", "Rejected or parsed unambiguously; no silent zero", W)
add(a, E, "P0", "Bonus changes the overtime rate", "$20/h, 50h + $200 non-discretionary bonus", "Regular rate $24; gross $1,320.00 (premium 0.5*24*10 = $120)", U, "Gusto: 'overtime and bonuses impact each other'")
add(a, E, "P1", "Discretionary bonus excluded from OT rate", "$20/h, 50h + $200 discretionary bonus entered as a custom earning", "Regular rate stays $20; gross $1,300.00 (1,000 + 100 premium + 200 bonus)", U + " + " + M, "Gusto bonus payroll article: discretionary bonuses excluded from OT")
add(a, E, "P1", "Bonus paid later for an already-paid period", "Run regular payroll, then add a bonus to the same period", "Regular rate of affected weeks recalculated; extra OT premium shown on the correction", M, "Gusto OT article: 'may recalculate Regular Rate of Pay'")
add(a, E, "P0", "4x10h shift = 40h in a daily-OT state", "CA employee, 4 days x 10h, $20/h", "Gross $880.00 (daily OT applies) vs $800.00 under federal-only rule", U + " + " + M, "Gusto state OT table")
add(a, E, "P1", "12h+ day double time", "CA, one 14h day at $20/h", "$360.00 (8 reg + 4 at 1.5x + 2 at 2x)", U)
add(a, E, "P1", "Seventh consecutive day", "CA, 8h each of 7 days", "Day 7 paid at 1.5x; weekly OT on first 6 days; gross $1,280.00 under the oracle's no-double-count assumption", U + " + " + M, "ASSUMPTION on double-count")
add(a, E, "P2", "Mixed pay rates in one week", "Employee with 2 hourly rates, 45h total", "Weighted regular rate used for the OT premium (FLSA)", M)
add(a, E, "P2", "Sub-cent intermediate values", "$15.555/h, 41h", "Rounded once, half-up, at the end: $645.53", U)
add(a, E, "P1", "Salaried exempt employee with hours typed in", "Exempt salary $78,000/yr, 50h entered", "No OT; hours do not change gross", M, "Gusto time tracking: exempt hours do not sync")
add(a, E, "P1", "Salaried non-exempt employee", "Non-exempt salary, 46h", "Only OT hours sync / are paid at premium; regular salary unchanged", M, "Gusto time tracking")
# ------------------------------------------------------------------------ Taxes & deductions
a = "Taxes / deductions"
add(a, P, "P0", "FICA on a normal paycheck", "Wages $1,000, YTD $0", "SS $62.00, Medicare $14.50", U + " + " + A)
add(a, B, "P0", "Crossing the Social Security wage base", "Wages $2,000, YTD $184,000 (2026 base $184,500)", "SS only on $500 = $31.00; Medicare $29.00", U, "SSA 2026 wage base")
add(a, B, "P1", "Exactly at the wage base", "YTD $184,500, wages $1,000", "SS $0.00; Medicare still $14.50", U)
add(a, B, "P1", "Additional Medicare threshold", "YTD $199,000, wages $2,000", "0.9% on the $1,000 above $200,000 = $9.00 (employee-only)", U, "IRS additional Medicare")
add(a, E, "P2", "Half-cent rounding", "Wages $10.00 -> Medicare 0.145", "$0.15 (half-up). Banker's rounding would give $0.14", U)
add(a, P, "P0", "Bonus on its own extra-pay payroll uses 22% flat", "$1,000 bonus, extra-pay payroll", "Federal withholding $220.00 by default (editable rate)", U + " + " + M, "Gusto bonus payrolls")
add(a, B, "P1", "Supplemental wages cross $1M in a year", "$2,000 bonus, YTD supplemental $999,000", "$1,000 at 22% + $1,000 at 37% = $590.00", U, "IRS Pub 15")
add(a, E, "P1", "Bonus inside a regular payroll", "Same $1,000 bonus added to a regular paycheck", "Aggregate method: withholding differs from flat 22%; both paths documented on the review screen", M, "Gusto / IRS")
add(a, E, "P2", "Bonus entered in the wrong earnings tab", "Bonus typed under 'Bonus' instead of 'Custom earnings'", "Treatment (tax, OT regular rate) identical to docs; no silent mis-classification", M, "Support-search excerpt warns about this; not seen on the fetched copy - verify wording in app")
add(a, B, "P0", "401(k) annual cap", "Elect $1,000, YTD $24,000, age 30", "Only $500 deducted (limit $24,500)", U, "IRS 2026 limits")
add(a, B, "P1", "Catch-up contribution ages", "Age 49 / 50 / 60 / 63 / 64 at YTD $24,500", "$0 / room / room (cap $35,750) / room / only to $32,500", U, "IRS 2026 limits")
add(a, N, "P1", "Deductions exceed gross pay", "Gross $100, post-tax deduction $500", "Blocked or shown as an explicit shortfall; net never silently negative", U + " + " + W)
add(a, E, "P1", "Pre-tax vs FICA wages", "Gross $2,000, Section 125 $100, 401(k) $200", "FICA wages $1,900; income-tax wages $1,700", U)
add(a, P, "P1", "Net-to-gross invariant", "Any paycheck", "net + all taxes + all deductions = gross, to the cent", U + " + " + A)
add(a, E, "P1", "401(k) on a bonus payroll cannot be switched off", "Bonus payroll, employee already at the annual deferral limit", "No deduction taken beyond the cap even though the toggle is locked on", U + " + " + M, "Gusto bonus payroll article")
add(a, E, "P2", "Garnishment / child support on off-cycle", "Employee with child-support order, off-cycle run", "Child support handled per docs; no over-withholding", M, "Gusto off-cycle article")
add(a, E, "P2", "Local tax edge: Multnomah County extra pay", "Separate extra-pay payroll, Oregon employee", "Preschool-for-All tax defaults to 0% unless opted in, as documented", M, "Gusto bonus payroll article")
# --------------------------------------------------------------- Run payroll workflow & status
a = "Payroll workflow / status"
add(a, P, "P0", "Happy path: create, review, submit", "Regular payroll for current pay period", "Status goes unprocessed -> submitted; review totals match employee rows", W + " + " + A)
add(a, P, "P1", "Off-cycle payroll with a reason", "Pick 'bonus' reason, one employee", "Taxes/deductions default per reason; time tracking and time-off do not sync", W + " + " + M, "Gusto off-cycle article")
add(a, P, "P1", "Cancel a submitted payroll before cut-off", "Submitted, now < 4:00 pm PT on deadline", "Returns to unprocessed; editable again", A + " + " + W, "Gusto API status table")
add(a, N, "P0", "Cancel after the cut-off", "Pending status (>= 4:00 pm PT on deadline)", "Cancel not offered / API 422; no debit reversal path from UI", A, "Gusto API status table")
add(a, N, "P0", "Submit the same payroll twice", "PUT submit on a processed payroll", "422; exactly one set of debits", A)
add(a, N, "P1", "Double-click on 'Submit payroll'", "Two rapid clicks, throttled network", "One submission only (idempotent); button disabled after first click", W + " + " + M)
add(a, N, "P1", "Calculate unknown payroll", "PUT /calculate with random UUID", "404", A)
add(a, N, "P1", "Calculate with a payroll blocker", "Company missing bank verification or federal tax setup", "422 with the blocker named (not a generic 500)", A, "Gusto API reference")
add(a, N, "P2", "Malformed payroll id", "'not-a-uuid', SQL-ish text, 300 chars", "4xx, never 5xx; no stack trace", A)
add(a, E, "P1", "Edit then navigate away without saving", "Change hours, press browser Back", "Unsaved changes warning or draft preserved; totals not stale", W + " + " + M)
add(a, E, "P1", "Two admins edit the same payroll", "Admin A and B both change hours", "Last-write or lock behaviour is defined; no lost update without notice", M)
add(a, E, "P1", "Session expires mid-payroll", "Idle 30+ min then Submit", "Redirect to login, data preserved or clear error; no half-submitted payroll", M)
add(a, E, "P2", "Terminated employee mid period", "Dismiss employee, run payroll", "Final pay handled (dismissal payroll); excluded from the regular run correctly", M)
add(a, E, "P2", "Employee added after payroll created", "New hire with start date in the period", "Included or clearly excluded; totals consistent", M)
# ------------------------------------------------------------------- Deadlines & timing
a = "Deadlines / timing"
add(a, P, "P0", "4-day payroll deadline", "Check date Fri 2026-12-04", "Deadline Mon 2026-11-30", U + " + " + A)
add(a, B, "P0", "Holiday inside the window", "Check date Fri 2026-11-27, Thanksgiving 11-26", "4-day deadline moves from Mon 11-23 to Fri 11-20", U, "Gusto: bank holidays require submitting one business day earlier")
add(a, B, "P0", "One second before the cut-off", "Submit 15:59:59 PT on deadline day", "On time", U + " + " + W)
add(a, B, "P0", "Exactly 16:00:00 PT", "Submit 16:00:00 PT", "ASSUMPTION: treated as late (status doc says 'at or after 4:00 pm' is pending). Confirm with product", U, "ASSUMPTION")
add(a, B, "P1", "One second after the cut-off", "Submit 16:00:01 PT Mon", "Late; processing moves to next business day (Tue)", U)
add(a, B, "P1", "Late on Friday", "Submit Fri 16:30 PT", "Processing starts Monday; check date pushed accordingly", U)
add(a, E, "P0", "DST ends", "Deadline Mon 2026-11-02 (PST). Submit 2026-11-02 23:59:59 UTC", "On time: cut-off is 00:00 UTC next day, not 23:00 UTC", U, "US DST ends 2026-11-01")
add(a, E, "P0", "Admin in India", "Browser timezone Asia/Kolkata, deadline Mon", "Deadline displayed as 4:00 pm PT (or converted correctly: 05:30 Tue IST); same status as a CA admin", U + " + " + W)
add(a, E, "P1", "'PST' vs 'PT' wording", "Compare summer vs winter deadline text", "Cut-off is 4 pm Pacific local time year-round; wording does not imply fixed UTC-8", M, "Docs say '4 PM PST' in one page, '4:00pm PT' in another")
add(a, E, "P1", "Check date on a weekend or holiday", "Pay schedule landing on Sat/Sun/bank holiday", "ASSUMPTION: pay date rolls to prior business day; confirm and verify shown date", M, "ASSUMPTION")
add(a, E, "P2", "Status transitions are time-driven", "Submitted payroll observed across 4 pm PT and check date", "submitted -> pending at 4 pm PT; pending -> paid at check date; no other transitions", U + " + " + A, "Gusto API status table")
# --------------------------------------------------------- Security, permissions, multi-tenant
a = "Security / permissions"
add(a, S, "P0", "No token / bad token", "GET payrolls without Authorization", "401", A)
add(a, S, "P0", "Cross-tenant access", "Use company A token against company B id", "403/404; no data leak", A)
add(a, S, "P0", "Non-admin cannot run payroll", "Employee-role user opens payroll URL directly", "Access denied; no payroll data in response body", W + " + " + M)
add(a, S, "P1", "Limited admin lacks payroll permission", "Custom admin role without Payroll", "Run payroll menu hidden and API/URL blocked", M)
add(a, S, "P1", "Script injection in earnings label", "Custom earning name '<img src=x onerror=alert(1)>'", "Escaped everywhere (review, pay stub, emails)", W + " + " + M)
add(a, S, "P1", "Sensitive data in URLs/logs", "Inspect URLs and console while running payroll", "No SSN, bank numbers or tokens in URL, console or local storage", M)
add(a, S, "P2", "Unsupported API version header", "X-Gusto-API-Version: 1999-01-01", "4xx, not 5xx", A)
# ---------------------------------------------------------------------- Integration / UX
a = "Integration / UX"
add(a, I, "P1", "Time tracking sync to regular payroll", "Approved timesheet 46h for hourly employee", "Payroll hours = approved hours; OT computed once", M + " + " + W, "Gusto time tracking")
add(a, I, "P1", "Time-off double pay", "Approved PTO in period, then off-cycle for same period", "PTO paid exactly once across both runs", M, "Public docs read inconsistently on whether extra-pay runs pay time off - clarify, then test")
add(a, I, "P2", "Mobile vs web parity", "Run same payroll on web and mobile app", "Same totals and validations", M)
add(a, I, "P2", "Accessibility of the review table", "Keyboard-only run, screen reader", "All inputs labelled; errors announced; focus order logical", M)
add(a, I, "P2", "Large payroll performance", "500 employees, bulk edit", "Page stays responsive; totals update; no timeouts", M)
# ------------------------------------------- Public paycheck calculator on live gusto.com (added 2026-11-21)
a = "Public calculator (live)"
LC = "Live gusto.com run 2026-11-21"
add(a, P, "P0", "Baseline weekly paycheck", "Alabama, weekly, $20/h x 40h, Single", "Gross $800.00; SS $49.60; Medicare $11.60; net + taxes + deductions = gross; panel = server response", W, LC)
add(a, P, "P0", "Overtime entered in the overtime field", "40h at $20 + 12h overtime at $30", "Gross $1,160.00 (oracle 52h FLSA); FICA $88.74", W, LC)
add(a, B, "P1", "Gross = rate x regular hours; FICA rounded per tax", "40.01h, 0.001h, $7.25 x 1h, 168h, 60h", "Gross to the cent; $7.25 x 1h -> SS 0.45 + Medicare 0.11 = 0.56", W, LC)
add(a, B, "P0", "Social Security wage base + Additional Medicare per check", "$5,000/h x 40h ($200k); $10,000/h x 40h ($400k)", "SS capped at $11,439.00; Addl Medicare $0.00 at exactly $200k, $1,800.00 at $400k", W, "SSA 2026 wage base $184,500")
add(a, E, "P1", "Tax year follows the check date", "Check date 2025-11-20, $200k check", "SS $10,918.20 (2025 base $176,100)", W, "SSA 2025 wage base")
add(a, E, "P0", "Deduction tax treatment", "$100 401(k) / Medical (s125) / HSA / Roth 401(k)", "401(k): FICA unchanged, income tax lower; s125/HSA: FICA on $700; Roth: post-tax, income tax unchanged", W, "IRS Pub 15-B")
add(a, E, "P1", "FICA exemptions", "Exempt from Social Security; exempt from Medicare", "SS $0.00 / Medicare $11.60; Medicare $0.00 / SS $49.60", W, LC)
add(a, P, "P1", "More hours never lower net pay", "1, 10, 39, 40, 41, 60 h", "Net strictly increasing", W, LC)
add(a, N, "P0", "Invalid wage / hours rejected", "-20, 0, 'abc' wage; -5, 0, 'xyz' hours", "Field flagged invalid; Calculate disabled", W, LC)
add(a, S, "P1", "Script in a numeric field", "<img src=x onerror=...> as wage", "Not executed; field invalid", W, LC)
add(a, N, "P0", "Fixed deduction larger than gross", "$800 gross; $1,000 401(k) / $1,000 Roth / $900 medical", "Blocked or capped; take-home never negative", W, LC)
add(a, B, "P1", "Absurd wage", "Wage 1e308", "Rejected, or a finite result; never a silent $0.00", W, LC)
add(a, N, "P0", "Calculation request fails", "Calculation endpoint answers 500 (fault injection; live also returns 429/422 under load)", "User sees an error message, not just a $0.00 paycheck", W, LC)
add(a, B, "P1", "More than 168 regular hours in a weekly period", "Weekly, 169h and 1,000h", "Rejected: a week has 168 hours", W, LC)
add(a, N, "P1", "Decimal comma in the wage", "'20,5'", "Rejected or read as 20.50; never $205.00", W, LC)
add(a, E, "P1", "Date hint vs field order per locale", "Browser locale en-GB and en-IN", "Hint (MM/DD/YYYY) matches the order of the date segments", W, LC)
add(a, E, "P2", "Wage helper text", "Read the hint under 'hourly wage'", "Describes the wage, not the overtime rule", W, LC)
add(a, N, "P1", "Overtime rate below the regular rate", "Regular $20, overtime $10 x 12h", "Flagged (FLSA requires >= 1.5x regular rate)", W, "FLSA; page hint 'Overtime is a higher hourly wage'")
add(a, E, "P1", "Accepting cookies keeps typed input", "Type $35 wage, then 'Accept all cookies'", "Wage still $35 after the banner closes", W, LC)

# ------------------------- Exploratory sweep of the same calculator, live 2026-11-22 (scripts/explore_more.py)
a = "Public calculator (exploratory)"
XL = "Exploratory run 2026-11-22"
X = "UI (explore_more.py)"
EXPLORE = {}   # scenario -> probe ids in reports/exploration/probes.json


def addx(typ, pri, scenario, data, expected, probes, basis=XL, auto=X):
    add(a, typ, pri, scenario, data, expected, auto, basis)
    EXPLORE[C[-1][0]] = probes


addx(P, "P1", "Wage formats a user may type", "'20.50', '7.25', '$20', ' 20 ', '1,000'", "Accepted as the number typed", ["W-01", "W-02", "W-04", "W-05", "W-06"])
addx(N, "P1", "Wage with letters / full-width digits / -0", "'20abc', '２０', '-0'", "Rejected with a message", ["W-08", "W-09", "W-12"])
addx(N, "P2", "Scientific notation in wage and hours", "'1e2' wage, '1e3' hours", "Rejected (not a money/hours format)", ["W-07", "H-03"])
addx(B, "P2", "Wage below the federal minimum", "$0.01/h", "Accepted with a minimum-wage warning", ["W-03"], "FLSA $7.25 federal minimum")
addx(B, "P2", "Wage with three decimals", "'20.999'", "Rejected, or a note that it is rounded", ["W-10"])
addx(B, "P2", "Absurd but finite wage", "$999,999,999/h", "Upper bound with a message", ["W-11"])
addx(B, "P1", "Hours above the length of the pay period", "Biweekly 337 h, Semi-monthly 400 h, Monthly 745 h", "Rejected (more hours than the period contains)", ["H-04", "H-05", "H-06"])
addx(B, "P1", "Regular + overtime hours above 168 in a week", "Weekly 40 h + 200 h / 150 h overtime", "Rejected", ["O-02", "C-05"])
addx(N, "P1", "Overtime field validation", "OT hours -5, OT rate $0; OT $30 (1.5x, positive)", "Negatives/zero rejected; 1.5x accepted", ["O-01", "O-03", "O-04"])
addx(N, "P1", "Deduction amount validation", "Fixed -100 / 50; percentage 99 / 100 / -5", "Negative and >= 100 % rejected; 50 and 99 % accepted", ["D-01", "D-02", "D-03", "D-04", "D-05"])
addx(B, "P0", "Decimal percentage deduction", "401(k) 4.5 % of $800; 99.99 %", "Pre-tax $36.00; 99.99 % accepted", ["D-06", "D-07", "C-06"])
addx(N, "P1", "Negative W-4 / state withholding values", "Step 3 -2000, 4a -5000, 4c -25, dependents -1, state extra -50", "Rejected with a message", ["F-01", "F-03", "F-04", "S-01", "S-04"])
addx(N, "P0", "Additional withholding larger than gross", "$800 gross; federal 4(c) $5,000; state additional $2,000", "Rejected or capped; take-home never negative", ["C-03", "C-04"], "IRS Pub 15-T; a paycheck cannot be negative")
addx(N, "P2", "Fractional number of dependents", "Alabama dependents 1.5", "Rejected (whole number on form A-4)", ["S-02", "C-07"], "Alabama form A-4 line 4")
addx(B, "P2", "W-4 plausibility", "Step 3 amount $2,001; 1,000 dependents", "Warning: no W-4 produces these values", ["F-02", "S-03"], "Form W-4 step 3")
addx(N, "P1", "Calendar validation of the pay date", "02/29/2028 (positive), 02/30/2026, month 13", "Leap day accepted; impossible dates rejected", ["DT-01", "DT-02", "DT-03"])
addx(B, "P1", "Pay-date year range", "Pay date in 1899 and in 2150, then Calculate", "Year outside supported tax tables rejected with a message", ["DT-04", "DT-05", "DT-06", "DT-07"])
addx(S, "P0", "Server-side validation of the calculation endpoint", "Page's own request replayed in-page with one field changed: wage -20 / 'abc' / missing, hours -40 / 100000, frequency 'Fortnightly', 401(k) 150 %, {}, malformed JSON, unknown state", "4xx validation error for every invalid request; never 200 with a computed paycheck, never 500", ["API-01", "API-02", "API-03", "API-04", "API-05", "API-06", "API-07", "API-08", "API-09", "API-10", "API-11"], "OWASP: validate on the server; CWE-602", "API (in-page fetch)")
addx(E, "P2", "Result panel after an input changes", "Calculate at $20, change wage to $30, do not recalculate", "Panel cleared or marked out of date", ["C-02"])
addx(E, "P1", "Automated WCAG 2.x A/AA scan of the form", "axe-core 4.10 on the calculator form", "No violations", ["AX-none"], "WCAG 2.2 AA")
addx(E, "P2", "Distinct accessible names", "Pre-tax deduction row vs fringe-benefit row", "Each control's label (or group legend) says which section it belongs to", ["A-01"], "WCAG 1.3.1 / 2.4.6")
addx(E, "P2", "Mobile layout 390 px", "iPhone-size viewport, touch", "No horizontal scroll; touch targets >= 24 px", ["M-01", "M-02"], "WCAG 2.5.8")
addx(E, "P2", "Console / network health", "Console errors and HTTP >= 400 while filling the form", "None", ["N-01"])

# Unit (reference-model) tests that implement a case: case -> substrings of pytest node ids
UNIT_MAP = {
    "TC-PAY-001": ["800.00-exactly 40h"], "TC-PAY-002": ["1160.00-Gusto doc example"],
    "TC-PAY-003": ["800.30-just over"], "TC-PAY-004": ["799.80-just under"], "TC-PAY-005": ["0.00-zero hours"],
    "TC-PAY-006": ["4640.00-max hours"], "TC-PAY-007": ["test_flsa_rejects_invalid_input"],
    "TC-PAY-010": ["1320.00-RR="], "TC-PAY-011": ["test_discretionary_bonus"],
    "TC-PAY-013": ["880.00-4x10", "test_same_hours_pay_differently"], "TC-PAY-014": ["360.00-8*20"],
    "TC-PAY-015": ["1280.00-7 consecutive"], "TC-PAY-017": ["645.53"],
    "TC-PAY-020": ["test_fica[1000-0-62.00"], "TC-PAY-021": ["crosses SS wage base"],
    "TC-PAY-022": ["already AT wage base"], "TC-PAY-023": ["crosses 200k"], "TC-PAY-024": ["half_up_not_bankers"],
    "TC-PAY-025": ["220.00-flat 22%"], "TC-PAY-026": ["590.00-1000 @22%"], "TC-PAY-029": ["500-only 500 of room"],
    "TC-PAY-030": ["test_k401_cap"], "TC-PAY-031": ["test_net_pay_negative_is_rejected"],
    "TC-PAY-032": ["test_taxable_wage_buckets"], "TC-PAY-033": ["test_net_pay_invariant_randomised"],
    "TC-PAY-034": ["0-limit reached"], "TC-PAY-051": ["4 business days back"], "TC-PAY-052": ["Thanksgiving pushes"],
    "TC-PAY-053": ["test_cutoff_boundary[when0"], "TC-PAY-054": ["test_cutoff_boundary[when1"],
    "TC-PAY-055": ["test_cutoff_boundary[when2", "test_late_submission_slips"], "TC-PAY-056": ["test_late_on_friday"],
    "TC-PAY-057": ["test_cutoff_uses_pst_after_dst_ends"], "TC-PAY-058": ["test_user_in_india"],
    "TC-PAY-061": ["test_status_machine"],
}

# Defects confirmed on live gusto.com (public hourly paycheck calculator), 2026-11-21
DEFECTS = [
    ("DEF-01", "TC-PAY-084", "Sev 2", "Fixed-dollar deduction larger than gross is accepted; take-home goes negative",
     "Alabama, weekly, $20 x 40h ($800). Deduction 401(k) $1,000 -> 'Take home pay -32.65% -$261.20'; Roth $1,000 -> -$347.96; Medical $900 -> -$100.00",
     "Blocked like a >= 100% percentage deduction is, or capped at available pay"),
    ("DEF-02", "TC-PAY-085", "Sev 3", "Wage 1e308 passes validation; server returns HTTP 200 with \"grossPay\":\"Inf\" and bare NaN (invalid JSON); user sees the generic 'We could not calculate this paycheck - something went wrong on our end'",
     "Type 1e308 as hourly wage (field shows a 309-digit number, not flagged), fill required fields, Calculate",
     "Upper bound on the wage field with a validation message; the API never returns non-finite money or a 200 for an uncomputable request. Same parser also reads '1e2' as $100 and '1e3' hours as 1,000"),
    ("DEF-04", "TC-PAY-087", "Sev 3", "Hours are not limited to the length of the pay period (every frequency, regular + overtime)",
     "Weekly, $20, 169h -> $3,380; 1,000h -> $20,000 gross for one week. Also Biweekly 337h, Semi-monthly 400h, Monthly 745h accepted; weekly 40h + 150h overtime -> $5,300. 100,000h makes the server answer HTTP 500",
     "Rejected: regular + overtime hours cannot exceed the hours in the period (168 per week)"),
    ("DEF-05", "TC-PAY-088", "Sev 2", "Decimal comma silently multiplies the wage by 10",
     "Type '20,5' as hourly wage -> field shows 205.00, gross $8,200 for 40h, no warning", "Rejected or read as 20.50"),
    ("DEF-06", "TC-PAY-089", "Sev 3", "Pay-date hint says (MM/DD/YYYY) but en-GB / en-IN browsers get Day/Month/Year segments",
     "Open with browser locale en-GB or en-IN; label vs date field order", "Hint follows the field (or field follows hint)"),
    ("DEF-07", "TC-PAY-090", "Sev 4", "Hourly-wage helper text is the overtime definition",
     "Hint under 'What is your employee's hourly wage?' reads 'Work more than 8 hours a workday or more than 40 hours per workweek.'",
     "Text that describes the wage"),
    ("DEF-08", "TC-PAY-091", "Sev 3", "Overtime rate below the regular rate is accepted silently",
     "$20 regular, overtime $10 x 12h -> gross $920 with no warning (hint itself says 'Overtime is a higher hourly wage')",
     "Warning when overtime rate < 1.5x regular rate"),
    ("DEF-09", "TC-PAY-092", "Sev 3", "Accepting the cookie banner reloads the page and wipes everything typed",
     "Type $35 wage, choose Weekly, click 'Accept all cookies' -> wage empty, frequency back to Bi-weekly",
     "Banner closes without losing input"),
    ("DEF-10", "TC-PAY-103", "Sev 2", "Percentage deductions are silently rounded to a whole percent",
     "401(k) 'Percent of gross pay' 4.5 -> box shows 5, pre-tax $40.00 instead of $36.00 on $800. 99.99 / 99.5 -> rounded to 100, then rejected 'Must be less than 100' although the hint says 0 to 100",
     "Decimal percentages kept (4.5 % -> $36.00), or rejected with a message"),
    ("DEF-11", "TC-PAY-105", "Sev 2", "Additional federal / state withholding larger than gross is accepted; take-home goes negative",
     "$800 gross. W-4 4(c) extra withholding $5,000 -> take home -$4,359.28 (-544.91 %); Alabama additional withholding $2,000 -> -$1,389.76",
     "Rejected or capped at available pay (same net-pay floor as DEF-01)"),
    ("DEF-12", "TC-PAY-109", "Sev 3", "Pay-date year is not range-checked: 1899 gives a silent $0.00 paycheck; 2150 is calculated with current tables",
     "Pay date 01/15/1899 -> no message, Calculate enabled, server HTTP 200 with grossPay 0.00, panel shows $0.00 everywhere and no error. 01/15/2150 -> calculated as if current year",
     "Year outside the supported tax years rejected with a message"),
    ("DEF-13", "TC-PAY-110", "Sev 3", "Calculation endpoint does not validate input server-side (UI-only validation)",
     "Page's own POST replayed in-page with one field changed: wage -20 -> HTTP 200 gross -$800, take home -$850; wage 'abc' or missing -> 200 gross $0, take home -$50; 401(k) 150 % -> 200 all zeros; hours -40 / 100,000 or frequency 'Fortnightly' -> HTTP 500. ({} and malformed JSON -> 400, unknown state -> 404: correct)",
     "4xx with a validation message for every invalid field; never 200 with a computed paycheck, never 500"),
    ("DEF-14", "TC-PAY-106", "Sev 3", "Fractional number of dependents accepted, then silently treated as 0",
     "Alabama dependents 1.5 -> not flagged, HTTP 200. Alabama tax: 0 deps $32.68, 1 dep $31.72, 1.5 deps $32.68 - the value is dropped, employee over-withheld, no message",
     "Whole numbers only, with a validation message"),
]
OBSERVATIONS = [
    ("WITHDRAWN DEF-03", "'Failed calculation shows a silent $0.00 paycheck' was raised from a manual probe that read only the result panel. TC-PAY-086 (500 injected) XPASSed on live: the page shows 'We could not calculate this paycheck'. Not a defect."),
    ("OBS-01", "Regular hours above 40 in a weekly period are paid at straight time with no overtime prompt (41h -> $820). By design the page takes overtime separately, but nothing points the user to it."),
    ("OBS-02", "A wage with 3 decimals is rounded to cents in the field before multiplying ($15.555 -> $15.56; 41h gives $637.96, not $637.76)."),
    ("OBS-03", "Percentages are formatted inconsistently (81.5% next to 81.51%, 8.8% next to 10.85%)."),
    ("OBS-04", "Headless browsers get a Cloudflare 403 challenge; automation has to run headed."),
    ("OBS-05", "The calculation endpoint rate-limits (HTTP 429) after roughly 40 calculations in a few minutes; the page then shows its 'could not calculate' error, which is correct."),
    ("OBS-06", "A wage below the $7.25 federal minimum ($0.01/h) is accepted with no warning."),
    ("OBS-07", "No upper bound on wage ($999,999,999/h) or dependents (1,000); W-4 step 3 accepts $2,001, which no W-4 can produce."),
    ("OBS-08", "After a calculation, changing an input leaves the old result on screen with no 'out of date' cue."),
    ("OBS-09", "Pre-tax deduction and fringe-benefit rows use identical labels ('Deduction name', 'Calculation Method', 'Deduction amount') with no group legend; screen-reader users cannot tell them apart. axe-core reports no WCAG A/AA violations on the form."),
    ("OBS-10", "Intermittent console error 'Request timed out' (seen in 1 of 2 runs); no failed first-party requests."),
]


API_DONE = {"Submit the same payroll twice", "Calculate unknown payroll", "Malformed payroll id", "No token / bad token",
            "Cross-tenant access", "Unsupported API version header"}
# "Script injection in earnings label" was listed here before, but no test enters an earnings label (the only
# XSS test is on the public calculator's wage field, TC-PAY-083), so it is no longer claimed as implemented.
UI_DONE = {"Negative hours", "Non-numeric hours", "Zero hours on regular payroll", "Hourly employee, exactly 40h",
           "Hourly employee with 12h overtime", "Admin in India"}


def auto_status(r):
    if "Unit" in r[7] or r[4] in API_DONE or r[4] in UI_DONE or r[1] == "Public calculator (live)":
        return "Implemented"
    return "Manual only" if r[7].strip() == "Manual" else "Planned"


def load_results():
    path = Path(__file__).parent.parent / "reports" / "results.json"
    return json.loads(path.read_text()) if path.exists() else {}


def load_probes():
    path = Path(__file__).parent.parent / "reports" / "exploration" / "probes.json"
    return {p["id"]: p for p in json.loads(path.read_text())} if path.exists() else {}


PROBE_DEFECT = {"W-07": "DEF-02", "H-03": "DEF-02", "H-04": "DEF-04", "H-05": "DEF-04", "H-06": "DEF-04", "O-02": "DEF-04",
                "C-05": "DEF-04", "D-06": "DEF-10", "C-06": "DEF-10", "C-03": "DEF-11", "C-04": "DEF-11", "S-02": "DEF-14",
                "C-07": "DEF-14", "DT-04": "DEF-12", "DT-05": "DEF-12", "DT-06": "DEF-12", "DT-07": "DEF-12"}


def explore_execution(case_id, probes):
    ids = EXPLORE.get(case_id, [])
    rows = [probes[i] for i in ids if i in probes]
    if not rows:
        return "Not run", "", ""
    bad = [r for r in rows if r["verdict"] == "ISSUE"]
    obs = [r for r in rows if r["verdict"] == "OBS"]
    if bad:
        defect = next((PROBE_DEFECT[r["id"]] for r in bad if r["id"] in PROBE_DEFECT), "DEF-13" if bad[0]["id"].startswith("API") else "")
        return "Fail", "; ".join(f"{r['id']}: {r['observed'][:110]}" for r in bad)[:600], defect
    if obs:
        return "Observation", "; ".join(f"{r['id']}: {r['observed'][:110]}" for r in obs)[:600], ""
    return "Pass", f"Passed on live gusto.com ({len(rows)} probes: {', '.join(r['id'] for r in rows)})", ""


def execution(case_id, results):
    """(Status, Actual result, Defect ID) for one case from reports/results.json.
    Live UI results win; unit results are reported as oracle-only (they test the reference model, not Gusto)."""
    if case_id in EXPLORE:
        return explore_execution(case_id, PROBES)
    live = [r for r in results.get("live", {}).get("tests", {}).values() if r.get("case") == case_id]
    if live:
        outs = [r["outcome"] for r in live]
        defect = next((r["defect"] for r in live if r.get("defect")), "") or ""
        if "failed" in outs or "xpass" in outs:
            det = next(r["detail"] for r in live if r["outcome"] in ("failed", "xpass"))
            return "Fail", f"Unexpected result on live gusto.com: {det}", defect
        if "xfail" in outs:
            d = next(x for x in DEFECTS if x[0] == defect)
            return "Fail", f"Defect reproduced on live gusto.com ({sum(o == 'xfail' for o in outs)}/{len(outs)} runs): {d[4]}", defect
        if all(o == "skipped" for o in outs):
            return "Skipped", live[0]["detail"], ""
        return "Pass", f"Passed on live gusto.com ({outs.count('passed')}/{len(outs)} test runs)", ""
    keys = UNIT_MAP.get(case_id)
    if keys:
        unit = [r for nid, r in results.get("unit", {}).get("tests", {}).items() if any(k in nid for k in keys)]
        if unit:
            ok = all(r["outcome"] == "passed" for r in unit)
            return ("Pass" if ok else "Fail",
                    f"Reference-model unit tests {'passed' if ok else 'FAILED'} ({len(unit)}); product behaviour not yet run", "")
    return "Not run", "", ""


def write():
    out = Path(__file__).parent.parent / "data"
    out.mkdir(exist_ok=True)
    results = load_results()
    global PROBES
    PROBES = load_probes()
    head = ["ID", "Area", "Type", "Priority", "Scenario", "Data / steps", "Expected result", "Automation", "Basis", "Automation status", "Status", "Actual result", "Defect ID"]
    table = [list(r) + [auto_status(r), *execution(r[0], results)] for r in C]
    with open(out / "test_cases.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(head); w.writerows(table)
    wb = Workbook(); ws = wb.active; ws.title = "Test cases"
    ws.append(head)
    fills = {"Pass": "D9EAD3", "Fail": "F4CCCC", "Skipped": "FFF2CC", "Observation": "DDEBF7"}
    for r in table:
        ws.append(r)
        if r[10] in fills:
            ws.cell(ws.max_row, 11).fill = PatternFill("solid", fgColor=fills[r[10]])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1F3A5F")
    widths = [11, 22, 11, 9, 38, 42, 52, 18, 30, 15, 11, 30, 12]
    for i, wd in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = wd
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions
    dv = DataValidation(type="list", formula1='"Not run,Pass,Fail,Observation,Blocked,Skipped"', allow_blank=False)
    ws.add_data_validation(dv); dv.add(f"K2:K{len(C) + 1}")
    s = wb.create_sheet("Summary")
    s.append(["Area", "Cases", "P0", "Positive", "Negative", "Boundary", "Edge", "Security", "Integration"])
    for area in dict.fromkeys(r[1] for r in C):
        rows = [r for r in C if r[1] == area]
        s.append([area, len(rows), sum(r[3] == "P0" for r in rows)] + [sum(r[2] == t for r in rows) for t in (P, N, B, E, S, I)])
    s.append(["TOTAL", len(C), sum(r[3] == "P0" for r in C)] + [sum(r[2] == t for r in C) for t in (P, N, B, E, S, I)])
    for c in s[1]:
        c.font = Font(bold=True)
    for c in s[s.max_row]:
        c.font = Font(bold=True)
    s.column_dimensions["A"].width = 26
    s.append([])
    s.append(["Execution status", "Cases"])
    for st in ("Pass", "Fail", "Observation", "Skipped", "Not run"):
        s.append([st, sum(r[10] == st for r in table)])

    d = wb.create_sheet("Defects")
    d.append(["Defect ID", "Test case", "Severity", "Summary", "Steps / evidence", "Expected", "Status"])
    for x in DEFECTS:
        d.append(list(x) + [("Open - found 2026-11-22" if x[0] >= "DEF-10" else "Open - found 2026-11-21") + ", re-verified 2026-11-22 (reports/evidence)"])
    d.append([])
    d.append(["Observation", "Note"])
    for o in OBSERVATIONS:
        d.append(list(o))
    for c in d[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="7F1D1D")
    for col, wd in zip("ABCDEFG", (11, 12, 9, 55, 60, 40, 22)):
        d.column_dimensions[col].width = wd
    for row in d.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(out / "test_cases.xlsx")
    return out


if __name__ == "__main__":
    print(write(), len(C), "cases")
