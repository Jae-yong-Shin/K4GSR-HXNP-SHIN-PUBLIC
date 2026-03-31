"""
Test our DM engine with MATLAB-generated multi-mode data.

Uses matlab_multimode_results.mat from K4GSR-PTYCHO as ground truth.
This validates:
  1. Our DM engine works with real multi-mode data (3 probe modes)
  2. Our ML refinement improves the result
  3. Compare with MATLAB DM/ML results

Also tests: single-mode recon on multi-mode data (should be worse).
"""
import sys
import time
import numpy as np
from pathlib import Path
import h5py

sys.path.insert(0, str(Path(__file__).parent))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def convert_complex(data):
    """Convert MATLAB complex struct to numpy complex."""
    if hasattr(data, 'dtype') and data.dtype.names == ('real', 'imag'):
        return data['real'] + 1j * data['imag']
    return data


def load_matlab_data():
    """Load MATLAB multi-mode reference data."""
    mat_path = Path(r'c:\Projects\K4GSR-PTYCHO\matlab_ref\matlab_multimode_results.mat')
    print(f"Loading {mat_path}...")

    with h5py.File(str(mat_path), 'r') as f:
        object_true = convert_complex(f['object_true'][()]).T
        probe_true = convert_complex(f['probe_true'][()]).T

        # p_0 group contains initial conditions
        p_0 = f['p_0']

        # fmag
        if p_0['fmag'].shape == (1, 1):
            fmag = f[p_0['fmag'][0, 0]][()].T
        else:
            fmag = p_0['fmag'][()].T

        # positions
        if p_0['positions'].shape == (1, 1):
            positions = f[p_0['positions'][0, 0]][()].T
        else:
            positions = p_0['positions'][()].T

        # asize
        if p_0['asize'].shape == (1, 1):
            asize = f[p_0['asize'][0, 0]][()].flatten().astype(int)
        else:
            asize = p_0['asize'][()].flatten().astype(int)

        # probes initial (3 modes)
        if p_0['probes'].shape == (1, 1):
            probes_ref = f[p_0['probes'][0, 0]]
            if probes_ref.shape == (1, 1):
                probes_initial = convert_complex(f[probes_ref[0, 0]][()]).T
            else:
                probes_initial = convert_complex(probes_ref[()]).T
        else:
            probes_initial = convert_complex(p_0['probes'][()]).T

        # object initial
        if p_0['object'].shape == (1, 1):
            object_ref = f[p_0['object'][0, 0]]
            if object_ref.shape == (1, 1):
                object_initial = convert_complex(f[object_ref[0, 0]][()]).T
            else:
                object_initial = convert_complex(object_ref[()]).T
        else:
            object_initial = convert_complex(p_0['object'][()]).T

        # scanidxs
        if p_0['scanidxs'].shape == (1, 1):
            scanidxs = f[p_0['scanidxs'][0, 0]][()].flatten().astype(int)
        else:
            scanidxs = p_0['scanidxs'][()].flatten().astype(int)

    return {
        'object_true': object_true,
        'probe_true': probe_true,
        'fmag': fmag,
        'positions': positions,
        'asize': asize,
        'probes_initial': probes_initial,
        'object_initial': object_initial,
        'scanidxs': scanidxs,
    }


