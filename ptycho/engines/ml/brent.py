"""
brent.py - One-dimensional minimization by parabolic interpolation & golden section

Python port of engines.ML.brent from cSAXS Ptychoshelves package

License:
Copyright (c) 2017 by Paul Scherrer Institute (http://www.psi.ch)
Python port: 2026

Original MATLAB code from cSAXS Ptychoshelves package
"""

import numpy as np


def brent(func, x0, dx, a1, a, a2, f1, f, f2, *varargin):
    """
    One-dimensional minimization by parabolic interpolation & golden section
    (does not use the gradient)

    MATLAB equivalent: engines.ML.brent

    Args:
        func: callable objective function (can be string name or function object)
        x0: starting point of linesearch (array)
        dx: direction of linesearch (array)
        a1: lower bracket steplength (a1 < a < a2)
        a: middle bracket steplength
        a2: upper bracket steplength
        f1: objective function at steplength a1
        f: objective function at steplength a
        f2: objective function at steplength a2
        *varargin: extra variables required by objective function

    Returns:
        a: final steplength
        f: objective function at final steplength
    """

    gold = 0.3819660  # golden ratio
    itmax = 5
    tol = 0.5
    eps = np.finfo(float).eps

    # Helper to call func and extract only f value
    def call_func(x_eval):
        """Helper to call func and extract only f value"""
        if isinstance(func, str):
            result = eval(f"{func}(x_eval, *varargin)")
        else:
            result = func(x_eval, *varargin)

        # Extract only f value (ignore gradient and other return values)
        if isinstance(result, tuple):
            return result[0]  # Return only f
        else:
            return result

    # Ensure step scalars are Python floats so CuPy arrays (x0, dx) can be
    # used without triggering "Unsupported type numpy.ndarray" errors.
    a1 = float(a1)
    a  = float(a)
    a2 = float(a2)
    f1 = float(f1)
    f  = float(f)
    f2 = float(f2)

    # Check order of bracket
    if (a1 > a) or (a2 < a):
        raise ValueError('brent called with bracket in wrong order')

    # Initialize
    v = a
    fv = f  # middle point on step before last
    w = a
    fw = f  # middle point on last step
    e = 0   # distance moved on step before last

    # Iterations
    for it in range(itmax):
        am = 0.5 * (a1 + a2)
        tol1 = tol * abs(a) + eps
        tol2 = 2 * tol1

        # Test for convergence
        if abs(a - am) <= (tol2 - 0.5 * (a2 - a1)):
            return a, f

        # Choose next point
        if abs(e) > tol1:  # construct a trial parabolic fit
            r = (a - w) * (f - fv)
            q = (a - v) * (f - fw)
            p = (a - v) * q - (a - w) * r
            q = 2 * (q - r)
            if q > 0:
                p = -p
            q = abs(q)
            etemp = e
            e = d

            # Check acceptability of parabolic fit
            ok = not (abs(p) >= abs(0.5 * q * etemp) or p <= q * (a1 - a) or p >= q * (a2 - a))

            if ok:  # take parabolic step
                d = p / q
                u = a + d
                if (u - a1) < tol2 or (a2 - u) < tol2:
                    d = np.sign(am - a) * tol1
            else:  # take golden section step
                if a >= am:
                    e = a1 - a
                else:
                    e = a2 - a
                d = gold * e
        else:  # take golden section step
            if a >= am:
                e = a1 - a
            else:
                e = a2 - a
            d = gold * e

        # Arrive here with d computed either from
        # parabolic fit or else from golden section
        if abs(d) >= tol1:
            u = a + d
        else:
            u = a + np.sign(d) * tol1

        # One function evaluation per iteration
        fu = call_func(x0 + u * dx)

        if fu <= f:
            if u >= a:
                a1 = a
            else:
                a2 = a
            v = w
            fv = fw
            w = a
            fw = f
            a = u
            f = fu
        else:
            if u < a:
                a1 = u
            else:
                a2 = u
            if fu <= fw or w == a:
                v = w
                fv = fw
                w = u
                fw = fu
            elif fu <= fv or v == a or v == w:
                v = u
                fv = fu

    print('exceeded maximum number of iterations')
    return a, f


# Module test
if __name__ == "__main__":
    print("Testing brent.py...")

    # Test with a simple quadratic function
    def quadratic(x):
        """Simple quadratic: f(x) = (x - 3)^2 + 5"""
        return np.sum((x - 3)**2) + 5

    # Starting point and direction
    x0 = np.array([0.0])
    dx = np.array([1.0])

    # Initial bracket around minimum
    a1 = 0.0
    a = 2.0
    a2 = 6.0

    f1 = quadratic(x0 + a1 * dx)
    f = quadratic(x0 + a * dx)
    f2 = quadratic(x0 + a2 * dx)

    print(f"Initial bracket:")
    print(f"  a1={a1:.2f}, f1={f1:.4f}")
    print(f"  a={a:.2f}, f={f:.4f}")
    print(f"  a2={a2:.2f}, f2={f2:.4f}")

    # Run brent
    a_final, f_final = brent(quadratic, x0, dx, a1, a, a2, f1, f, f2)

    print(f"\nFinal result:")
    print(f"  a={a_final:.6f}, f={f_final:.6f}")
    print(f"  Expected: a=3.0, f=5.0")

    # Check convergence (brent uses tol=0.5, so tolerance should be reasonable)
    assert abs(a_final - 3.0) < 1.0, f"Expected a≈3.0, got {a_final}"
    assert abs(f_final - 5.0) < 1.0, f"Expected f≈5.0, got {f_final}"

    # More importantly, check that it's better than initial bracket
    assert f_final <= f, "Final value should be better than or equal to initial"
    assert f_final <= f1, "Final value should be better than or equal to bracket left"
    assert f_final <= f2, "Final value should be better than or equal to bracket right"

    print("\nTest passed!")
    print(f"Note: Brent algorithm uses tol=0.5, so result is approximate within tolerance.")
