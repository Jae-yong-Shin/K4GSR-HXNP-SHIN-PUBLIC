"""
Proper 1:1 Comparison: Python DM/LSQML vs MATLAB DM/ML
=======================================================
Both engines run on EXACTLY the same input data:
  - fmag_input    (from matlab_proper_comparison.mat)
  - positions_input
  - probe_init
  - object_init

Comparison is:
  1. Python vs Ground Truth  (same metric as MATLAB)
  2. Python reconstruction vs MATLAB reconstruction  (true 1:1 similarity)
"""

import numpy as np
import h5py
import time
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from engines.gpu.gpu_wrapper import set_use_gpu, check_gpu_available
from engines.gpu.DM import DM
from engines.gpu.LSQML import LSQML


# ── data loading ──────────────────────────────────────────────────────────────

def load_matlab_comparison(mat_path):
    """Load matlab_proper_comparison.mat (HDF5 / v7.3 format)."""
    with h5py.File(mat_path, 'r') as f:

        def cplx(key):
            v = f[key][()]
            if v.dtype.names and 'real' in v.dtype.names:
                return (v['real'] + 1j * v['imag']).T.astype(np.complex64)
            # Real-valued stored as complex struct sometimes
            return v.T.astype(np.complex64)

        def real_arr(key):
            v = f[key][()]
            return v.T.astype(np.float32)

        def scalar(key):
            return float(f[key][()].flat[0])

        return {
            # ── inputs for Python ───────────────────────────
            'fmag':         real_arr('fmag_input'),       # [Ny, Nx, N_pos]
            'positions':    real_arr('positions_input'),  # [N_pos, 2]
            'probe_init':   cplx('probe_init'),           # [Ny, Nx]
            'object_init':  cplx('object_init'),          # [obj_r, obj_c]
            # ── ground truth ────────────────────────────────
            'object_true':  cplx('object_true'),
            'probe_true':   cplx('probe_true'),
            # ── MATLAB reconstructions ──────────────────────
            'mat_obj_dm':   cplx('object_dm'),
            'mat_probe_dm': cplx('probe_dm'),
            'mat_obj_ml':   cplx('object_ml'),
            'mat_probe_ml': cplx('probe_ml'),
            # ── MATLAB metrics ──────────────────────────────
            'mat_obj_dm_corr':   scalar('obj_dm_corr'),
            'mat_probe_dm_corr': scalar('probe_dm_corr'),
            'mat_obj_ml_corr':   scalar('obj_ml_corr'),
            'mat_probe_ml_corr': scalar('probe_ml_corr'),
            'mat_elapsed_dm':    scalar('elapsed_dm'),
            'mat_elapsed_ml':    scalar('elapsed_ml'),
        }


# ── utilities ─────────────────────────────────────────────────────────────────

def corr(a1, a2):
    """Complex array correlation coefficient."""
    r = min(a1.shape[0], a2.shape[0])
    c = min(a1.shape[1], a2.shape[1])
    a1 = a1[:r, :c].ravel().astype(np.complex64)
    a2 = a2[:r, :c].ravel().astype(np.complex64)
    a1 = a1 - np.mean(a1)
    a2 = a2 - np.mean(a2)
    num = float(np.abs(np.sum(a1 * np.conj(a2))))
    den = float(np.sqrt(np.sum(np.abs(a1)**2) * np.sum(np.abs(a2)**2))) + 1e-30
    return num / den


def pass_fail(val, threshold=0.95):
    return '[PASS]' if val >= threshold else '[DIFF]'


def _phase_align(a, ref):
    """Align global phase of `a` to match `ref` via optimal complex rotation."""
    r = min(a.shape[0], ref.shape[0])
    c = min(a.shape[1], ref.shape[1])
    z = np.sum(a[:r, :c] * np.conj(ref[:r, :c]))
    phase = np.angle(z)
    return a * np.exp(-1j * phase)


def _crop(a, ref):
    r = min(a.shape[0], ref.shape[0])
    c = min(a.shape[1], ref.shape[1])
    return a[:r, :c], ref[:r, :c]