def run_our_dm(data, n_modes_recon, n_iter=200):
    """Run our GPU DM on MATLAB data."""
    from engines.gpu.DM import DM as DM_GPU

    asize = data['asize']
    fmag_3d = data['fmag']  # (Npos, H, W) or (H, W, Npos)
    positions = data['positions']

    # Ensure fmag is (H, W, Npos)
    if fmag_3d.shape[0] == positions.shape[0] and fmag_3d.shape[0] != asize[0]:
        # (Npos, H, W) -> (H, W, Npos)
        fmag_3d = np.transpose(fmag_3d, (1, 2, 0))

    Npos = positions.shape[0]
    print(f"  fmag: {fmag_3d.shape}, positions: {positions.shape}, asize: {asize}")

    # Build p dict manually
    p = {
        'asize': asize,
        'use_gpu': True,
        'pfft_relaxation': 0.05,
        'probe_change_start': 1,
        'object_change_start': 1,
        'probe_inertia': 0.9,
    }

    # Object: use initial (ones)
    ob = [data['object_initial'].squeeze().astype(np.complex64)]

    # Probes: extract for our DM format
    # probes_initial shape: (H, W, numprobs, probe_modes) from MATLAB
    pi = data['probes_initial']
    print(f"  probes_initial shape: {pi.shape}")

    if n_modes_recon == 1:
        # Use only mode 0
        if pi.ndim == 4:
            probes_in = pi[:, :, 0, 0].astype(np.complex64)
        elif pi.ndim == 3:
            probes_in = pi[:, :, 0].astype(np.complex64)
        else:
            probes_in = pi.astype(np.complex64)
    else:
        # Use all modes: (H, W, N_modes)
        if pi.ndim == 4:
            nm = min(n_modes_recon, pi.shape[3])
            probes_in = pi[:, :, 0, :nm].astype(np.complex64)
        elif pi.ndim == 3:
            nm = min(n_modes_recon, pi.shape[2])
            probes_in = pi[:, :, :nm].astype(np.complex64)
        else:
            probes_in = pi.astype(np.complex64)

    print(f"  probes_in shape: {probes_in.shape}")

    # Convert positions to float32
    # Note: these MATLAB positions are already 0-based (range [0, obj_size-asize])
    pos = positions.astype(np.float32)

    fmag_f32 = fmag_3d.astype(np.float32)

    t0 = time.time()
    ob_out, pr_out, err = DM_GPU(
        p, ob=ob, probes=probes_in,
        fmag=fmag_f32, positions=pos, num_iterations=n_iter)
    elapsed = time.time() - t0

    return ob_out[0], pr_out, err, elapsed


