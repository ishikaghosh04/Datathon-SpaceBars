# Well, Oh Well: time-series, failure-risk and repair-effectiveness track

**Run everything with graphs:** `pip install -r requirements.txt`, then open `Well_Oh_Well_analysis.ipynb` and set `DATA_DIR` (or the `WOW_DATA` environment variable) to the folder with the three Parquet files, and Run All. It takes about 3 minutes and needs about 6 GB of RAM. A pre-run copy with every chart is in `Well_Oh_Well_analysis.html`, and the figures are in `outputs/figures/`.
Scripts only: `bash src/run_all.sh "<path>/Competition Dataset" work outputs`, then `python src/economics.py <data> work outputs`.

## Prototype settings (chosen after checking data coverage, not Strathcona requirements)
| Setting | Value | Why |
|---|---|---|
| Demo date | **2026-06-30** | Leaves a full 30-day failure window and about 4 months of outcomes to reveal before the data ends on 2026-10-27 |
| Volume unit | **m³ oil** (per day for rates). 1 m³ = 6.2898 bbl | Native unit of the data. Business: quote margin in CAD/m³ |
| Failure prediction window | **next 30 days** | |
| Repair outcome window | **90 days after job start** | |

## What the data supports (step 1)
- Join key `uwi` (= `well_id`); daily rows by `production_date`, jobs by `start_date`, failures by `failure_start_date`.
- **Failure log starts in mid-2025** (2 records before 2025; complete from 2025-Q3). A *failure episode* is therefore defined as a failure-log record OR a failure-driven repair job (rod / pump / tubing repair; 65–96% of these jobs match a logged failure in 2025-H2–2026), merged within 7 days. This gives one consistent event series from 2021.
- Failures link to jobs reliably: 81% have a job on the same well the same day, 98% within −3..+7 days.
- Zero oil on Producing wells is real downtime (0 hours on plus a downtime code). Zero oil with 24 h on and no water (26.6k rows) is treated as a missing reading. 168 wells have missing days, which stay missing (not zero).
- `job_type` "Rod Repair" (2021–22, cost often $0) was renamed to "Corod Rod Repair" / "Stick Rod Repair" in 2023.

## Method (all trailing windows on each well's own daily series, so a value on date t uses only data ≤ t)
- **Baseline** = rolling median oil on normal running days (≥20 h on), days t−104..t−14. **Current** = 7-day mean including downtime days. **oil_lost_per_day** = max(0, baseline − current).
- **Other time-series features**: 7-vs-30-day change, 30-day rolling OLS trend, downtime share over 7 and 30 days, water-cut level and change, volatility (CV), pump-efficiency and torque ratio (7d vs 90d), RPM, failures in the last 365 d, days since the last failure / rod job, jobs in the last 365 d, well age.
- **Risk model**: logistic regression on weekly scoring dates. Trains on score dates 2022-01..2025-11-30 (labels close by 2025-12-30) and tests on 2026-01-05..2026-05-31, so there is no label overlap. The demo-date model is refit on all labels that closed by 2026-06-30.
- **Repair effectiveness (rod repairs, 7,131 jobs with complete 90-day follow-up)**. The counterfactual for "crew waited" is that the well keeps producing at its rate on the 2 days before the job (its failed state). Actual production from the job day onward includes repair downtime. A repeat is a new rod failure episode more than 7 days and up to 90 days after the job.

## Results
**Model vs production drop at equal inspection capacity (test Jan–Jun 2026, 932 distinct failure episodes, about 870 eligible wells per week):**

| Wells inspected / week | Model: flagged (median warning) | Drop alone | Random |
|---|---|---|---|
| 25 | 177 (18 d) | 81 (18 d) | 84 |
| 50 | 269 (22 d) | 162 (16.5 d) | 152 |
| 100 | 398 (24 d) | 286 (17 d) | 277 |

ROC-AUC is 0.74 for the model and 0.56 for the drop alone; PR-AUC is 0.36 vs 0.19, where 0.16 is chance. Calibration on test is close: the top decile predicts 43% and 43% happened.
On the demo date, of the top 50 wells, **31 failed within 30 days for the model vs 18 for the drop ranking** (the base rate is 18%, about 9 of 50).
The strongest predictors are recent downtime (down7), failures in the last 365 d, and a recent rod job (a negative coefficient on days since the rod job, so a recent job means higher risk).

**Rod repairs (all with complete 90-day follow-up):** median oil recovered vs waiting is **139 m³ per job over 90 days** (215 m³ when the well was clearly down). Wells return to a median **89%** of their pre-failure baseline, and the median downtime loss is 5 m³. A rod failure returns within 90 days after **59%** of jobs (Corod 52%, Stick 70%). The highest rates are in Winter, and after "Broken Sucker Rod Body" and Fatigue failures. These patterns are evidence to investigate, not causes.

