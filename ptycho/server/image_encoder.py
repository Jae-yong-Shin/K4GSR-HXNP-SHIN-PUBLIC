"""
image_encoder.py - Complex array to base64 PNG conversion for browser display
"""
import io
import base64
import numpy as np


def complex_to_png_bytes(arr, mode='amplitude', colormap='viridis', max_size=512):
    """
    Convert complex 2D array to PNG bytes.

    Args:
        arr: 2D complex or real ndarray
        mode: 'amplitude', 'phase', 'real', 'imag'
        colormap: 'viridis', 'gray', 'hot', 'hsv'
        max_size: max dimension (downsamples if larger)
    Returns:
        PNG bytes
    """
    if arr.ndim > 2:
        arr = arr.squeeze()
    if arr.ndim > 2:
        arr = arr[:, :, 0] if arr.ndim == 3 else arr

    # Extract component
    if mode == 'amplitude':
        data = np.abs(arr).astype(np.float64)
    elif mode == 'phase':
        data = np.angle(arr).astype(np.float64)
    elif mode == 'real':
        data = np.real(arr).astype(np.float64)
    elif mode == 'imag':
        data = np.imag(arr).astype(np.float64)
    else:
        data = np.abs(arr).astype(np.float64)

    # Downsample if needed
    h, w = data.shape
    if max(h, w) > max_size:
        scale = max_size / max(h, w)
        new_h, new_w = int(h * scale), int(w * scale)
        # Simple block averaging
        from scipy.ndimage import zoom
        data = zoom(data, (new_h / h, new_w / w), order=1)

    # Normalize to 0-255
    # Use percentile clipping for amplitude to handle near-uniform images
    if mode == 'amplitude':
        vmin = np.nanpercentile(data, 0.5)
        vmax = np.nanpercentile(data, 99.5)
    else:
        vmin, vmax = np.nanmin(data), np.nanmax(data)
    if vmax - vmin < 1e-12:
        normalized = np.zeros_like(data, dtype=np.uint8)
    else:
        normalized = np.clip((data - vmin) / (vmax - vmin) * 255, 0, 255).astype(np.uint8)

    # Apply colormap
    rgb = _apply_colormap(normalized, colormap, is_phase=(mode == 'phase'))

    # Encode PNG
    from PIL import Image
    img = Image.fromarray(rgb, 'RGB')
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def complex_to_base64(arr, mode='amplitude', colormap='viridis', max_size=512):
    """Convert complex 2D array to base64-encoded PNG data URI."""
    png_bytes = complex_to_png_bytes(arr, mode, colormap, max_size)
    b64 = base64.b64encode(png_bytes).decode('ascii')
    return f'data:image/png;base64,{b64}'


def make_thumbnail(arr, mode='amplitude', size=128):
    """Create small thumbnail for history display."""
    return complex_to_base64(arr, mode=mode, max_size=size)


def _apply_colormap(normalized, colormap, is_phase=False):
    """Apply colormap to 0-255 normalized array. Returns RGB uint8."""
    h, w = normalized.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)

    if colormap == 'gray':
        rgb[:, :, 0] = normalized
        rgb[:, :, 1] = normalized
        rgb[:, :, 2] = normalized

    elif colormap == 'viridis':
        # Simplified viridis: dark purple -> teal -> yellow
        t = normalized.astype(np.float32) / 255.0
        rgb[:, :, 0] = np.clip((0.267 + t * (0.993 - 0.267) * t) * 255, 0, 255).astype(np.uint8)
        rgb[:, :, 1] = np.clip((0.004 + t * 0.906) * 255, 0, 255).astype(np.uint8)
        rgb[:, :, 2] = np.clip((0.329 + t * (0.143 - 0.329 + 0.6 * t)) * 255, 0, 255).astype(np.uint8)

    elif colormap == 'hot':
        t = normalized.astype(np.float32) / 255.0
        rgb[:, :, 0] = np.clip(t * 3 * 255, 0, 255).astype(np.uint8)
        rgb[:, :, 1] = np.clip((t - 0.33) * 3 * 255, 0, 255).astype(np.uint8)
        rgb[:, :, 2] = np.clip((t - 0.67) * 3 * 255, 0, 255).astype(np.uint8)

    elif colormap == 'hsv' or is_phase:
        # HSV colormap — good for phase
        t = normalized.astype(np.float32) / 255.0
        h_val = t * 360
        s_val = np.ones_like(t)
        v_val = np.ones_like(t) * 0.9
        _hsv_to_rgb(h_val, s_val, v_val, rgb)

    else:
        # Default grayscale
        rgb[:, :, 0] = normalized
        rgb[:, :, 1] = normalized
        rgb[:, :, 2] = normalized

    return rgb


