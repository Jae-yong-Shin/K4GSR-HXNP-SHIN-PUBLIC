"""
errorplot.py - Build an errormetric plot vs iteration number

Python port of core.errorplot from cSAXS Ptychoshelves package

License:
Copyright (c) 2017 by Paul Scherrer Institute (http://www.psi.ch)
Python port: 2026

Original MATLAB code from cSAXS Ptychoshelves package
"""

import numpy as np


# Module-level persistent variable (equivalent to MATLAB persistent)
_errormetric = []


def errorplot(argin=None):
    """
    Build an errormetric plot vs iteration number

    MATLAB equivalent: core.errorplot

    Usage:
        e = errorplot()      Clears the persistent variable, returns empty
        e = errorplot(x)     Appends x to the persistent variable
        e = errorplot([])    Only reads the persistent variable (returns numpy array)
        e = errorplot(None)  Clears the persistent variable (same as errorplot())

    Args:
        argin: value to append (scalar or array), None to clear, or empty list to read only

    Returns:
        errormetric: array of error values
    """
    global _errormetric

    # Clear if no argument or None
    if argin is None:
        _errormetric = []
    # Read only if empty list
    elif isinstance(argin, list) and len(argin) == 0:
        pass  # Don't modify, just return
    # Append value
    else:
        if isinstance(argin, (int, float)):
            _errormetric.append(argin)
        elif isinstance(argin, np.ndarray):
            _errormetric.append(argin.item() if argin.size == 1 else argin)
        else:
            _errormetric.append(argin)

    # Return as numpy array if not empty
    if len(_errormetric) > 0:
        return np.array(_errormetric)
    else:
        return np.array([])


# Module test
if __name__ == "__main__":
    print("Testing errorplot.py...")

    # Clear
    e = errorplot()
    print(f"After clear: {e}")
    assert len(e) == 0, "Should be empty after clear"

    # Append values
    errorplot(1.0)
    errorplot(0.5)
    errorplot(0.25)

    e = errorplot([])  # Read only
    print(f"After appending [1.0, 0.5, 0.25]: {e}")
    assert len(e) == 3, "Should have 3 values"
    assert np.allclose(e, [1.0, 0.5, 0.25]), "Values should match"

    # Append more
    errorplot(0.125)
    e = errorplot([])
    print(f"After appending 0.125: {e}")
    assert len(e) == 4, "Should have 4 values"

    # Clear again
    e = errorplot()
    print(f"After second clear: {e}")
    assert len(e) == 0, "Should be empty again"

    print("\nTest passed!")
