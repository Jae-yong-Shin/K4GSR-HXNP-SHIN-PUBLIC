"""
mean2.py - Average along first two dimensions (ported from cSAXS +math/mean2.m)

MEAN2 average along first two dimensions

Inputs:
  x: N-dimensional array
Returns:
  y: (N-2)-dimensional array (averaged over first 2 dims)

License:
Copyright (c) 2017 by Paul Scherrer Institute (http://www.psi.ch)
Author: CXS group, PSI
Python port: 2026

Original MATLAB code from cSAXS software package
"""

import numpy as np

try:
    import cupy as cp
    def get_xp(arr):
        return cp.get_array_module(arr)
except ImportError:
    cp = None
    def get_xp(arr):
        return np


def mean2(x):
    """
    Average along first two dimensions

    MATLAB equivalent: mean(mean(x, 1), 2)

    Args:
        x: numpy or cupy array of any dimension

    Returns:
        Array with first two dimensions averaged
    """
    xp = get_xp(x)
    # MATLAB: mean(mean(x, 1), 2)
    # dim=1 means first dimension (0 in Python)
    # dim=2 means second dimension (1 in Python)
    y = xp.mean(xp.mean(x, axis=0), axis=0)

    return y


# Module test
if __name__ == "__main__":
    print("Testing mean2.py...")

    # Test 1: 2D array
    x1 = np.array([[1, 2, 3],
                   [4, 5, 6]])
    result1 = mean2(x1)
    expected1 = 3.5  # (1+2+3+4+5+6)/6
    print(f"Test 1 (2D): {result1} == {expected1} : {np.isclose(result1, expected1)}")

    # Test 2: 3D array
    x2 = np.ones((2, 3, 4))
    result2 = mean2(x2)
    print(f"Test 2 (3D): shape {result2.shape} == (4,) : {result2.shape == (4,)}")
    print(f"         all ones: {np.allclose(result2, 1.0)}")

    # Test 3: 4D array
    x3 = np.arange(2*3*4*5).reshape(2, 3, 4, 5)
    result3 = mean2(x3)
    print(f"Test 3 (4D): shape {result3.shape} == (4, 5) : {result3.shape == (4, 5)}")

    print("Tests complete!")
