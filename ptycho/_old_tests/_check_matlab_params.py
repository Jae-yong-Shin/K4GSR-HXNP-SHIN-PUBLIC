"""Extract key MATLAB simulation parameters."""
import numpy as np
import h5py
from pathlib import Path

mat_path = Path(r'c:\Projects\K4GSR-PTYCHO\matlab_ref\matlab_multimode_results.mat')

def to_val(f, ref):
    """Dereference HDF5 object ref."""
    if ref.shape == (1, 1):
        try:
            return f[ref[0, 0]][()].flatten()
        except:
            return ref[()].flatten()
    return ref[()].flatten()

with h5py.File(str(mat_path), 'r') as f:
    p_0 = f['p_0']

    # Key scalar params
    for k in ['energy', 'z', 'ds', 'lambda', 'numpos', 'probe_modes',
              'object_modes', 'numprobs', 'numscans', 'Nphot']:
        if k in p_0:
            try:
                v = p_0[k][()].flatten()
                print(f"  {k}: {v}")
            except:
                print(f"  {k}: (error reading)")

    # Mode start
    if 'mode_start' in p_0:
        v = p_0['mode_start'][()].flatten()
        print(f"  mode_start: {v} (as chars: {''.join(chr(int(c)) for c in v if c > 0)})")

    if 'mode_start_pow' in p_0:
        v = p_0['mode_start_pow'][()].flatten()
        print(f"  mode_start_pow: {v}")

    # Simulation params
    sim = p_0['simulation']
    for k in ['energy', 'photons_per_pixel', 'illumination',
              'incoherence_blur', 'det_pixel_size', 'objheight',
              'prop_from_focus', 'delta_z_total']:
        if k in sim:
            try:
                v = sim[k][()].flatten()
                print(f"  sim/{k}: {v}")
            except:
                print(f"  sim/{k}: (error)")

    # asize and dx_spec
    if 'dx_spec' in p_0:
        dx = p_0['dx_spec'][()].flatten()
        print(f"  dx_spec: {dx} m -> {dx * 1e9} nm")

    # Check fmag intensity level
    if p_0['fmag'].shape[0] == 43:
        fmag = p_0['fmag'][()]  # (43, 192, 192)
    else:
        fmag = p_0['fmag'][()].T

    print(f"\n  fmag shape: {fmag.shape}")
    print(f"  fmag range: [{fmag.min():.4f}, {fmag.max():.4f}]")
    print(f"  fmag^2 per pattern: {(fmag**2).sum(axis=(1,2)).mean():.4e}")
