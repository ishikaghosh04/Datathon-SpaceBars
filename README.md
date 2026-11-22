# Well, Oh Well (WOW)

A local Streamlit dashboard. **Inspect** ranks wells using point-in-time scores and shows the flag reasons and oil history. **Repair** chooses a portfolio subject to budget, crew-days, and one job per well. **Did it work?** shows oil production around a recorded repair and separates recorded events from comparable-job estimates.

## Run locally with Python 3.12

Extract the GitHub ZIP. In VS Code, open `Well-Oh-Well/WellOhWell` inside the extracted repository. For the standalone app ZIP, open the extracted `WellOhWell` folder. The folder you open should contain both `app.py` and `requirements.txt`. Install [Python 3.12](https://www.python.org/downloads/) if needed, then open **Terminal → New Terminal**.

### Windows PowerShell

~~~powershell
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
~~~

If `py` is unavailable, try `python --version`. If it reports Python 3.12, use `python -m venv .venv` and then run the same two `.venv` commands. If neither command finds Python 3.12, install it and reopen VS Code. These commands invoke the environment's Python directly, so PowerShell activation is unnecessary.

### macOS or Linux

~~~sh
python3.12 --version
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
~~~

Open the **Local URL** printed in the terminal. Start in **Sample · synthetic**, which works with the bundled sample files. For **Team data**, set **Datathon folder** in the sidebar to the folder with `Sam`, `Seerat`, and the three Parquet files. The GitHub ZIP omits the raw Parquet files. Use your authorized local copies for Team data. On subsequent runs, use just the Streamlit command for your operating system.

## Team inputs

- Estimates: Datathon/well_estimates.csv or Datathon/Sam/well_estimates.csv. Use the existing schema, including as_of_date, well_id, job_type, oil_lost_per_day, failure_risk, expected_extra_oil, repeat_failure_rate, comparable_job_count and flag_reason. The supplied file contains one scored date, 2026-06-30. For additional date choices, append scored snapshots with their original dates. The app requires an exact date match and never backfills earlier dates from later scores.
- Repairs: The app includes `data/repair_inputs_rod.csv` for the June 30 team snapshot. It uses Seerat's median field cost estimates and median elapsed job durations as a proxy for crew-days. An export in the selected Datathon directory or its Seerat subfolder takes precedence. Expected columns are `well_id`, `job_type`, `repair_cost` (CAD), and `crew_days`. Rename `repair_cost_cad` to `repair_cost` if you use a fresh export. Include `as_of_date` for date-specific estimates. The app normalizes well IDs, validates unique keys, and excludes jobs missing cost, crew duration, or expected oil.
- History: daily_production.parquet, production_failures.parquet, and well_jobs.parquet in Datathon. Team failure outcomes come from the explicit failure log. They may differ from model labels, which also included qualifying repair-driven episodes. The imported single-well tag is separate from the ranked wells because its well is absent from the available score snapshot.
- Oil margin is a user-selected scenario assumption. The default is the base amount from Seerat's workbook. Do not describe it as a June 30 value known at that date. Compare plans with the team if presenting a strictly point-in-time economics scenario.

## Canary Read API

1. Use an event-supplied Read API host and read-only token. For the local environment already used to import the CSV, the Views web API is configured on port 55236. The base URL must be HTTPS and should omit /api/v2. Obtain a trusted CA PEM file if the local certificate is not already trusted.
2. Copy canary_tags.example.json into the Datathon data folder as canary_tags.json. Verify the complete Views tag path in the target environment. The example maps the real well behind the locally imported DemoWell.Oil_m3 tag. A different server may use a different view name.
3. In the same PowerShell session in which you start Streamlit, set the environment variables below. Enter the token at the masked prompt. Keep the token out of chat, source control, and the ZIP.

~~~powershell
$env:CANARY_READ_URL = 'https://localhost:55236'
$env:CANARY_API_TOKEN = Read-Host 'Canary Read API token' -MaskInput
# Set this only if your installation needs a CA PEM file.
# $env:CANARY_CA_FILE = 'C:\path\to\trusted-ca.pem'
~~~

In Team data, choose **Canary Read API** as the production source. On Inspect, enable **Show the imported Canary demo well** unless you have mapped a ranked well. Confirm that the chart caption says **Canary Read API**. If the request fails, the app labels the local Parquet fallback explicitly. Dates are interpreted in America/Edmonton by default. CANARY_TIME_ZONE can override it.

The production-drop metric compares a trailing median (days -104 through -14) with the last seven calendar days. It requires at least 14 baseline readings and all seven recent days. It does not apply the model's operating-hours filter. The locally imported series is too short to meet that baseline at the demo date. The API call reads daily volume tags, skips bad or uncertain quality, and follows pagination.

## Live demo checklist

1. In Sample mode, switch between the two replay dates. Select a flagged well, confirm the chart stops at the selected date, then reveal subsequent events.
2. In Team data on June 30, confirm the ranked well table and flag reasons load. Switch the production source to Canary and confirm the source caption on the imported-well chart. Enable later production to show the full imported history.
3. In Team data, open Repair and switch between **Normal Week** (C$105,000 and 9.7 crew-days) and **Tight Week** (C$73,500 and 6.8 crew-days). At the default margin, expect 33 and 24 jobs, respectively. Choose **Custom** to enter your own limits. Check that spend and crew use stay within limits and no well repeats.
4. Open Did it work?, select a well and a recorded repair. Check the repair date marker, follow-up records, and comparable-job count.
5. Rerun the two independent business checks with the same Python environment:

~~~powershell
.\.venv\Scripts\python.exe verify.py
~~~

On macOS or Linux, run `./.venv/bin/python verify.py`.

The workbook rounds some intermediate display values. The verification compares the recomputed gains against the workbook within one cent and requires exact candidate matches.

## Visual inspection workflow

- In **Inspect**, click a map pin or a ranking bar to open that well's risk, flag reason, area, and oil timeline. The well dropdown includes all wells in the current filter. The map and bars show up to 10 wells. Pin locations in Team data use the latest valid surface coordinates available through the replay date. Sample mode uses synthetic locations.
- If the street basemap cannot load, turn it off in **Map settings**. The well layer is local. The optional basemap retrieves street tiles from CARTO.
- In **Repair**, the contribution bars show up to ten selected jobs by estimated net gain.
- In **Did it work?**, the paired bars compare observed daily production before and after the repair. Check the observed day counts when comparing partial windows.
