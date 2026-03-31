import numpy as np
import h5py
import sys

mat_path = r'c:\Projects\K4GSR-PTYCHO\matlab_ref\matlab_multimode_results.mat'

def read_complex(ds):
    """Read HDF5 dataset with structured (real, imag) dtype into complex array."""
    raw = ds[()]
    if raw.dtype.names and 'real' in raw.dtype.names and 'imag' in raw.dtype.names:
        return raw['real'] + 1j * raw['imag']
    return raw

with h5py.File(mat_path, 'r') as f:
    print("=== HDF5 keys ===")
    for k in sorted(f.keys()):
        v = f[k]
        if hasattr(v, 'shape'):
            print(f"  {k}: shape={v.shape}, dtype={v.dtype}")
        else:
            print(f"  {k}: {type(v).__name__}")
    
    # Check p_0 group
    if 'p_0' in f and isinstance(f['p_0'], h5py.Group):
        print(f"\n=== p_0 group contents ===")
        def visit(name, obj):
            if isinstance(obj, h5py.Dataset):
                print(f"  p_0/{name}: shape={obj.shape}, dtype={obj.dtype}")
        f['p_0'].visititems(visit)
    
    # Object true
    if 'object_true' in f:
        ot = read_complex(f['object_true'])
        # MATLAB stores transposed (column-major)
        ot = ot.T
        print(f"\n=== Object True ===")
        print(f"  shape: {ot.shape}")
        print(f"  |obj| range: [{np.abs(ot).min():.4f}, {np.abs(ot).max():.4f}]")
        print(f"  angle range: [{np.angle(ot).min():.4f}, {np.angle(ot).max():.4f}] rad")
    
    # Object DM
    if 'object_dm' in f:
        od = read_complex(f['object_dm']).T
        print(f"\n=== Object DM ===")
        print(f"  shape: {od.shape}")
        print(f"  |obj| range: [{np.abs(od).min():.6f}, {np.abs(od).max():.6f}]")
        print(f"  angle range: [{np.angle(od).min():.4f}, {np.angle(od).max():.4f}] rad")
    
    # Object ML
    if 'object_ml' in f:
        om = read_complex(f['object_ml']).T
        print(f"\n=== Object ML ===")
        print(f"  shape: {om.shape}")
        print(f"  |obj| range: [{np.abs(om).min():.6f}, {np.abs(om).max():.6f}]")
        print(f"  angle range: [{np.angle(om).min():.4f}, {np.angle(om).max():.4f}] rad")
    
    # True probe
    if 'probe_true' in f:
        pt = read_complex(f['probe_true']).T
        print(f"\n=== Probe True ===")
        print(f"  shape: {pt.shape}")
        amp = np.abs(pt)
        print(f"  |P| min={amp.min():.4f}, max={amp.max():.4f}, sum|P|^2={np.sum(amp**2):.2f}")
        row = amp[amp.shape[0]//2, :]
        hm = row.max() / 2
        above = np.where(row > hm)[0]
        if len(above) > 1:
            print(f"  FWHM(center row): {above[-1] - above[0]} px")
    
    # DM probe modes
    print(f"\n=== DM Probe Modes ===")
    for i in range(1, 10):
        key = f'probe_dm_mode{i}'
        if key not in f:
            break
        pm = read_complex(f[key]).T
        amp = np.abs(pm)
        power = np.sum(amp**2)
        print(f"  Mode {i}: shape={pm.shape}, |P| min={amp.min():.4f}, max={amp.max():.4f}, sum|P|^2={power:.2f}")
        row = amp[amp.shape[0]//2, :]
        hm = row.max() / 2
        above = np.where(row > hm)[0]
        if len(above) > 1:
            print(f"    FWHM(center row): {above[-1] - above[0]} px")
    
    # DM incoherent
    if 'probe_dm_incoherent' in f:
        pi = f['probe_dm_incoherent'][()].T
        print(f"\n=== DM Incoherent (sum of mode intensities) ===")
        print(f"  shape: {pi.shape}, min={pi.min():.4f}, max={pi.max():.4f}")
    
    # ML probe modes
    print(f"\n=== ML Probe Modes ===")
    for i in range(1, 10):
        key = f'probe_ml_mode{i}'
        if key not in f:
            break
        pm = read_complex(f[key]).T
        amp = np.abs(pm)
        power = np.sum(amp**2)
        print(f"  Mode {i}: shape={pm.shape}, |P| min={amp.min():.4f}, max={amp.max():.4f}, sum|P|^2={power:.2f}")
        row = amp[amp.shape[0]//2, :]
        hm = row.max() / 2
        above = np.where(row > hm)[0]
        if len(above) > 1:
            print(f"    FWHM(center row): {above[-1] - above[0]} px")
    
    # ML incoherent
    if 'probe_ml_incoherent' in f:
        pi = f['probe_ml_incoherent'][()].T
        print(f"\n=== ML Incoherent (sum of mode intensities) ===")
        print(f"  shape: {pi.shape}, min={pi.min():.4f}, max={pi.max():.4f}")
    
    # Mode power fractions
    print(f"\n=== Mode Power Fractions ===")
    for engine in ['dm', 'ml']:
        powers = []
        for i in range(1, 10):
            key = f'probe_{engine}_mode{i}'
            if key not in f:
                break
            pm = read_complex(f[key])
            powers.append(np.sum(np.abs(pm)**2))
        total = sum(powers)
        print(f"  {engine.upper()}: total power = {total:.2f}")
        for i, pw in enumerate(powers):
            print(f"    Mode {i+1}: {pw:.2f} ({100*pw/total:.1f}%)")

print("\nDone.")
