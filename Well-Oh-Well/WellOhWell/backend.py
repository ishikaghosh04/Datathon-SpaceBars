import csv
import itertools
import json
import math
import os
import re
import ssl
import urllib.request
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

KEYS = ("well_id", "job_type")
ESTIMATES = KEYS + ("as_of_date", "oil_lost_per_day", "failure_risk",
                    "expected_extra_oil", "repeat_failure_rate",
                    "comparable_job_count", "flag_reason")
COSTS = KEYS + ("repair_cost", "crew_days")
DEMO_DATE = date(2026, 6, 30)
BASE_MARGIN = 438.776448
SCENARIOS = {
    "A": (15000, 1.0, {"J1", "J3", "J5"}, 809329.3883),
    "B": (25000, 1.5, {"J1", "J3", "J4", "J5"}, 1069471.895),
}
REPAIR_TYPES = {"Corod Rod Repair", "Stick Rod Repair", "Rod Repair"}


def well_key(value):
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def number(value, minimum=0, maximum=math.inf):
    try:
        parsed = float(value)
    except (ValueError, TypeError):
        return None
    return parsed if math.isfinite(parsed) and minimum <= parsed <= maximum else None


def load_csv(path, required):
    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = set(required) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{Path(path).name} is missing columns: {', '.join(sorted(missing))}")
        return list(reader)


def join_inputs(estimates, costs):
    def key(row):
        normalized = well_key(row["well_id"]), row["job_type"].strip()
        if not all(normalized):
            raise ValueError("A well_id or job_type is blank.")
        return normalized

    lookup = {}
    for row in costs:
        pair = key(row)
        if pair in lookup:
            raise ValueError(f"Duplicate repair input for {pair}. Filter costs to one snapshot.")
        lookup[pair] = row
    seen = set()
    joined = []
    for estimate in estimates:
        pair = key(estimate)
        if pair in seen:
            raise ValueError(f"Duplicate estimate for {pair} on this replay date.")
        seen.add(pair)
        cost = lookup.get(pair, {})
        row = dict(estimate, well_id=pair[0], job_type=pair[1])
        cost_value = number(cost.get("repair_cost"))
        crew_value = number(cost.get("crew_days"))
        row.update(
            repair_cost=cost_value if cost_value else None, crew_days=crew_value,
            failure_risk=number(row["failure_risk"], maximum=1),
            expected_extra_oil=number(row["expected_extra_oil"]),
            oil_lost_per_day=number(row["oil_lost_per_day"]),
            repeat_failure_rate=number(row["repeat_failure_rate"], maximum=1),
            comparable_job_count=number(row["comparable_job_count"]),
        )
        row["missing"] = ", ".join(
            name for name in ("repair_cost", "crew_days", "expected_extra_oil",
                              "failure_risk", "oil_lost_per_day", "repeat_failure_rate",
                              "comparable_job_count") if row[name] is None
        )
        joined.append(row)
    return joined


def optimize(rows, budget, crew_limit, margin):
    candidates = []
    for row in rows:
        cost, crew, oil = (row[k] for k in ("repair_cost", "crew_days", "expected_extra_oil"))
        if None in (cost, crew, oil):
            continue
        gain = oil * margin - cost
        if gain > 0 and cost <= budget and crew <= crew_limit:
            candidates.append(dict(row, net_gain=gain))

    groups = defaultdict(list)
    for index, row in enumerate(candidates):
        groups[row["well_id"]].append(index)

    if len(candidates) <= 18:
        best, best_gain = (), 0
        for choices in itertools.product(*[(-1, *group) for group in groups.values()]):
            plan = [candidates[i] for i in choices if i >= 0]
            gain = sum(row["net_gain"] for row in plan)
            if (gain > best_gain
                    and sum(row["repair_cost"] for row in plan) <= budget + 1e-8
                    and sum(row["crew_days"] for row in plan) <= crew_limit + 1e-8):
                best, best_gain = plan, gain
        return sorted(best, key=lambda row: -row["net_gain"])

    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    n = len(candidates)
    row_indices = [0] * n + [1] * n
    indices = list(range(n)) * 2
    values = [r["repair_cost"] for r in candidates] + [r["crew_days"] for r in candidates]
    for i, members in enumerate(groups.values(), 2):
        row_indices.extend([i] * len(members))
        indices.extend(members)
        values.extend([1.0] * len(members))
    upper = [budget, crew_limit] + [1.0] * len(groups)
    matrix = coo_matrix((values, (row_indices, indices)), shape=(len(upper), n)).tocsc()
    result = milp(
        -np.array([row["net_gain"] for row in candidates]),
        integrality=np.ones(n),
        bounds=Bounds(0, 1),
        constraints=LinearConstraint(matrix, -np.inf, upper),
        options={"mip_rel_gap": 0.0, "time_limit": 30.0},
    )
    if not result.success:
        raise ValueError("The solver did not prove an optimum within 30 seconds.")
    plan = [row for row, selected in zip(candidates, result.x) if selected > 0.5]
    if (sum(row["repair_cost"] for row in plan) > budget + 1e-6
            or sum(row["crew_days"] for row in plan) > crew_limit + 1e-6
            or len({row["well_id"] for row in plan}) != len(plan)):
        raise ValueError("The solver returned a plan outside the selected limits.")
    return sorted(plan, key=lambda row: -row["net_gain"])


