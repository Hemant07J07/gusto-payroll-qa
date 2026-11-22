"""
Gusto Embedded Payroll API checks (DEMO environment only - never point this at production).

Needs:  GUSTO_API_TOKEN   (Bearer token from a demo app)
        GUSTO_COMPANY_ID  (UUID of a demo company)
Optional: GUSTO_API_BASE (default https://api.gusto-demo.com), GUSTO_API_VERSION (default 2026-06-15)

SCHEMA CAVEAT: endpoint paths, the 202-async calculate, 404/422 behaviour, the status table and the debit
breakdown come from docs.gusto.com. Individual response field names were NOT verified against a live
response - each such test is written defensively (skips if the field is absent) so the first real run
tells you exactly what to tighten.
"""
import os
import uuid
from datetime import datetime
from decimal import Decimal

import pytest
import requests

from payroll_oracle import is_business_day

pytestmark = pytest.mark.api

BASE = os.getenv("GUSTO_API_BASE", "https://api.gusto-demo.com").rstrip("/")
VERSION = os.getenv("GUSTO_API_VERSION", "2026-06-15")
TOKEN, COMPANY = os.getenv("GUSTO_API_TOKEN"), os.getenv("GUSTO_COMPANY_ID")

if not (TOKEN and COMPANY):
    pytest.skip("set GUSTO_API_TOKEN and GUSTO_COMPANY_ID (demo env) to run API tests", allow_module_level=True)
if "gusto-demo" not in BASE:
    pytest.skip("refusing to run mutating API tests against a non-demo host", allow_module_level=True)


class _TimeoutSession(requests.Session):
    """requests ignores a `Session.timeout` attribute (the first version set one, so every call could hang
    forever). The timeout has to be passed per request; this does it for every call."""

    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", 30)
        return super().request(*args, **kwargs)


@pytest.fixture(scope="module")
def api():
    s = _TimeoutSession()
    s.headers.update({"Authorization": f"Bearer {TOKEN}", "X-Gusto-API-Version": VERSION, "Accept": "application/json"})
    return s


def url(path: str) -> str:
    return f"{BASE}/v1/companies/{COMPANY}{path}"


@pytest.fixture(scope="module")
def payrolls(api):
    r = api.get(url("/payrolls"), params={"processing_statuses": "unprocessed,processed", "include_off_cycle": "true"})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ auth ----
def test_missing_token_is_401():
    r = requests.get(url("/payrolls"), headers={"X-Gusto-API-Version": VERSION}, timeout=30)
    assert r.status_code == 401


def test_garbage_token_is_401():
    r = requests.get(url("/payrolls"), headers={"Authorization": "Bearer not-a-token", "X-Gusto-API-Version": VERSION}, timeout=30)
    assert r.status_code == 401


# ------------------------------------------------------- negative / robust ----
def test_calculate_unknown_payroll_is_404(api):
    r = api.put(url(f"/payrolls/{uuid.uuid4()}/calculate"))
    assert r.status_code == 404


@pytest.mark.parametrize("bad_id", ["not-a-uuid", "0", "' OR 1=1 --", "a" * 300])
def test_calculate_malformed_id_never_5xx(api, bad_id):
    r = api.put(url(f"/payrolls/{bad_id}/calculate"))
    assert r.status_code in (400, 404, 422), f"got {r.status_code}"


def test_unsupported_api_version_is_client_error(api):
    r = requests.get(url("/payrolls"), headers={"Authorization": f"Bearer {TOKEN}", "X-Gusto-API-Version": "1999-01-01"}, timeout=30)
    assert 400 <= r.status_code < 500


def test_other_companys_payroll_is_not_visible(api):
    """Multi-tenant isolation probe: random company id must not leak data."""
    r = api.get(f"{BASE}/v1/companies/{uuid.uuid4()}/payrolls")
    assert r.status_code in (403, 404)


# ------------------------------------------------------------ invariants ----
def test_payroll_deadlines_are_business_days_before_check_date(payrolls):
    checked = 0
    for p in payrolls:
        if not (p.get("payroll_deadline") and p.get("check_date")):
            continue
        deadline = datetime.fromisoformat(p["payroll_deadline"].replace("Z", "+00:00")).date()
        check = datetime.fromisoformat(p["check_date"]).date() if len(p["check_date"]) == 10 else \
            datetime.fromisoformat(p["check_date"].replace("Z", "+00:00")).date()
        pid = p.get("payroll_uuid") or p.get("uuid")
        assert deadline < check, f"payroll {pid}: deadline {deadline} not before check date {check}"
        assert is_business_day(deadline), f"payroll {pid}: deadline {deadline} is a weekend"
        checked += 1
    if not checked:
        pytest.skip("no payroll exposes payroll_deadline/check_date")


def test_company_debit_equals_sum_of_components(payrolls):
    """Docs: company_debit is the combined total of net_pay, reimbursement, tax and child-support debits."""
    seen = 0
    for p in payrolls:
        t = p.get("totals") or {}
        if "company_debit" not in t:
            continue
        parts = sum(Decimal(str(t.get(k) or "0")) for k in ("net_pay_debit", "reimbursement_debit", "tax_debit", "child_support_debit"))
        assert Decimal(str(t["company_debit"])) == parts, f"payroll {p.get('payroll_uuid')}: {t}"
        seen += 1
    if not seen:
        pytest.skip("no processed payroll with totals in demo company")


def test_resubmitting_a_processed_payroll_is_rejected(api, payrolls):
    done = next((p for p in payrolls if p.get("processed") is True), None)
    if not done:
        pytest.skip("need a processed payroll in the demo company")
    pid = done.get("payroll_uuid") or done.get("uuid")
    r = api.put(url(f"/payrolls/{pid}/submit"), json={})
    assert r.status_code == 422, "double submit must not be accepted"


def test_calculate_is_async_202(api, payrolls):
    open_p = next((p for p in payrolls if p.get("processed") is False), None)
    if not open_p:
        pytest.skip("need an unprocessed payroll in the demo company")
    pid = open_p.get("payroll_uuid") or open_p.get("uuid")
    r = api.put(url(f"/payrolls/{pid}/calculate"))
    assert r.status_code in (202, 422), r.text  # 422 is acceptable when a payroll blocker (bank/tax setup) exists
