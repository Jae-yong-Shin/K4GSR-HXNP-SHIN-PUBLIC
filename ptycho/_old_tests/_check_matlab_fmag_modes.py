"""Check if MATLAB fmag was generated with single or multi-mode."""
import numpy as np
import h5py
from pathlib import Path

mat_path = Path(r'c:\Projects\K4GSR-PTYCHO\matlab_ref\matlab_multimode_results.mat')

def to_complex(data):
    if hasattr(data, 'dtype') and data.dtype.names == ('real', 'imag'):
        return data['real'] + 1j * data['imag']
    return data

with h5py.File(str(mat_path), 'r') as f:
    p_0 = f['p_0']

    # Check all keys in p_0
    print("=== p_0 keys ===")
    def print_keys(group, prefix=''):
        for k in group.keys():
            v = group[k]
            if hasattr(v, 'shape'):
                print(f"  {prefix}{k}: shape={v.shape}, dtype={v.dtype}")
            elif hasattr(v, 'keys'):
                print(f"  {prefix}{k}: (group)")
                print_keys(v, prefix + '  ')
            else:
                print(f"  {prefix}{k}: {type(v)}")

    print_keys(p_0)

    # Check simulation subgroup
    if 'simulation' in p_0:
        sim = p_0['simulation']
        print("\n=== simulation keys ===")
        print_keys(sim)

        # Load simulation probe
        if 'probe' in sim:
            if sim['probe'].shape == (1, 1):
                sp = to_complex(f[sim['probe'][0, 0]][()]).T
            else:
                sp = to_complex(sim['probe'][()]).T
            print(f"\n  sim probe: shape={sp.shape}, power={np.sum(np.abs(sp)**2):.1f}")

        # Check for N_modes or probe_modes in simulation
        for k in ['N_modes', 'probe_modes', 'Nmodes', 'n_modes', 'modes']:
            if k in sim:
                v = sim[k][()]
                print(f"  sim/{k}: {v}")

    # Check main p_0 for probe_modes
    for k in ['probe_modes', 'N_modes', 'Nmodes']:
        if k in p_0:
            if p_0[k].shape == (1, 1):
                v = f[p_0[k][0, 0]][()].flatten()
            else:
                v = p_0[k][()].flatten()
            print(f"\n  p_0/{k}: {v}")

    # Reconstruct intensity from sim probe and compare with fmag
    # Load object_true
    object_true = to_complex(f['object_true'][()]).T

    # Load sim probe
    if 'simulation' in p_0 and 'probe' in p_0['simulation']:
        if p_0['simulation']['probe'].shape == (1, 1):
            sim_probe = to_complex(f[p_0['simulation']['probe'][0, 0]][()]).T
        else:
            sim_probe = to_complex(p_0['simulation']['probe'][()]).T
    else:
        sim_probe = None

    # Load fmag
    if p_0['fmag'].shape == (1, 1):
        fmag = f[p_0['fmag'][0, 0]][()].T
    else:
        fmag = p_0['fmag'][()].T

    # Load positions
    if p_0['positions'].shape == (1, 1):
        positions = f[p_0['positions'][0, 0]][()].T
    else:
        positions = p_0['positions'][()].T

    asize = [192, 192]

    if sim_probe is not None:
        print(f"\n=== Check: single-probe forward vs fmag ===")
        # Try computing intensity with just sim_probe
        pos0 = positions[0]
        r, c = int(round(pos0[0])), int(round(pos0[1]))
        patch = object_true[r:r+asize[0], c:c+asize[1]]
        if patch.shape == (asize[0], asize[1]):
            psi = np.fft.fft2(sim_probe * patch)
            I_single = np.abs(psi)**2
            fmag_sq = fmag[:, :, 0]**2
            # Scale comparison
            ratio = fmag_sq.sum() / max(I_single.sum(), 1e-30)
            print(f"  fmag^2 sum: {fmag_sq.sum():.4e}")
            print(f"  |FFT(sim_probe * obj)|^2 sum: {I_single.sum():.4e}")
            print(f"  ratio: {ratio:.4e}")
            print(f"  sqrt(ratio): {np.sqrt(ratio):.4f}")

        # Try with mode 0 probe
        probes = p_0['probes']
        if probes.shape == (1, 1):
            pr = to_complex(f[probes[0, 0]][()]).T
        else:
            pr = to_complex(probes[()]).T
        p0 = pr[:, :, 0, 0]
        psi0 = np.fft.fft2(p0 * patch)
        I_mode0 = np.abs(psi0)**2
        ratio0 = fmag_sq.sum() / max(I_mode0.sum(), 1e-30)
        print(f"\n  |FFT(mode0_probe * obj)|^2 sum: {I_mode0.sum():.4e}")
        print(f"  ratio (fmag^2 / mode0): {ratio0:.4e}")
        print(f"  sqrt(ratio): {np.sqrt(ratio0):.4f}")

        # All 3 modes incoherent sum
        I_multi = np.zeros(asize, dtype=np.float64)
        for m in range(pr.shape[3]):
            pm = pr[:, :, 0, m]
            psi_m = np.fft.fft2(pm * patch)
            I_multi += np.abs(psi_m)**2
        ratio_multi = fmag_sq.sum() / max(I_multi.sum(), 1e-30)
        print(f"\n  I_multi (3 modes incoherent) sum: {I_multi.sum():.4e}")
        print(f"  ratio (fmag^2 / multi): {ratio_multi:.4e}")
        print(f"  sqrt(ratio): {np.sqrt(ratio_multi):.4f}")
