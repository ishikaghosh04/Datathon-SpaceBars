# Well, Oh Well

Well, Oh Well helps oilfield maintenance planners decide which wells to inspect, which repairs fit the crew's available time and budget, and what happened after past repairs. The Streamlit dashboard uses historical Strathcona data in Team mode and includes a synthetic walkthrough you can run immediately.

[Quick start](#quick-start) · [Dashboard walkthrough](#dashboard-walkthrough) · [Team data](#team-data) · [Canary and Axiom](#canary-and-axiom) · [Repository guide](#repository-guide)

## Quick start

Clone or download this repository. Open [`Well-Oh-Well/WellOhWell`](Well-Oh-Well/WellOhWell) in VS Code. The app folder contains `app.py` and `requirements.txt`. For the standalone archive, open the extracted folder containing those files. Use [Python 3.12](https://www.python.org/downloads/).

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

If Windows has Python 3.12 on the `python` command and `py` is unavailable, use `python -m venv .venv` for the first command.

### macOS or Linux

```sh
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

Open the **Local URL** printed in the terminal. On your first visit, choose **Sample · synthetic** in the sidebar. Sample mode includes **Inspect**, **Repair**, and **Did it work?**. To see **Failure Explorer** and the historical team inputs, follow [Team data](#team-data). Once dependencies are installed, rerun the last command to start the app again.

## Dashboard walkthrough

Use **Data mode**, **Replay date**, and **Section** in the sidebar to set the context for your walkthrough.

| Section | Where to click | How to read it |
| --- | --- | --- |
| **Inspect** | Click a map marker or ranking bar, or use **Well to inspect**. Expand **Full inspection ranking** for the table. | The map and bars show up to ten ranked wells. The selected well's panel shows the estimated 30-day failure risk, why the well was flagged, estimated oil lost, and its production history through the replay date. **Reveal later outcomes** shows recorded failures in the following 30 days when records are available. |
| **Failure Explorer** | In **Team data**, choose a **Failure date range**, **Operating area**, and **Reported cause**. Select a row under **Affected wells**, then click **Inspect selected well**. | The Sankey follows operating area → reported cause → failure type. Band width represents the number of recorded failures. The donut shows the failure-type share for the same filters. Dates are limited by the replay date. |
| **Repair** | In **Team data**, switch between **Normal Week**, **Tight Week**, and **Custom**. Sample mode uses custom limits. | The planner selects up to one job per well within the budget and crew-days. The plan shows selected jobs, estimated spend and net gain, and which jobs contribute the most. Oil margin is a scenario assumption. |
| **Did it work?** | Select a well and a recorded rod repair. Review the production comparison and follow-up records. | Compare observed daily oil before and after the repair and check the number of observed days in each window. Recorded failures 8–90 days after repair and repeat-failure estimates from comparable jobs appear alongside each other. |

### Try the Team data demo

1. Select **Team data** and **June 30, 2026**. In **Inspect**, choose one of the ranked wells and review its flag reason and oil history.
2. In **Failure Explorer**, choose **Cactus Lake** and **Corrosion**. Watch the Sankey, donut, and well table update. Select a well and open it in **Inspect**.
3. In **Repair**, compare **Normal Week** (C$105,000 and 9.7 crew-days) with **Tight Week** (C$73,500 and 6.8 crew-days). Compare which jobs fit and the estimated gain under each scenario.
4. In **Did it work?**, open an available recorded repair and look for changes in the observed before-and-after oil production.

If the street map is blank, open **Map settings** and turn off **Show street basemap**. The offline plot uses local well coordinates and supports well selection.

## Team data

The raw Strathcona Parquet files are distributed separately. Use authorized copies and set **Datathon folder** in the sidebar to the directory containing your inputs. You can also set `WOW_DATA` before starting the app to prefill the folder.

| Input | Location inside the data folder | Used for |
| --- | --- | --- |
| `well_estimates.csv` | Data folder root or `Sam/`. The repository includes [the team's example snapshot](Sam/well_estimates.csv). | Available replay dates, risk ranking, and comparable repair estimates. |
| `daily_production.parquet` | Data folder root | Production history and well locations. |
| `production_failures.parquet` | Data folder root | Failure Explorer and recorded follow-up failures. |
| `well_jobs.parquet` | Data folder root | Recorded jobs and repair dates. |
| `repair_inputs_rod.csv` or `repair_inputs.csv` | Data folder root or `Seerat/` | Repair cost in CAD and crew-days for the planner. |

The supplied Team snapshot is scored as of **June 30, 2026**. The replay date menu comes from the `as_of_date` values in the estimates file. Inspect and historical replay can load without a repair cost export. To enable the repair planner, provide `well_id`, `job_type`, `repair_cost`, and `crew_days`. Include `as_of_date` for date-specific repair estimates. See [Repair economics](Seerat/repair_economics.md) for how the team estimated costs and used historical job durations as a proxy for crew-days.

## Canary and Axiom

Start with **Local Parquet** in the Streamlit sidebar for the standard walkthrough. There are two optional Canary integrations.

### Open a well in Axiom

For mapped wells, **Inspect → Open production history in Axiom** launches an Axiom chart of the imported measurements. To prepare your own connections, run the following from the app folder in the Python environment you used to start Streamlit. Replace the example paths and tag prefix with yours.

```powershell
$dataDir = 'C:\path\to\Datathon'
$staging = Join-Path $env:TEMP 'WellOhWell-Axiom'
.\.venv\Scripts\python.exe export_axiom_history.py $dataDir $staging --tag-prefix 'ServerName.DatasetName'
```

1. Import the generated `well_history_import.csv` with your Canary CSV Collector. It contains timestamped oil, downtime, and rod-torque readings for three Cactus Lake wells by default. Use repeated `--well` flags or `--end YYYY-MM-DD` to change the export.
2. In Axiom, browse **Add Trends** and confirm the imported well tags match the prefix used in the export. Copy `axiom_wells.json` from staging into the data folder selected in Streamlit.
3. If Axiom is hosted elsewhere, set `WOW_AXIOM_URL` to your server's base URL before starting Streamlit. The default is `https://localhost`. A mapped well opens a paused, 105-day history ending on the selected replay date, subject to the dates available in Canary.

The team's local Axiom demo includes **Well History** and a separate **Production Overview** application. Production Overview has a downtime donut gauge, an oil circular gauge, a torque-versus-oil scatter plot, and a weekly downtime bar chart, with **Full history**, **June**, and **July** views. These are saved applications on the team's Canary instance. The repository includes the export script and demo oil CSV for setting up your own instance.

### Read oil history inside Streamlit

1. Copy [`canary_tags.example.json`](Well-Oh-Well/WellOhWell/canary_tags.example.json) into your data folder as `canary_tags.json`. Replace the example entry with your well ID and complete Canary Views tag path.
2. In the same terminal used to launch Streamlit, set `CANARY_READ_URL` to the HTTPS base URL for your Read API and `CANARY_API_TOKEN` to a read-only token. Use the base URL without `/api/v2`. For a local instance, use the Views API port configured by your administrator. Set `CANARY_CA_FILE` if your deployment uses a custom trusted CA bundle. Keep tokens out of the repository.
3. In **Team data**, choose **Canary Read API** under **Production data**. Select a mapped well, or enable **Show the imported Canary demo well** when using the example tag. Check the production chart caption to confirm whether it used Canary or fell back to local Parquet.

## Repository guide

| Path | What you'll find |
| --- | --- |
| [`Well-Oh-Well/WellOhWell/`](Well-Oh-Well/WellOhWell) | Streamlit app, data loading and repair planning, Failure Explorer, Axiom export script, and bundled sample inputs. |
| [`Sam/`](Sam) | Risk analysis, model outputs, and scored well estimates. Start with the [analysis notes](Sam/README_analysis.md). |
| [`Seerat/`](Seerat) | Repair economics, scripts for preparing model inputs, and the comparison workbook. Start with the [economics notes](Seerat/repair_economics.md). |
| [`Well Oh Well.twbx`](Well%20Oh%20Well.twbx) | Tableau workbook. |
| [`canary_demo_oil.csv`](canary_demo_oil.csv) | Timestamped daily oil readings for the Canary demo well. |

### Check the sample repair calculations

From the app folder, run `.\.venv\Scripts\python.exe verify.py` on Windows or `./.venv/bin/python verify.py` on macOS or Linux. The script checks the sample repair scenarios, including selected jobs and net gain, against the bundled worked example.
