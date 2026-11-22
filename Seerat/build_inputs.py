"""Build repair_inputs.csv (business handoff) for Well, Oh Well.
Inputs: well_jobs.parquet (field cost estimates, job durations), daily_production.parquet (which wells exist on the demo date).
Only information dated before the demo date is used."""
import pandas as pd, numpy as np
import os, sys
DATA = os.environ.get("WOW_DATA", "data")

def load(name, columns=None):
    path = os.path.join(DATA, name)
    try:
        return pd.read_parquet(path, columns=columns)
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
        from miniparquet import ParquetFile
        return ParquetFile(path).read(columns)

OUT = 'out'
os.makedirs(OUT, exist_ok=True)
DEMO = pd.Timestamp('2026-07-01')          # agreed prototype demo date
COST_LOOKBACK = pd.Timestamp('2024-07-01')  # use the 24 months of jobs before the demo date

j = load('well_jobs.parquet')
p = load('daily_production.parquet', ['uwi','field_operating_area','production_date','well_daily_status','flow_direction','oil_produced_m3','hours_on_prod'])

def norm(s):
    return ' '.join(str(s).split()) if isinstance(s, str) else s
j['job_type_n'] = j.job_type.map(norm)

MAP = {
    ('Rod Truck', 'Corod Rod Repair'): 'rod_repair',
    ('Rod Truck', 'Rod Repair'): 'rod_repair',
    ('Rod Truck', 'Stick Rod Repair'): 'rod_repair',
    ('Rod Truck', 'Polish Rod Repair'): 'rod_repair',
    ('Rod Truck', 'Rotor Change'): 'rod_repair',
    ('Rod Truck', 'Corod Rod Replacement - New String'): 'rod_string_replacement',
    ('Rod Truck', 'Stick Rod Replacement - New String'): 'rod_string_replacement',
    ('Workover', 'Rod Break - Corod'): 'rod_repair_rig',
    ('Workover', 'Rod Break - Stick'): 'rod_repair_rig',
    ('Workover', 'Rod Repair'): 'rod_repair_rig',
    ('Workover', 'Pump Repair/Replacement'): 'pump_repair',
    ('Workover', 'PCP Replacement'): 'pump_repair',
    ('Workover', 'Pump Repair'): 'pump_repair',
    ('Workover', 'PCP Upgrade'): 'pump_repair',
    ('Workover', 'BHP Replacement'): 'pump_repair',
    ('Workover', 'Pump Upgrade'): 'pump_repair',
    ('Workover', 'Tubing Repair'): 'tubing_repair',
    ('Workover', 'Packer Repair'): 'tubing_repair',
    ('Workover', 'Cleanout'): 'cleanout',
    ('Workover', 'Clean-out'): 'cleanout',
    ('Workover', 'Reactivation'): 'reactivation',
}
j['wow_job_type'] = [MAP.get((c, t)) for c, t in zip(j.job_category, j.job_type_n)]
JT = ['rod_repair', 'rod_string_replacement', 'rod_repair_rig', 'pump_repair', 'tubing_repair', 'cleanout', 'reactivation']

# mapping table for the team (same mapping must be used by Astro for comparable repairs)
mp = (j[j.wow_job_type.notna()].groupby(['wow_job_type', 'job_category', 'job_type_n']).size()
      .rename('jobs_all_years').reset_index().rename(columns={'job_type_n': 'source_job_type', 'job_category': 'source_job_category'}))
mp.to_csv(OUT + '/job_type_map.csv', index=False)

# comparable jobs: mapped, started in lookback window and before demo date
c = j[j.wow_job_type.notna() & (j.start_date >= COST_LOOKBACK) & (j.start_date < DEMO)].copy()
c['cost_ok'] = c.field_est_total > 0
c['dur_ok'] = (c.job_duration_days > 0) & (c.job_duration_days <= 30)

def stats(g, col, ok):
    v = g.loc[g[ok], col]
    return pd.Series({'n': len(v), 'med': v.median(), 'p25': v.quantile(.25), 'p75': v.quantile(.75)})

cost_w = c.groupby(['uwi', 'wow_job_type']).apply(lambda g: stats(g, 'field_est_total', 'cost_ok'), include_groups=False)
cost_a = c.groupby(['field_operating_area', 'wow_job_type']).apply(lambda g: stats(g, 'field_est_total', 'cost_ok'), include_groups=False)
cost_c = c.groupby('wow_job_type').apply(lambda g: stats(g, 'field_est_total', 'cost_ok'), include_groups=False)
dur_a = c.groupby(['field_operating_area', 'wow_job_type']).apply(lambda g: stats(g, 'job_duration_days', 'dur_ok'), include_groups=False)
dur_c = c.groupby('wow_job_type').apply(lambda g: stats(g, 'job_duration_days', 'dur_ok'), include_groups=False)

