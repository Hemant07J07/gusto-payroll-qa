"""Overtime / gross-pay rules. Expected values are hand-computed, not copied from the code under test."""
from decimal import Decimal as D

import pytest

from payroll_oracle import weekly_gross_ca, weekly_gross_flsa

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "rate,hours,bonus,expected,why",
    [
        # --- positive
        (20, 40, 0, "800.00", "exactly 40h: no OT"),
        (20, 41, 0, "830.00", "1h OT: 800 + 1*30"),
        (20, 52, 0, "1160.00", "Gusto doc example: premium = 0.5*20*12 = 120"),
        # --- boundary
        (20, "39.99", 0, "799.80", "just under threshold"),
        (20, "40.01", 0, "800.30", "just over threshold: 800.20 + 0.10 premium"),
        (20, 0, 0, "0.00", "zero hours"),
        (20, 168, 0, "4640.00", "max hours in a week: 3360 + 0.5*20*128 = 3360 + 1280"),
        # --- edge: regular-rate interaction between bonus and OT
        (20, 50, 200, "1320.00", "RR=(1000+200)/50=24 -> premium 0.5*24*10=120"),
        (20, 40, 200, "1000.00", "bonus but no OT -> no premium"),
        (20, 0, 200, "200.00", "bonus only, no hours (avoid div-by-zero)"),
        # --- edge: sub-cent intermediate values are rounded once, half-up, at the end
        ("15.555", 41, 0, "645.53", "637.755 + 7.7775 = 645.5325 -> 645.53"),
    ],
)
def test_flsa_weekly_gross(rate, hours, bonus, expected, why):
    assert weekly_gross_flsa(rate, hours, bonus) == D(expected), why


def test_discretionary_bonus_is_excluded_from_regular_rate():
    """Gusto: discretionary bonuses do not count toward overtime. Treat it as pay on top of FLSA gross."""
    assert weekly_gross_flsa(20, 50) + D("200") == D("1300.00")
    assert weekly_gross_flsa(20, 50, 200) == D("1320.00")  # non-discretionary is different: $20 more


@pytest.mark.parametrize(
    "rate,hours,bonus",
    [(-1, 40, 0), (20, -0.5, 0), (20, 169, 0), (20, 40, -5)],
)
def test_flsa_rejects_invalid_input(rate, hours, bonus):
    with pytest.raises(ValueError):
        weekly_gross_flsa(rate, hours, bonus)


@pytest.mark.parametrize(
    "days,expected,why",
    [
        ([8, 8, 8, 8, 8, 0, 0], "800.00", "plain 5x8"),
        ([0] * 7, "0.00", "no work"),
        ([8, 0, 0, 0, 0, 0, 0], "160.00", "exactly 8h in a day"),
        (["8.01", 0, 0, 0, 0, 0, 0], "160.30", "8.01h: 0.01h at 1.5x"),
        ([12, 0, 0, 0, 0, 0, 0], "280.00", "12h: 8*20 + 4*30"),
        (["12.01", 0, 0, 0, 0, 0, 0], "280.40", "12.01h: 0.01h at 2x"),
        ([14, 0, 0, 0, 0, 0, 0], "360.00", "8*20 + 4*30 + 2*40"),
        ([10, 10, 10, 10, 0, 0, 0], "880.00", "4x10 = 40h: FLSA says no OT, CA daily OT does"),
        ([8, 8, 8, 8, 8, 8, 0], "1040.00", "6x8=48h: 8 weekly OT hours"),
        ([8] * 7, "1280.00", "7 consecutive days: 800 + 240 weekly + 240 seventh-day"),
        ([8, 8, 8, 8, 8, 8, 9], "1320.00", "7th day 9h: 8*30 + 1*40"),
    ],
)
def test_ca_style_daily_overtime(days, expected, why):
    assert weekly_gross_ca(20, days) == D(expected), why


def test_same_hours_pay_differently_under_flsa_vs_ca():
    """Key business-logic divergence: 4x10h = 40h. A tester who only knows the federal rule would miss this."""
    assert weekly_gross_flsa(20, 40) == D("800.00")
    assert weekly_gross_ca(20, [10, 10, 10, 10, 0, 0, 0]) == D("880.00")


@pytest.mark.parametrize("days", [[8] * 6, [8] * 8, [25, 0, 0, 0, 0, 0, 0]])
def test_ca_rejects_bad_shapes(days):
    with pytest.raises(ValueError):
        weekly_gross_ca(20, days)