def _diff_metrics(py_img, mat_img):
    """Compute diff metrics after phase alignment + amplitude matching."""
    py_a, mat_a = _crop(py_img, mat_img)
    py_a = _phase_align(py_a, mat_a)

    # Amplitude normalization: scale Python to match MATLAB mean amplitude
    scale = (np.mean(np.abs(mat_a)) / (np.mean(np.abs(py_a)) + 1e-30))
    py_a = py_a * scale

    diff_amp   = np.abs(py_a) - np.abs(mat_a)           # signed amp diff
    diff_phase = np.angle(py_a * np.conj(mat_a))         # phase diff rad

    rmse_amp   = float(np.sqrt(np.mean(diff_amp**2)))
    mae_amp    = float(np.mean(np.abs(diff_amp)))
    rmse_phase = float(np.sqrt(np.mean(diff_phase**2)))
    mae_phase  = float(np.mean(np.abs(diff_phase)))

    ref_amp = float(np.mean(np.abs(mat_a))) + 1e-30
    nrmse   = rmse_amp / ref_amp  # normalized RMSE (amplitude)

    return {
        'diff_amp':   diff_amp,
        'diff_phase': diff_phase,
        'rmse_amp':   rmse_amp,
        'mae_amp':    mae_amp,
        'rmse_phase': rmse_phase,
        'mae_phase':  mae_phase,
        'nrmse':      nrmse,
        'py_aligned': py_a,
        'mat_crop':   mat_a,
    }


