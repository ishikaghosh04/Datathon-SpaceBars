"""Join Astro's well_estimates.csv with repair costs, compute net gain, and solve the budget/crew problem exactly.
- Astro's job types are the source rod job names ('Corod Rod Repair', 'Stick Rod Repair'), so costs are rebuilt for those.
- Uses only jobs that started before the demo date."""
import os, sys, numpy as np, pandas as pd
from scipy.optimize import milp, LinearConstraint, Bounds
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get('WOW_DATA', 'data')

def load(name, columns=None):
    path = os.path.join(DATA, name)
    try:
        return pd.read_parquet(path, columns=columns)
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools'))
        from miniparquet import ParquetFile
        return ParquetFile(path).read(columns)

DEMO = pd.Timestamp('2026-07-01'); LOOK = pd.Timestamp('2024-07-01'); M3 = 6.2898
MARGIN = {'low': 55.61 * M3, 'base': 69.76 * M3, 'high': 76.96 * M3}  # C$/m3, see margin_assumptions.csv

w = pd.read_csv(os.environ.get('WOW_EST', 'well_estimates.csv'))
j = load('well_jobs.parquet'); j['jt'] = j.job_type.map(lambda s: ' '.join(str(s).split()))
c = j[(j.job_category == 'Rod Truck') & j.jt.isin(w.job_type.unique()) & (j.start_date >= LOOK) & (j.start_date < DEMO)]
area_of = load('daily_production.parquet', ['uwi', 'field_operating_area', 'production_date'])
area_of = area_of[area_of.production_date < DEMO].sort_values('production_date').groupby('uwi').field_operating_area.last()

def pick(g):
    g = g[g.field_est_total > 0]
    return g.field_est_total.median(), len(g), g.field_est_total.quantile(.25), g.field_est_total.quantile(.75)
d = c[(c.job_duration_days > 0) & (c.job_duration_days <= 30)]
rows = []
for _, r in w.iterrows():
    a = area_of.get(r.well_id)
    for lvl, sub, need in [('well', c[(c.uwi == r.well_id) & (c.jt == r.job_type)], 3),
                           ('area', c[(c.field_operating_area == a) & (c.jt == r.job_type)], 10),
                           ('company', c[c.jt == r.job_type], 10)]:
        med, n, lo, hi = pick(sub)
        if n >= need: break
    da = d[(d.field_operating_area == a) & (d.jt == r.job_type)]
    dsrc = f'measured: median elapsed duration of {len(da)} {r.job_type} jobs in {a}; proxy for crew-days, excludes travel'
    if len(da) < 10:
        da = d[d.jt == r.job_type]; dsrc = f'measured: company median elapsed duration of {len(da)} {r.job_type} jobs; proxy for crew-days, excludes travel'
    rows.append({'well_id': r.well_id, 'job_type': r.job_type, 'repair_cost_cad': round(med),
                 'crew_days': round(da.job_duration_days.median(), 2),
                 'cost_source': f'field estimate: median of {n} {r.job_type} jobs ({lvl}{"" if lvl == "company" else ": " + (r.well_id if lvl == "well" else str(a))}), Jul 2024-Jun 2026',
                 'crew_days_source': dsrc, 'cost_low_cad': round(lo), 'cost_high_cad': round(hi), 'field_operating_area': a})
ri = pd.DataFrame(rows)
os.makedirs('out', exist_ok=True)
ri[['well_id', 'job_type', 'repair_cost_cad', 'crew_days', 'cost_source', 'crew_days_source']].to_csv('out/repair_inputs_rod.csv', index=False)

m = w.merge(ri, on=['well_id', 'job_type'], how='left', validate='1:1')
assert m.repair_cost_cad.notna().all()
for k, v in MARGIN.items():
    m[f'net_gain_{k}_cad'] = m.expected_extra_oil * v - m.repair_cost_cad
m['oil_value_cad'] = m.expected_extra_oil * MARGIN['base']          # = break-even repair cost
m['net_gain_per_dollar'] = m.net_gain_base_cad / m.repair_cost_cad
m['net_gain_per_crew_day_cad'] = m.net_gain_base_cad / m.crew_days
m['confidence'] = np.where((m.comparable_job_count < 100) | (m.repeat_failure_rate > 0.6), 'low', 'normal')
m['inspect_flag'] = m.flag_reason.notna()

def solve(budget, crew, margin='base'):
    g = m[f'net_gain_{margin}_cad'].to_numpy(); n = len(m)
    wells = pd.factorize(m.well_id)[0]
    A = [m.repair_cost_cad.to_numpy(), m.crew_days.to_numpy()]
    W = np.zeros((wells.max() + 1, n)); W[wells, np.arange(n)] = 1
    cons = [LinearConstraint(np.vstack(A), -np.inf, [budget, crew]), LinearConstraint(W, 0, 1)]
    res = milp(-g, constraints=cons, integrality=np.ones(n), bounds=Bounds(0, 1))
    x = res.x > 0.5
    return m[x], -res.fun

SCEN = {'rod_base_week': (105000, 9.7), 'rod_tight_week': (73500, 6.8)}
out = []
for name, (b, cr) in SCEN.items():
    sel, val = solve(b, cr)
    most_oil = m[m.net_gain_base_cad > 0].sort_values('expected_extra_oil', ascending=False)
    out.append((name, b, cr, len(sel), sel.repair_cost_cad.sum(), sel.crew_days.sum(), sel.expected_extra_oil.sum(), val))
    sel.assign(scenario=name).to_csv(f'out/plan_{name}.csv', index=False)
m.to_csv('out/well_estimates_joined.csv', index=False)
print(pd.DataFrame(out, columns=['scenario', 'budget', 'crew_days', 'jobs', 'cost', 'crew_used', 'extra_oil_m3', 'net_gain_base']).to_string())
print('rows', len(m), 'positive gain', (m.net_gain_base_cad > 0).sum(), 'inspect flags', m.inspect_flag.sum(),
      'flagged but negative gain', (m.inspect_flag & (m.net_gain_base_cad <= 0)).sum())
print(ri.groupby('job_type').repair_cost_cad.median(), ri.groupby('job_type').crew_days.median())