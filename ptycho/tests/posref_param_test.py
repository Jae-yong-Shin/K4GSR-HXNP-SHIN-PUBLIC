"""
posref_param_test.py
====================
Position refinement parameter sweep test.
SyntheticPtycho로 데이터를 생성하고 LSQML posref를 테스트합니다.

== 여기서만 파라미터를 수정하세요 ==
"""

# ─────────────────────────────────────────────────────────────────────────────
# PARAMETERS  (여기서만 수정)
# ─────────────────────────────────────────────────────────────────────────────

# 테스트할 object source (MATLAB .mat 파일, object_true 키 사용)
# ds1=MonaLisa, ds3=CameraMan, ds5=USAF, ds6=Mandrill
OBJECT_MAT = 'matlab_posref_comparison_ds5.mat'   # root 기준 경로

# ── 실험 물리 파라미터 (template_artificial_data.m 기준) ─────────────────────
# pixel_size = λ·z / (asize·det_pixel_size) ≈ 104 nm/px
# scan_step 1.5 μm ≈ 14.4 px
PHYSICS = dict(
    energy_keV       = 6.2,     # X-선 에너지 (keV)
    z_m              = 5.0,     # 시료-검출기 거리 (m)
    det_pixel_size_m = 75e-6,   # 검출기 픽셀 크기 (m)
)

# 각 configuration: dict 형태
# asize       : 프로브/회절패턴 크기 (px) - 클수록 고해상도, 느림
# overlap     : 스캔 overlap 비율 (0.0~0.95) - scan_step_um 없을 때 사용
# scan_step_um: 물리 단위 step (μm) - 있으면 overlap 무시
# scan_lx_um  : 스캔 영역 가로 (μm) - None이면 object 크기로 결정
# scan_ly_um  : 스캔 영역 세로 (μm)
# N_photons   : 패턴당 최대 광자수 - 클수록 SNR↑, 느림
CONFIGS = [
    # MATLAB baseline: 1.5μm step, 10μm×10μm scan, noise-free
    dict(label='MATLAB-like (1.5μm step, inf ph)',
         asize=128, scan_step_um=1.5, scan_lx_um=10.0, scan_ly_um=10.0, N_photons=9999),
    # 동일 조건, 저소음
    dict(label='low noise (1.5μm step, 1k ph)',
         asize=128, scan_step_um=1.5, scan_lx_um=10.0, scan_ly_um=10.0, N_photons=1000),
    # 더 조밀한 스텝 (1.0 μm)
    dict(label='denser (1.0μm step, 1k ph)',
         asize=128, scan_step_um=1.0, scan_lx_um=10.0, scan_ly_um=10.0, N_photons=1000),
    # 낮은 SNR
    dict(label='low SNR (1.5μm step, 100ph)',
         asize=128, scan_step_um=1.5, scan_lx_um=10.0, scan_ly_um=10.0, N_photons=100),
]

# LSQML 알고리즘 파라미터
N_ITER      = 50    # reconstruction iterations
NOISE_SIGMA = 3.0   # position noise sigma (px)
RNG_SEED    = 42    # random seed (positions noise + diffraction)
# probe: PtychoShelves의 probe_PSI.mat 자동 로드 (asize에 맞게 crop)

# 출력 이미지 파일명
OUTPUT_PNG = 'posref_param_test.png'

# ─────────────────────────────────────────────────────────────────────────────
# (이 아래는 수정 불필요)
# ─────────────────────────────────────────────────────────────────────────────

import numpy as np
import time
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from synth_ptycho import SyntheticPtycho, load_object_true
from engines.gpu.gpu_wrapper import set_use_gpu, check_gpu_available
from engines.gpu.LSQML import LSQML


def corr(a1, a2):
    r = min(a1.shape[0], a2.shape[0])
    c = min(a1.shape[1], a2.shape[1])
    a1 = a1[:r, :c].ravel().astype(np.complex128)
    a2 = a2[:r, :c].ravel().astype(np.complex128)
    a1 -= a1.mean(); a2 -= a2.mean()
    denom = np.sqrt(np.sum(np.abs(a1)**2) * np.sum(np.abs(a2)**2))
    if denom < 1e-30: return 0.0
    return float(np.abs(np.dot(a1.conj(), a2)) / denom)