# candidate wells: production wells with a record in the 90 days before the demo date
win = p[(p.production_date >= DEMO - pd.Timedelta(days=90)) & (p.production_date < DEMO) & (p.flow_direction == 'production')]
last = win.sort_values('production_date').groupby('uwi').tail(1)[['uwi', 'field_operating_area', 'well_daily_status']]
last = last[last.well_daily_status.isin(['Producing', 'Suspended'])]

rows = []
for _, w in last.iterrows():
    types = ['reactivation'] if w.well_daily_status == 'Suspended' else [t for t in JT if t != 'reactivation']
    for t in types:
        r = {'well_id': w.uwi, 'job_type': t, 'field_operating_area': w.field_operating_area, 'status_on_demo_date': w.well_daily_status}
        key_w, key_a = (w.uwi, t), (w.field_operating_area, t)
        if key_w in cost_w.index and cost_w.loc[key_w, 'n'] >= 3:
            s = cost_w.loc[key_w]; src = f"field estimate: median of {int(s.n)} {t} jobs on this well (Jul 2024-Jun 2026)"; lvl = 'well'
        elif key_a in cost_a.index and cost_a.loc[key_a, 'n'] >= 10:
            s = cost_a.loc[key_a]; src = f"field estimate: median of {int(s.n)} {t} jobs in {w.field_operating_area} (Jul 2024-Jun 2026)"; lvl = 'area'
        elif t in cost_c.index and cost_c.loc[t, 'n'] >= 10:
            s = cost_c.loc[t]; src = f"field estimate: company median of {int(s.n)} {t} jobs (Jul 2024-Jun 2026)"; lvl = 'company'
        else:
            s = None; src = 'no credible estimate - see break-even cost'; lvl = 'none'
        if key_a in dur_a.index and dur_a.loc[key_a, 'n'] >= 10:
            d = dur_a.loc[key_a]; dsrc = f"measured: median elapsed duration of {int(d.n)} {t} jobs in {w.field_operating_area}; proxy for crew-days, excludes travel"
        elif t in dur_c.index:
            d = dur_c.loc[t]; dsrc = f"measured: company median elapsed duration of {int(d.n)} {t} jobs; proxy for crew-days, excludes travel"
        else:
            d = None; dsrc = 'unknown'
        r.update({
            'repair_cost_cad': round(s.med, 0) if s is not None else np.nan,
            'repair_cost_low_cad': round(s.p25, 0) if s is not None else np.nan,
            'repair_cost_high_cad': round(s.p75, 0) if s is not None else np.nan,
            'cost_level': lvl, 'cost_source': src,
            'crew_days': round(d.med, 2) if d is not None else np.nan,
            'crew_days_source': dsrc,
            'crew_type': 'rod truck' if t in ('rod_repair', 'rod_string_replacement') else 'service rig',
        })
        rows.append(r)
ri = pd.DataFrame(rows)
ri[['well_id', 'job_type', 'repair_cost_cad', 'crew_days', 'cost_source', 'crew_days_source']].to_csv(OUT + '/repair_inputs.csv', index=False)
ri.to_csv(OUT + '/repair_inputs_detail.csv', index=False)

print(ri.groupby(['job_type', 'cost_level']).size().unstack(fill_value=0))
print(ri.groupby('job_type')[['repair_cost_cad', 'crew_days']].median())
print('wells', ri.well_id.nunique(), 'rows', len(ri))
print(cost_c); print(dur_c)

# scale check for full-optimizer scenarios: weekly spend and crew-days on mapped job types, Q2 2026
q = j[j.wow_job_type.notna() & (j.start_date >= '2026-04-01') & (j.start_date < DEMO)]
q = q[(q.job_duration_days > 0) & (q.job_duration_days <= 30)]
wk = 13
print('Q2 2026 mapped jobs', len(q), 'spend/wk', q.field_est_total.sum() / wk, 'crew-days/wk', q.job_duration_days.sum() / wk,
      'jobs/wk', len(q) / wk)
print(q.groupby('wow_job_type').agg(n=('uwi', 'size'), spend=('field_est_total', 'sum'), days=('job_duration_days', 'sum')))