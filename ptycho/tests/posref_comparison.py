"""
Position Refinement Comparison (Multi-Dataset)
================================================
Tests whether probe_position_search recovers reconstruction quality
when scan positions are deliberately corrupted with noise (σ=3px).

Tests datasets: 1=MonaLisa, 3=CameraMan, 5=USAF

Input:  matlab_posref_comparison_ds{N}.mat (one per dataset)
Output: posref_comparison_ds{N}.png   - 5-column visual comparison
        posref_positions_ds{N}.png    - position error scatter
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
from engines.gpu.LSQML import LSQML


DATASETS = [
    (1, 'MonaLisa'),
    (3, 'CameraMan'),
    (5, 'USAF'),
]


# ── data loading ──────────────────────────────────────────────────────────────

def load_posref_mat(mat_path):
    with h5py.File(mat_path, 'r') as f:

        def cplx(key):
            v = f[key][()]
            if v.dtype.names and 'real' in v.dtype.names:
                return (v['real'] + 1j * v['imag']).T.astype(np.complex64)
            return v.T.astype(np.complex64)

        def real_arr(key):
            return f[key][()].T.astype(np.float32)

        def scalar(key):
            return float(f[key][()].flat[0])

        return {
            'fmag':               real_arr('fmag_input'),
            'positions_clean':    real_arr('positions_clean'),
            'positions_noisy':    real_arr('positions_noisy'),
            'probe_init':         cplx('probe_init'),
            'object_init':        cplx('object_init'),
            'object_true':        cplx('object_true'),
            'probe_true':         cplx('probe_true'),
            # MATLAB baselines
            'mat_obj_noref':      cplx('object_noref'),
            'mat_probe_noref':    cplx('probe_noref'),
            'mat_obj_noref_corr': scalar('obj_noref_corr'),
            'mat_prb_noref_corr': scalar('probe_noref_corr'),
            'mat_elapsed_noref':  scalar('elapsed_noref'),
            'mat_obj_posref':     cplx('object_posref'),
            'mat_probe_posref':   cplx('probe_posref'),
            'mat_obj_posref_corr':scalar('obj_posref_corr'),
            'mat_prb_posref_corr':scalar('probe_posref_corr'),
            'mat_elapsed_posref': scalar('elapsed_posref'),
            'mat_pos_err_before': scalar('pos_error_before'),
            'mat_pos_err_after':  scalar('pos_error_after'),
            'positions_recovered':real_arr('positions_recovered'),
        }


# ── utilities ──────────────────────────────────────────────────────────────────

def corr(a1, a2):
    r = min(a1.shape[0], a2.shape[0])
    c = min(a1.shape[1], a2.shape[1])
    a1 = a1[:r, :c].ravel().astype(np.complex128)
    a2 = a2[:r, :c].ravel().astype(np.complex128)
    a1 -= a1.mean(); a2 -= a2.mean()
    denom = np.sqrt(np.sum(np.abs(a1)**2) * np.sum(np.abs(a2)**2))
    if denom < 1e-30: return 0.0
    return float(np.abs(np.dot(a1.conj(), a2)) / denom)


# ── visualization ──────────────────────────────────────────────────────────────

def visualize(d, py_noref_obj, py_noref_probe, py_posref_obj, py_posref_probe,
              py_pos_posref, out_path, n_iter, ds_name):

    BG   = '#111111'
    FS_T = 9
    FS_R = 8
    INTERP = 'nearest'

    obj_true   = d['object_true']
    probe_true = d['probe_true']

    cols = [
        ('Ground Truth',        obj_true,           probe_true),
        (f'MATLAB MLc\n(no posref, noisy)\n{n_iter} iter',
         d['mat_obj_noref'],  d['mat_probe_noref']),
        (f'MATLAB MLc\n(posref start=5, noisy)\n{n_iter} iter',
         d['mat_obj_posref'], d['mat_probe_posref']),
        (f'Python LSQML\n(no posref, noisy)\n{n_iter} iter',
         py_noref_obj,        py_noref_probe),
        (f'Python LSQML\n(posref start=5, noisy)\n{n_iter} iter',
         py_posref_obj,       py_posref_probe),
    ]

    obj_corrs = [None] + [corr(c[1], obj_true) for c in cols[1:]]
    probe_corrs = [None] + [corr(c[2], probe_true) for c in cols[1:]]

    fig, axes = plt.subplots(4, 5, figsize=(26, 20),
                             gridspec_kw={'hspace': 0.08, 'wspace': 0.04},
                             facecolor=BG)

    for ax in axes.ravel():
        ax.set_facecolor(BG)
        for sp in ax.spines.values():
            sp.set_edgecolor('#444')

    def show(ax, img, cmap, vmin, vmax, cv=None, border=None):
        ax.imshow(img, cmap=cmap, interpolation=INTERP,
                  vmin=vmin, vmax=vmax, aspect='equal')
        ax.set_xticks([]); ax.set_yticks([])
        if border:
            for sp in ax.spines.values():
                sp.set_edgecolor(border); sp.set_linewidth(2.5)
        if cv is not None and not np.isnan(cv):
            color = 'lime' if cv >= 0.95 else ('yellow' if cv >= 0.80 else 'red')
            ax.text(0.03, 0.03, f'r={cv:.4f}',
                    transform=ax.transAxes, fontsize=8.5, color=color,
                    bbox=dict(facecolor='black', alpha=0.6, pad=1.5),
                    verticalalignment='bottom')

    col_colors = ['white', '#ff9944', '#44ff88', '#ff9944', '#44ff88']
    for ci, (title, _, _) in enumerate(cols):
        axes[0, ci].set_title(title, fontsize=FS_T, fontweight='bold', pad=6,
                               color=col_colors[ci])

    for ci, (_, obj, probe) in enumerate(cols):
        vmax_obj   = np.percentile(np.abs(obj_true),   99)
        vmax_probe = np.percentile(np.abs(probe_true), 99)
        oc = obj_corrs[ci]
        pc = probe_corrs[ci]
        border = '#44ff88' if ci in (2, 4) else ('#ff9944' if ci in (1, 3) else None)

        show(axes[0, ci], np.abs(obj),    'gray',   0, vmax_obj,   oc, border)
        show(axes[1, ci], np.angle(obj),  'RdBu_r', -np.pi, np.pi, oc, border)
        show(axes[2, ci], np.abs(probe),  'gray',   0, vmax_probe, pc, border)
        show(axes[3, ci], np.angle(probe),'RdBu_r', -np.pi, np.pi, pc, border)

    row_labels = ['Object\nAmplitude', 'Object\nPhase',
                  'Probe\nAmplitude',  'Probe\nPhase']
    for ri, label in enumerate(row_labels):
        axes[ri, 0].set_ylabel(label, fontsize=FS_R, labelpad=6,
                                fontweight='bold', color='white')

    for ri in [1, 3]:
        sm = plt.cm.ScalarMappable(cmap='RdBu_r', norm=plt.Normalize(-np.pi, np.pi))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=axes[ri, :], shrink=0.5, pad=0.01, aspect=18)
        cbar.set_label('Phase (rad)', fontsize=7, color='#aaa')
        cbar.ax.tick_params(labelsize=6, colors='#aaa')
        cbar.set_ticks([-np.pi, 0, np.pi])
        cbar.set_ticklabels(['-π', '0', 'π'])

    pos_err_before = np.mean(np.sqrt(np.sum((d['positions_noisy'] - d['positions_clean'])**2, axis=1)))
    pos_err_py = np.mean(np.sqrt(np.sum((py_pos_posref - d['positions_clean'])**2, axis=1)))
    rows_txt = [
        f'MATLAB MLc no-posref : Obj={d["mat_obj_noref_corr"]:.4f}  Probe={d["mat_prb_noref_corr"]:.4f}  ({d["mat_elapsed_noref"]:.1f}s)',
        f'MATLAB MLc posref    : Obj={d["mat_obj_posref_corr"]:.4f}  Probe={d["mat_prb_posref_corr"]:.4f}  ({d["mat_elapsed_posref"]:.1f}s)  pos {d["mat_pos_err_before"]:.2f}→{d["mat_pos_err_after"]:.2f}px',
        f'Python LSQML no-posref : Obj={corr(py_noref_obj, obj_true):.4f}  Probe={corr(py_noref_probe, probe_true):.4f}',
        f'Python LSQML posref    : Obj={corr(py_posref_obj, obj_true):.4f}  Probe={corr(py_posref_probe, probe_true):.4f}  pos {pos_err_before:.2f}→{pos_err_py:.2f}px',
    ]
    fig.text(0.5, -0.01, '\n'.join(rows_txt),
             ha='center', va='top', fontsize=8, color='#ccc',
             fontfamily='monospace',
             bbox=dict(facecolor='#222', alpha=0.7, pad=4))

    plt.suptitle(
        f'Position Refinement Test  [{ds_name}]  (noisy positions σ=3px, seed=42)\n'
        'orange=no posref  green=with posref (start iter 5)  r=corr vs GT',
        fontsize=12, y=1.003, color='white')

    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor=BG)
    plt.close()
    print(f'  [OK] Saved: {out_path.name}')


def visualize_positions(d, py_pos_posref, out_path, ds_name):
    pos_clean   = d['positions_clean']
    pos_noisy   = d['positions_noisy']
    pos_mat_rec = d['positions_recovered']

    fig, axes = plt.subplots(1, 3, figsize=(18, 6), facecolor='#111')
    titles = ['Clean vs Noisy (input)', 'Clean vs MATLAB recovered', 'Clean vs Python recovered']
    pos_sets = [(pos_clean, pos_noisy), (pos_clean, pos_mat_rec), (pos_clean, py_pos_posref)]

    for ax, title, (ref, est) in zip(axes, titles, pos_sets):
        ax.set_facecolor('#111')
        ax.scatter(ref[:, 1], ref[:, 0], c='cyan',   s=20, alpha=0.7, label='clean', zorder=3)
        ax.scatter(est[:, 1], est[:, 0], c='orange', s=20, alpha=0.7, label='estimated', zorder=2)
        for i in range(len(ref)):
            ax.annotate('', xy=(est[i, 1], est[i, 0]),
                        xytext=(ref[i, 1], ref[i, 0]),
                        arrowprops=dict(arrowstyle='->', color='#888', lw=0.6))
        err = np.mean(np.sqrt(np.sum((ref - est)**2, axis=1)))
        ax.set_title(f'{title}\nmean error = {err:.3f} px', fontsize=9, color='white')
        ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
        ax.tick_params(colors='#aaa')
        for sp in ax.spines.values(): sp.set_edgecolor('#444')
        ax.set_xlabel('col (px)', color='#aaa', fontsize=8)
        ax.set_ylabel('row (px)', color='#aaa', fontsize=8)

    plt.suptitle(f'Scan Position Recovery  [{ds_name}]', fontsize=12, color='white')
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='#111')
    plt.close()
    print(f'  [OK] Saved: {out_path.name}')


# ── per-dataset runner ─────────────────────────────────────────────────────────

def run_dataset(ds_num, ds_name, root, gpu):
    mat_path = root / f'matlab_posref_comparison_ds{ds_num}.mat'
    if not mat_path.exists():
        print(f'  [SKIP] Not found: {mat_path.name}  (run MATLAB first)')
        return False

    print(f'\nLoading: {mat_path.name}')
    d = load_posref_mat(mat_path)
    fmag      = d['fmag']
    pos_noisy = d['positions_noisy']
    pos_clean = d['positions_clean']

    # Clamp noisy positions to valid object range
    obj_h, obj_w = d['object_init'].shape[:2]
    prb_h, prb_w = d['probe_init'].shape[:2]
    pos_noisy = pos_noisy.copy()
    pos_noisy[:, 0] = np.clip(pos_noisy[:, 0], 0, obj_h - prb_h)
    pos_noisy[:, 1] = np.clip(pos_noisy[:, 1], 0, obj_w - prb_w)

    pos_err_init = np.mean(np.sqrt(np.sum((pos_noisy - pos_clean)**2, axis=1)))
    print(f'  fmag:{fmag.shape}  probe:{d["probe_init"].shape}  object:{d["object_init"].shape}')
    print(f'  pos noise (clamped): {pos_err_init:.3f}px')

    p_lsqml = dict(
        probe_modes=1, object_modes=1,
        probe_change_start=1, object_change_start=1,
        beta_LSQ=0.5, beta_probe=1.0, beta_object=1.0,
        pfft_relaxation=0.1, delta_p=0.1,
        use_gpu=gpu,
    )
    N_ITER = 50

    # Run 1: NO posref
    print(f'  [1/2] LSQML {N_ITER} iter, NO posref...')
    t0 = time.time()
    ob_noref_r, pr_noref_r, _ = LSQML(
        {**p_lsqml, 'probe_position_search': 0},
        [d['object_init'].copy()], d['probe_init'].copy(), fmag, pos_noisy.copy(), N_ITER
    )
    t_noref = time.time() - t0
    c_noref_obj   = corr(ob_noref_r[0], d['object_true'])
    c_noref_probe = corr(pr_noref_r,    d['probe_true'])
    print(f'       Obj={c_noref_obj:.4f}  Probe={c_noref_probe:.4f}  ({t_noref:.1f}s)')

    # Run 2: WITH posref
    print(f'  [2/2] LSQML {N_ITER} iter, WITH posref (start=5)...')
    t0 = time.time()
    ob_posref_r, pr_posref_r, _, py_pos_posref = LSQML(
        {**p_lsqml, 'probe_position_search': 5},
        [d['object_init'].copy()], d['probe_init'].copy(), fmag, pos_noisy.copy(), N_ITER,
        return_positions=True
    )
    t_posref = time.time() - t0
    c_posref_obj   = corr(ob_posref_r[0], d['object_true'])
    c_posref_probe = corr(pr_posref_r,    d['probe_true'])
    pos_err_after = np.mean(np.sqrt(np.sum((py_pos_posref - pos_clean)**2, axis=1)))
    recovery = 100 * (pos_err_init - pos_err_after) / pos_err_init
    print(f'       Obj={c_posref_obj:.4f}  Probe={c_posref_probe:.4f}  ({t_posref:.1f}s)')
    print(f'       pos: {pos_err_init:.3f}→{pos_err_after:.3f}px  ({recovery:+.1f}%)')

    # Summary
    print(f'\n  {"Method":<26} {"Obj":>7} {"Probe":>7} {"Time":>6}')
    print(f'  {"-"*50}')
    print(f'  {"MATLAB MLc no-posref":<26} {d["mat_obj_noref_corr"]:>7.4f} {d["mat_prb_noref_corr"]:>7.4f} {d["mat_elapsed_noref"]:>5.1f}s')
    print(f'  {"MATLAB MLc posref":<26} {d["mat_obj_posref_corr"]:>7.4f} {d["mat_prb_posref_corr"]:>7.4f} {d["mat_elapsed_posref"]:>5.1f}s  pos {d["mat_pos_err_before"]:.2f}→{d["mat_pos_err_after"]:.2f}px')
    print(f'  {"Python LSQML no-posref":<26} {c_noref_obj:>7.4f} {c_noref_probe:>7.4f} {t_noref:>5.1f}s')
    print(f'  {"Python LSQML posref":<26} {c_posref_obj:>7.4f} {c_posref_probe:>7.4f} {t_posref:>5.1f}s  pos {pos_err_init:.2f}→{pos_err_after:.2f}px')

    # Plots
    out_dir = Path(__file__).parent.parent / 'results'
    out_dir.mkdir(exist_ok=True)
    visualize(d, ob_noref_r[0], pr_noref_r, ob_posref_r[0], pr_posref_r,
              py_pos_posref, out_dir / f'posref_comparison_ds{ds_num}.png', N_ITER, ds_name)
    visualize_positions(d, py_pos_posref,
                        out_dir / f'posref_positions_ds{ds_num}.png', ds_name)
    return True


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    root = Path(__file__).parent.parent / 'matlab_ref'

    gpu = check_gpu_available()
    set_use_gpu(gpu)
    print(f'GPU: {"ON" if gpu else "OFF (CPU mode)"}')

    for ds_num, ds_name in DATASETS:
        print('\n' + '=' * 70)
        print(f'Dataset {ds_num}: {ds_name}')
        print('=' * 70)
        run_dataset(ds_num, ds_name, root, gpu)

    print('\n[ALL DONE]')
