"""imshift_linear_ax.py

Port of MATLAB imshift_linear_ax.m (line-by-line).

MATLAB:
    function img_out = imshift_linear_ax(img, shift, ax, method, extrap_val)
        if nargin < 4; method = 'linear'; end
        if nargin < 5; extrap_val = nan; end
        if all(shift == 0); img_out=img; return; end
        Npix = size(img);
        img = single(img);
        img = shiftdim(img, ax-1);  % move ax to front
        img_out = img;
        ind = {':',':',':'};
        ax_0 = 1+mod(ax,ndims(img));  % fixed axis (perpendicular to ax)
        if strcmpi(method, 'circ')
            for i = 1:Npix(ax_0)
                ind{ax_0} = i;
                img_out(ind{:}) = circshift(img(ind{:}), round(shift(i)), ax);
            end
        else
            for ii = 1:Npix(ax_0)
                ind{ax_0} = ii;
                img_out(ind{:}) = interp1(1:size(img,1), img(ind{:}), -shift(ii)+(1:size(img,1)), method, extrap_val);
            end
        end
        img_out = shiftdim(img_out, ax-1);  % move ax back (no-op when ax-1=0)
    end

Called as: imshift_linear_ax(invar, shift_Y, 1, 'nearest', 0)
  -> img shape: (Nlayers, Nangles), shift: (Nangles,)
  -> ax=1 (rows), method='nearest', extrap_val=0
  -> ax_0 = 1+mod(1,2) = 2  (the other axis = columns)
  -> shiftdim(img, 0) = no-op
  -> loop over ii=1:Nangles (columns):
       img_out[:, ii] = interp1(1:Nlayers, img[:,ii], -shift(ii)+(1:Nlayers))
       = interpolate col ii at positions (1:Nlayers) - shift(ii) (MATLAB 1-based)
       = Python: interpolate col at x_orig - shift[ii] (0-based: arange(Nlayers) - shift[ii])

For 2D img (Nlayers, Nangles) and ax=1:
  - shiftdim(img, 0) = no-op (already rows-first)
  - ax_0 in MATLAB = 2 (columns)
  - iterate over columns (Nangles)
  - each column: interp at positions -shift[ii] + (1:Nlayers) (1-based)
    = Python: interp at positions arange(Nlayers) - shift[ii]  (0-based)
"""

import numpy as np
from scipy.interpolate import interp1d


def imshift_linear_ax(img, shift, ax, method='linear', extrap_val=np.nan):
    """Shift each slice of img along axis `ax` by per-slice amount in `shift`.

    Parameters
    ----------
    img        : ndarray (Nlayers, Nangles) or similar
    shift      : scalar or array of shifts, one per slice perpendicular to ax
    ax         : int, MATLAB 1-based axis to shift along
    method     : str, interpolation method: 'linear', 'nearest', 'circ'
    extrap_val : float, fill value outside bounds (default nan)

    Returns
    -------
    img_out : ndarray (same shape as input, float32)
    """
    shift = np.asarray(shift, dtype=float)

    # if all(shift == 0); img_out=img; return; end
    if np.all(shift == 0):
        return img.copy()

    # img = single(img)
    img = np.asarray(img, dtype=np.float32)
    ax0 = ax - 1   # Python 0-based axis to shift along

    # For ax=1 (rows/axis0): iterate over columns (axis1)
    # ax_0 = 1 + mod(ax, ndims) = 1 + mod(1,2) = 2 in MATLAB (1-based)
    # In Python: the OTHER axis = 1 when ax0=0
    if ax0 == 0:
        # shift each column of shape (Nlayers, Nangles) along rows
        Nlayers, Nangles = img.shape[0], img.shape[1] if img.ndim > 1 else 1
        out = img.copy()
        x_orig = np.arange(Nlayers, dtype=float)

        # broadcast scalar shift
        if shift.ndim == 0 or shift.size == 1:
            shift_arr = np.full(Nangles, float(shift))
        else:
            shift_arr = shift.ravel()

        for ii in range(Nangles):
            s = float(shift_arr[ii])
            if img.ndim == 2:
                col = img[:, ii]
            elif img.ndim == 3:
                col = img[:, ii, :]   # (Nlayers, depth) - should not happen for ax=1 2D case
            else:
                col = img[:, ii]

            if method.lower() == 'circ':
                # circshift(col, round(s), ax=1) in MATLAB -> np.roll along axis 0
                if img.ndim == 2:
                    out[:, ii] = np.roll(col, int(round(s)))
                else:
                    out[:, ii, :] = np.roll(col, int(round(s)), axis=0)
            else:
                # interp1(1:N, col, -shift+(1:N), method, extrap_val)
                # MATLAB 1-based: interp at -s + [1..N] = [1-s, 2-s, ..., N-s]
                # Python 0-based: interp at [0-s, 1-s, ..., (N-1)-s] = x_orig - s
                xi = x_orig - s
                kind = 'nearest' if method.lower() == 'nearest' else method.lower()
                if img.ndim == 2:
                    f = interp1d(x_orig, col.astype(float), kind=kind,
                                 bounds_error=False, fill_value=extrap_val)
                    out[:, ii] = f(xi).astype(np.float32)
                elif img.ndim == 3:
                    # apply along axis 0 for each depth slice
                    for k in range(col.shape[1]):
                        f = interp1d(x_orig, col[:, k].astype(float), kind=kind,
                                     bounds_error=False, fill_value=extrap_val)
                        out[:, ii, k] = f(xi).astype(np.float32)
        return out

    elif ax0 == 1:
        # shift each row along columns (axis 1)
        Nlayers, Ncols = img.shape[0], img.shape[1]
        out = img.copy()
        x_orig = np.arange(Ncols, dtype=float)

        if shift.ndim == 0 or shift.size == 1:
            shift_arr = np.full(Nlayers, float(shift))
        else:
            shift_arr = shift.ravel()

        for ii in range(Nlayers):
            s = float(shift_arr[ii])
            row = img[ii, :]
            if method.lower() == 'circ':
                out[ii, :] = np.roll(row, int(round(s)))
            else:
                xi = x_orig - s
                kind = 'nearest' if method.lower() == 'nearest' else method.lower()
                f = interp1d(x_orig, row.astype(float), kind=kind,
                             bounds_error=False, fill_value=extrap_val)
                out[ii, :] = f(xi).astype(np.float32)
        return out

    else:
        raise NotImplementedError(f'imshift_linear_ax: ax={ax} not implemented')