## well_estimates.csv (handoff to Astro): one row per eligible well × candidate job type on the demo date
| Column | Meaning | Unit |
|---|---|---|
| as_of_date | Demo date; every input uses data on or before it | date |
| well_id | `uwi` without punctuation | text |
| job_type | Candidate repair. The rod type comes from the well's last Corod/Stick repair. Wells with unknown rod type get both rows (see flag_reason) | text, matches `well_jobs.job_type` |
| oil_lost_per_day | max(0, own baseline − last-7-day mean oil) | m³ oil/day |
| failure_risk | Model probability of a failure episode in the next 30 days | 0–1 |
| expected_extra_oil | 90 × max(0, comparable restore ratio × baseline − current) − comparable median downtime loss. Blank-equivalent 0 means no recoverable gap | m³ oil over 90 days |
| repeat_failure_rate | Share of comparable jobs followed by a new rod failure within 90 days | 0–1 |
| comparable_job_count | Jobs behind the two comparable values: same job type in the same operating area if there are ≥30, else the job type across all areas. Only jobs whose 90-day follow-up finished by the demo date | count |
| flag_reason | Why the well is flagged for inspection (top 50 by risk, or ≥1 m³/d and ≥25% below baseline). Empty means not flagged | text |

There are 1,163 rows on 890 wells, and 153 wells are flagged. No values in this file are assumed; costs and crew-days come from Business (`repair_inputs.csv`). Extra dashboard context (baseline, current rate, area, rank) is in `well_estimates_context.csv`. Per-job history for the "Did it work?" page is in `rod_repair_outcomes.csv` (the `known_by_demo_date` column marks jobs whose outcome was known by the demo date).

## Caveat for the pitch
Before mid-2025 there is no failure log, so a "failure" there means a failure-driven repair job. The model therefore predicts *repair-worthy failures that crews actually responded to*, and wells that failed but weren't worked on are invisible. Also, a production drop alone is barely better than random at spotting upcoming failures. Most of the signal is recent downtime and failure history.

## Profit view (src/economics.py, notebook section 5)
**Outside data.** Strathcona company-wide C$/boe figures from [S1] Q3 2026 results (https://boereport.com/2026/11/08/strathcona-resources-ltd-reports-third-quarter-2026-financial-and-operating-results-and-announces-quarterly-dividend/) and [S2] Q4/FY2025 results (https://boereport.com/2026/03/11/strathcona-resources-ltd-reports-fourth-quarter-and-full-year-2025-financial-and-operating-results-year-end-reserves-announces-quarterly-dividend-and-board-approval-to-commence-normal-course-issuer/).
**Marginal netback** = sales net of blending − royalties − energy opex − transportation. Non-energy opex is treated as fixed (assumption A2).

| Period | Sales | Royalties | Energy opex | Transport | Marginal netback C$/bbl | C$/m³ |
|---|---|---|---|---|---|---|
| FY2025 (used for demo-date decisions) | 65.12 | 8.45 | 4.28 | 8.61 | 43.78 | 275.4 |
| Q3 2026 | 99.47 | 22.97 | 5.77 | 9.13 | 61.60 | 387.5 |

- **The dataset matches public reporting.** Summed daily oil reads 20.84 Mbbl/d in Q4 2025 (reported 21, Lloydminster Conventional), down 6% q/q (reported −7%). It reads 20.07 in Q3 2026 (reported ~20).
- **Rod repairs pay back fast.** Across 4,796 jobs from 2023 to 2026 with a known cost: median cost C$4.6k, median value of oil recovered in 90 days C$38.9k, median profit C$33k, 81% profitable within 90 days, median payback 8 days. Repeat failures are already inside these numbers, because the 90-day actual production includes them.
- **Demo-date budget scenarios.** Scenario A is C$50k and 10 crew-days; the optimiser picks 17 jobs for C$1.67M expected 90-day net value, against C$1.41M ranking by drop and C$0.43M ranking by risk. Scenario B is C$150k and 30 crew-days: C$3.38M, against C$2.69M and C$1.11M. Ranking by risk maximises failures headed off (9.0 vs 4.4 expected in 30 days in A), not oil, so the dashboard should show both.
- **Stand-in costs.** `outputs/repair_inputs_standin.csv` uses median job-history cost and duration, labelled ASSUMPTION. Business's `repair_inputs.csv` replaces it.
- **Caveats.** These are company-wide prices that include thermal bitumen (A1), so treat dollar values as approximate. The counterfactual assumes a failed well stays down for 90 days without the repair.
