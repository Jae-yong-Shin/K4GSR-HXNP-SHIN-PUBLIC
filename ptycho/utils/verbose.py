"""
verbose.py - Logging utility (ported from cSAXS +utils/verbose.m)

Function verbose(level, message)

verbose() : returns current verbose level
verbose(n): set the level to n
verbose(n, message): displays the message if n <= current verbose level
verbose(n, message, v1, v2, ...) behaves like sprintf(message, v1, v2, ...)

Suggested levels:
 1: important information
 2: general information
 3: debugging

License:
Copyright (c) 2017 by Paul Scherrer Institute (http://www.psi.ch)
Author: CXS group, PSI
Python port: 2026

Original MATLAB code from cSAXS software package
"""

import sys
import inspect

# Persistent state (module-level variables, equivalent to MATLAB persistent)
_verbose_level = 1
_verbose_prefix = None


def verbose(*args):
    """
    Verbose logging function

    Usage:
        verbose() -> returns current level
        verbose(n) -> sets level to n
        verbose(n, message, *values) -> prints if n <= level
    """
    global _verbose_level, _verbose_prefix

    # Case 1: no arguments - return current level
    if len(args) == 0:
        return _verbose_level

    # Case 2: single argument - set level or prefix
    if len(args) == 1:
        arg = args[0]
        if isinstance(arg, str):
            # Try to convert string to number (MATLAB: str2num)
            try:
                _verbose_level = int(arg)
            except ValueError:
                _verbose_level = float(arg)
        elif isinstance(arg, dict) and 'prefix' in arg:
            # Struct with prefix field (MATLAB: isstruct)
            _verbose_prefix = arg['prefix']
        else:
            # Numeric level
            _verbose_level = arg
        return None

    # Case 3: level + message + optional args
    if len(args) >= 2:
        level = args[0]
        message_fmt = args[1]
        message_args = args[2:] if len(args) > 2 else ()

        if _verbose_level >= level:
            # Format message (MATLAB: sprintf)
            try:
                message = message_fmt % message_args
            except TypeError:
                # If % formatting fails, try format()
                message = message_fmt.format(*message_args)

            # Output with appropriate formatting
            _output_print_fct(level, message, _verbose_level, _verbose_prefix)

    return None


def _output_print_fct(level, message_str, verbose_level, verbose_prefix):
    """
    Output function with level-dependent formatting

    MATLAB equivalent: output_print_fct (line 86-97)
    """
    if verbose_level > 3:
        # Debug mode: include caller function and line number
        # MATLAB: [st, ~] = dbstack(2)
        frame = inspect.currentframe()
        try:
            caller_frame = frame.f_back.f_back.f_back  # Go up 3 levels
            if caller_frame is not None:
                func_name = caller_frame.f_code.co_name
                line_no = caller_frame.f_lineno
                message_str = f"{func_name} [{line_no}] : {message_str}"
            else:
                message_str = f"[root] : {message_str}"
        finally:
            del frame  # Avoid reference cycle
    elif verbose_prefix is not None:
        # Prefix mode
        message_str = f"[{verbose_prefix}] : {message_str}"

    # MATLAB: disp(str) -> Python: print
    print(message_str)


# Convenience function for common usage
def set_verbose_level(level):
    """Set verbose level (convenience wrapper)"""
    verbose(level)


def get_verbose_level():
    """Get current verbose level"""
    return verbose()


# Module test
if __name__ == "__main__":
    print("Testing verbose.py...")

    # Test 1: Get current level
    print(f"Current level: {verbose()}")

    # Test 2: Set level
    verbose(2)
    print(f"Set to 2, current: {verbose()}")

    # Test 3: Conditional output
    verbose(1, "This should print (level 1)")
    verbose(3, "This should NOT print (level 3 > 2)")

    # Test 4: With format arguments
    verbose(2, "Format test: %d %s", 42, "answer")

    # Test 5: Debug mode
    verbose(4)
    verbose(2, "Debug mode test")

    print("Tests complete!")
