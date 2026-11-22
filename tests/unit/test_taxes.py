"""FICA, supplemental (bonus) withholding, 401(k) caps, taxable-wage buckets and net-pay invariants."""
import random
from decimal import Decimal as D

import pytest

from payroll_oracle import (
    NegativeNetPay, fica_employee, k401_allowed, net_pay, supplemental_flat_withholding, taxable_wages,
)

pytestmark = pytest.mark.unit


# ------------------------------------------------------------------ FICA ----
@pytest.mark.parametrize(
    "wages,ytd,ss,med,addl,why",
    [
        (1000, 0, "62.00", "14.50", "0.00", "plain"),
        (2000, 184000, "31.00", "29.00", "0.00", "crosses SS wage base: only 500 taxable"),
        (1000, 184500, "0.00", "14.50", "0.00", "already AT wage base"),
        (1000, 190000, "0.00", "14.50", "0.00", "above wage base: Medicare still applies"),
        ("0.02", "184499.99", "0.00", "0.00", "0.00", "0.01 taxable * 6.2% = 0.0006 -> 0.00"),
        (2000, 199000, "0.00", "29.00", "9.00", "crosses 200k: 1000 over -> 0.9% = 9.00 (SS already capped at 184.5k)"),
        (1000, 200000, "0.00", "14.50", "9.00", "exactly at threshold: whole paycheck is 'over'; SS capped"),
        (1000, 250000, "0.00", "14.50", "9.00", "well above both"),
        (0, 0, "0.00", "0.00", "0.00", "zero wages"),
    ],
)
def test_fica(wages, ytd, ss, med, addl, why):
    f = fica_employee(wages, ytd)
    assert (f.social_security, f.medicare, f.additional_medicare) == (D(ss), D(med), D(addl)), why


def test_medicare_rounding_is_half_up_not_bankers():
    """10.00 * 1.45% = 0.145 exactly. Half-up -> 0.15; banker's rounding would give 0.14."""
    assert fica_employee(10).medicare == D("0.15")


def test_fica_rejects_negative_wages():
    with pytest.raises(ValueError):
        fica_employee(-1)


# ------------------------------------------------------ supplemental (bonus) --
@pytest.mark.parametrize(
    "bonus,ytd,expected,why",
    [
        (1000, 0, "220.00", "flat 22%"),
        (0, 0, "0.00", "no bonus"),
        (2000, 999000, "590.00", "1000 @22% + 1000 @37%"),
        (500, 1000000, "185.00", "all of it above $1M -> 37%"),
        (1000000, 0, "220000.00", "exactly $1M is still 22%"),
        ("1000000.01", 0, "220000.00", "0.01 over -> 0.0037 -> rounds to 0.00 extra"),
    ],
)
def test_supplemental_withholding(bonus, ytd, expected, why):
    assert supplemental_flat_withholding(bonus, ytd) == D(expected), why


def test_supplemental_rejects_negative_bonus():
    with pytest.raises(ValueError):
        supplemental_flat_withholding(-1)


# ------------------------------------------------------------------ 401(k) ---
@pytest.mark.parametrize(
    "requested,ytd,age,expected,why",
    [
        (1000, 0, 30, "1000", "well under limit"),
        (1000, 24000, 30, "500", "only 500 of room left"),
        (1000, 24500, 30, "0", "limit reached"),
        (1000, 24500, 49, "0", "49: no catch-up"),
        (1000, 24500, 50, "1000", "50: catch-up 8,000 -> cap 32,500"),
        (1000, 32000, 55, "500", "partial room under catch-up cap"),
        (1000, 35000, 60, "750", "60-63 'super' catch-up: cap 35,750"),
        (1000, 35000, 63, "750", "63 still super catch-up"),
        (1000, 32500, 64, "0", "64: back to standard catch-up cap 32,500"),
        (0, 0, 40, "0", "no election"),
    ],
)
def test_k401_cap(requested, ytd, age, expected, why):
    assert k401_allowed(requested, ytd, age) == D(expected), why


def test_k401_rejects_negative():
    with pytest.raises(ValueError):
        k401_allowed(-1, 0, 30)


# ------------------------------------------------- taxable buckets / net pay --
def test_taxable_wage_buckets():
    fica_w, fit_w = taxable_wages(2000, section125=100, k401_pretax=200)
    assert (fica_w, fit_w) == (D(1900), D(1700)), "401k lowers FIT wages only; sec.125 lowers both"


def test_taxable_wages_never_negative():
    assert taxable_wages(100, section125=500) == (D(0), D(0))


def test_net_pay_hand_computed():
    f = fica_employee(2000)  # 124.00 + 29.00
    assert net_pay(2000, 150, f) == D("1697.00")
    assert net_pay(2000, 150, f, k401_pretax=200) == D("1497.00")


def test_net_pay_negative_is_rejected():
    with pytest.raises(NegativeNetPay):
        net_pay(100, 10, fica_employee(100), posttax=500)


def test_net_pay_invariant_randomised():
    """Property-style check: net + every deduction == gross, for 500 seeded random paychecks."""
    rng = random.Random(2026)
    for _ in range(500):
        gross = D(rng.randint(10_000, 900_000)) / 100
        ytd = D(rng.randint(0, 30_000_000)) / 100
        k401 = (gross * D(rng.randint(0, 20)) / 100).quantize(D("0.01"))
        fica_w, _ = taxable_wages(gross, k401_pretax=k401)
        f = fica_employee(fica_w, ytd)
        fit = (gross * D("0.1")).quantize(D("0.01"))
        net = net_pay(gross, fit, f, k401_pretax=k401)
        assert net + fit + f.employee_total + k401 == gross