def visualize_diff(d, py_dm_obj, py_dm_probe, py_ml_obj, py_ml_probe, out_path, num_iter):
    """
    Difference analysis: Python vs MATLAB  (after phase-align + amplitude match)

    Layout (3 columns × 3 rows  ×  2 panels = DM panel | ML panel):
      Row 0: MATLAB recon  |  Python recon  |  Amplitude diff (signed)
      Row 1: Phase (MATLAB)|  Phase (Python)|  Phase diff
      Row 2: |Diff| heatmap (amplitude)
    """
    INTERP = 'nearest'

    obj_true = d['object_true']

    # ── compute diffs ────────────────────────────────────────────────────────
    dm_obj   = _diff_metrics(py_dm_obj,   d['mat_obj_dm'])
    dm_probe = _diff_metrics(py_dm_probe, d['mat_probe_dm'])
    ml_obj   = _diff_metrics(py_ml_obj,   d['mat_obj_ml'])
    ml_probe = _diff_metrics(py_ml_probe, d['mat_probe_ml'])

    # Print table
    print('\n' + '=' * 62)
    print(f'{"Comparison":<22} {"NRMSE":>8} {"RMSE_amp":>10} {"MAE_φ(°)":>10} {"RMSE_φ(°)":>10}')
    print('-' * 62)
    for label, m in [
        ('DM  Object',  dm_obj),
        ('DM  Probe',   dm_probe),
        ('LSQML Object', ml_obj),
        ('LSQML Probe',  ml_probe),
    ]:
        print(f'{label:<22} {m["nrmse"]:>8.4f} {m["rmse_amp"]:>10.4f}'
              f' {np.degrees(m["mae_phase"]):>10.2f} {np.degrees(m["rmse_phase"]):>10.2f}')
    print('=' * 62)

    # ── figure layout: 6-col × 4-row ─────────────────────────────────────────
    # Left 3 cols = DM comparison, right 3 cols = ML comparison
    # Col within each panel: [MATLAB | Python | Diff]
    fig, axes = plt.subplots(4, 6, figsize=(32, 22),
                             gridspec_kw={'hspace': 0.06, 'wspace': 0.04})

    def show(ax, img, cmap, vmin, vmax, label=None):
        ax.imshow(img, cmap=cmap, interpolation=INTERP, vmin=vmin, vmax=vmax, aspect='equal')
        ax.set_xticks([]); ax.set_yticks([])
        if label:
            ax.text(0.03, 0.97, label, transform=ax.transAxes, fontsize=8,
                    color='white', va='top',
                    bbox=dict(facecolor='black', alpha=0.5, pad=1))

    # ── panel builder ────────────────────────────────────────────────────────
    def draw_panel(col_offset, label_prefix, dm_or_ml_obj, dm_or_ml_probe,
                   mat_obj, mat_probe, n_iter_mat, n_iter_py):
        m_o = dm_or_ml_obj
        m_p = dm_or_ml_probe

        # symmetric amplitude diff scale
        amp_max_o = float(np.percentile(np.abs(m_o['diff_amp']), 99))
        amp_max_p = float(np.percentile(np.abs(m_p['diff_amp']), 99))

        # Row 0: Object amplitude
        vmax_o = float(np.percentile(np.abs(m_o['mat_crop']), 99.5)) or 1e-6
        show(axes[0, col_offset+0], np.abs(m_o['mat_crop']),  'gray', 0, vmax_o,
             f'MATLAB {label_prefix}\n{n_iter_mat} iter  r={corr(mat_obj, obj_true):.4f}')
        vmax_o_py = float(np.percentile(np.abs(m_o['py_aligned']), 99.5)) or 1e-6
        show(axes[0, col_offset+1], np.abs(m_o['py_aligned']), 'gray', 0, vmax_o_py,
             f'Python {label_prefix}\n{n_iter_py} iter  r={corr(py_dm_obj if label_prefix=="DM" else py_ml_obj, obj_true):.4f}')
        show(axes[0, col_offset+2], m_o['diff_amp'], 'RdBu_r', -amp_max_o, amp_max_o,
             f'Δ Amp  NRMSE={m_o["nrmse"]:.3f}')

        # Row 1: Object phase
        ph_mat = _norm_phase(m_o['mat_crop'])
        ph_py  = _norm_phase(m_o['py_aligned'])
        show(axes[1, col_offset+0], ph_mat, 'RdBu_r', -np.pi, np.pi, 'Object Phase (MATLAB)')
        show(axes[1, col_offset+1], ph_py,  'RdBu_r', -np.pi, np.pi, 'Object Phase (Python)')
        phase_max = float(np.percentile(np.abs(m_o['diff_phase']), 99)) or 0.1
        show(axes[1, col_offset+2], m_o['diff_phase'], 'PRGn', -phase_max, phase_max,
             f'Δ Phase  MAE={np.degrees(m_o["mae_phase"]):.1f}°  RMSE={np.degrees(m_o["rmse_phase"]):.1f}°')

        # Row 2: Probe amplitude
        vmax_p = float(np.percentile(np.abs(m_p['mat_crop']), 99.5)) or 1e-6
        show(axes[2, col_offset+0], np.abs(m_p['mat_crop']),  'gray', 0, vmax_p,
             f'Probe (MATLAB {label_prefix})\nr={corr(mat_probe, d["probe_true"]):.4f}')
        vmax_p_py = float(np.percentile(np.abs(m_p['py_aligned']), 99.5)) or 1e-6
        show(axes[2, col_offset+1], np.abs(m_p['py_aligned']), 'gray', 0, vmax_p_py,
             f'Probe (Python {label_prefix})\nr={corr(py_dm_probe if label_prefix=="DM" else py_ml_probe, d["probe_true"]):.4f}')
        show(axes[2, col_offset+2], m_p['diff_amp'], 'RdBu_r', -amp_max_p, amp_max_p,
             f'Δ Probe Amp  NRMSE={m_p["nrmse"]:.3f}')

        # Row 3: |Amplitude diff| heatmap (always positive)
        show(axes[3, col_offset+0], np.abs(m_o['diff_amp']), 'hot', 0, amp_max_o,
             '|Δ Obj Amp| heatmap')
        show(axes[3, col_offset+1], np.abs(m_p['diff_amp']), 'hot', 0, amp_max_p,
             '|Δ Probe Amp| heatmap')
        show(axes[3, col_offset+2], np.abs(m_o['diff_phase']), 'hot', 0, phase_max,
             '|Δ Obj Phase| heatmap')

    draw_panel(0, 'DM',   dm_obj,   dm_probe,
               d['mat_obj_dm'], d['mat_probe_dm'], num_iter[0], num_iter[2])
    draw_panel(3, 'LSQML', ml_obj,  ml_probe,
               d['mat_obj_ml'], d['mat_probe_ml'], num_iter[1], num_iter[3])

    # ── panel divider ─────────────────────────────────────────────────────────
    for ri in range(4):
        for ax in axes[ri, :]:
            ax.set_facecolor('#111')
    fig.patches.append(plt.Rectangle((0.498, 0), 0.004, 1, fill=True,
                                     facecolor='#444', transform=fig.transFigure,
                                     zorder=10))

    # ── column headers ────────────────────────────────────────────────────────
    for ci, title in enumerate(['MATLAB DM', 'Python DM', 'Difference',
                                  'MATLAB MLc', 'Python LSQML', 'Difference']):
        axes[0, ci].set_title(title, fontsize=11, fontweight='bold',
                               color='white', pad=5)

    # ── row labels ────────────────────────────────────────────────────────────
    for ri, lbl in enumerate(['Object Amp', 'Object Phase',
                               'Probe Amp', '|Diff| Heatmap']):
        axes[ri, 0].set_ylabel(lbl, fontsize=10, fontweight='bold',
                                color='white', labelpad=4)

    # ── colorbars ─────────────────────────────────────────────────────────────
    for ci in [2, 5]:   # diff columns
        for ri, (cmap, lbl) in enumerate([('RdBu_r', 'Δ Amp'),
                                           ('PRGn',   'Δ Phase (rad)'),
                                           ('RdBu_r', 'Δ Probe Amp'),
                                           ('hot',    '|Diff|')]):
            sm = plt.cm.ScalarMappable(cmap=cmap)
            sm.set_array([])
            cbar = fig.colorbar(sm, ax=axes[ri, ci], shrink=0.7, pad=0.02)
            cbar.set_label(lbl, fontsize=7)
            cbar.ax.tick_params(labelsize=6)

    plt.suptitle(
        'Python vs MATLAB Difference Analysis  (after phase-align + amplitude-match)\n'
        'Left: DM comparison  |  Right: LSQML vs ML comparison\n'
        'NRMSE = normalized RMSE (amplitude),  MAE/RMSE phase in degrees',
        fontsize=12, color='white', y=1.002)

    fig.patch.set_facecolor('#111')
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='#111')
    plt.close()
    print(f'[OK] Saved: {out_path.name}')


