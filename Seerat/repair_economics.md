# Well, Oh Well: repair economics (business handoff)

## Prototype settings
| Setting | Value | Why |
|---|---|---|
| Demo date | 2026-07-01 | Failures are logged consistently from June 2025. This leaves 13 months of history before the demo date and about 4 months after it to check results. |
| Oil volume unit | m³ (cubic metres) | The unit the dataset uses. Margins are converted at 1 m³ = 6.2898 bbl. |
| Failure prediction window | 90 days | Fits inside the data after the demo date (data ends 2026-10-27). |
| Repair outcome window | 90 days | Matches the finding that 75% of repeat failures happen within 90 days of a repair. |

These are prototype settings chosen by the team, not Strathcona requirements.

## Files
- `repair_inputs.csv`: one row per well and candidate job type on the demo date (8,407 rows, 1,792 wells). Producing wells get six repair types; suspended wells get `reactivation`.
- `repair_inputs_detail.csv`: the same rows plus low/high cost (25th/75th percentile), cost level (well/area/company), crew type and area.
- `job_type_map.csv`: how the source `job_category` + `job_type` values map to our 7 job types. **Astro must use the same mapping** for comparable repairs.
- `margin_assumptions.csv`: low/base/high oil margin, with the source page for each figure.
- `budget_scenarios.csv`: worked-example scenarios A/B and full-scale weekly scenarios.
- `repair_inputs_rod.csv`: costs and crew-days keyed on Astro's rod job types (joins 1:1 with well_estimates.csv).
- `well_estimates_joined.csv`: Astro's estimates + costs + net gain at low/base/high margin + confidence label.
- `plan_rod_base_week.csv`, `plan_rod_tight_week.csv`: the optimizer's chosen jobs.
- `worked_example_candidates.csv`, `worked_example_all_combinations.csv`: the hand-checkable optimizer example.

## Where the costs and crew-days come from
- **Repair cost**: `well_jobs.field_est_total` is a *field estimate* (`actual_final_job_cost` is empty in every row). Zero or negative estimates (16% of repair jobs) are treated as missing. We use the median of comparable jobs from Jul 2024 to Jun 2026: the same well if it has 3+ such jobs, else the same area (10+), else the company. Every candidate row has at least a company-level estimate. If a future job type has none, leave the cost blank and compare against the **break-even repair cost** = expected extra oil × margin.
- **Crew-days**: `job_duration_days` (end minus start), excluding values ≤ 0 or > 30. This is elapsed time, used as a proxy for crew time. It excludes travel and rig moves.

## Margin
Incremental margin per m³ = (sales net of blending − royalties − energy opex − transportation) × 6.2898, using Lloydminster Conventional segment figures from Strathcona's MD&A. Non-energy opex is excluded because it already contains downhole maintenance (repair) costs. Including it would count the repair cost twice. These are segment averages, not well-level profits.

| Case | Period | C$/bbl | C$/m³ | Source |
|---|---|---|---|---|
| Low | 9M 2025 | 55.61 | 349.8 | Q3 2026 MD&A p. 23 |
| Base | 9M 2026 | 69.76 | 438.8 | Q3 2026 MD&A p. 23 |
| High | Q2 2026 | 76.96 | 484.1 | Q3 2026 MD&A p. 21; Q2 2026 MD&A p. 21 |

Check: the dataset averages about 20,076 bbl/d of oil in Q3 2026. Strathcona reports 19,795 bbl/d of crude for the Lloydminster Conventional segment (Q3 2026 MD&A p. 36). So the dataset matches that segment, which is why its margins are used.

## Calculation
- Expected extra oil (m³) = oil recovered over the 90-day outcome window after the repair, **net of the repair downtime and of repeat failures** (Astro's `expected_extra_oil`).
- Oil value = expected extra oil × margin. This is also the **break-even repair cost**.
- Net gain = oil value − repair cost.
- Net gain per $1 of repair = net gain ÷ repair cost. Net gain per crew-day = net gain ÷ crew-days. Both are comparison metrics only.
- Payback days = crew-days + repair cost ÷ (oil lost per day × margin). This is only shown for wells that are down, where the benefit starts as soon as the well restarts.
- Repeat failures: `expected_extra_oil` already reflects how often similar repairs failed again, so **do not subtract repeat failures a second time**. Use `repeat_failure_rate` and `comparable_job_count` as a confidence label (for example, low confidence if fewer than 10 comparable jobs or a repeat rate above 50%).
- Optimizer: choose at most one job per well to maximize total net gain, subject to total cost ≤ budget and total crew-days ≤ crew-days available.

## Joined with Astro's well_estimates.csv
- 1,163 rows (890 producing wells) for two job types: `Corod Rod Repair` and `Stick Rod Repair`. Astro uses the source job names, so `repair_inputs_rod.csv` has costs keyed on those names. Every row joins 1:1.
- 273 wells have both rod job types listed because their rod type is unknown. The optimizer allows only one job per well, but the team should confirm each well's real rod type.
- `failure_risk` is a 30-day risk. `repeat_failure_rate` and `comparable_job_count` describe groups of similar jobs (job type × area), not the individual well.
- Full-week result, solved exactly with an integer program (`join_estimates.py`):
  - Rod base week (C$105,000, 9.7 crew-days, measured Apr–Jun 2026 average): 33 jobs, C$104,994, 8.15 crew-days, about C$4.20M estimated net gain.
  - Rod tight week (70%): 24 jobs, C$73,322, 5.82 crew-days, about C$3.36M.
  - The budget runs out before the crews do.
- 189 rows have an inspection flag. 20 of them lose money as a repair (for example, 71% failure risk but no expected extra oil). That is why "inspect" and "repair" are separate decisions.

## Worked example (Astro's numbers)
7 real candidate jobs (J1 and J2 are alternatives on the same well):
- Scenario A (C$15,000, 1.0 crew-day): best plan J1+J3+J5, net gain C$809,329. J4 has the second-highest single gain but does not fit alongside the others. Cheaper J5 does.
- Scenario B (C$25,000, 1.5 crew-days): best plan J1+J3+J4+J5, net gain C$1,069,472.
- J7 is the highest-risk well in the list, but Astro expects no extra oil from a repair: inspect, don't repair.

## Reproduce
```
python build_inputs.py      # writes out/repair_inputs*.csv and out/job_type_map.csv
python join_estimates.py    # joins well_estimates.csv, writes out/repair_inputs_rod.csv, out/well_estimates_joined.csv, out/plan_*.csv
python worked_example.py    # writes out/worked_example_*.csv
```
Put the parquet files in `data/` (or set `WOW_DATA`). Uses pandas and pyarrow; `tools/miniparquet.py` is a fallback reader for environments without pyarrow.

AI disclosure: built with help from Claude (Anthropic). The team checked the figures against the source reports and the data.
