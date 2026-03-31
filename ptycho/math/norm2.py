"""
norm2.py - Normalized Euclidean norm (ported from cSAXS +math/norm2.m)

NORM2 1/N * Euclidean norm along first 2 dims

Inputs:
  x: N-dimensional array
Returns:
  Norm value (N-2 dimensional array)

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

# Try relative import first, fall back to absolute for testing
try:
    from . import mean2
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    import mean2


def norm2(x):
    """
    Normalized 2-norm along first two dimensions

    MATLAB equivalent: sqrt(mean2(abs(x).^2))

    Args:
        x: numpy or cupy array (can be complex)

    Returns:
        Norm value (averaged over first 2 dims)
    """
    xp = get_xp(x)
    # MATLAB: sqrt(mean2(abs(x).^2))
    return xp.sqrt(mean2.mean2(xp.abs(x)**2))


# Module test
if __name__ == "__main__":
    print("Testing norm2.py...")

    # Test 1: 2D real array
    x1 = np.array([[3, 4],
                   [0, 0]])
    result1 = norm2(x1)
    expected1 = np.sqrt((9 + 16) / 4)  # sqrt((3^2 + 4^2) / 4) = sqrt(25/4) = 2.5
    print(f"Test 1 (2D real): {result1:.4f} == {expected1:.4f} : {np.isclose(result1, expected1)}")

    # Test 2: 2D complex array
    x2 = np.array([[1+1j, 0],
                   [0, 1-1j]])
    result2 = norm2(x2)
    # |1+1j|^2 = 2, |1-1j|^2 = 2, mean = (2+2)/4 = 1, sqrt(1) = 1
    expected2 = 1.0
    print(f"Test 2 (2D complex): {result2:.4f} == {expected2:.4f} : {np.isclose(result2, expected2)}")

    # Test 3: 3D array
    x3 = np.ones((4, 5, 3), dtype=complex)
    result3 = norm2(x3)
    expected3 = np.ones(3)  # Each element = sqrt(mean(1)) = 1
    print(f"Test 3 (3D): shape {result3.shape} == (3,) : {result3.shape == (3,)}")
    print(f"         all ones: {np.allclose(result3, expected3)}")

    # Test 4: Compare with standard norm
    x4 = np.random.randn(10, 10)
    result4 = norm2(x4)
    expected4 = np.linalg.norm(x4) / np.sqrt(x4.size)
    print(f"Test 4 (random): {result4:.6f} ~= {expected4:.6f} : {np.isclose(result4, expected4)}")

    print("Tests complete!")