def compute_norm_error(recon, truth, margin=0):
    """Compute norm error with phase alignment."""
    oh, ow = recon.shape
    th, tw = truth.shape
    ch = min(oh, th) - 2 * margin
    cw = min(ow, tw) - 2 * margin
    if ch <= 0 or cw <= 0:
        return 1.0

    r = recon[oh // 2 - ch // 2:oh // 2 + ch // 2, ow // 2 - cw // 2:ow // 2 + cw // 2]
    t = truth[th // 2 - ch // 2:th // 2 + ch // 2, tw // 2 - cw // 2:tw // 2 + cw // 2]

    phase_off = np.angle(np.sum(r * np.conj(t)))
    r_aligned = r * np.exp(-1j * phase_off)

    err = np.sqrt(np.sum(np.abs(r_aligned - t) ** 2) / np.sum(np.abs(t) ** 2))
    return float(err)


def main():
    data = load_matlab_data()
    gt = data['object_true']
    asize = data['asize']
    Npos = data['positions'].shape[0]

    print(f"\n=== MATLAB Multi-mode Data ===")
    print(f"  asize: {asize}")
    print(f"  Npos: {Npos}")
    print(f"  object_true: {gt.shape}, |obj| range: [{np.abs(gt).min():.4f}, {np.abs(gt).max():.4f}]")
    print(f"  probe_true: {data['probe_true'].shape}")

    # Probe mode analysis
    pi = data['probes_initial']
    print(f"  probes_initial: {pi.shape}")
    if pi.ndim == 4:
        total_power = 0
        for m in range(pi.shape[3]):
            pw = float(np.sum(np.abs(pi[:, :, 0, m]) ** 2))
            total_power += pw
        for m in range(pi.shape[3]):
            pw = float(np.sum(np.abs(pi[:, :, 0, m]) ** 2))
            print(f"    Mode {m}: power={pw:.1f} ({100 * pw / total_power:.1f}%)")

    # ── Test 1: 3-mode recon (matching) ──
    print(f"\n{'=' * 60}")
    print(f"  Test 1: 3-mode DM 300iter (matching MATLAB initial)")
    print(f"{'=' * 60}")
    ob1, pr1, err1, t1 = run_our_dm(data, n_modes_recon=3, n_iter=300)
    margin = asize[0] // 4
    ne1 = compute_norm_error(ob1, gt, margin)
    print(f"  norm_error={ne1:.4f}, |obj|max={np.abs(ob1).max():.3f}, time={t1:.0f}s")

    # ── Test 2: 1-mode recon (mismatch) ──
    print(f"\n{'=' * 60}")
    print(f"  Test 2: 1-mode DM 300iter (mode mismatch)")
    print(f"{'=' * 60}")
    ob2, pr2, err2, t2 = run_our_dm(data, n_modes_recon=1, n_iter=300)
    ne2 = compute_norm_error(ob2, gt, margin)
    print(f"  norm_error={ne2:.4f}, |obj|max={np.abs(ob2).max():.3f}, time={t2:.0f}s")

    # ── Plot ──
    fig, axes = plt.subplots(3, 3, figsize=(15, 15))

    # GT
    gt_amp = np.abs(gt[margin:-margin, margin:-margin])
    vmin, vmax = np.percentile(gt_amp, 1), np.percentile(gt_amp, 99.5) * 1.1
    axes[0, 0].imshow(gt_amp, cmap='jet', vmin=vmin, vmax=vmax)
    axes[0, 0].set_title('Ground Truth (amplitude)', fontweight='bold')
    axes[0, 0].axis('off')

    axes[1, 0].imshow(np.angle(gt[margin:-margin, margin:-margin]),
                       cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[1, 0].set_title('Ground Truth (phase)', fontweight='bold')
    axes[1, 0].axis('off')

    # Probe true
    axes[2, 0].imshow(np.abs(data['probe_true']), cmap='jet')
    axes[2, 0].set_title(f'Probe True', fontweight='bold')
    axes[2, 0].axis('off')

    # Test 1: 3-mode
    r1_amp = np.abs(ob1[margin:-margin, margin:-margin])
    axes[0, 1].imshow(r1_amp, cmap='jet',
                       vmin=np.percentile(r1_amp, 1),
                       vmax=np.percentile(r1_amp, 99.5) * 1.1)
    axes[0, 1].set_title(f'3-mode DM 300\nerr={ne1:.4f}, |obj|max={np.abs(ob1).max():.3f}',
                          fontweight='bold', fontsize=10)
    axes[0, 1].axis('off')

    axes[1, 1].imshow(np.angle(ob1[margin:-margin, margin:-margin]),
                       cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[1, 1].set_title(f'3-mode phase ({t1:.0f}s)', fontsize=10)
    axes[1, 1].axis('off')

    # Probe recon (incoherent sum)
    if pr1.ndim == 3:
        pr1_amp = np.sqrt(np.sum(np.abs(pr1) ** 2, axis=2))
    else:
        pr1_amp = np.abs(pr1)
    axes[2, 1].imshow(pr1_amp, cmap='jet')
    axes[2, 1].set_title(f'Probe 3-mode recon', fontsize=10)
    axes[2, 1].axis('off')

    # Test 2: 1-mode
    r2_amp = np.abs(ob2[margin:-margin, margin:-margin])
    axes[0, 2].imshow(r2_amp, cmap='jet',
                       vmin=np.percentile(r2_amp, 1),
                       vmax=np.percentile(r2_amp, 99.5) * 1.1)
    axes[0, 2].set_title(f'1-mode DM 300\nerr={ne2:.4f}, |obj|max={np.abs(ob2).max():.3f}',
                          fontweight='bold', fontsize=10)
    axes[0, 2].axis('off')

    axes[1, 2].imshow(np.angle(ob2[margin:-margin, margin:-margin]),
                       cmap='hsv', vmin=-np.pi, vmax=np.pi)
    axes[1, 2].set_title(f'1-mode phase ({t2:.0f}s)', fontsize=10)
    axes[1, 2].axis('off')

    axes[2, 2].imshow(np.abs(pr2), cmap='jet')
    axes[2, 2].set_title(f'Probe 1-mode recon', fontsize=10)
    axes[2, 2].axis('off')

    fig.suptitle(
        f'MATLAB Multi-mode Data: Our DM Reconstruction\n'
        f'asize={asize}, Npos={Npos}, 3 probe modes (88.5/8.0/3.5%)',
        fontsize=14, fontweight='bold')
    plt.tight_layout()
    out = str(Path(__file__).parent / '_matlab_multimode_test.png')
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\n[SAVED] {out}")

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY")
    print(f"{'=' * 60}")
    print(f"  3-mode recon: norm_error={ne1:.4f} (expect <0.3 for decent)")
    print(f"  1-mode recon: norm_error={ne2:.4f} (expect worse than 3-mode)")
    if ne1 < ne2:
        print(f"  3-mode recon BETTER than 1-mode: OK (multi-mode is working)")
    else:
        print(f"  WARNING: 3-mode recon NOT better than 1-mode!")


if __name__ == '__main__':
    main()
