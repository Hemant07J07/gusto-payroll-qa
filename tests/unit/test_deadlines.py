"""Submission deadline, 4 pm PT cut-off, timezone/DST handling and payroll status transitions."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from payroll_oracle import (
    PT, evaluate_submission, is_business_day, next_business_day, payroll_deadline, payroll_status,
)

pytestmark = pytest.mark.unit
THANKSGIVING = {date(2026, 11, 26)}


@pytest.mark.parametrize(
    "check,speed,holidays,expected,why",
    [
        (date(2026, 12, 4), "4-day", (), date(2026, 11, 30), "Fri check date, 4 business days back = Mon"),
        (date(2026, 12, 4), "2-day", (), date(2026, 12, 2), "2 business days back"),
        (date(2026, 12, 4), "next-day", (), date(2026, 12, 3), "1 business day back"),
        (date(2026, 12, 7), "4-day", (), date(2026, 12, 1), "Mon check date: weekend is skipped"),
        (date(2026, 11, 27), "4-day", (), date(2026, 11, 23), "no holiday modelled"),
        (date(2026, 11, 27), "4-day", THANKSGIVING, date(2026, 11, 20), "Thanksgiving pushes deadline 1 business day earlier"),
        (date(2026, 11, 27), "2-day", THANKSGIVING, date(2026, 11, 24), "holiday inside 2-day window"),
        (date(2026, 11, 27), "next-day", THANKSGIVING, date(2026, 11, 25), "holiday = the day before check date"),
    ],
)
def test_payroll_deadline(check, speed, holidays, expected, why):
    assert payroll_deadline(check, speed, holidays) == expected, why


def test_deadline_is_always_a_business_day():
    d = date(2026, 1, 1)
    for _ in range(400):
        for speed in ("4-day", "2-day", "next-day"):
            assert is_business_day(payroll_deadline(d, speed))
        d += timedelta(days=1)


# ---- 4 pm PT cut-off -------------------------------------------------------
def pt(y, m, d, hh, mm, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=PT)


@pytest.mark.parametrize(
    "when,on_time",
    [
        (pt(2026, 11, 23, 15, 59, 59), True),
        (pt(2026, 11, 23, 16, 0, 0), False),   # ASSUMPTION: exactly 16:00:00 is late -> clarify with product
        (pt(2026, 11, 23, 16, 0, 1), False),
        (pt(2026, 11, 23, 0, 0, 0), True),
        (pt(2026, 11, 20, 23, 59, 0), True),   # days early
    ],
)
def test_cutoff_boundary(when, on_time):
    assert evaluate_submission(when, date(2026, 11, 23)).on_time is on_time


def test_late_submission_slips_one_business_day():
    r = evaluate_submission(pt(2026, 11, 23, 17, 0), date(2026, 11, 23))
    assert (r.on_time, r.processing_start) == (False, date(2026, 11, 24))


def test_late_on_friday_slips_to_monday():
    r = evaluate_submission(pt(2026, 12, 4, 16, 30), date(2026, 12, 4))
    assert r.processing_start == date(2026, 12, 7)


def test_late_before_holiday_skips_holiday():
    r = evaluate_submission(pt(2026, 11, 25, 16, 30), date(2026, 11, 25), THANKSGIVING)
    assert r.processing_start == date(2026, 11, 27)


def test_submitted_after_weekend_miss():
    """Deadline Fri, user submits Sat 10:00 -> cannot start before Monday."""
    r = evaluate_submission(pt(2026, 12, 5, 10, 0), date(2026, 12, 4))
    assert (r.on_time, r.processing_start) == (False, date(2026, 12, 7))


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        evaluate_submission(datetime(2026, 11, 23, 15, 0), date(2026, 11, 23))


# ---- timezone / DST traps ---------------------------------------------------
@pytest.mark.parametrize(
    "utc_str,on_time,why",
    [
        # DST ended Sun 2026-11-01 -> on Mon 11-02 PT is UTC-8: 16:00 PST = 00:00 UTC next day
        ("2026-11-03T00:00:00+00:00", False, "16:00 PST sharp"),
        ("2026-11-02T23:59:59+00:00", True, "15:59:59 PST (a PDT-based cutoff of 23:00Z would wrongly say late)"),
        ("2026-11-02T23:00:00+00:00", True, "23:00Z is only 15:00 PST"),
    ],
)
def test_cutoff_uses_pst_after_dst_ends(utc_str, on_time, why):
    assert evaluate_submission(datetime.fromisoformat(utc_str), date(2026, 11, 2)).on_time is on_time, why


def test_cutoff_in_pdt_before_dst_ends():
    # Fri 2026-10-30 is still PDT (UTC-7): 16:00 PDT = 23:00 UTC
    assert evaluate_submission(datetime(2026, 10, 30, 22, 59, 59, tzinfo=timezone.utc), date(2026, 10, 30)).on_time
    assert not evaluate_submission(datetime(2026, 10, 30, 23, 0, 0, tzinfo=timezone.utc), date(2026, 10, 30)).on_time


IST = ZoneInfo("Asia/Kolkata")


def test_user_in_india_crossing_the_date_line():
    """Deadline Mon 11-23. For a user in IST the cutoff is 05:30 on *Tuesday* local time."""
    assert evaluate_submission(datetime(2026, 11, 24, 5, 29, 59, tzinfo=IST), date(2026, 11, 23)).on_time
    assert not evaluate_submission(datetime(2026, 11, 24, 5, 30, 0, tzinfo=IST), date(2026, 11, 23)).on_time


def test_next_business_day_skips_weekend_and_holiday():
    assert next_business_day(date(2026, 11, 25), THANKSGIVING) == date(2026, 11, 27)
    assert next_business_day(date(2026, 12, 4)) == date(2026, 12, 7)


# ---- status state machine ----------------------------------------------------
DEADLINE, CHECK = date(2026, 11, 23), date(2026, 11, 27)


@pytest.mark.parametrize(
    "processed,now,expected",
    [
        (False, pt(2026, 11, 22, 9, 0), "unprocessed"),
        (False, pt(2026, 11, 30, 9, 0), "unprocessed"),            # never submitted, even after check date
        (True, pt(2026, 11, 22, 9, 0), "submitted"),
        (True, pt(2026, 11, 23, 15, 59, 59), "submitted"),
        (True, pt(2026, 11, 23, 16, 0, 0), "pending"),
        (True, pt(2026, 11, 26, 23, 59, 59), "pending"),
        (True, pt(2026, 11, 27, 0, 0, 0), "paid"),
        (True, pt(2026, 12, 15, 0, 0, 0), "paid"),
    ],
)
def test_status_machine(processed, now, expected):
    assert payroll_status(processed, now, DEADLINE, CHECK) == expected
