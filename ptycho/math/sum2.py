"""
sum2.py - Sum along first 2 dims (ported from cSAXS +math/sum2.m)

SUM2 sum along first two dimensions

Inputs:
  x: N-dimensional array
Returns:
  Sum along first 2 dims (N-2 dimensional array)

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


def sum2(x):
    """
    Sum along first two dimensions

    MATLAB equivalent: sum(sum(x, 1), 2)

    Args:
        x: numpy or cupy array

    Returns:
        Sum over first 2 dimensions
    """
    xp = get_xp(x)
    # MATLAB: sum(sum(x, 1), 2)
    # sum(x, 1) -> sum along dim 1 (MATLAB) = axis 0 (Python)
    # sum(..., 2) -> sum along dim 2 (MATLAB) = axis 0 (Python, again, after first reduction)
    return xp.sum(xp.sum(x, axis=0), axis=0)


# Module test
if __name__ == "__main__":
    print("Testing sum2.py...")

    # Test 1: 2D array
    x1 = np.array([[1, 2],
                   [3, 4]])
    result1 = sum2(x1)
    expected1 = 10  # 1+2+3+4
    print(f"Test 1 (2D): {result1} == {expected1} : {result1 == expected1}")

    # Test 2: 3D array
    x2 = np.ones((4, 5, 3))
    result2 = sum2(x2)
    expected2 = np.array([20, 20, 20])  # Each: 4*5 = 20
    print(f"Test 2 (3D): shape {result2.shape} == (3,) : {result2.shape == (3,)}")
    print(f"         all 20s: {np.allclose(result2, expected2)}")

    # Test 3: 4D array
    x3 = np.ones((2, 3, 4, 5))
    result3 = sum2(x3)
    expected3 = np.ones((4, 5)) * 6  # Each: 2*3 = 6
    print(f"Test 3 (4D): shape {result3.shape} == (4, 5) : {result3.shape == (4, 5)}")
    print(f"         all 6s: {np.allclose(result3, expected3)}")

    # Test 4: Complex array
    x4 = np.array([[1+1j, 2+2j],
                   [3+3j, 4+4j]])
    result4 = sum2(x4)
    expected4 = 10+10j
    print(f"Test 4 (complex): {result4} == {expected4} : {result4 == expected4}")

    print("\nTests complete!")
