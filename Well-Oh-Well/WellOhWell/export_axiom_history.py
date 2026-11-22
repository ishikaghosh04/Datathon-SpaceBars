import argparse
import csv
import json
import math
from datetime import date, timedelta
from pathlib import Path

import duckdb

from backend import well_key

DEFAULT_WELLS = ("106020703627W300", "103010603627W300", "104040503627W300")
TAG_NAMES = ("Oil_m3", "Downtime_h", "RodTorque_ftlb")


def export_history(data_folder, output_folder, wells, end, tag_prefix):
    start = end - timedelta(days=104)
    parquet = data_folder / "daily_production.parquet"
    if not parquet.is_file():
        raise ValueError(f"Could not find {parquet}")
    keys = list(dict.fromkeys(well_key(well) for well in wells))
    with duckdb.connect() as conn:
        rows = conn.execute("""
            SELECT uwi_key, day, oil_produced_m3, hours_down, pcp_pump_rod_torque_ftlb
            FROM (
                SELECT regexp_replace(upper(CAST(uwi AS VARCHAR)), '[^A-Z0-9]', '', 'g') AS uwi_key,
                       CAST(production_date AS DATE) AS day, oil_produced_m3, hours_down,
                       pcp_pump_rod_torque_ftlb
                FROM read_parquet(?)
                WHERE CAST(production_date AS DATE) BETWEEN ? AND ?
            )
            WHERE uwi_key IN (SELECT UNNEST(?))
            ORDER BY day, uwi_key
        """, [str(parquet), start, end, keys]).fetchall()

    samples = {}
    tags = {well: set() for well in keys}
    for well, day, *values in rows:
        for name, value in zip(TAG_NAMES, values):
            if value is None or not math.isfinite(value):
                continue
            tag = f"Wells.{well}.{name}"
            previous = samples.setdefault((day, tag), value)
            if previous != value:
                raise ValueError(f"Conflicting daily measurements for {tag} on {day}.")
            tags[well].add(name)
    missing = [well for well, names in tags.items() if not names]
    if missing:
        raise ValueError(f"No readings in this date range for {', '.join(missing)}.")

    output_folder.mkdir(parents=True, exist_ok=True)
    csv_path = output_folder / "well_history_import.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["tag", "timestamp", "value"])
        writer.writerows((tag, f"{day} 12:00:00", value)
                         for (day, tag), value in samples.items())
    mapping = {well: [f"{tag_prefix}.Wells.{well}.{name}" for name in TAG_NAMES if name in names]
               for well, names in tags.items()}
    (output_folder / "axiom_wells.json").write_text(
        json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(samples):,} readings for {len(mapping)} wells from {start} to {end}.")
    return csv_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare a historical CSV and Streamlit Axiom links.")
    parser.add_argument("data_folder", type=Path)
    parser.add_argument("output_folder", type=Path)
    parser.add_argument("--well", action="append", help="Repeat to override the three Cactus Lake wells.")
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 6, 30))
    parser.add_argument("--tag-prefix", default="sacabambaspis.WellOhWell")
    args = parser.parse_args()
    try:
        export_history(args.data_folder, args.output_folder, args.well or DEFAULT_WELLS,
                       args.end, args.tag_prefix)
    except (OSError, ValueError, duckdb.Error) as exc:
        parser.exit(1, f"{exc}\n")
