# Gusto Payroll QA - test model, API and UI automation (Python)

Module under test: **Payroll > Run payroll** (regular, off-cycle, bonus) on https://gusto.com, plus Gusto's
public hourly paycheck calculator, which runs the same kind of rules without needing an account.

| Layer | Folder | Needs | Marker |
| --- | --- | --- | --- |
| Reference model (unit) | `tests/unit` | nothing | `unit` |
| API (demo host only) | `tests/api` | `GUSTO_API_TOKEN`, `GUSTO_COMPANY_ID` | `api` |
| UI, public calculator | `tests/ui/test_public_calculator.py` | internet, **headed** browser | `ui` |
| UI, logged-in app | `tests/ui/test_run_payroll_app.py` | `.auth/gusto.json` from `scripts/save_login_state.py` | `ui` |

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && playwright install chromium
pytest -m unit                                                     # runs anywhere, no network
pytest tests/ui/test_public_calculator.py --headed                 # live gusto.com (headless gets a Cloudflare 403)
USE_MOCK_CALCULATOR=1 pytest tests/ui/test_public_calculator.py    # framework self-test, offline, headless OK
USE_MOCK_CALCULATOR=1 MOCK_BUG=negnet pytest tests/ui/test_public_calculator.py   # seed one bug; the suite must go red
python scripts/inspect_page.py                                     # prints every control's name= attribute
GUSTO_API_TOKEN=... GUSTO_COMPANY_ID=... pytest -m api
python scripts/build_test_cases.py                                 # regenerates data/test_cases.xlsx/.csv with run results
python scripts/capture_evidence.py [DEF-01 ...]                    # re-test defects in visible Chrome, annotated screenshots
```

Every run records each test's outcome in `reports/results.json` (per layer: unit / live / mock[:bug] / api).
`scripts/build_test_cases.py` turns that into the Status / Actual result / Defect ID columns of the matrix and a
Defects sheet. `FINDINGS.md` lists the defects confirmed on live gusto.com and the faults fixed in this framework.

Notes
- `src/payroll_oracle.py` is an independent reference model, not Gusto's engine. It does not model progressive
  income-tax withholding or state taxes; the UI tests assert invariants for those.
- Tests marked `known_defect("DEF-xx")` reproduce a confirmed live bug. They are strict-xfail on live runs: green
  while the bug exists, red the day it is fixed (then remove the marker). On the clean mock they must pass.
- The live calculation endpoint rate-limits (HTTP 429). The page object paces calculations (1.5 s) and retries a
  429 once; one live run of the calculator suite is ~45 calculations, so don't loop it.
- Use a Gusto demo/trial company only. `.auth/` holds live session cookies and is git-ignored.
- Cases marked ASSUMPTION in the matrix are questions for the product owner.
