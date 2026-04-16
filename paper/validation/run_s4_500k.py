"""Run Shadow4 BL10 with 500k rays × 5 conditions (matching MC browser).

Usage:
    python paper/validation/run_s4_500k.py

Output:
    paper/validation/data/s4_{condition}_500k.json
"""
import os, sys, json, time

# Add parent to path for shadow4_bl10 module
sys.path.insert(0, os.path.dirname(__file__))
from shadow4_bl10 import run_shadow4_bl10

N_RAYS = 500000
N_REPEATS = 5
SEEDS = [12345, 23456, 34567, 45678, 56789]
CONDITIONS = [
    {"energy": 10.0, "ssa": 50,  "label": "10keV_ssa50"},
    {"energy": 5.0,  "ssa": 50,  "label": "5keV_ssa50"},
    {"energy": 20.0, "ssa": 50,  "label": "20keV_ssa50"},
    {"energy": 10.0, "ssa": 10,  "label": "10keV_ssa10"},
    {"energy": 10.0, "ssa": 200, "label": "10keV_ssa200"},
]

out_dir = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(out_dir, exist_ok=True)

results_summary = []

for cond in CONDITIONS:
    print(f"\n{'='*60}")
    print(f"  {cond['label']}  ({N_RAYS} rays x {N_REPEATS} repeats)")
    print(f"{'='*60}")

    fwhm_h_list, fwhm_v_list = [], []
    n_good_list = []
    all_results = []

    for rep in range(N_REPEATS):
        t0 = time.time()
        result = run_shadow4_bl10(
            E_keV=cond['energy'],
            ssa_um=cond['ssa'],
            nrays=N_RAYS,
            seed=SEEDS[rep],
            verbose=(rep == 0),
        )
        elapsed = time.time() - t0

        if result is None:
            print(f"  Rep {rep+1}: FAILED ({elapsed:.1f}s)")
            continue

        fh = (result.get('fine_fwhm_h_m') or result.get('fwhm_h_m') or 0) * 1e9
        fv = (result.get('fine_fwhm_v_m') or result.get('fwhm_v_m') or 0) * 1e9
        ng = result.get('nrays_good', 0)

        fwhm_h_list.append(fh)
        fwhm_v_list.append(fv)
        n_good_list.append(ng)
        all_results.append(result)

        print(f"  Rep {rep+1}: H={fh:.1f}nm V={fv:.1f}nm survived={ng} ({elapsed:.1f}s)")

    if not fwhm_h_list:
        print(f"  ALL REPEATS FAILED")
        continue

    import statistics as _stat
    mean_h = _stat.mean(fwhm_h_list)
    mean_v = _stat.mean(fwhm_v_list)
    std_h = _stat.stdev(fwhm_h_list) if len(fwhm_h_list) > 1 else 0
    std_v = _stat.stdev(fwhm_v_list) if len(fwhm_v_list) > 1 else 0
    mean_ng = _stat.mean(n_good_list)

    # Pick best run for profile data
    best_idx = max(range(len(all_results)), key=lambda i: all_results[i]['nrays_good'])
    best = all_results[best_idx]

    print(f"\n  Mean: H={mean_h:.1f}+/-{std_h:.1f}nm  V={mean_v:.1f}+/-{std_v:.1f}nm  survived={mean_ng:.0f}")

    results_summary.append({
        'condition': cond['label'],
        'energy_keV': cond['energy'],
        'ssa_um': cond['ssa'],
        'nRays': N_RAYS,
        'nRepeats': N_REPEATS,
        'fwhmH_nm': round(mean_h, 1),
        'fwhmH_std': round(std_h, 1),
        'fwhmV_nm': round(mean_v, 1),
        'fwhmV_std': round(std_v, 1),
        'nSurvived_mean': round(mean_ng),
        'centroidH_nm': round((best.get('centroid_h_m') or 0) * 1e9, 1),
        'centroidV_nm': round((best.get('centroid_v_m') or 0) * 1e9, 1),
    })

    # Save best run full result
    best['fwhm_h_mean_nm'] = mean_h
    best['fwhm_v_mean_nm'] = mean_v
    best['fwhm_h_std_nm'] = std_h
    best['fwhm_v_std_nm'] = std_v
    best['n_repeats'] = N_REPEATS
    fname = os.path.join(out_dir, f"s4_{cond['label']}_500k.json")
    with open(fname, 'w') as f:
        json.dump(best, f, indent=2)
    print(f"  Saved: {fname}")

print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
print(json.dumps(results_summary, indent=2))

# Save summary
summary_path = os.path.join(out_dir, 's4_500k_summary.json')
with open(summary_path, 'w') as f:
    json.dump(results_summary, f, indent=2)
print(f"\nSummary saved: {summary_path}")
