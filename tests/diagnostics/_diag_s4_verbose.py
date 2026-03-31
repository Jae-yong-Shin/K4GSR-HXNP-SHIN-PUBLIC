import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'paper', 'validation'))

from shadow4_bl10 import run_shadow4_bl10
import shadow4_bl10

class VerboseListener:
    def status_message(self, message):
        if message and message.strip():
            print(f"  [STATUS] {message.strip()}")
    def warning_message(self, message=""):
        if message and message.strip():
            print(f"  [WARN] {message.strip()}")
    def error_message(self, message=""):
        if message and message.strip():
            print(f"  [ERROR] {message.strip()}")
    def set_progress_value(self, value):
        pass

shadow4_bl10._QuietHybridListener = VerboseListener

for cond in [
    {"energy": 10.0, "ssa": 50},
    {"energy": 10.0, "ssa": 10},
    {"energy": 10.0, "ssa": 200},
    {"energy": 5.0,  "ssa": 50},
]:
    print(f"\n{'='*60}")
    print(f"E={cond['energy']}keV, SSA={cond['ssa']}um")
    print(f"{'='*60}")
    try:
        result = run_shadow4_bl10(
            E_keV=cond['energy'],
            ssa_um=cond['ssa'],
            nrays=100000,
            verbose=True,
            hybrid=True,
        )
        fwhm_h = result.get('fwhm_h_m', 0) * 1e9
        fwhm_v = result.get('fwhm_v_m', 0) * 1e9
        nrays = result.get('nrays_good', 0)
        print(f"  RESULT: FWHM H={fwhm_h:.1f}nm, V={fwhm_v:.1f}nm, rays={nrays}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  ERROR: {e}")

print("\nDone.")
