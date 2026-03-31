"""
linesearch.py - Line search routine (does not use the gradient)

Python port of engines.ML.linesearch from cSAXS Ptychoshelves package

License:
Copyright (c) 2017 by Paul Scherrer Institute (http://www.psi.ch)
Python port: 2026

Original MATLAB code from cSAXS Ptychoshelves package
"""

import numpy as np
import warnings

# Handle both relative and absolute imports
try:
    from .brent import brent
except ImportError:
    from brent import brent


def linesearch(func, x0, f0, df0, dx, a, *varargin):
    """
    Line search routine (does not use the gradient)

    MATLAB equivalent: engines.ML.linesearch

    Args:
        func: callable objective function (or string name)
              Function may return (f, grad) or (f, grad, p), but only f is used
        x0: starting point of search (array)
        f0: objective function at x0
        df0: derivative of objective function along dx at x0
        dx: direction of linesearch (array)
        a: steplength input as guess output as taken
        *varargin: extra variables required by objective function

    Returns:
        x: final point of search
        f: objective function at final point
        a: final steplength
        flg: indicates how step was determined
             (0 for Armijo step, 1 for bracketing and refining a minimum)
    """

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
    a = float(a)
    f0 = float(f0)
    df0 = float(df0)

    # Check if descent direction
    if df0 >= 0:
        warnings.warn('linesearch called w/o descent direction')
        x = x0.copy()
        f = f0
        flg = 0
        return x, f, a, flg

    # First point
    a1 = 0.0
    f1 = f0

    # Try initial steplength
    f = call_func(x0 + a * dx)

    # Keep track of old values & hopefully bracket a minimum
    a2 = a
    f2 = f

    # Make sure initial step is feasible
    while np.isinf(f):
        a2 = a
        a = 0.25 * a
        f = call_func(x0 + a * dx)

    # Decide what to do next based on Armijo condition
    b = 0  # parameter in Armijo condition (>=0)

    # If f does not satisfy Armijo condition (steplength may be too
    # large) -> decrease steplength until Armijo is satisfied
    if f > f0 + a * b * df0:
        while f > f0 + a * b * df0:
            if np.isinf(f2) or (f <= f2):
                a2 = a
                f2 = f
            a = 0.25 * a  # decrease steplength
            f = call_func(x0 + a * dx)

    # Arrive here with a1=a0=0 and f<f1 (at least)
    tmp = 1
    while f2 <= f:  # try doubling a2
        a2 = 2 * a2
        f2 = call_func(x0 + a2 * dx)

        if f2 < f:
            a1 = a
            f1 = f
            a = a2
            f = f2
        if tmp == 5:
            break
        else:
            tmp = tmp + 1

    # Case where we should have a bracket, but f2 is infinite
    while np.isinf(f2):
        # disp('should have a bracket but f2 is infinite')
        u = a + 0.25 * (a2 - a)  # point between a and a2
        fu = call_func(x0 + u * dx)

        if fu < f:
            a1 = a
            f1 = f
            a = u
            f = fu
        else:
            a2 = u
            f2 = fu

    # Last steps
    if (f < f1) and (f < f2) and np.isfinite(f2):  # bracketing successful -> refine minimum
        a, f = brent(func, x0, dx, a1, a, a2, f1, f, f2, *varargin)
        flg = 1  # use conjugate gradient next loop
    else:  # bracketing unsuccessful -> stop
        flg = 0  # use steepest descent next loop

    x = x0 + a * dx
    return x, f, a, flg


# Module test
if __name__ == "__main__":
    print("Testing linesearch.py...")

    # Test with Rosenbrock function (returns f and grad)
    def rosenbrock_with_grad(x):
        """Rosenbrock function with gradient"""
        f = (1 - x[0])**2 + 100 * (x[1] - x[0]**2)**2
        grad = np.zeros(2)
        grad[0] = -2 * (1 - x[0]) - 400 * x[0] * (x[1] - x[0]**2)
        grad[1] = 200 * (x[1] - x[0]**2)
        return f, grad

    # Starting point
    x0 = np.array([0.0, 0.0])
    f0, grad = rosenbrock_with_grad(x0)

    # Direction: negative gradient (steepest descent)
    dx = -grad / np.linalg.norm(grad)
    df0 = np.dot(grad, dx)

    # Initial steplength guess
    a_guess = 0.01

    print(f"Starting point: x0={x0}")
    print(f"  f0={f0:.6f}")
    print(f"  gradient={grad}")
    print(f"  direction={dx}")
    print(f"  df0={df0:.6f}")

    # Run linesearch (func returns (f, grad) but linesearch only uses f)
    x, f, a, flg = linesearch(rosenbrock_with_grad, x0, f0, df0, dx, a_guess)

    print(f"\nLinesearch result:")
    print(f"  x={x}")
    print(f"  f={f:.6f}")
    print(f"  steplength a={a:.6f}")
    print(f"  flag={flg} ({'conjugate gradient' if flg==1 else 'steepest descent'})")

    # Check that we improved
    assert f < f0, f"Function should decrease: f0={f0}, f={f}"
    print(f"\nImprovement: {f0:.6f} -> {f:.6f} (Δf={f0-f:.6f})")

    print("\nTest passed!")