# ── visualization ─────────────────────────────────────────────────────────────

def _norm_phase(img):
    """Center phase to [-π, π] using median as reference."""
    ph = np.angle(img)
    ph = ph - np.median(ph)
    return (ph + np.pi) % (2 * np.pi) - np.pi


def visualize(d, py_dm_obj, py_dm_probe, py_ml_obj, py_ml_probe, out_path, num_iter):
    """
    5-column × 4-row image comparison.
    Columns: Ground Truth | MATLAB DM | MATLAB ML | Python DM | Python LSQML
    Rows:    Obj Amp | Obj Phase | Probe Amp | Probe Phase
    """
    INTERP = 'nearest'
    FS_TITLE = 10
    FS_ROW   = 11

    obj_true   = d['object_true']
    probe_true = d['probe_true']
    mat_obj_dm   = d['mat_obj_dm']
    mat_probe_dm = d['mat_probe_dm']
    mat_obj_ml   = d['mat_obj_ml']
    mat_probe_ml = d['mat_probe_ml']

    def crop(a, ref):
        r = min(a.shape[0], ref.shape[0])
        c = min(a.shape[1], ref.shape[1])
        return a[:r, :c]

    # ── build data grid  [row][col] ──────────────────────────────────────────
    # Row 0: Object amplitude
    obj_amps = [
        np.abs(obj_true),
        np.abs(crop(mat_obj_dm, obj_true)),
        np.abs(crop(mat_obj_ml, obj_true)),
        np.abs(crop(py_dm_obj,  obj_true)),
        np.abs(crop(py_ml_obj,  obj_true)),
    ]
    vmax_obj = np.percentile(np.abs(obj_true), 99)

    # Row 1: Object phase (normalized)
    obj_phases = [
        _norm_phase(obj_true),
        _norm_phase(crop(mat_obj_dm, obj_true)),
        _norm_phase(crop(mat_obj_ml, obj_true)),
        _norm_phase(crop(py_dm_obj,  obj_true)),
        _norm_phase(crop(py_ml_obj,  obj_true)),
    ]

    # Row 2: Probe amplitude
    probe_amps = [
        np.abs(probe_true),
        np.abs(mat_probe_dm),
        np.abs(mat_probe_ml),
        np.abs(py_dm_probe),
        np.abs(py_ml_probe),
    ]
    vmax_probe = np.percentile(np.abs(probe_true), 99)

    # Row 3: Probe phase (normalized)
    probe_phases = [
        _norm_phase(probe_true),
        _norm_phase(mat_probe_dm),
        _norm_phase(mat_probe_ml),
        _norm_phase(py_dm_probe),
        _norm_phase(py_ml_probe),
    ]

    # ── correlation labels ───────────────────────────────────────────────────
    obj_corrs = [
        1.0,
        d['mat_obj_dm_corr'],
        d['mat_obj_ml_corr'],
        corr(py_dm_obj, obj_true),
        corr(py_ml_obj, obj_true),
    ]
    probe_corrs = [
        1.0,
        d['mat_probe_dm_corr'],
        d['mat_probe_ml_corr'],
        corr(py_dm_probe, probe_true),
        corr(py_ml_probe, probe_true),
    ]
    col_titles = [
        'Ground Truth',
        f'MATLAB DM\n({num_iter[0]} iter)',
        f'MATLAB MLc\n({num_iter[1]} iter)',
        f'Python DM\n({num_iter[2]} iter)',
        f'Python LSQML\n({num_iter[3]} iter)',
    ]
    row_labels = ['Object\nAmplitude', 'Object\nPhase', 'Probe\nAmplitude', 'Probe\nPhase']

    # ── layout ───────────────────────────────────────────────────────────────
    fig, axes = plt.subplots(4, 5, figsize=(26, 20),
                             gridspec_kw={'hspace': 0.08, 'wspace': 0.04})

    # Column headers (top row)
    for ci, title in enumerate(col_titles):
        axes[0, ci].set_title(title, fontsize=FS_TITLE, fontweight='bold', pad=6)

    def _auto_scale(img_list, shared=False):
        """Return (vmin, vmax) list — shared uses global 99th percentile."""
        if shared:
            vmax = max(np.percentile(np.abs(img), 99) for img in img_list)
            return [(0, vmax)] * len(img_list)
        return [(0, np.percentile(np.abs(img), 99.5) or 1e-10) for img in img_list]

    def show(ax, img, cmap, vmin, vmax, corr_val=None):
        ax.imshow(img, cmap=cmap, interpolation=INTERP,
                  vmin=vmin, vmax=vmax, aspect='equal')
        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_linewidth(1.5)
        if corr_val is not None and not np.isnan(corr_val):
            color = 'lime' if corr_val >= 0.95 else ('yellow' if corr_val >= 0.8 else 'red')
            ax.text(0.03, 0.03, f'r={corr_val:.4f}',
                    transform=ax.transAxes, fontsize=8.5, color=color,
                    bbox=dict(facecolor='black', alpha=0.55, pad=1.5),
                    verticalalignment='bottom')

    # Per-column independent amplitude scaling (shape comparison, not absolute scale)
    scales_obj   = _auto_scale(obj_amps,   shared=False)
    scales_probe = _auto_scale(probe_amps, shared=False)

    # Draw all 4 rows
    for ci in range(5):
        cv  = None if ci == 0 else obj_corrs[ci]
        cv2 = None if ci == 0 else probe_corrs[ci]
        show(axes[0, ci], obj_amps[ci],   'gray',    *scales_obj[ci],   cv)
        show(axes[1, ci], obj_phases[ci], 'RdBu_r', -np.pi, np.pi,     cv)
        show(axes[2, ci], probe_amps[ci], 'gray',    *scales_probe[ci], cv2)
        show(axes[3, ci], probe_phases[ci], 'RdBu_r', -np.pi, np.pi,   cv2)

    # Row labels on the left
    for ri, label in enumerate(row_labels):
        axes[ri, 0].set_ylabel(label, fontsize=FS_ROW, labelpad=6, fontweight='bold')

    # Single colorbar for phase rows (shared scale ±π)
    for ri in [1, 3]:
        sm = plt.cm.ScalarMappable(cmap='RdBu_r', norm=plt.Normalize(-np.pi, np.pi))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=axes[ri, :], shrink=0.55, pad=0.01, aspect=18)
        cbar.set_label('Phase (rad)', fontsize=8)
        cbar.ax.tick_params(labelsize=7)
        cbar.set_ticks([-np.pi, -np.pi/2, 0, np.pi/2, np.pi])
        cbar.set_ticklabels(['-π', '-π/2', '0', 'π/2', 'π'])

    # Amplitude note
    fig.text(0.99, 0.5,
             'Amplitude: per-column normalized\n(shape comparison)',
             ha='right', va='center', fontsize=8, color='#aaa',
             rotation=90)

    plt.suptitle(
        'Ptychography Reconstruction Comparison  (identical input data)\n'
        'r = correlation vs ground truth  |  green ≥ 0.95  yellow ≥ 0.80  red < 0.80',
        fontsize=13, y=1.002)

    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='#111')
    plt.close()
    print(f'[OK] Saved: {out_path.name}')


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':

    mat_path = Path(__file__).parent.parent / 'matlab_ref' / 'matlab_proper_comparison.mat'

    if not mat_path.exists():
        print(f'[ERROR] Not found: {mat_path}')
        print('Run run_proper_comparison.m in MATLAB first, then retry.')
        sys.exit(1)

    print('=' * 70)
    print('Proper 1:1 Comparison: Python DM/LSQML vs MATLAB DM/ML')
    print('Both engines use IDENTICAL input data')
    print('=' * 70)

    gpu = check_gpu_available()
    set_use_gpu(gpu)
    print(f'GPU: {"ON" if gpu else "OFF (CPU mode)"}')

    # Load MATLAB data
    d = load_matlab_comparison(mat_path)

    fmag      = d['fmag']
    positions = d['positions']
    print(f'\nShared input data:')
    print(f'  fmag:       {fmag.shape}')
    print(f'  positions:  {positions.shape}')
    print(f'  probe_init: {d["probe_init"].shape}')
    print(f'  object_init:{d["object_init"].shape}')
    print(f'  object_true:{d["object_true"].shape}')

    # ── Parameter presets: GPU/CPU switch changes params to match MATLAB engine ──
    # GPU preset  → matches MATLAB GPU_engines_test.m  (use_gpu=true,  asize=[128,128])
    # CPU preset  → matches MATLAB CPU_engines_test.m  (use_gpu=false, asize=[192,192])
    if gpu:
        # GPU_engines_test.m DM: pfft_relaxation=0.1, probe_change_start=5
        p_dm = dict(
            probe_modes=1, object_modes=1,
            probe_change_start=5, object_change_start=1,
            probe_inertia=0.9,          # = 1 - probe_regularization(0.1)
            pfft_relaxation=0.1,        # GPU_engines_test.m: 0.1
            use_gpu=True
        )
        # GPU_engines_test.m MLc: pfft_relaxation=0.1, probe_change_start=1
        p_ml = dict(
            probe_modes=1, object_modes=1,
            probe_change_start=1, object_change_start=1,
            beta_LSQ=0.5, beta_probe=1.0, beta_object=1.0,
            pfft_relaxation=0.1,        # GPU_engines_test.m: 0.1
            delta_p=0.1,
            use_gpu=True
        )
        N_ITER_PY = 50   # GPU_engines_test.m: DM=50, MLc=50
        preset_label = 'GPU preset (matches MATLAB GPU_engines_test.m)'
    else:
        # CPU_engines_test.m (GPU engine, use_gpu=false): pfft_relaxation=0.05
        p_dm = dict(
            probe_modes=1, object_modes=1,
            probe_change_start=1, object_change_start=1,
            probe_inertia=0.9,
            pfft_relaxation=0.05,       # CPU_engines_test.m: 0.05
            use_gpu=False
        )
        p_ml = dict(
            probe_modes=1, object_modes=1,
            probe_change_start=1, object_change_start=1,
            beta_LSQ=0.5, beta_probe=1.0, beta_object=1.0,
            pfft_relaxation=0.05,       # CPU_engines_test.m: 0.05
            delta_p=0.1,
            use_gpu=False
        )
        N_ITER_PY = 100   # CPU: 더 많은 iter로 품질 확인
        preset_label = 'CPU preset (matches MATLAB CPU_engines_test.m)'

    print(f'Engine preset: {preset_label}')

    # ── Python DM (same inputs as MATLAB) ────────────────────────────────────
    print(f'\n[1/2] Running Python DM ({N_ITER_PY} iterations)...')
    ob_dm = [d['object_init'].copy()]
    pr_dm = d['probe_init'].copy()
    t0 = time.time()
    ob_dm_r, pr_dm_r, _ = DM(p_dm, ob_dm, pr_dm, fmag, positions, N_ITER_PY)
    py_dm_t = time.time() - t0

    # ── Python LSQML (same inputs as MATLAB) ─────────────────────────────────
    print(f'\n[2/2] Running Python LSQML ({N_ITER_PY} iterations)...')
    ob_ml = [d['object_init'].copy()]
    pr_ml = d['probe_init'].copy()
    t0 = time.time()
    ob_ml_r, pr_ml_r, _ = LSQML(p_ml, ob_ml, pr_ml, fmag, positions, N_ITER_PY)
    py_ml_t = time.time() - t0

    # ── Correlations vs ground truth ─────────────────────────────────────────
    obj_true   = d['object_true']
    probe_true = d['probe_true']

    py_dm_oc  = corr(ob_dm_r[0], obj_true)
    py_dm_pc  = corr(pr_dm_r,    probe_true)
    py_ml_oc  = corr(ob_ml_r[0], obj_true)
    py_ml_pc  = corr(pr_ml_r,    probe_true)

    # ── TRUE 1:1: Python reconstruction vs MATLAB reconstruction ─────────────
    sim_dm_obj   = corr(ob_dm_r[0], d['mat_obj_dm'])
    sim_dm_probe = corr(pr_dm_r,    d['mat_probe_dm'])
    sim_ml_obj   = corr(ob_ml_r[0], d['mat_obj_ml'])
    sim_ml_probe = corr(pr_ml_r,    d['mat_probe_ml'])

    # ── Print results ─────────────────────────────────────────────────────────
    print('\n' + '=' * 70)
    print('=== Section A: vs Ground Truth (SAME data, same metric) ===')
    print(f'{"Method":<18} {"Obj Corr":>10} {"Probe Corr":>12} {"Time":>8}')
    print('-' * 54)
    print(f'{"MATLAB DM":<18} {d["mat_obj_dm_corr"]:>10.6f} {d["mat_probe_dm_corr"]:>12.6f}  ({d["mat_elapsed_dm"]:.2f}s)')
    print(f'{"MATLAB ML":<18} {d["mat_obj_ml_corr"]:>10.6f} {d["mat_probe_ml_corr"]:>12.6f}  ({d["mat_elapsed_ml"]:.2f}s)')
    print('-' * 54)
    print(f'{"Python DM":<18} {py_dm_oc:>10.6f} {py_dm_pc:>12.6f}  ({py_dm_t:.2f}s)')
    print(f'{"Python LSQML":<18} {py_ml_oc:>10.6f} {py_ml_pc:>12.6f}  ({py_ml_t:.2f}s)')

    print('\n=== Section B: Python vs MATLAB Reconstruction (TRUE 1:1) ===')
    print(f'{"DM  Obj   sim":<18} {sim_dm_obj:.6f}  {pass_fail(sim_dm_obj)}')
    print(f'{"DM  Probe sim":<18} {sim_dm_probe:.6f}  {pass_fail(sim_dm_probe)}')
    print(f'{"ML  Obj   sim":<18} {sim_ml_obj:.6f}  {pass_fail(sim_ml_obj)}')
    print(f'{"ML  Probe sim":<18} {sim_ml_probe:.6f}  {pass_fail(sim_ml_probe)}')
    print('=' * 70)

    # ── Visualization ─────────────────────────────────────────────────────────
    num_iter = [50, 50, N_ITER_PY, N_ITER_PY]   # MATLAB DM(GPU), MATLAB MLc(GPU), Python DM, Python LSQML

    results_dir = Path(__file__).parent.parent / 'results'
    results_dir.mkdir(exist_ok=True)

    out = results_dir / 'proper_comparison.png'
    visualize(d, ob_dm_r[0], pr_dm_r, ob_ml_r[0], pr_ml_r, out, num_iter)

    out_diff = results_dir / 'diff_analysis.png'
    visualize_diff(d, ob_dm_r[0], pr_dm_r, ob_ml_r[0], pr_ml_r, out_diff, num_iter)

    print('\n[DONE]')