def run_lsqml(ob_init, probe, fmag, positions, use_posref, gpu):
    p = dict(
        probe_modes=1, object_modes=1,
        probe_change_start=1, object_change_start=1,
        beta_LSQ=0.5, beta_probe=1.0, beta_object=1.0,
        pfft_relaxation=0.1, delta_p=0.1,
        use_gpu=gpu,
        probe_position_search=5 if use_posref else 0,
    )
    t0 = time.time()
    if use_posref:
        ob_r, pr_r, _, pos_r = LSQML(p, [ob_init.copy()], probe.copy(),
                                       fmag, positions.copy(), N_ITER,
                                       return_positions=True)
    else:
        ob_r, pr_r, _ = LSQML(p, [ob_init.copy()], probe.copy(),
                                fmag, positions.copy(), N_ITER)
        pos_r = positions.copy()
    return ob_r[0], pr_r, pos_r, time.time() - t0


if __name__ == '__main__':
    root = Path(__file__).parent.parent

    gpu = check_gpu_available()
    set_use_gpu(gpu)
    print(f'GPU: {"ON" if gpu else "OFF"}')

    obj_true = load_object_true(root / OBJECT_MAT)
    print(f'Object: {obj_true.shape}  from {OBJECT_MAT}')

    results = []

    for cfg in CONFIGS:
        label     = cfg['label']
        asize     = cfg['asize']
        N_photons = cfg['N_photons']
        overlap   = cfg.get('overlap', 0.75)

        print('\n' + '=' * 65)
        print(f'{label}')
        print('=' * 65)

        gen = SyntheticPtycho(
            object        = obj_true,
            asize         = asize,
            overlap       = overlap,
            scan_step_um  = cfg.get('scan_step_um', None),
            scan_lx_um    = cfg.get('scan_lx_um', None),
            scan_ly_um    = cfg.get('scan_ly_um', None),
            N_photons     = N_photons,
            **PHYSICS,
            # probe: probe_PSI.mat automatically loaded from PtychoShelves
        )

        # 물리 단위 정보 출력
        if gen.pixel_size_nm > 0:
            print(f'  pixel_size={gen.pixel_size_nm:.1f} nm/px  '
                  f'(E={PHYSICS["energy_keV"]} keV, '
                  f'z={PHYSICS["z_m"]} m, '
                  f'dp={PHYSICS["det_pixel_size_m"]*1e6:.0f} μm)')

        data = gen.generate(noise_sigma=NOISE_SIGMA, rng_seed=RNG_SEED)

        pos_err_init = float(np.mean(
            np.sqrt(np.sum((data.positions_noisy - data.positions_clean)**2, axis=1))
        ))
        step_str = (f'{data.avg_step:.1f}px ({data.avg_step_um:.2f}μm)'
                    if data.avg_step_um > 0 else f'{data.avg_step:.1f}px')
        print(f'  Npos={data.Npos}  step={step_str}  '
              f'actual_ovlp={data.overlap:.1%}  N_ph={N_photons}')
        print(f'  fmag:{data.fmag.shape}  max={data.fmag.max():.2f}')
        print(f'  pos noise: mean={pos_err_init:.3f}px')

        # no-posref
        print(f'  [1/2] NO posref...')
        ob_nr, pr_nr, _, t_nr = run_lsqml(
            data.object_init, data.probe, data.fmag,
            data.positions_noisy, False, gpu
        )
        c_nr = corr(ob_nr, data.object_true)
        print(f'       Obj={c_nr:.4f}  ({t_nr:.1f}s)')

        # with posref
        print(f'  [2/2] WITH posref...')
        ob_pr, pr_pr, pos_rec, t_pr = run_lsqml(
            data.object_init, data.probe, data.fmag,
            data.positions_noisy, True, gpu
        )
        c_pr = corr(ob_pr, data.object_true)
        pos_err_after = float(np.mean(
            np.sqrt(np.sum((pos_rec - data.positions_clean)**2, axis=1))
        ))
        recovery = 100 * (pos_err_init - pos_err_after) / pos_err_init
        print(f'       Obj={c_pr:.4f}  ({t_pr:.1f}s)  '
              f'pos {pos_err_init:.2f}→{pos_err_after:.2f}px ({recovery:+.1f}%)')

        results.append({
            'label':          label,
            'asize':          asize,
            'overlap':        data.overlap,
            'N_photons':      N_photons,
            'Npos':           data.Npos,
            'avg_step':       data.avg_step,
            'avg_step_um':    data.avg_step_um,
            'pixel_size_nm':  data.pixel_size_nm,
            'c_nr':           c_nr,
            'c_pr':           c_pr,
            'pos_err_init':   pos_err_init,
            'pos_err_after':  pos_err_after,
            'recovery':       recovery,
            'ob_nr':          ob_nr,
            'ob_pr':          ob_pr,
            'obj_true':       data.object_true,
        })

    # ── Visualization ─────────────────────────────────────────────────────────
    BG = '#111'
    n  = len(results)
    fig, axes = plt.subplots(3, n, figsize=(n * 4.2, 11),
                              gridspec_kw={'hspace': 0.05, 'wspace': 0.04},
                              facecolor=BG)
    if n == 1:
        axes = axes[:, np.newaxis]

    vmax = np.percentile(np.abs(results[0]['obj_true']), 99)

    def show(ax, img, cv=None, border=None, border_w=2.5):
        ax.imshow(np.abs(img), cmap='gray', vmin=0, vmax=vmax, aspect='equal',
                  interpolation='nearest')
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_edgecolor(border or '#444')
            sp.set_linewidth(border_w if border else 0.8)
        if cv is not None:
            c = 'lime' if cv >= 0.70 else ('yellow' if cv >= 0.55 else 'red')
            ax.text(0.03, 0.03, f'r={cv:.3f}', transform=ax.transAxes, fontsize=8,
                    color=c, va='bottom',
                    bbox=dict(facecolor='black', alpha=0.6, pad=1.5))

    for ci, r in enumerate(results):
        # Row 0: ground truth
        show(axes[0, ci], r['obj_true'], border=None)
        if r['pixel_size_nm'] > 0:
            step_str = f'{r["avg_step"]:.1f}px ({r["avg_step_um"]:.2f}μm)'
            px_str   = f'  px={r["pixel_size_nm"]:.0f}nm'
        else:
            step_str = f'{r["avg_step"]:.1f}px'
            px_str   = ''
        axes[0, ci].set_title(
            f'{r["label"]}\nasize={r["asize"]}  ovlp={r["overlap"]:.0%}\n'
            f'step={step_str}{px_str}\n'
            f'N_ph={r["N_photons"]}  Npos={r["Npos"]}',
            color='white', fontsize=7.0, pad=4
        )

        # Row 1: no posref
        show(axes[1, ci], r['ob_nr'], cv=r['c_nr'], border='#ff9944')

        # Row 2: with posref
        show(axes[2, ci], r['ob_pr'], cv=r['c_pr'], border='#44ff88')
        rec_c = 'lime' if r['recovery'] > 50 else ('yellow' if r['recovery'] > 20 else 'red')
        axes[2, ci].text(0.03, 0.97,
            f'pos {r["pos_err_init"]:.1f}→{r["pos_err_after"]:.1f}px\n{r["recovery"]:+.0f}%',
            transform=axes[2, ci].transAxes, fontsize=7,
            color=rec_c, va='top',
            bbox=dict(facecolor='black', alpha=0.6, pad=1.5))

    row_labels = ['Ground Truth', 'No posref (orange)', 'With posref (green)']
    for ri, lab in enumerate(row_labels):
        axes[ri, 0].set_ylabel(lab, fontsize=9, color='white', labelpad=6, fontweight='bold')

    plt.suptitle(
        f'Posref Param Test  [{Path(OBJECT_MAT).stem}]\n'
        f'LSQML {N_ITER} iter  noise σ={NOISE_SIGMA}px  probe=probe_PSI.mat',
        fontsize=11, y=1.01, color='white'
    )

    results_dir = Path(__file__).parent.parent / 'results'
    results_dir.mkdir(exist_ok=True)
    out = results_dir / OUTPUT_PNG
    plt.savefig(out, dpi=130, bbox_inches='tight', facecolor=BG)
    plt.close()
    print(f'\n[OK] Saved: {out}')

    # Summary
    print('\n' + '=' * 78)
    print(f'{"Config":<40} {"Npos":>5} {"NoRef":>6} {"Posref":>6} {"PosRec":>8}')
    print('-' * 78)
    for r in results:
        print(f'{r["label"][:40]:<40} {r["Npos"]:>5} '
              f'{r["c_nr"]:>6.3f} {r["c_pr"]:>6.3f} {r["recovery"]:>+7.1f}%')
    print('=' * 78)
