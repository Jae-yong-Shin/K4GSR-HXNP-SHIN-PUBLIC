"""
GPU wrapper layer for transparent CPU/GPU operation.

Provides MATLAB-like GPU functions:
- Garray: Move array to GPU
- Gzeros: Create zeros array on GPU
- Gfun: Execute function on GPU (element-wise)
- Ggather: Move array from GPU to CPU

Usage:
    from gpu_wrapper import set_use_gpu, Garray, Gzeros

    set_use_gpu(True)  # Enable GPU

    # Arrays are automatically created on GPU
    arr = Gzeros((100, 100), dtype=np.complex64)
    arr_gpu = Garray(cpu_array)
    result = Ggather(arr_gpu)  # Back to CPU
"""

import os
import numpy as np

# Auto-detect CUDA_PATH from pip-installed nvidia packages if not set
if 'CUDA_PATH' not in os.environ:
    try:
        import site
        _sp = site.getsitepackages()[-1]
        _cuda_rt = os.path.join(_sp, 'nvidia', 'cuda_runtime')
        if os.path.isdir(_cuda_rt):
            os.environ['CUDA_PATH'] = _cuda_rt
    except Exception:
        pass

# Global flag for GPU usage
USE_GPU = False

try:
    import cupy as cp
    GPU_AVAILABLE = True
except (ImportError, Exception):
    GPU_AVAILABLE = False
    cp = None


def check_gpu_available():
    """Check if GPU is available."""
    return GPU_AVAILABLE


def set_use_gpu(use_gpu):
    """
    Set global GPU usage flag.

    Parameters
    ----------
    use_gpu : bool
        If True, use GPU acceleration (requires CuPy)
        If False, use CPU only
    """
    global USE_GPU

    if use_gpu and not GPU_AVAILABLE:
        raise RuntimeError(
            "GPU requested but CuPy is not installed. "
            "Install CuPy: pip install cupy-cuda11x (replace 11x with your CUDA version)"
        )

    USE_GPU = use_gpu
    return USE_GPU


def Garray(array):
    """
    Move array to GPU (if USE_GPU=True).

    Equivalent to MATLAB's gpuArray().

    Parameters
    ----------
    array : ndarray or cupy.ndarray
        Input array

    Returns
    -------
    ndarray or cupy.ndarray
        GPU array if USE_GPU=True, otherwise CPU array

    Examples
    --------
    >>> arr_cpu = np.zeros((100, 100))
    >>> arr_gpu = Garray(arr_cpu)  # Moves to GPU if USE_GPU=True
    """
    if array is None:
        return None

    if USE_GPU:
        if GPU_AVAILABLE:
            return cp.asarray(array)
        else:
            raise RuntimeError("USE_GPU=True but CuPy is not available")
    else:
        if GPU_AVAILABLE and isinstance(array, cp.ndarray):
            return cp.asnumpy(array)
        return np.asarray(array)


def Gzeros(shape, dtype=np.complex64, is_complex=None):
    """
    Create zeros array on GPU (if USE_GPU=True).

    Equivalent to MATLAB's Gzeros().

    Parameters
    ----------
    shape : int or tuple of ints
        Shape of the array
    dtype : dtype, optional
        Data type (default: np.complex64)
    is_complex : bool, optional
        If True, force complex dtype. If None, use dtype as-is.
        This matches MATLAB's Gzeros(size, true) syntax.

    Returns
    -------
    ndarray or cupy.ndarray
        Zeros array on GPU or CPU

    Examples
    --------
    >>> arr = Gzeros((192, 192))  # Complex array
    >>> arr = Gzeros((100, 100), dtype=np.float32)  # Real array
    >>> arr = Gzeros((100, 100), is_complex=True)  # Force complex
    """
    # Handle is_complex flag (MATLAB compatibility)
    if is_complex is True:
        if dtype == np.float32:
            dtype = np.complex64
        elif dtype == np.float64:
            dtype = np.complex128
    elif is_complex is False:
        if dtype == np.complex64:
            dtype = np.float32
        elif dtype == np.complex128:
            dtype = np.float64

    if USE_GPU:
        if GPU_AVAILABLE:
            return cp.zeros(shape, dtype=dtype)
        else:
            raise RuntimeError("USE_GPU=True but CuPy is not available")
    else:
        return np.zeros(shape, dtype=dtype)


def Gfun(func, *args, **kwargs):
    """
    Execute function element-wise on GPU (if USE_GPU=True).

    Equivalent to MATLAB's arrayfun() on GPU.

    Parameters
    ----------
    func : callable
        Function to execute element-wise
    *args : arrays
        Input arrays (all must have compatible shapes)
    **kwargs : dict
        Additional keyword arguments

    Returns
    -------
    ndarray or cupy.ndarray
        Result of element-wise function application

    Notes
    -----
    On GPU, this uses broadcasting and vectorization for efficiency.
    For more complex operations, consider using CuPy's ElementwiseKernel.

    Examples
    --------
    >>> def add_func(a, b):
    ...     return a + b
    >>> result = Gfun(add_func, arr1, arr2)

    >>> # For GPU, equivalent to vectorized operation
    >>> result = Gfun(lambda x, y: x * np.conj(y), psi, probe)
    """
    if USE_GPU:
        if GPU_AVAILABLE:
            # On GPU, just call the function (relies on CuPy's broadcasting)
            # For custom kernels, users can pass ElementwiseKernel directly
            return func(*args, **kwargs)
        else:
            raise RuntimeError("USE_GPU=True but CuPy is not available")
    else:
        # On CPU, just call the function (relies on NumPy's broadcasting)
        return func(*args, **kwargs)


def Ggather(array):
    """
    Move array from GPU to CPU.

    Equivalent to MATLAB's gather().

    Parameters
    ----------
    array : ndarray or cupy.ndarray
        Input array (GPU or CPU)

    Returns
    -------
    ndarray
        CPU array

    Examples
    --------
    >>> arr_gpu = Garray(np.zeros((100, 100)))
    >>> arr_cpu = Ggather(arr_gpu)
    """
    if array is None:
        return None

    if USE_GPU and GPU_AVAILABLE:
        if isinstance(array, cp.ndarray):
            return cp.asnumpy(array)
        else:
            return np.asarray(array)
    else:
        return np.asarray(array)


def norm2(array):
    """
    Compute L2 norm of array.

    Equivalent to MATLAB's norm(array(:), 2).

    Parameters
    ----------
    array : ndarray or cupy.ndarray
        Input array

    Returns
    -------
    float
        L2 norm
    """
    if USE_GPU and GPU_AVAILABLE and isinstance(array, cp.ndarray):
        return float(cp.linalg.norm(array.ravel()))
    else:
        return float(np.linalg.norm(array.ravel()))


def sum2(array):
    """
    Sum all elements in array.

    Equivalent to MATLAB's sum(array(:)).

    Parameters
    ----------
    array : ndarray or cupy.ndarray
        Input array

    Returns
    -------
    scalar
        Sum of all elements
    """
    if USE_GPU and GPU_AVAILABLE and isinstance(array, cp.ndarray):
        return cp.sum(array)
    else:
        return np.sum(array)


# Export module-level USE_GPU
__all__ = [
    'USE_GPU',
    'GPU_AVAILABLE',
    'set_use_gpu',
    'check_gpu_available',
    'Garray',
    'Gzeros',
    'Gfun',
    'Ggather',
    'norm2',
    'sum2'
]
