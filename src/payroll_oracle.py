"""
payroll_oracle.py - a small, *independent* reference model of the payroll rules
that Gusto documents publicly. It is a TEST ORACLE, not a re-implementation of
Gusto's tax engine: we use it to cross-check numbers shown by the app / API.

Deliberately NOT modelled: progressive federal income-tax withholding (IRS Pub 15-T),
state/local taxes. For those we only assert invariants (net = gross - everything).

Every rule below carries its source. Anything marked ASSUMPTION is a point where the
public docs are silent or ambiguous - those become "clarify with product" questions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

D = Decimal
CENT = D("0.01")
PT = ZoneInfo("America/Los_Angeles")

# ---- 2026 constants (IRS/SSA announcements, Nov 2025) ------------------------
SS_RATE = D("0.062")
SS_WAGE_BASE_2026 = D("184500")
MEDICARE_RATE = D("0.0145")
ADDL_MEDICARE_RATE = D("0.009")          # employee-only
ADDL_MEDICARE_THRESHOLD = D("200000")
SUPP_FLAT_RATE = D("0.22")               # IRS optional flat rate (Gusto default for extra-pay payroll)
SUPP_MANDATORY_RATE = D("0.37")          # supplemental wages above $1M in a calendar year
SUPP_THRESHOLD = D("1000000")
K401_LIMIT_2026 = D("24500")
K401_CATCHUP_50 = D("8000")
K401_CATCHUP_60_63 = D("11250")
FLSA_WEEKLY_THRESHOLD = D("40")

CUTOFF = time(16, 0)                     # 4:00 pm PT (Gusto processing docs)
SPEED_BUSINESS_DAYS = {"4-day": 4, "2-day": 2, "next-day": 1}


class NegativeNetPay(ValueError):
    pass


def money(x) -> Decimal:
    """Round half-up to cents (payroll convention; banker's rounding would differ)."""
    return D(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def _dec(x, name: str, *, allow_negative: bool = False) -> Decimal:
    v = D(str(x))
    if not allow_negative and v < 0:
        raise ValueError(f"{name} must not be negative: {v}")
    return v


# ------------------------------------------------------------------ overtime --
def weekly_gross_flsa(rate, hours, nondiscretionary_bonus=0) -> Decimal:
    """Federal (FLSA) weekly pay: 1.5x regular rate over 40h/week.
    Regular rate includes non-discretionary bonus (Gusto: 'overtime and bonuses impact
    each other'). premium = 0.5 * regular_rate * OT hours (Gusto OT article formula)."""
    rate, hours, bonus = _dec(rate, "rate"), _dec(hours, "hours"), _dec(nondiscretionary_bonus, "bonus")
    if hours > 168:
        raise ValueError("a week has only 168 hours")
    if hours == 0:
        return money(bonus)
    straight = rate * hours
    ot_hours = max(D(0), hours - FLSA_WEEKLY_THRESHOLD)
    regular_rate = (straight + bonus) / hours
    return money(straight + bonus + D("0.5") * regular_rate * ot_hours)


def weekly_gross_ca(rate, daily_hours: Sequence) -> Decimal:
    """California-style rules (Gusto state OT table):
    >8h/day 1.5x, >12h/day 2x, 7th consecutive day: first 8h 1.5x then 2x, >40 regular h/week 1.5x.
    ASSUMPTION: hours already paid as daily/7th-day OT are not counted again toward weekly OT.
    daily_hours: 7 entries in workweek order."""
    rate = _dec(rate, "rate")
    hrs = [_dec(h, "daily hours") for h in daily_hours]
    if len(hrs) != 7:
        raise ValueError("need exactly 7 daily entries")
    if any(h > 24 for h in hrs):
        raise ValueError("a day has only 24 hours")
    seventh_applies = all(h > 0 for h in hrs)
    reg = ot15 = dt = D(0)
    for i, h in enumerate(hrs):
        if i == 6 and seventh_applies:
            ot15 += min(h, D(8)); dt += max(D(0), h - 8)
        else:
            reg += min(h, D(8))
            ot15 += min(max(h - 8, D(0)), D(4))
            dt += max(D(0), h - 12)
    weekly_ot = max(D(0), reg - FLSA_WEEKLY_THRESHOLD)
    pay = rate * (reg - weekly_ot) + rate * D("1.5") * (ot15 + weekly_ot) + rate * 2 * dt
    return money(pay)


# --------------------------------------------------------------------- taxes --
@dataclass(frozen=True)
class Fica:
    social_security: Decimal
    medicare: Decimal
    additional_medicare: Decimal  # employee only

    @property
    def employee_total(self) -> Decimal:
        return self.social_security + self.medicare + self.additional_medicare


def fica_employee(fica_wages, ytd_fica_wages=0, wage_base=SS_WAGE_BASE_2026) -> Fica:
    w, ytd = _dec(fica_wages, "wages"), _dec(ytd_fica_wages, "ytd")
    ss_taxable = max(D(0), min(ytd + w, wage_base) - min(ytd, wage_base))
    addl_taxable = max(D(0), ytd + w - ADDL_MEDICARE_THRESHOLD) - max(D(0), ytd - ADDL_MEDICARE_THRESHOLD)
    return Fica(money(ss_taxable * SS_RATE), money(w * MEDICARE_RATE), money(addl_taxable * ADDL_MEDICARE_RATE))


def supplemental_flat_withholding(bonus, ytd_supplemental=0) -> Decimal:
    """22% up to $1M of supplemental wages per calendar year, 37% on the excess (IRS Pub 15)."""
    bonus, ytd = _dec(bonus, "bonus"), _dec(ytd_supplemental, "ytd")
    at_22 = max(D(0), min(bonus, SUPP_THRESHOLD - ytd))
    return money(at_22 * SUPP_FLAT_RATE + (bonus - at_22) * SUPP_MANDATORY_RATE)


def k401_allowed(requested, ytd_deferrals, age: int) -> Decimal:
    """Employee elective deferral actually allowed this period (cap = 402(g) limit + catch-up).
    Not modelled: mandatory Roth catch-up for prior-year FICA wages > $150k."""
    req, ytd = _dec(requested, "requested"), _dec(ytd_deferrals, "ytd")
    limit = K401_LIMIT_2026
    if 60 <= age <= 63:
        limit += K401_CATCHUP_60_63
    elif age >= 50:
        limit += K401_CATCHUP_50
    return min(req, max(D(0), limit - ytd))


def taxable_wages(gross, section125=0, k401_pretax=0) -> tuple[Decimal, Decimal]:
    """(fica_wages, federal_income_tax_wages). Sec.125 reduces both; traditional 401(k) reduces only FIT wages."""
    g, s125, k = _dec(gross, "gross"), _dec(section125, "sec125"), _dec(k401_pretax, "401k")
    return max(D(0), g - s125), max(D(0), g - s125 - k)


def net_pay(gross, fit_withheld, fica: Fica, k401_pretax=0, section125=0, posttax=0, other_taxes=0) -> Decimal:
    net = (_dec(gross, "gross") - _dec(fit_withheld, "fit") - fica.employee_total - _dec(k401_pretax, "401k")
           - _dec(section125, "sec125") - _dec(posttax, "posttax") - _dec(other_taxes, "other"))
    if net < 0:
        raise NegativeNetPay(f"deductions exceed gross by {-net}")
    return money(net)


# ----------------------------------------------------------------- deadlines --
def is_business_day(d: date, holidays: Iterable[date] = ()) -> bool:
    return d.weekday() < 5 and d not in set(holidays)


def next_business_day(d: date, holidays: Iterable[date] = ()) -> date:
    hol = set(holidays)
    d += timedelta(days=1)
    while not is_business_day(d, hol):
        d += timedelta(days=1)
    return d


def payroll_deadline(check_date: date, speed: str, holidays: Iterable[date] = ()) -> date:
    """Submit N business days before the check date (4-day / 2-day / next-day).
    Bank holidays inside the window push the deadline one business day earlier (Gusto docs)."""
    hol, d, n = set(holidays), check_date, SPEED_BUSINESS_DAYS[speed]
    while n:
        d -= timedelta(days=1)
        if is_business_day(d, hol):
            n -= 1
    return d


def cutoff_dt(deadline: date) -> datetime:
    return datetime.combine(deadline, CUTOFF, tzinfo=PT)


@dataclass(frozen=True)
class Submission:
    on_time: bool
    processing_start: date


def evaluate_submission(submitted_at: datetime, deadline: date, holidays: Iterable[date] = ()) -> Submission:
    """ASSUMPTION: 16:00:00.000 PT exactly counts as LATE (the status doc says 'at or after 4:00pm PT' = pending).
    Late submissions slip to the next business day (Gusto docs)."""
    if submitted_at.tzinfo is None:
        raise ValueError("submitted_at must be timezone-aware")
    pt = submitted_at.astimezone(PT)
    if pt < cutoff_dt(deadline):
        return Submission(True, deadline)
    hol = set(holidays)
    candidate = pt.date() if (is_business_day(pt.date(), hol) and pt.time() < CUTOFF) else next_business_day(pt.date(), hol)
    return Submission(False, max(candidate, next_business_day(deadline, hol)))


def payroll_status(processed: bool, now: datetime, deadline: date, check_date: date) -> str:
    """unprocessed -> submitted -> pending (>=4pm PT on deadline) -> paid (>= check_date). Source: Gusto API status table.
    ASSUMPTION: 'paid' begins at 00:00 PT on check_date."""
    if not processed:
        return "unprocessed"
    now = now.astimezone(PT)
    if now >= datetime.combine(check_date, time(0, 0), tzinfo=PT):
        return "paid"
    return "pending" if now >= cutoff_dt(deadline) else "submitted"
