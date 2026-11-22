# Defect evidence - live gusto.com (last run 2026-11-22 16:44)

Red outlines and the yellow note are annotations added by `scripts/capture_evidence.py`.

| Defect | Re-test | Observed | Evidence | Checked |
| --- | --- | --- | --- | --- |
| DEF-01 | REPRODUCED | gross 800.00, take-home -261.20 | [DEF-01_negative_take_home.png](DEF-01_negative_take_home.png)<br>[video/DEF-01.webm](video/DEF-01.webm) | 2026-11-22 16:42 |
| DEF-02 | REPRODUCED | HTTP 200, Inf/NaN in body: True, strict JSON: False | [DEF-02_huge_wage.png](DEF-02_huge_wage.png)<br>[DEF-02_server_response.json.txt](DEF-02_server_response.json.txt)<br>[video/DEF-02.webm](video/DEF-02.webm) | 2026-11-22 16:42 |
| DEF-04 | REPRODUCED | 1000 h weekly -> gross 20000.00 | [DEF-04_1000_hours_weekly.png](DEF-04_1000_hours_weekly.png)<br>[video/DEF-07_DEF-05_DEF-04.webm](video/DEF-07_DEF-05_DEF-04.webm) | 2026-11-22 16:42 |
| DEF-05 | REPRODUCED | '20,5' -> 205.00, gross 8200.00 | [DEF-05_decimal_comma.png](DEF-05_decimal_comma.png)<br>[video/DEF-07_DEF-05_DEF-04.webm](video/DEF-07_DEF-05_DEF-04.webm) | 2026-11-22 16:42 |
| DEF-06 | REPRODUCED | hint MM/DD/YYYY with Day-first fields in ['en-GB', 'en-IN'] | [DEF-06_date_hint_en-GB.png](DEF-06_date_hint_en-GB.png)<br>[video/DEF-06_en-GB.webm](video/DEF-06_en-GB.webm)<br>[DEF-06_date_hint_en-IN.png](DEF-06_date_hint_en-IN.png)<br>[video/DEF-06_en-IN.webm](video/DEF-06_en-IN.webm) | 2026-11-22 16:42 |
| DEF-07 | REPRODUCED | hint = 'Work more than 8 hours a workday or more than 40 hours per workweek.' | [DEF-07_wage_hint.png](DEF-07_wage_hint.png)<br>[video/DEF-07_DEF-05_DEF-04.webm](video/DEF-07_DEF-05_DEF-04.webm) | 2026-11-22 16:42 |
| DEF-08 | REPRODUCED | OT $10 x 12 -> gross 920.00 | [DEF-08_overtime_below_regular.png](DEF-08_overtime_below_regular.png)<br>[video/DEF-08.webm](video/DEF-08.webm) | 2026-11-22 16:42 |
| DEF-09 | REPRODUCED | before ('35.00', 'Weekly') -> after ('', 'Biweekly') | [DEF-09_step1_before_accepting_cookies.png](DEF-09_step1_before_accepting_cookies.png)<br>[DEF-09_step2_after_accepting_cookies.png](DEF-09_step2_after_accepting_cookies.png)<br>[video/DEF-09.webm](video/DEF-09.webm) | 2026-11-22 16:42 |
| DEF-10 | REPRODUCED | 4.5 % -> box shows '5', pre-tax 40.00 | [DEF-10_percentage_rounded.png](DEF-10_percentage_rounded.png)<br>[video/DEF-10.webm](video/DEF-10.webm) | 2026-11-22 16:42 |
| DEF-11 | REPRODUCED | federal extra $5,000 -> take-home -4315.28; state extra $2,000 -> take-home -1347.96 | [DEF-11_federal_extra_withholding.png](DEF-11_federal_extra_withholding.png)<br>[DEF-11_state_extra_withholding.png](DEF-11_state_extra_withholding.png)<br>[video/DEF-11.webm](video/DEF-11.webm) | 2026-11-22 16:42 |
| DEF-12 | REPRODUCED | pay date 1899-01-15: HTTP 200, gross 0.00, error shown False | [DEF-12_pay_year_1899.png](DEF-12_pay_year_1899.png)<br>[video/DEF-12.webm](video/DEF-12.webm) | 2026-11-22 16:42 |
| DEF-13 | REPRODUCED | negative wage -20 -> HTTP 200; wage 'abc' -> HTTP 200; negative hours -40 -> HTTP 500; unknown pay frequency 'Fortnightly' -> HTTP 500 | [DEF-13_server_side_validation.png](DEF-13_server_side_validation.png)<br>[DEF-13_server_validation.json.txt](DEF-13_server_validation.json.txt)<br>[video/DEF-13.webm](video/DEF-13.webm) | 2026-11-22 16:42 |
| DEF-14 | REPRODUCED | state tax 0 deps 32.68, 1 dep 31.72, 1.5 deps 32.68 (treated as 0), no message | [DEF-14_fractional_dependents.png](DEF-14_fractional_dependents.png)<br>[video/DEF-14.webm](video/DEF-14.webm) | 2026-11-22 16:44 |
