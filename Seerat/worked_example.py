"""Worked example for checking the optimizer by hand: 7 real candidate jobs from Astro's well_estimates.csv
(joined with costs by join_estimates.py), two small budget/crew scenarios, and every feasible combination."""
import itertools, pandas as pd

M3_TO_BBL = 6.2898
MARGIN = {'low': 55.61 * M3_TO_BBL, 'base': 69.76 * M3_TO_BBL, 'high': 76.96 * M3_TO_BBL}
m = pd.read_csv('out/well_estimates_joined.csv')
PICK = [('J1', '101110403520W300', 'Stick Rod Repair'), ('J2', '101110403520W300', 'Corod Rod Repair'),
        ('J3', '106150503728W300', 'Corod Rod Repair'), ('J4', '142133003327W300', 'Corod Rod Repair'),
        ('J5', '108063404125W300', 'Stick Rod Repair'), ('J6', '100020205917W400', 'Corod Rod Repair'),
        ('J7', '101042204225W300', 'Stick Rod Repair')]
c = pd.concat([m[(m.well_id == w) & (m.job_type == t)].assign(job_id=i) for i, w, t in PICK])
c['oil_value_cad'] = (c.expected_extra_oil * MARGIN['base']).round(0)       # = break-even repair cost
c['payback_days'] = (c.crew_days + c.repair_cost_cad / (c.oil_lost_per_day * MARGIN['base'])).where(c.net_gain_base_cad > 0).round(1)
cols = ['job_id', 'well_id', 'job_type', 'field_operating_area', 'expected_extra_oil', 'oil_lost_per_day', 'failure_risk',
        'repeat_failure_rate', 'comparable_job_count', 'confidence', 'repair_cost_cad', 'cost_low_cad', 'cost_high_cad', 'crew_days',
        'oil_value_cad', 'net_gain_low_cad', 'net_gain_base_cad', 'net_gain_high_cad', 'net_gain_per_dollar',
        'net_gain_per_crew_day_cad', 'payback_days', 'flag_reason']
c[cols].to_csv('out/worked_example_candidates.csv', index=False)

SCEN = {'A_tight': (15000, 1.0), 'B_base': (25000, 1.5)}
rows = []
for k in range(len(c) + 1):
    for s in itertools.combinations(c.job_id, k):
        sub = c[c.job_id.isin(s)]
        if sub.well_id.duplicated().any():
            continue
        r = {'plan': '+'.join(s) if s else '(none)', 'total_cost_cad': sub.repair_cost_cad.sum(),
             'total_crew_days': round(sub.crew_days.sum(), 2), 'total_extra_oil_m3': round(sub.expected_extra_oil.sum(), 1),
             'total_net_gain_cad': round(sub.net_gain_base_cad.sum(), 0)}
        for n, (b, cr) in SCEN.items():
            r[f'fits_{n}'] = bool(r['total_cost_cad'] <= b and r['total_crew_days'] <= cr + 1e-9)
        rows.append(r)
cb = pd.DataFrame(rows); cb.to_csv('out/worked_example_all_combinations.csv', index=False)
for n in SCEN:
    best = cb[cb[f'fits_{n}']].sort_values('total_net_gain_cad', ascending=False).iloc[0]
    print(n, SCEN[n], best.plan, best.total_net_gain_cad)