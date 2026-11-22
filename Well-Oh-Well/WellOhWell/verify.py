import argparse
from pathlib import Path

from backend import ESTIMATES, COSTS, join_inputs, load_csv, optimize, verify_scenarios

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--data", type=Path, help="Optional Datathon folder")
args = parser.parse_args()
sample = root / "sample"
for result in verify_scenarios(sample):
    print(result)

estimates = load_csv(sample / "well_estimates.csv", ESTIMATES)
costs = load_csv(sample / "repair_inputs.csv", COSTS)
first = estimates[0]["as_of_date"]
joined = join_inputs([r for r in estimates if r["as_of_date"] == first], costs)
assert not any(r["missing"] for r in joined)
assert not optimize(joined, 0, 1, 400)
assert all(r["repair_cost"] is None for r in join_inputs([estimates[0]], []))
assert len({r["well_id"] for r in optimize(joined, 15000, 1, 400)}) == len(optimize(joined, 15000, 1, 400))

if args.data:
    estimates = load_csv(args.data / "Sam" / "well_estimates.csv", ESTIMATES)
    for snapshot in sorted({row["as_of_date"] for row in estimates}):
        joined = join_inputs([r for r in estimates if r["as_of_date"] == snapshot], [])
        print(snapshot, len(joined), "candidate rows;", len({r["well_id"] for r in joined}), "wells")
