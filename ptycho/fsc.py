"""
Fourier Shell Correlation (FSC) for 2D ptychography resolution estimation.

Standard ptychography FSC method:
  1. Split scan positions into two independent subsets (even/odd indices)
  2. Reconstruct each subset independently
  3. Compute FSC on the PHASE images (not amplitude)

FSC formula:
  FSC(q) = Re[ sum_shell( F1(q) * conj(F2(q)) ) ]
           / sqrt( sum_shell[|F1|^2] * sum_shell[|F2|^2] )

Resolution is defined where FSC crosses the threshold (0.5 or 1/2-bit).

Reference: van Heel & Schatz, J. Struct. Biol. 151, 250 (2005)
"""
import numpy as np


def _center_crop_pair(img1, img2, margin):
    """Center-crop two images to the same size with margin trimming."""
    h1, w1 = img1.shape
    h2, w2 = img2.shape
    ch = min(h1, h2) - 2 * margin
    cw = min(w1, w2) - 2 * margin
    if ch <= 0 or cw <= 0:
        raise ValueError("Images too small for given margin (ch=%d, cw=%d)" % (ch, cw))

    r1 = img1[h1 // 2 - ch // 2:h1 // 2 + ch // 2,
              w1 // 2 - cw // 2:w1 // 2 + cw // 2]
    r2 = img2[h2 // 2 - ch // 2:h2 // 2 + ch // 2,
              w2 // 2 - cw // 2:w2 // 2 + cw // 2]
    return r1, r2


def _phase_align(recon, truth):
    """Remove global phase offset between two complex images."""
    phase_off = np.angle(np.sum(recon * np.conj(truth)))
    return recon * np.exp(-1j * phase_off)


def half_bit_threshold(n_pixels_per_shell):
    """
    Compute the 1/2-bit information threshold for FSC.

    Formula (van Heel & Schatz 2005):
      T_1/2bit = (0.2071 + 1.9102 / sqrt(n)) / (1.2071 + 0.9102 / sqrt(n))

    Parameters
    ----------
    n_pixels_per_shell : array-like
        Number of pixels in each radial shell.

    Returns
    -------
    threshold : ndarray
        1/2-bit threshold values for each shell.
    """
    n = np.asarray(n_pixels_per_shell, dtype=np.float64)
    sqrt_n = np.sqrt(np.maximum(n, 1.0))
    return (0.2071 + 1.9102 / sqrt_n) / (1.2071 + 0.9102 / sqrt_n)


def _compute_fsc_curve(img1_real, img2_real, pixel_size_nm):
    """
    Core FSC computation on two real-valued 2D images (same size).

    Parameters
    ----------
    img1_real, img2_real : ndarray (real, 2D, same shape)
    pixel_size_nm : float

    Returns
    -------
    freq, fsc_vals, n_pix, hbt : arrays
    """
    ny, nx = img1_real.shape

    F1 = np.fft.fftshift(np.fft.fft2(img1_real))
    F2 = np.fft.fftshift(np.fft.fft2(img2_real))

    cy, cx = ny // 2, nx // 2
    yy, xx = np.mgrid[0:ny, 0:nx]
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)

    r_max = min(cy, cx)
    n_shells = r_max

    fsc_vals = np.zeros(n_shells, dtype=np.float64)
    n_pix = np.zeros(n_shells, dtype=np.float64)
    freq = np.zeros(n_shells, dtype=np.float64)

    for i in range(n_shells):
        mask = (r >= i) & (r < i + 1)
        n_in_shell = np.sum(mask)
        n_pix[i] = n_in_shell

        if n_in_shell == 0:
            fsc_vals[i] = 0.0
            continue

        f1_shell = F1[mask]
        f2_shell = F2[mask]

        numerator = np.real(np.sum(f1_shell * np.conj(f2_shell)))
        denom1 = np.sum(np.abs(f1_shell) ** 2)
        denom2 = np.sum(np.abs(f2_shell) ** 2)
        denom = np.sqrt(denom1 * denom2)

        if denom > 0:
            fsc_vals[i] = numerator / denom
        else:
            fsc_vals[i] = 0.0

        freq[i] = (i + 0.5) / (max(ny, nx) * pixel_size_nm)

    hbt = half_bit_threshold(n_pix)
    return freq, fsc_vals, n_pix, hbt


def fsc_phase(ob1, ob2, pixel_size_nm=1.0, margin=None):
    """
    Compute FSC on the PHASE of two complex reconstructions.

    This is the standard ptychography FSC method: compare the phase images
    of two independent reconstructions (e.g., from split data sets).

    Parameters
    ----------
    ob1, ob2 : ndarray (complex, 2D)
        Two independent reconstructions.
    pixel_size_nm : float
        Pixel size in nm.
    margin : int or None
        Edge pixels to crop. Default: min(shape) // 8.

    Returns
    -------
    result : dict
        Same keys as fsc_2d, with resolution values from phase FSC.
    """
    if margin is None:
        margin = min(ob1.shape[0], ob1.shape[1], ob2.shape[0], ob2.shape[1]) // 8

    c1, c2 = _center_crop_pair(ob1, ob2, margin)
    c1 = _phase_align(c1, c2)

    ph1 = np.angle(c1)
    ph2 = np.angle(c2)

    freq, fsc_vals, n_pix, hbt = _compute_fsc_curve(ph1, ph2, pixel_size_nm)

    resolution_05 = _find_crossing(freq, fsc_vals, 0.5)
    resolution_hb = _find_crossing_curve(freq, fsc_vals, hbt)

    return {
        'freq_nm_inv': freq,
        'fsc': fsc_vals,
        'half_bit': hbt,
        'n_pixels_per_shell': n_pix,
        'resolution_nm': resolution_05,
        'resolution_half_bit_nm': resolution_hb,
        'nyquist_nm': 2.0 * pixel_size_nm,
    }


def split_positions(Npos, method='even_odd'):
    """
    Split scan position indices into two independent subsets.

    Parameters
    ----------
    Npos : int
        Total number of scan positions.
    method : str
        'even_odd' : indices 0,2,4,... vs 1,3,5,...
        'random'   : random 50/50 split (seed=42 for reproducibility)

    Returns
    -------
    idx1, idx2 : ndarray of int
        Two index arrays (non-overlapping, union = all positions).
    """
    if method == 'even_odd':
        idx1 = np.arange(0, Npos, 2)
        idx2 = np.arange(1, Npos, 2)
    elif method == 'random':
        rng = np.random.default_rng(42)
        perm = rng.permutation(Npos)
        half = Npos // 2
        idx1 = np.sort(perm[:half])
        idx2 = np.sort(perm[half:])
    else:
        raise ValueError("Unknown split method: %s" % method)
    return idx1, idx2


def fsc_2d(img1, img2, pixel_size_nm=1.0, margin=None):
    """
    Compute FSC between two 2D complex images (amplitude+phase).

    NOTE: For ptychography, prefer fsc_phase() on phase images.
    This function operates on complex images directly.

    Parameters
    ----------
    img1, img2 : ndarray (complex, 2D)
    pixel_size_nm : float
    margin : int or None

    Returns
    -------
    result : dict with FSC curve and resolution estimates.
    """
    if margin is None:
        margin = min(img1.shape[0], img1.shape[1], img2.shape[0], img2.shape[1]) // 8

    c1, c2 = _center_crop_pair(img1, img2, margin)
    c1 = _phase_align(c1, c2)

    ny, nx = c1.shape
    F1 = np.fft.fftshift(np.fft.fft2(c1))
    F2 = np.fft.fftshift(np.fft.fft2(c2))

    cy, cx = ny // 2, nx // 2
    yy, xx = np.mgrid[0:ny, 0:nx]
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    r_max = min(cy, cx)
    n_shells = r_max

    fsc_vals = np.zeros(n_shells, dtype=np.float64)
    n_pix = np.zeros(n_shells, dtype=np.float64)
    freq = np.zeros(n_shells, dtype=np.float64)

    for i in range(n_shells):
        mask = (r >= i) & (r < i + 1)
        n_in_shell = np.sum(mask)
        n_pix[i] = n_in_shell
        if n_in_shell == 0:
            continue
        f1_shell = F1[mask]
        f2_shell = F2[mask]
        numerator = np.real(np.sum(f1_shell * np.conj(f2_shell)))
        denom = np.sqrt(np.sum(np.abs(f1_shell) ** 2) * np.sum(np.abs(f2_shell) ** 2))
        if denom > 0:
            fsc_vals[i] = numerator / denom
        freq[i] = (i + 0.5) / (max(ny, nx) * pixel_size_nm)

    hbt = half_bit_threshold(n_pix)
    resolution_05 = _find_crossing(freq, fsc_vals, 0.5)
    resolution_hb = _find_crossing_curve(freq, fsc_vals, hbt)

    return {
        'freq_nm_inv': freq,
        'fsc': fsc_vals,
        'half_bit': hbt,
        'n_pixels_per_shell': n_pix,
        'resolution_nm': resolution_05,
        'resolution_half_bit_nm': resolution_hb,
        'nyquist_nm': 2.0 * pixel_size_nm,
    }


def _find_crossing(freq, fsc, threshold_val):
    """Find spatial frequency where FSC drops below a fixed threshold."""
    for i in range(1, len(fsc)):
        if fsc[i] < threshold_val and freq[i] > 0:
            if i > 0 and fsc[i - 1] >= threshold_val:
                f0, f1 = freq[i - 1], freq[i]
                v0, v1 = fsc[i - 1], fsc[i]
                if abs(v0 - v1) > 1e-12:
                    f_cross = f0 + (threshold_val - v0) / (v1 - v0) * (f1 - f0)
                else:
                    f_cross = f1
                if f_cross > 0:
                    return 1.0 / f_cross
            elif freq[i] > 0:
                return 1.0 / freq[i]
    return None


def _find_crossing_curve(freq, fsc, threshold_curve):
    """Find spatial frequency where FSC drops below a variable threshold curve."""
    for i in range(1, len(fsc)):
        if fsc[i] < threshold_curve[i] and freq[i] > 0:
            if i > 0 and fsc[i - 1] >= threshold_curve[i - 1]:
                f0, f1 = freq[i - 1], freq[i]
                v0 = fsc[i - 1] - threshold_curve[i - 1]
                v1 = fsc[i] - threshold_curve[i]
                if abs(v0 - v1) > 1e-12:
                    f_cross = f0 + (0.0 - v0) / (v1 - v0) * (f1 - f0)
                else:
                    f_cross = f1
                if f_cross > 0:
                    return 1.0 / f_cross
            elif freq[i] > 0:
                return 1.0 / freq[i]
    return None


def plot_fsc(fsc_result, title='', ax=None):
    """
    Plot FSC curve with 0.5 and 1/2-bit threshold lines.

    Parameters
    ----------
    fsc_result : dict
        Output of fsc_phase() or fsc_2d().
    title : str
    ax : matplotlib Axes or None

    Returns
    -------
    ax : matplotlib Axes
    """
    import matplotlib.pyplot as plt

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=(6, 4))

    freq = fsc_result['freq_nm_inv']
    fsc = fsc_result['fsc']
    hbt = fsc_result['half_bit']
    res_05 = fsc_result['resolution_nm']
    res_hb = fsc_result['resolution_half_bit_nm']
    nyquist = fsc_result['nyquist_nm']

    idx = slice(1, None)

    ax.plot(freq[idx], fsc[idx], 'b-', linewidth=1.5, label='FSC')
    ax.axhline(y=0.5, color='r', linestyle='--', linewidth=1.0, alpha=0.7, label='0.5 threshold')
    ax.plot(freq[idx], hbt[idx], 'g--', linewidth=1.0, alpha=0.7, label='1/2-bit threshold')

    if res_05 is not None:
        freq_05 = 1.0 / res_05
        ax.axvline(x=freq_05, color='r', linestyle=':', linewidth=1.0, alpha=0.5)
        ax.annotate('%.1f nm' % res_05,
                     xy=(freq_05, 0.5), xytext=(freq_05 + freq[-1] * 0.05, 0.55),
                     fontsize=8, color='r', fontweight='bold',
                     arrowprops=dict(arrowstyle='->', color='r', lw=0.8))

    if res_hb is not None:
        freq_hb = 1.0 / res_hb
        ax.axvline(x=freq_hb, color='g', linestyle=':', linewidth=1.0, alpha=0.5)
        y_at_cross = 0.3
        for i in range(1, len(freq)):
            if freq[i] >= freq_hb:
                y_at_cross = hbt[i]
                break
        ax.annotate('%.1f nm' % res_hb,
                     xy=(freq_hb, y_at_cross), xytext=(freq_hb + freq[-1] * 0.05, y_at_cross - 0.08),
                     fontsize=8, color='g', fontweight='bold',
                     arrowprops=dict(arrowstyle='->', color='g', lw=0.8))

    ax.set_xlabel('Spatial frequency (1/nm)', fontsize=9)
    ax.set_ylabel('FSC', fontsize=9)
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlim(left=0)
    ax.legend(fontsize=7, loc='upper right')
    ax.grid(True, alpha=0.3)

    parts = []
    if title:
        parts.append(title)
    res_str = ''
    if res_05 is not None:
        res_str += '0.5: %.1f nm' % res_05
    if res_hb is not None:
        if res_str:
            res_str += ', '
        res_str += '1/2-bit: %.1f nm' % res_hb
    if res_str:
        parts.append(res_str)
    parts.append('Nyquist: %.1f nm' % nyquist)
    ax.set_title('\n'.join(parts), fontsize=9, fontweight='bold')

    return ax
