# Well, Oh Well

A local Streamlit dashboard. **Inspect** ranks wells using point-in-time scores and shows the flag reasons and oil history. **Repair** chooses a portfolio subject to budget, crew-days, and one job per well. **Did it work?** shows oil production around a recorded repair and separates recorded events from comparable-job estimates.

## Run in VS Code on Windows

Extract the ZIP. Open the extracted folder in VS Code, then use **Terminal → New Terminal** and run:

~~~powershell
uv run --python 3.12 --with-requirements requirements.txt streamlit run app.py --server.address 127.0.0.1
~~~

Use the local address printed in the terminal. Start in **Sample · synthetic**, then switch to **Team data**. Set **Datathon folder** in the sidebar to the folder that contains Sam, Seerat, and the three Parquet files. The app defaults to the existing OneDrive Desktop Datathon folder when it detects Sam's CSV.

## Team inputs

- Estimates: Datathon/well_estimates.csv or Datathon/Sam/well_estimates.csv. Use the existing schema, including as_of_date, well_id, job_type, oil_lost_per_day, failure_risk, expected_extra_oil, repeat_failure_rate, comparable_job_count and flag_reason. The supplied file contains one scored date, 2026-06-30. For additional date choices, append scored snapshots with their original dates. The app requires an exact date match and never backfills earlier dates from later scores.
- Repairs: Datathon/repair_inputs.csv or the rod-keyed repair_inputs_rod.csv in Datathon or Seerat. Expected columns are well_id, job_type, repair_cost (CAD), and crew_days. If the export uses different headers, rename those two numeric fields before loading. Include as_of_date for date-specific estimates. The business handoff says the rod-keyed export matches the job names in the scores. The app normalizes punctuation and case in the well ID, validates unique keys, and excludes jobs missing cost, crew duration, or expected oil.
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
3. Open Repair, change budget and crew-days, and check that spend and crew use stay within limits and no well repeats. If the full rod costs are missing, use Sample mode and show the separately labeled business checks. Scenario A selects J1 + J3 + J5. Scenario B selects J1 + J3 + J4 + J5.
4. Open Did it work?, select a well and a recorded repair. Check the repair date marker, follow-up records, and comparable-job count.
5. Use this command to rerun the two independent business checks:

~~~powershell
uv run --python 3.12 python verify.py
~~~

The workbook rounds some intermediate display values. The verification compares the recomputed gains against the workbook within one cent and requires exact candidate matches.

## Visual inspection workflow

- In **Inspect**, click a point in the offline longitude/latitude plot or a ranking bar to open that well's risk, flag reason, area, and oil timeline. The well dropdown includes all wells in the current filter. The plot and bars show up to 10 wells. Locations in Team data use the latest valid surface coordinates available through the replay date. Sample mode uses synthetic locations.
- The offline plot is the default and does not request map tiles. To use the optional CARTO street map instead, enable **Show street basemap** in **Map settings**.
- In **Repair**, the contribution bars show up to ten selected jobs by estimated net gain.
- In **Did it work?**, the paired bars compare observed daily production before and after the repair. Check the observed day counts when comparing partial windows.
