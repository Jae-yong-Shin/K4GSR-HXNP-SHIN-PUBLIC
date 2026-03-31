"""test_subpixel_alignment.py

Numerical tests for find_shift_fast_2D (ported from MATLAB).

Tests:
  1. test_subpixel_full_range     -- sub-pixel shift, full_range, <0.1px
  2. test_no_spectral_filter      -- sigma=0 (no high-pass filter)
  3. test_limited_range_method    -- limited_range method
  4. test_3d_stack                -- 3D input (N slices), shape (N,2)
  5. test_precomputed_fft         -- apply_fft=False path
  6. test_zero_shift              -- identical images -> shift~[0,0]
  7. test_align_tomo_smoke        -- align_tomo_Xcorr shape test
  8. test_align_tomo_recovers_shifts -- shift recovery correlation

Run: python test_subpixel_alignment.py
  or: pytest test_subpixel_alignment.py -v
"""

import sys, os
import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from utils.find_shift_fast_2D import find_shift_fast_2D


def make_blob(Ny=128, Nx=128, sigma_blob=10.0, rng=None):
    if rng is None:
        rng = np.random.default_rng(42)
    y0, x0 = np.mgrid[0:Ny, 0:Nx]
    blob = np.exp(-((y0 - Ny//2)**2 + (x0 - Nx//2)**2) / sigma_blob**2)
    blob = blob + 0.01 * rng.standard_normal((Ny, Nx))
    return blob.astype(complex)


def apply_known_shift(blob, shift_x, shift_y):
    from scipy.ndimage import shift as ndshift
    shifted = ndshift(blob.real, [-shift_y, -shift_x], mode='wrap')
    return shifted.astype(complex)

def test_subpixel_full_range():
    blob = make_blob(128, 128)
    true_x, true_y = 3.5, -2.3
    shifted = apply_known_shift(blob, true_x, true_y)
    result = find_shift_fast_2D(blob, shifted, sigma=0.01, apply_fft=True)
    assert result.shape == (2,)
    err_x = abs(result[0] - true_x)
    err_y = abs(result[1] - true_y)
    assert err_x < 0.1
    assert err_y < 0.1


def test_no_spectral_filter():
    blob = make_blob(128, 128)
    shifted = apply_known_shift(blob, 2.0, 1.0)
    result = find_shift_fast_2D(blob, shifted, sigma=0, apply_fft=True)
    err = float(np.max(np.abs(result - [2.0, 1.0])))
    assert err < 0.5


def test_limited_range_method():
    blob = make_blob(128, 128)
    shifted = apply_known_shift(blob, 5.0, -3.0)
    result = find_shift_fast_2D(blob, shifted, sigma=0.01, apply_fft=True,
                                method='limited_range')
    err = float(np.max(np.abs(result - [5.0, -3.0])))
    assert err < 0.2


def test_3d_stack():
    N = 4
    base = make_blob(128, 128)
    true_sh = [(2.5, -1.5), (-3.0, 0.5), (1.0, 4.0), (0.0, 0.0)]
    o1 = np.stack([base]*N, axis=2)
    o2 = np.stack([apply_known_shift(base, tx, ty) for tx,ty in true_sh], axis=2)
    result = find_shift_fast_2D(o1, o2, sigma=0.01, apply_fft=True)
    assert result.shape == (N, 2)
    for k, (tx, ty) in enumerate(true_sh):
        assert abs(result[k, 0] - tx) < 0.2
        assert abs(result[k, 1] - ty) < 0.2


def test_precomputed_fft():
    from scipy.signal.windows import tukey
    blob = make_blob(128, 128)
    true_x, true_y = -4.0, 2.7
    shifted = apply_known_shift(blob, true_x, true_y)
    Ny, Nx = blob.shape
    win = tukey(Ny, 0.5).reshape(-1,1) * tukey(Nx, 0.5).reshape(1,-1)
    o1f = np.fft.fft2(blob * win)
    o2f = np.fft.fft2(shifted * win)
    result = find_shift_fast_2D(o1f, o2f, sigma=0.01, apply_fft=False)
    err = float(np.max(np.abs(result - [true_x, true_y])))
    assert err < 0.1


def test_zero_shift():
    blob = make_blob(64, 64)
    result = find_shift_fast_2D(blob, blob.copy(), sigma=0.01, apply_fft=True)
    assert float(np.max(np.abs(result))) < 0.5


def test_align_tomo_smoke():
    from tomo.align_tomo_Xcorr import align_tomo_Xcorr
    Ny, Nx, Na = 32, 32, 5
    angles = np.linspace(0, np.pi, Na, endpoint=False)
    y0, x0 = np.mgrid[0:Ny, 0:Nx]
    base = np.exp(-((y0-16)**2+(x0-16)**2)/20.0)
    obj = np.stack([base*np.exp(1j*a) for a in angles], axis=2)
    ts, var, var_al = align_tomo_Xcorr(obj, angles, params={'max_iter': 1})
    assert ts.shape == (Na, 2)
    assert var.shape == (Ny, Nx, Na)
    assert var_al.shape == (Ny, Nx, Na)
    assert not np.any(np.isnan(ts))


def test_align_tomo_recovers_shifts():
    from tomo.align_tomo_Xcorr import align_tomo_Xcorr
    from scipy.ndimage import shift as ndshift
    Ny, Nx, Na = 64, 64, 6
    angles = np.linspace(0, np.pi, Na, endpoint=False)
    y0, x0 = np.mgrid[0:Ny, 0:Nx]
    base = (np.exp(-((y0-32)**2+(x0-32)**2)/50.0) +
            0.3*np.exp(-((y0-20)**2+(x0-44)**2)/10.0)).astype(complex)
    true_shifts = np.array([[-2,0],[-1,0],[0,0],[1,0],[2,0],[3,0]], dtype=float)
    obj = np.stack(
        [ndshift(base.real,[true_shifts[i,1],true_shifts[i,0]],mode='wrap')
         *np.exp(1j*angles[i]) for i in range(Na)],
        axis=2
    )
    ts, _, _ = align_tomo_Xcorr(obj.astype(complex), angles,
                                params={'max_iter':2,'filter_data':0.05})
    ts_c = ts - ts.mean(axis=0)
    true_c = true_shifts - true_shifts.mean(axis=0)
    corr = float(np.corrcoef(ts_c[:,0], true_c[:,0])[0,1])
    assert abs(corr) > 0.5


if __name__ == '__main__':
    import traceback, sys
    tests = [
        ('test_subpixel_full_range',         test_subpixel_full_range),
        ('test_no_spectral_filter',          test_no_spectral_filter),
        ('test_limited_range_method',        test_limited_range_method),
        ('test_3d_stack',                   test_3d_stack),
        ('test_precomputed_fft',             test_precomputed_fft),
        ('test_zero_shift',                 test_zero_shift),
        ('test_align_tomo_smoke',            test_align_tomo_smoke),
        ('test_align_tomo_recovers_shifts',  test_align_tomo_recovers_shifts),
    ]
    passed, failed = 0, 0
    for name, fn in tests:
        try:
            fn()
            print(f'  PASS  {name}')
            passed += 1
        except Exception as e:
            print(f'  FAIL  {name}: {e}')
            traceback.print_exc()
            failed += 1
    print()
    print(f'Results: {passed} passed, {failed} failed')
    if failed: sys.exit(1)
