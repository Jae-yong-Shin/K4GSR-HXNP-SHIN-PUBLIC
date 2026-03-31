"""Analyze MATLAB multi-mode probe structure to understand how modes were generated."""
import numpy as np
import h5py
from pathlib import Path

mat_path = Path(r'c:\Projects\K4GSR-PTYCHO\matlab_ref\matlab_multimode_results.mat')

with h5py.File(str(mat_path), 'r') as f:
    p_0 = f['p_0']

    # Load initial probes (3 modes)
    if p_0['probes'].shape == (1, 1):
        probes_ref = f[p_0['probes'][0, 0]]
        if probes_ref.shape == (1, 1):
            probes = (probes_ref[0, 0])
            probes = f[probes][()]
        else:
            probes = probes_ref[()]
    else:
        probes = p_0['probes'][()]

    # Handle complex
    def to_complex(data):
        if hasattr(data, 'dtype') and data.dtype.names == ('real', 'imag'):
            return data['real'] + 1j * data['imag']
        return data

    probes = to_complex(probes).T  # (H, W, numprobs, probe_modes)
    print(f"probes shape: {probes.shape}")

    # Also load probe_initial (single mode?)
    try:
        if p_0['probe_initial'].shape == (1, 1):
            pi = f[p_0['probe_initial'][0, 0]][()]
        else:
            pi = p_0['probe_initial'][()]
        probe_init = to_complex(pi).T
        print(f"probe_initial shape: {probe_init.shape}")
    except:
        probe_init = None
        print("No probe_initial found")

    # Load simulation probe
    try:
        sim = p_0['simulation']
        if 'probe' in sim:
            sp = sim['probe']
            if sp.shape == (1, 1):
                sim_probe = to_complex(f[sp[0, 0]][()]).T
            else:
                sim_probe = to_complex(sp[()]).T
            print(f"simulation/probe shape: {sim_probe.shape}")
        else:
            sim_probe = None
    except:
        sim_probe = None
        print("No simulation/probe found")

print(f"\n=== Mode Analysis ===")
for m in range(probes.shape[3]):
    pm = probes[:, :, 0, m]
    amp = np.abs(pm)
    phase = np.angle(pm)
    power = float(np.sum(amp**2))
    print(f"\nMode {m}:")
    print(f"  |P| range: [{amp.min():.4f}, {amp.max():.4f}]")
    print(f"  power: {power:.1f}")
    print(f"  phase range: [{phase.min():.2f}, {phase.max():.2f}] rad")

    # FWHM
    row = amp[amp.shape[0]//2, :]
    hm = row.max() / 2
    above = np.where(row > hm)[0]
    if len(above) > 1:
        print(f"  FWHM(row): {above[-1] - above[0]} px")

    # Centroid
    y, x = np.mgrid[:amp.shape[0], :amp.shape[1]]
    total = amp.sum()
    if total > 0:
        cy = float((y * amp).sum() / total)
        cx = float((x * amp).sum() / total)
        print(f"  centroid: ({cy:.1f}, {cx:.1f})")

# Cross-correlation between modes
print(f"\n=== Mode Cross-Correlations ===")
for i in range(probes.shape[3]):
    for j in range(i+1, probes.shape[3]):
        pi_flat = probes[:, :, 0, i].ravel()
        pj_flat = probes[:, :, 0, j].ravel()
        # Pearson correlation (complex)
        corr = np.abs(np.sum(pi_flat * np.conj(pj_flat))) / (
            np.sqrt(np.sum(np.abs(pi_flat)**2) * np.sum(np.abs(pj_flat)**2)))
        print(f"  |<P{i}|P{j}>| / (||P{i}|| ||P{j}||) = {corr:.4f}")

# Mode difference analysis
print(f"\n=== Mode Differences ===")
p0 = probes[:, :, 0, 0]
for m in range(1, probes.shape[3]):
    pm = probes[:, :, 0, m]
    # Normalize both to unit power
    p0n = p0 / np.sqrt(np.sum(np.abs(p0)**2))
    pmn = pm / np.sqrt(np.sum(np.abs(pm)**2))
    diff = np.sqrt(np.sum(np.abs(p0n - pmn)**2))
    print(f"  ||P0_norm - P{m}_norm|| = {diff:.4f}")

    # Phase diff at peak
    i0_peak = np.unravel_index(np.abs(p0).argmax(), p0.shape)
    im_peak = np.unravel_index(np.abs(pm).argmax(), pm.shape)
    print(f"  Peak location: mode0={i0_peak}, mode{m}={im_peak}")

    # Amplitude profile comparison
    row0 = np.abs(p0[p0.shape[0]//2, :])
    rowm = np.abs(pm[pm.shape[0]//2, :])
    if row0.max() > 0 and rowm.max() > 0:
        row0n = row0 / row0.max()
        rowmn = rowm / rowm.max()
        print(f"  Profile similarity: {np.corrcoef(row0n, rowmn)[0,1]:.4f}")

if sim_probe is not None:
    print(f"\n=== Simulation Probe vs Mode 0 ===")
    sp_amp = np.abs(sim_probe)
    m0_amp = np.abs(probes[:, :, 0, 0])
    print(f"  sim_probe |P| max: {sp_amp.max():.4f}")
    print(f"  mode 0 |P| max: {m0_amp.max():.4f}")
    print(f"  sim_probe power: {np.sum(sp_amp**2):.1f}")
    print(f"  mode 0 power: {np.sum(m0_amp**2):.1f}")
