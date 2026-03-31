"""
cgmin1.py - Conjugate-gradient optimization routine

Python port of engines.ML.cgmin1 from cSAXS Ptychoshelves package

License:
Copyright (c) 2017 by Paul Scherrer Institute (http://www.psi.ch)
Python port: 2026

Original MATLAB code from cSAXS Ptychoshelves package

NOTE: linesearch subroutines do not use the gradient
"""

import numpy as np
import sys
from pathlib import Path

# Import verbose
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'utils'))
from verbose import verbose

# Handle both relative and absolute imports
try:
    from .linesearch import linesearch
except ImportError:
    from linesearch import linesearch


def cgmin1(func, x, itmax=None, ftol=None, xtol=None, *varargin):
    """
    Conjugate-gradient optimization routine
    NOTE: linesearch subroutines do not use the gradient

    MATLAB equivalent: engines.ML.cgmin1

    Args:
        func: string name or callable of objective function which returns both the
              objective function value and the gradient
        x: input as initial starting point and output as final point
        itmax: maximum number of iterations (None for default = 50)
        ftol: relative function tolerance (None for default = 1e-3)
        xtol: absolute solution tolerance (None for default = 1e-3)
        *varargin: extra variables required by objective function

    Returns:
        x: final optimized point
        p: parameter dict (if returned by objective function)

    DISCLAIMER: This code is not intended for distribution. I have many
    versions of this code and am constantly revising it. I believe this
    version is working properly. However, I will not vouch for the code.
    Anyone using the code for thesis research has a responsibility to go
    through the code line-by-line and read relevant references to understand
    the code completely.

    Sam Thurman, May 9, 2005
    """

    # Set defaults
    if itmax is None:
        itmax = 50
    if ftol is None:
        ftol = 1e-3
    if xtol is None:
        xtol = 1e-3

    # Loop
    flg = 0  # use steepest descent for first iteration
    step = 0  # to guess at initial steplength
    p = None  # will store parameter dict if returned

    for it in range(1, itmax + 1):
        # Function evaluation
        # Handle both string function names and callable functions
        if isinstance(func, str):
            result = eval(f"{func}(x, *varargin)")
        else:
            result = func(x, *varargin)

        # Unpack result
        if isinstance(result, tuple):
            if len(result) == 3:
                f, grad, p_new = result
                # Update varargin with new p for next iteration
                if len(varargin) > 0:
                    varargin = (p_new,) + varargin[1:]
                    p = p_new
            elif len(result) == 2:
                f, grad = result
            else:
                raise ValueError(f"Unexpected return from objective function: {len(result)} values")
        else:
            raise ValueError("Objective function must return at least (f, grad)")

        # Check for feasibility
        if np.isinf(f):
            raise ValueError('encountered an infeasible solution')

        grad_norm = np.linalg.norm(grad.flatten())
        if it == 0 or it % 1 == 0:  # Print every iteration
            print(f"  Iter {it+1}: f={f:.6e}, ||grad||={grad_norm:.6e}")

        if grad_norm == 0:
            return x, p if p is not None else x  # done if gradient is zero (unlikely)

        # Pick search direction
        if (flg == 1) and (it % 25 != 0):  # linesearch found a minimum -> use cg equations
            gg = np.dot(g.flatten(), g.flatten())
            # dgg = np.dot(grad.flatten(), grad.flatten())  # this statement for Fletcher-Reeves
            dgg = np.dot((grad.flatten() + g.flatten()), grad.flatten())  # this statement for Polak-Ribiere
            ga = dgg / gg
            g = -grad
            h = g + ga * h
            dx = h / np.linalg.norm(h.flatten())
            df = np.dot(grad.flatten(), dx.flatten())
        else:
            # Condition met if: flg==0 OR it%25==0 OR df>0
            # Revert to steepest descent
            pass

        if (flg == 0) or (it % 25 == 0) or ('df' in locals() and df > 0):  # revert to steepest decent
            g = -grad
            h = g
            dx = h / np.linalg.norm(h.flatten())
            df = np.dot(grad.flatten(), dx.flatten())

        # Initial steplength guess
        if step == 0:
            # Same as fminusub.m (line 124) in optim toolbox
            step = max(0.001, min([1, 2 * abs(f / (np.dot(grad.flatten(), dx.flatten())))]))
        else:  # otherwise use previous steplength
            step = step / 10

        # Linesearch
        if it % 1 == 0:  # Print before linesearch
            print(f"    Before linesearch: df={df:.6e}, step={step:.6e}")
        x, fvalue, step, flg = linesearch(func, x, f, df, dx, step, *varargin)
        if it % 1 == 0:  # Print after linesearch
            print(f"    After linesearch: flg={flg}, new_step={step:.6e}, f_change={abs(f-fvalue):.6e}")

        # Iteration callback (for WebSocket UI)
        if len(varargin) > 0 and isinstance(varargin[0], dict):
            _cb = varargin[0].get('_iteration_callback')
            if _cb:
                _cb({'type': 'iteration_update', 'engine': 'ML',
                     'iteration': it, 'total_iterations': itmax,
                     'error': float(fvalue)})
            _ce = varargin[0].get('_cancel_event')
            if _ce and _ce.is_set():
                verbose(2, 'ML cancelled by user')
                return x, p if p is not None else x

        # Test for convergence
        f_check = 2 * abs(f - fvalue) <= ftol * (abs(f) + abs(fvalue) + ftol)
        x_check = step * np.linalg.norm(dx.flatten()) <= xtol
        if it % 1 == 0:  # Print every iteration
            print(f"    Convergence: f_check={f_check}, x_check={x_check}, step={step:.6e}, |f-fvalue|={abs(f-fvalue):.6e}")
        if f_check and x_check and (it != 1):  # normal return
            print(f"  Converged at iteration {it+1}")
            return x, p if p is not None else x

    verbose(3, 'Maximum number of iterations exceeded.')
    return x, p if p is not None else x


# Module test
if __name__ == "__main__":
    print("Testing cgmin1.py...")

    # Test with Rosenbrock function
    def rosenbrock_with_grad(x):
        """Rosenbrock function with gradient"""
        f = (1 - x[0])**2 + 100 * (x[1] - x[0]**2)**2

        grad = np.zeros(2)
        grad[0] = -2 * (1 - x[0]) - 400 * x[0] * (x[1] - x[0]**2)
        grad[1] = 200 * (x[1] - x[0]**2)

        return f, grad

    # Starting point
    x0 = np.array([0.0, 0.0])
    print(f"Starting point: x0={x0}")
    print(f"  f0={rosenbrock_with_grad(x0)[0]:.6f}")

    # Run cgmin1
    x_final = cgmin1(rosenbrock_with_grad, x0.copy(), itmax=50, ftol=1e-3, xtol=1e-3)

    # Handle return value (could be x or (x, p))
    if isinstance(x_final, tuple):
        x_final = x_final[0]

    f_final, _ = rosenbrock_with_grad(x_final)

    print(f"\nOptimization result:")
    print(f"  x_final={x_final}")
    print(f"  f_final={f_final:.6f}")
    print(f"  Expected: x~[1, 1], f~0")

    # Check convergence (Rosenbrock minimum is at [1, 1] with f=0)
    assert f_final < 0.1, f"Function should be close to 0, got {f_final}"
    assert np.linalg.norm(x_final - np.array([1.0, 1.0])) < 0.5, \
        f"Solution should be close to [1, 1], got {x_final}"

    print("\nTest passed!")
