"""
pshift.py - Periodic shift (ported from cSAXS +utils/pshift.m)

AOUT = pshift(AIN, CTRPOS)

Shift array AIN periodically so that CTRPOS is placed at (1,1).
Supports both integer and sub-pixel shifts.

License:
Copyright (c) 2017 by Paul Scherrer Institute (http://www.psi.ch)
Author: CXS group, PSI
Python port: 2026

Original MATLAB code from cSAXS software package
"""

import numpy as np


def pshift(ain, ctrpos, precision=1e-2):
    """
    Periodic shift with sub-pixel accuracy

    Args:
        ain: 2D input array
        ctrpos: [row, col] position to shift to (1,1) - 1-based MATLAB indexing!
        precision: threshold for sub-pixel shift (default 1e-2)

    Returns:
        Shifted array

    MATLAB indexing note:
        ctrpos in MATLAB is 1-based, so ctrpos=[1,1] means first element
        In Python, we convert: ctrpos - 1
    """
    # MATLAB: sz = size(ain)
    sz = np.array(ain.shape)

    # MATLAB: if length(sz) ~= 2
    if len(sz) != 2:
        raise ValueError("Unsupported array size (must be 2D)")

    # Handle logical arrays
    # MATLAB: ain_is_logical = islogical(ain)
    ain_is_logical = ain.dtype == bool
    if ain_is_logical:
        ain = ain.astype(float)

    # MATLAB: aout = zeros(sz, class(ain))
    aout = np.zeros(sz, dtype=ain.dtype)

    # MATLAB: ctr = mod(reshape(ctrpos, [1 2]) - 1, sz)
    # Note: ctrpos is 1-based in MATLAB, so subtract 1
    ctrpos = np.array(ctrpos).reshape(2)
    ctr = np.mod(ctrpos - 1, sz)  # Convert to 0-based and wrap

    # MATLAB: ctr_int = round(ctr); ctr_dec = ctr - ctr_int
    ctr_int = np.round(ctr).astype(int)
    ctr_dec = ctr - ctr_int

    # MATLAB: use_dec = true; if max(max(abs(ctr_dec))) < precision
    use_dec = True
    if np.max(np.abs(ctr_dec)) < precision:
        use_dec = False

    # MATLAB: c2 = sz - ctr_int
    c2 = sz - ctr_int

    # Integer shift using array slicing
    # MATLAB (1-based):
    #   aout(1:c2(1), 1:c2(2)) = ain(ctr_int(1)+1:end, ctr_int(2)+1:end)
    # Python (0-based):
    #   aout[0:c2[0], 0:c2[1]] = ain[ctr_int[0]:, ctr_int[1]:]

    aout[0:c2[0], 0:c2[1]] = ain[ctr_int[0]:, ctr_int[1]:]
    aout[0:c2[0], c2[1]:] = ain[ctr_int[0]:, 0:ctr_int[1]]
    aout[c2[0]:, 0:c2[1]] = ain[0:ctr_int[0], ctr_int[1]:]
    aout[c2[0]:, c2[1]:] = ain[0:ctr_int[0], 0:ctr_int[1]]

    # Sub-pixel shift using FFT
    if use_dec:
        # MATLAB: faout = fftn(aout)
        faout = np.fft.fftn(aout)

        # MATLAB: [q1,q2] = ndgrid(-ceil(sz(1)/2):floor(sz(1)/2 - 1), ...)
        q1, q2 = np.mgrid[
            -int(np.ceil(sz[0]/2)):int(np.floor(sz[0]/2)),
            -int(np.ceil(sz[1]/2)):int(np.floor(sz[1]/2))
        ]

        # MATLAB: q1 = fftshift(q1); q2 = fftshift(q2)
        q1 = np.fft.fftshift(q1)
        q2 = np.fft.fftshift(q2)

        # MATLAB: aout = ifftn(exp(2i * pi * (...)) .* faout)
        phase = 2j * np.pi * (q2 * ctr_dec[1] / sz[1] + q1 * ctr_dec[0] / sz[0])
        aout = np.fft.ifftn(np.exp(phase) * faout)

    # Restore logical type if needed
    if ain_is_logical:
        aout = aout.astype(bool)

    return aout


# Module test
if __name__ == "__main__":
    print("Testing pshift.py...")

    # Test 1: Integer shift
    x1 = np.arange(16).reshape(4, 4)
    print("Original:")
    print(x1)

    # Shift so (2,2) goes to (1,1) - MATLAB 1-based!
    result1 = pshift(x1, [2, 2])
    print("\nShifted (ctrpos=[2,2]):")
    print(result1.real.astype(int))
    # Expected: element at (2,2) which is value 5 should now be at (1,1) -> index [0,0]
    print(f"  Value at [0,0]: {result1[0,0].real:.0f} (expected: 5)")

    # Test 2: Sub-pixel shift
    x2 = np.zeros((8, 8))
    x2[4, 4] = 1.0  # Peak at center
    result2 = pshift(x2, [4.5, 4.5])  # Shift by 0.5 pixels
    print(f"\nTest 2 (sub-pixel): max at {np.unravel_index(np.argmax(np.abs(result2)), result2.shape)}")

    # Test 3: Complex array
    x3 = np.arange(9, dtype=complex).reshape(3, 3) + 1j * np.arange(9).reshape(3, 3)
    result3 = pshift(x3, [2, 2])
    print(f"\nTest 3 (complex): result[0,0] = {result3[0,0]} (expected: 4+4j)")

    print("\nTests complete!")
