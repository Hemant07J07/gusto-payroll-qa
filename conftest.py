import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# make `pages.*` importable from tests/ui regardless of where pytest is launched
sys.path.insert(0, str(Path(__file__).parent / "tests" / "ui"))

RESULTS = Path(__file__).parent / "reports" / "results.json"
_records: dict[str, dict] = {}


def _mode(nodeid: str) -> str:
    if nodeid.startswith("tests/unit"):
        return "unit"
    if nodeid.startswith("tests/api"):
        return "api"
    if os.getenv("USE_MOCK_CALCULATOR"):
        return "mock" + (f":{os.getenv('MOCK_BUG')}" if os.getenv("MOCK_BUG") else "")
    return "live"


def pytest_runtest_logreport(report):
    """Remember every test's outcome, keyed by test id, with its TC-PAY case id and known-defect id."""
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        item_case = getattr(report, "case_id", None)
        outcome = report.outcome
        if hasattr(report, "wasxfail"):
            outcome = "xfail" if report.skipped else "xpass"
        msg = ""
        if report.failed or outcome == "xfail":
            msg = (report.longreprtext or "").strip().splitlines()[-1][:300] if report.longreprtext else ""
        elif report.skipped and isinstance(report.longrepr, tuple):
            msg = str(report.longrepr[2])[:300]
        _records[report.nodeid] = {"case": item_case, "defect": getattr(report, "defect_id", None),
                                   "outcome": outcome, "detail": msg, "seconds": round(report.duration, 2)}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    m = item.get_closest_marker("case")
    d = item.get_closest_marker("known_defect")
    rep.case_id = m.args[0] if m else None
    rep.defect_id = d.args[0] if d else None


def pytest_sessionfinish(session, exitstatus):
    if not _records:
        return
    RESULTS.parent.mkdir(exist_ok=True)
    data = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for nodeid, rec in _records.items():
        run = data.setdefault(_mode(nodeid), {"tests": {}})
        run["tests"][nodeid] = rec
        run["updated"] = now
    RESULTS.write_text(json.dumps(data, indent=1, sort_keys=True))