def verify_scenarios(directory):
    raw = load_csv(Path(directory) / "worked_example.csv",
                   ("candidate", "well_id", "repair_cost", "crew_days", "expected_extra_oil"))
    candidates = [
        dict(row, **{k: float(row[k]) for k in ("repair_cost", "crew_days", "expected_extra_oil")})
        for row in raw
    ]
    results = []
    for scenario, (budget, crew, expected_jobs, expected_gain) in SCENARIOS.items():
        plan = optimize(candidates, budget, crew, BASE_MARGIN)
        jobs = {row["candidate"] for row in plan}
        gain = sum(row["net_gain"] for row in plan)
        if jobs != expected_jobs or abs(gain - expected_gain) > 0.01:
            raise ValueError(f"Scenario {scenario} did not match the business workbook.")
        results.append({"Scenario": scenario, "Selected jobs": " + ".join(sorted(jobs)),
                        "Spend (C$)": sum(row["repair_cost"] for row in plan),
                        "Crew-days": round(sum(row["crew_days"] for row in plan), 2),
                        "Net gain (C$)": round(gain, 2)})
    return results


def from_parquet(directory, filename, well, date_column, value_column, start, end):
    import duckdb
    path = Path(directory) / filename
    if not path.is_file():
        raise ValueError(f"{filename} is missing from the Datathon folder.")
    with duckdb.connect() as connection:
        return connection.execute(f"""
            SELECT CAST({date_column} AS DATE), {value_column}
            FROM read_parquet(?)
            WHERE regexp_replace(upper(CAST(uwi AS VARCHAR)), '[^A-Z0-9]', '', 'g') = ?
              AND CAST({date_column} AS DATE) BETWEEN ? AND ?
              AND {value_column} IS NOT NULL
            ORDER BY 1
        """, [str(path), well_key(well), start, end]).fetchall()


def production_drop(points, cutoff):
    baseline = [v for day, v in points if cutoff - timedelta(days=104) <= day <= cutoff - timedelta(days=14)]
    recent = [v for day, v in points if cutoff - timedelta(days=6) <= day <= cutoff]
    if len(baseline) < 14 or len(recent) != 7:
        return None
    return max(0, median(baseline) - mean(recent))


def canary_read(well, start, end, tags):
    base = os.getenv("CANARY_READ_URL", "").rstrip("/")
    token = os.getenv("CANARY_API_TOKEN", "")
    tag = tags.get(well_key(well))
    if not base or not token or not tag:
        raise ValueError("Configure the Read API URL, token, and a tag mapping for this well.")
    if urlsplit(base).scheme != "https":
        raise ValueError("The Canary Read API URL must use HTTPS.")
    zone_name = os.getenv("CANARY_TIME_ZONE", "America/Edmonton")
    try:
        zone = timezone.utc if zone_name == "UTC" else ZoneInfo(zone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Install tzdata or set a valid CANARY_TIME_ZONE.") from exc
    context = ssl.create_default_context(cafile=os.getenv("CANARY_CA_FILE") or None)
    payload = {
        "apiToken": token, "tags": [tag], "includeQuality": True, "maxSize": 1000,
        "startTime": datetime.combine(start, time.min, zone).isoformat(),
        "endTime": datetime.combine(end + timedelta(days=1), time.min, zone).isoformat(),
    }
    points = {}
    for _ in range(20):
        request = urllib.request.Request(
            base + "/api/v2/getTagData", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=10, context=context) as response:
            result = json.load(response)
        if result.get("statusCode") != "Good" or result.get("errors"):
            raise ValueError("Canary rejected the request. Check token permissions and the tag path.")
        for record in result.get("data", {}).get(tag, []):
            stamp = datetime.fromisoformat(record["t"].replace("Z", "+00:00"))
            day = stamp.astimezone(zone).date()
            value = number(record.get("v"))
            if value is not None and (int(record.get("q", 0)) & 0xC0) == 0xC0 and start <= day <= end:
                if day in points and points[day] != value:
                    raise ValueError("The mapped tag has multiple readings per day. Map a daily oil tag.")
                points[day] = value
        continuation = result.get("continuation")
        if not continuation or not any(continuation):
            return sorted(points.items())
        payload["continuation"] = continuation
    raise ValueError("The Canary request exceeded 20 pages. Narrow the date range.")




def well_locations(path, cutoff):
    """Return the most recent valid surface coordinates available by the replay date."""
    import duckdb

    with duckdb.connect() as connection:
        rows = connection.execute("""
            SELECT well_id, latitude, longitude, well_name, field_operating_area
            FROM (
                SELECT regexp_replace(upper(uwi), '[^A-Z0-9]', '', 'g') AS well_id,
                       surface_latitude AS latitude, surface_longitude AS longitude,
                       well_name, field_operating_area, production_date
                FROM read_parquet(?)
                WHERE production_date <= ? AND uwi IS NOT NULL
                  AND surface_latitude BETWEEN -90 AND 90
                  AND surface_longitude BETWEEN -180 AND 180
                  AND surface_latitude <> 0 AND surface_longitude <> 0
            )
            QUALIFY row_number() OVER (
                PARTITION BY well_id
                ORDER BY production_date DESC, latitude, longitude, well_name, field_operating_area
            ) = 1
        """, [str(path), cutoff]).fetchall()
    return {
         well: {
            "latitude": float(lat),
            "longitude": float(lon),
            "name": name or well,
            "area": area or "Area unavailable",
        }
        for well, lat, lon, name, area in rows
    }
