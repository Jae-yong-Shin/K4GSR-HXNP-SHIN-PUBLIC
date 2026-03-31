"""S4: Test SSA-only vs KB-only hybrid to separate contributions."""
import sys, os, copy
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'paper', 'validation'))

# Import S4 components
import numpy as np
from shadow4.sources.source_geometrical.source_gaussian import SourceGaussian

# Import the full beamline function source to modify it
import shadow4_bl10
from shadow4_bl10 import run_shadow4_bl10

# We need to create a modified version that allows separate SSA/KB hybrid control
# The simplest way: modify the function temporarily

original_code = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                     'paper', 'validation', 'shadow4_bl10.py')).read()

# Run 4 variants for SSA10@10keV and SSA50@10keV
conditions = [
    {"energy": 10.0, "ssa": 10},
    {"energy": 10.0, "ssa": 50},
    {"energy": 5.0, "ssa": 50},
]

class QuietListener:
    def status_message(self, message): pass
    def warning_message(self, message=""): pass
    def error_message(self, message=""): pass

shadow4_bl10._QuietHybridListener = QuietListener

print(f"{'Condition':<16} {'Mode':<20} {'H(nm)':>8} {'V(nm)':>8} {'rays':>8}")
print("-" * 70)

for c in conditions:
    # 1. No hybrid
    r = run_shadow4_bl10(c['energy'], c['ssa'], nrays=100000, verbose=False, hybrid=False)
    h = r.get('fwhm_h_m', 0) * 1e9
    v = r.get('fwhm_v_m', 0) * 1e9
    n = r.get('nrays_good', 0)
    print(f"{c['energy']}keV SSA{c['ssa']:<4} {'No hybrid':<20} {h:8.1f} {v:8.1f} {n:8d}")
    
    # 2. Full hybrid
    r = run_shadow4_bl10(c['energy'], c['ssa'], nrays=100000, verbose=False, hybrid=True)
    h = r.get('fwhm_h_m', 0) * 1e9
    v = r.get('fwhm_v_m', 0) * 1e9
    n = r.get('nrays_good', 0)
    print(f"{'':<16} {'Full hybrid':<20} {h:8.1f} {v:8.1f} {n:8d}")
    print()

print("\nDone.")