def _hsv_to_rgb(h, s, v, out):
    """Vectorized HSV to RGB conversion."""
    h60 = h / 60.0
    hi = np.floor(h60).astype(int) % 6
    f = h60 - np.floor(h60)
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)

    for i in range(6):
        mask = hi == i
        if i == 0:
            out[mask, 0] = (v[mask] * 255).astype(np.uint8)
            out[mask, 1] = (t[mask] * 255).astype(np.uint8)
            out[mask, 2] = (p[mask] * 255).astype(np.uint8)
        elif i == 1:
            out[mask, 0] = (q[mask] * 255).astype(np.uint8)
            out[mask, 1] = (v[mask] * 255).astype(np.uint8)
            out[mask, 2] = (p[mask] * 255).astype(np.uint8)
        elif i == 2:
            out[mask, 0] = (p[mask] * 255).astype(np.uint8)
            out[mask, 1] = (v[mask] * 255).astype(np.uint8)
            out[mask, 2] = (t[mask] * 255).astype(np.uint8)
        elif i == 3:
            out[mask, 0] = (p[mask] * 255).astype(np.uint8)
            out[mask, 1] = (q[mask] * 255).astype(np.uint8)
            out[mask, 2] = (v[mask] * 255).astype(np.uint8)
        elif i == 4:
            out[mask, 0] = (t[mask] * 255).astype(np.uint8)
            out[mask, 1] = (p[mask] * 255).astype(np.uint8)
            out[mask, 2] = (v[mask] * 255).astype(np.uint8)
        elif i == 5:
            out[mask, 0] = (v[mask] * 255).astype(np.uint8)
            out[mask, 1] = (p[mask] * 255).astype(np.uint8)
            out[mask, 2] = (q[mask] * 255).astype(np.uint8)


def complex_to_raw_base64(arr, max_size=256):
    """
    Encode complex 2D array as base64 interleaved float32 for client-side rendering.
    Returns dict with 'data' (base64 string) and 'shape' [H, W].
    """
    if arr.ndim > 2:
        arr = arr.squeeze()
    if arr.ndim > 2:
        arr = arr[:, :, 0] if arr.ndim == 3 else arr

    h, w = arr.shape[:2]
    if max(h, w) > max_size:
        scale = max_size / max(h, w)
        new_h, new_w = int(h * scale), int(w * scale)
        from scipy.ndimage import zoom
        real_part = zoom(arr.real.astype(np.float64), (new_h / h, new_w / w), order=1)
        imag_part = zoom(arr.imag.astype(np.float64), (new_h / h, new_w / w), order=1)
        arr = (real_part + 1j * imag_part).astype(np.complex64)
        h, w = arr.shape[:2]

    flat = arr.ravel().astype(np.complex64)
    interleaved = np.empty(2 * flat.size, dtype=np.float32)
    interleaved[0::2] = flat.real
    interleaved[1::2] = flat.imag
    return {
        'data': base64.b64encode(interleaved.tobytes()).decode('ascii'),
        'shape': [h, w],
    }


def positions_to_base64(positions, asize, max_size=256):
    """Render scan positions as a PNG image."""
    from PIL import Image, ImageDraw

    pos = np.array(positions)
    rows, cols = pos[:, 0], pos[:, 1]
    margin = asize[0] // 2
    r_min, r_max = rows.min() - margin, rows.max() + margin
    c_min, c_max = cols.min() - margin, cols.max() + margin

    h = int(r_max - r_min)
    w = int(c_max - c_min)
    scale = min(max_size / max(h, w, 1), 1.0)
    ih, iw = max(int(h * scale), 1), max(int(w * scale), 1)

    img = Image.new('RGB', (iw, ih), (16, 24, 34))
    draw = ImageDraw.Draw(img)

    for i in range(len(pos)):
        y = int((rows[i] - r_min) * scale)
        x = int((cols[i] - c_min) * scale)
        r = max(2, int(3 * scale))
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(77, 184, 255))

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    return f'data:image/png;base64,{b64}'
