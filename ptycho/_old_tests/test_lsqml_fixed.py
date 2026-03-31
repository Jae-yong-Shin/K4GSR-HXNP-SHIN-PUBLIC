"""
Test fixed LSQML (decoupled fallback for imbalanced systems).
1. LSQML standalone from ones init
2. ePIE50 + LSQML50
"""
import sys
import numpy as np
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from synth_ptycho import SyntheticPtycho, estimate_probe_fwhm
from server.data_loader import DataLoader


def norm_error(ob_final, truth):
    oh, ow = ob_final.shape
    th, tw = truth.shape
    ch, cw = min(oh, th), min(ow, tw)
    ob_c = ob_final[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
    tr_c = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]
    phase_diff = np.angle(np.sum(ob_c * np.conj(tr_c)))
    ob_aligned = ob_c * np.exp(-1j * phase_diff)
    return np.sqrt(np.sum(np.abs(ob_aligned - tr_c)**2) / np.sum(np.abs(tr_c)**2))


# Generate data
asize = 128
energy_keV = 6.2
z_m = 1.0
det_pixel_m = 75e-6
N_photons = int(1e8)

dl = DataLoader()
probe = dl._build_fresnel_probe(
    {'fwhm_h_m': 200e-9, 'fwhm_v_m': 200e-9,
     'focal_length_m': 0.3, 'defocus_m': 0.0},
    asize, energy_keV, z_m, det_pixel_m)
fwhm_px = estimate_probe_fwhm(probe)

lam = 1239.842e-9 / (energy_keV * 1e3)
pixel_nm = lam * z_m / (asize * det_pixel_m) * 1e9
step_px = fwhm_px * 0.25
scan_area_px = 2 * step_px * 0.57 * np.sqrt(250) * 1.2
scan_area_um = max(0.5, scan_area_px * pixel_nm * 1e-3)

gen = SyntheticPtycho.from_dataset(
    asize=asize, energy_keV=energy_keV, z_m=z_m,
    det_pixel_size_m=det_pixel_m, N_photons=N_photons,
    scan_step_um=None, overlap=0.75,
    scan_lx_um=scan_area_um, scan_ly_um=scan_area_um,
    probe=probe)
ds = gen.generate(noise_sigma=0.0, rng_seed=42)
truth = ds.object_true.squeeze()

print(f"Scenario: N={N_photons:.0e}, Npos={ds.Npos}, FWHM={fwhm_px:.1f}px")

data = {
    'fmag': ds.fmag, 'positions': ds.positions_clean,
    'probes': ds.probe, 'object_init': ds.object_init,
    'asize': (asize, asize), 'Npos': ds.Npos,
}

from engines.gpu.LSQML import LSQML
from engines.gpu.ePIE import ePIE

# =====================================================
# TEST 1: Fixed LSQML standalone (100 iter)
# =====================================================
print(f"\n{'=' * 60}")
print(f"  TEST 1: Fixed LSQML standalone (100 iter)")
print(f"{'=' * 60}")

p1 = dl.build_p_dict(data, {
    'number_iterations': 100, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
})
probes_in = p1['probes'][:, :, 0, 0] if p1['probes'].ndim == 4 else p1['probes']
ob_in = [o.squeeze() for o in p1['object']] if isinstance(p1['object'], list) else [p1['object'].squeeze()]

t0 = time.time()
ob1, pr1, err1 = LSQML(p1, ob=ob_in, probes=probes_in,
                         fmag=p1['fmag'], positions=p1['positions'], num_iterations=100)
dt1 = time.time() - t0
ne1 = norm_error(ob1[0].squeeze(), truth)
g1 = "EXCELLENT" if ne1 < 0.15 else "GOOD" if ne1 < 0.30 else "MARGINAL" if ne1 < 0.50 else "POOR"
print(f"\n  LSQML100: norm_error={ne1:.4f} ({g1}), |obj| max={np.abs(ob1[0]).max():.4f}, time={dt1:.1f}s")

# =====================================================
# TEST 2: ePIE50 + Fixed LSQML50
# =====================================================
print(f"\n{'=' * 60}")
print(f"  TEST 2: ePIE50 + Fixed LSQML50")
print(f"{'=' * 60}")

p2a = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
})
probes2 = p2a['probes'][:, :, 0, 0] if p2a['probes'].ndim == 4 else p2a['probes']
ob2 = [o.squeeze() for o in p2a['object']] if isinstance(p2a['object'], list) else [p2a['object'].squeeze()]

t0 = time.time()
ob2_epie, pr2_epie, err2_epie = ePIE(p2a, ob=ob2, probes=probes2,
                                       fmag=p2a['fmag'], positions=p2a['positions'], num_iterations=50)
dt2a = time.time() - t0
ne2a = norm_error(ob2_epie[0].squeeze(), truth)
print(f"  ePIE50: norm_error={ne2a:.4f}, time={dt2a:.1f}s")

# Now LSQML
p2b = dl.build_p_dict(data, {
    'number_iterations': 50, 'use_gpu': False,
    'pfft_relaxation': 0.05, 'probe_change_start': 1,
    'object_change_start': 1,
})
p2b['object'] = ob2_epie
if pr2_epie.ndim == 2:
    p2b['probes'] = pr2_epie.reshape(pr2_epie.shape[0], pr2_epie.shape[1], 1, 1)
else:
    p2b['probes'] = pr2_epie

probes2b = p2b['probes'][:, :, 0, 0] if p2b['probes'].ndim == 4 else p2b['probes']
ob2b = [o.squeeze() for o in p2b['object']] if isinstance(p2b['object'], list) else [p2b['object'].squeeze()]

t0 = time.time()
ob2_out, pr2_out, err2_out = LSQML(p2b, ob=ob2b, probes=probes2b,
                                     fmag=p2b['fmag'], positions=p2b['positions'], num_iterations=50)
dt2b = time.time() - t0
ne2 = norm_error(ob2_out[0].squeeze(), truth)
g2 = "EXCELLENT" if ne2 < 0.15 else "GOOD" if ne2 < 0.30 else "MARGINAL" if ne2 < 0.50 else "POOR"
print(f"\n  ePIE50+LSQML50: norm_error={ne2:.4f} ({g2}), |obj| max={np.abs(ob2_out[0]).max():.4f}, time={dt2a+dt2b:.1f}s")

# =====================================================
# SUMMARY
# =====================================================
print(f"\n{'=' * 60}")
print(f"  SUMMARY (Fixed LSQML)")
print(f"{'=' * 60}")
print(f"  LSQML100 standalone: norm_error={ne1:.4f} ({g1})")
print(f"  ePIE50+LSQML50:     norm_error={ne2:.4f} ({g2})")
print(f"  (Reference: ePIE50 alone = {ne2a:.4f})")
