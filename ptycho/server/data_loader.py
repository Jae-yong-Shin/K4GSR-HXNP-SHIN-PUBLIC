"""
data_loader.py - Load ptychography data from .mat, .h5, .npy, or synthetic generation
"""
import numpy as np
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def convert_complex(data):
    """Convert HDF5 structured complex to numpy complex."""
    if hasattr(data, 'dtype') and data.dtype.names == ('real', 'imag'):
        return data['real'] + 1j * data['imag']
    return np.asarray(data)


class DataLoader:
    """Loads ptychography data and builds the p dict for engines."""

    def __init__(self):
        self.current_data = None  # Cached loaded data

    def load_mat(self, path):
        """
        Load from MATLAB .mat file (HDF5 v7.3 format).
        Supports both full comparison format and simple format.
        Returns dict with fmag, positions, probes, object, asize, etc.
        """
        import h5py
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f'MAT file not found: {path}')

        data = {}
        with h5py.File(path, 'r') as f:
            keys = list(f.keys())

            # Try to load from p_0 structure (proper_comparison format)
            if 'p_0' in keys:
                p_0 = f['p_0']
                data['fmag'] = self._deref(f, p_0, 'fmag').T.astype(np.float32)
                data['positions'] = self._deref(f, p_0, 'positions').T.astype(np.float32)
                asize_raw = self._deref(f, p_0, 'asize').flatten().astype(int)
                data['asize'] = tuple(asize_raw)

                if 'probes' in p_0:
                    data['probes'] = convert_complex(self._deref(f, p_0, 'probes')).T
                    data['has_file_probe'] = True
                if 'object' in p_0:
                    data['object_init'] = convert_complex(self._deref(f, p_0, 'object')).T
                if 'scanidxs' in p_0:
                    data['scanidxs'] = self._deref(f, p_0, 'scanidxs').flatten().astype(int)

            else:
                # Simple format: direct arrays
                if 'fmag' in keys:
                    data['fmag'] = convert_complex(f['fmag'][()]).T.astype(np.float32)
                if 'positions' in keys:
                    data['positions'] = f['positions'][()].T.astype(np.float32)
                if 'asize' in keys:
                    data['asize'] = tuple(f['asize'][()].flatten().astype(int))

            # Ground truth (optional)
            if 'object_true' in keys:
                data['object_true'] = convert_complex(f['object_true'][()]).T
            if 'probe_true' in keys:
                data['probe_true'] = convert_complex(f['probe_true'][()]).T

        # Derive asize from fmag if not set
        if 'asize' not in data and 'fmag' in data:
            data['asize'] = (data['fmag'].shape[0], data['fmag'].shape[1])

        self.current_data = data
        return data

    def load_h5(self, path, projection_index=0, asize=None, max_positions=None):
        """
        Smart HDF5 loader with auto-detection.

        Scans the file structure and identifies diffraction patterns, positions,
        metadata (energy, distance, pixel size), mask, and probe by heuristics.
        Handles 3D (N,H,W) and 4D (Nangles,N,H,W) ptycho-tomo data.

        Args:
            path: HDF5 file path
            projection_index: For 4D ptycho-tomo data, which projection to use
            asize: If set, center-crop detector to this size
            max_positions: If set, subsample to this many positions
        """
        import h5py
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f'HDF5 file not found: {path}')

        data = {}
        with h5py.File(path, 'r') as f:
            all_ds = self._scan_h5_datasets(f)
            print(f'H5: Found {len(all_ds)} datasets in file')

            # --- Diffraction data ---
            diff_ds = self._find_diffraction(all_ds)
            if diff_ds is None:
                raise ValueError(
                    'HDF5: Could not auto-detect diffraction data. '
                    'Need a 3D+ array with square last two dims.')
            print(f'H5: Diffraction -> {diff_ds["path"]}  {diff_ds["shape"]}')

            diff_raw = f[diff_ds['path']][()]

            # Handle 4D ptycho-tomo: (Nangles, Npos, H, W)
            if diff_raw.ndim == 4:
                n_proj = diff_raw.shape[0]
                idx = min(projection_index, n_proj - 1)
                print(f'H5: 4D data ({n_proj} projections), selecting #{idx}')
                diff_raw = diff_raw[idx]

            # Now 3D: determine (N,H,W) vs (H,W,N)
            if diff_raw.ndim == 3:
                s = diff_raw.shape
                if s[1] == s[2]:
                    # (N, H, W) — most common
                    Npos_total = s[0]
                    det_size = s[1]
                    axis_order = 'NHW'
                elif s[0] == s[1]:
                    # (H, W, N)
                    Npos_total = s[2]
                    det_size = s[0]
                    axis_order = 'HWN'
                else:
                    # Ambiguous — assume (N, H, W)
                    Npos_total = s[0]
                    det_size = s[1]
                    axis_order = 'NHW'
            else:
                raise ValueError(
                    f'HDF5: diffraction must be 3D or 4D, got {diff_raw.ndim}D')

            # --- Subsample positions ---
            if max_positions and Npos_total > max_positions:
                idx_sel = np.linspace(0, Npos_total - 1, max_positions, dtype=int)
                print(f'H5: Subsampling {Npos_total} -> {len(idx_sel)} positions')
            else:
                idx_sel = np.arange(Npos_total)
            Npos = len(idx_sel)

            # --- Center crop ---
            crop_size = asize if asize else det_size
            c0 = (det_size - crop_size) // 2
            c1 = c0 + crop_size

            if axis_order == 'NHW':
                patterns = diff_raw[np.ix_(idx_sel,
                                           np.arange(c0, c1),
                                           np.arange(c0, c1))].astype(np.float32)
                # → (Npos, crop, crop) → (crop, crop, Npos)
                fmag = np.transpose(patterns, (1, 2, 0))
            else:
                patterns = diff_raw[c0:c1, c0:c1, :][:, :, idx_sel].astype(np.float32)
                fmag = patterns

            fmag = np.maximum(fmag, 0)

            # Auto-detect intensity vs magnitude
            # Intensity typically has max >> 1e4, magnitude has max ~ 10-100
            if fmag.max() > 1e4:
                print(f'H5: Detected intensity data (max={fmag.max():.0f}), taking sqrt')
                fmag = np.sqrt(fmag)

            # Auto-detect DC position: if center pixel is brightest, need fftshift
            mid = crop_size // 2
            center_val = np.mean(fmag[mid-2:mid+2, mid-2:mid+2, :])
            corner_val = np.mean(fmag[:3, :3, :])
            if center_val > corner_val * 5:
                print('H5: DC at center detected, applying fftshift')
                fmag = np.fft.fftshift(fmag, axes=(0, 1))

            data['fmag'] = fmag
            data['asize'] = (crop_size, crop_size)
            data['Npos'] = Npos

            # --- Positions ---
            pos_ds = self._find_positions(all_ds, Npos_total)
            if pos_ds is None:
                raise ValueError(
                    'HDF5: Could not auto-detect scan positions. '
                    f'Need array with one dim = {Npos_total} and other dim = 2 or 3.')
            print(f'H5: Positions -> {pos_ds["path"]}  {pos_ds["shape"]}')

            pos_raw = f[pos_ds['path']][()]
            # Handle 3D positions (Nangles, N, 2) — select projection
            if pos_raw.ndim == 3:
                pi = min(projection_index, pos_raw.shape[0] - 1)
                print(f'H5: 3D positions ({pos_raw.shape}), selecting projection #{pi}')
                pos_raw = pos_raw[pi]
            # Normalize to (N, 2) or (N, 3)
            if pos_raw.ndim == 2:
                if pos_raw.shape[0] in (2, 3) and pos_raw.shape[1] == Npos_total:
                    pos_raw = pos_raw.T
            elif pos_raw.ndim == 1 and Npos_total == 1:
                pos_raw = pos_raw.reshape(1, -1)
            pos_raw = pos_raw[idx_sel].astype(np.float64)

            # --- Metadata: energy, distance, pixel_size ---
            energy_keV = self._find_scalar(f, all_ds,
                keywords=['energy', 'nrj', 'photon_energy'],
                name_hint='energy')
            z_m = self._find_scalar(f, all_ds,
                keywords=['distance', 'detector_distance', 'z_distance', 'ccd_dist'],
                name_hint='distance')
            dpix = self._find_scalar(f, all_ds,
                keywords=['pixel_size', 'x_pixel_size', 'det_pixel', 'pixelsize'],
                name_hint='pixel_size')

            # Unit normalization
            if energy_keV is not None:
                if energy_keV > 1000:
                    energy_keV /= 1000.0  # eV → keV
                print(f'H5: Energy = {energy_keV:.2f} keV')
                data['energy_keV'] = energy_keV

            if z_m is not None:
                if z_m > 100:
                    z_m /= 1000.0  # mm → m
                print(f'H5: Distance = {z_m:.4f} m')
                data['z_m'] = z_m

            if dpix is not None:
                if dpix > 0.01:
                    dpix /= 1000.0  # mm → m
                print(f'H5: Pixel size = {dpix*1e6:.1f} um')
                data['det_pixel_m'] = dpix

            # --- Convert positions to pixel coordinates ---
            # Compute recon pixel size if physical params available
            if energy_keV and z_m and dpix:
                lambda_m = 1239.842e-9 / (energy_keV * 1e3)
                dx = lambda_m * z_m / (crop_size * dpix)
                data['pixel_size_nm'] = dx * 1e9
                print(f'H5: Recon pixel size = {dx*1e9:.2f} nm')

            # Detect if positions are already in pixels (name hint or value range)
            pos_path_lower = pos_ds['path'].lower()
            pos_is_pixel = '_px' in pos_path_lower or 'pixel' in pos_path_lower
            pos_xy = pos_raw[:, :2]
            pos_range = np.ptp(pos_xy, axis=0).max()

            if pos_is_pixel or pos_range > 100:
                # Already pixel coordinates
                print(f'H5: Positions in pixels (range={pos_range:.1f})')
                pos_px = pos_xy
            elif energy_keV and z_m and dpix:
                if pos_range < 0.01:
                    print(f'H5: Positions in metres (range={pos_range:.6f})')
                    pos_px = pos_xy / dx
                else:
                    print(f'H5: Positions in mm (range={pos_range:.3f})')
                    pos_px = (pos_xy * 1e-3) / dx
            else:
                print(f'H5: Positions unit unknown (range={pos_range:.3f}), assuming pixels')
                pos_px = pos_xy

            pos_px = pos_px.copy()
            pos_px -= pos_px.min(axis=0)
            pos_px += 1  # minimal margin (position refinement is sub-pixel)
            # No auto-swap — column order is handled by UI Columns dropdown
            # (or load_with_mapping's position_columns parameter)
            positions = pos_px.astype(np.float32)

            data['positions'] = positions

            # --- Mask ---
            mask_ds = self._find_mask(all_ds, det_size)
            if mask_ds is not None:
                print(f'H5: Mask -> {mask_ds["path"]}  {mask_ds["shape"]}')
                mask_raw = f[mask_ds['path']][()]
                if asize and det_size != crop_size:
                    mask_raw = mask_raw[c0:c1, c0:c1]
                # Normalize: 1=good in our convention
                if mask_raw.max() > 1:
                    # Bitfield mask — treat nonzero as bad
                    fmask = (mask_raw == 0).astype(np.float32)
                else:
                    fmask = mask_raw.astype(np.float32)
                # Match fftshift of fmag
                if center_val > corner_val * 5:
                    fmask = np.fft.fftshift(fmask)
                data['fmask'] = fmask

            # --- Probe (optional) ---
            probe_ds = self._find_probe(all_ds, crop_size)
            if probe_ds is not None:
                print(f'H5: Probe -> {probe_ds["path"]}  {probe_ds["shape"]}')
                probe_raw = convert_complex(
                    f[probe_ds['path']][()]).astype(np.complex128)
                # 3D probe stack (Nproj, Ny, Nx) → select projection
                if probe_raw.ndim == 3:
                    pi = projection_index if projection_index < probe_raw.shape[0] else 0
                    print(f'H5: 3D probe stack, selecting projection #{pi}')
                    probe_raw = probe_raw[pi]
                data['probes'] = probe_raw
                data['has_file_probe'] = True

        # Default probe if not found
        if 'probes' not in data:
            probe = self._default_probe(data['asize'])
            probe = self._scale_probe_to_data(probe, data['fmag'])
            data['probes'] = probe

        # Object size
        obj_h = int(np.ceil(data['positions'][:, 0].max())) + crop_size + 2
        obj_w = int(np.ceil(data['positions'][:, 1].max())) + crop_size + 2
        data['object_size'] = (obj_h, obj_w)

        print(f'H5: {Npos} positions, {crop_size}x{crop_size} detector, '
              f'object {obj_h}x{obj_w}, fmag [{data["fmag"].min():.2f}, {data["fmag"].max():.2f}]')

        self.current_data = data
        return data

    # ── HDF5 auto-detection helpers ──────────────────────────────

    def _scan_h5_datasets(self, group, prefix=''):
        """Recursively collect all datasets with paths, shapes, dtypes."""
        import h5py
        datasets = []
        for key in group.keys():
            full = f'{prefix}/{key}' if prefix else key
            item = group[key]
            if isinstance(item, h5py.Dataset):
                datasets.append({
                    'path': full,
                    'shape': item.shape,
                    'dtype': item.dtype,
                    'ndim': item.ndim,
                    'size': item.size,
                    'name': key.lower(),
                })
            elif isinstance(item, h5py.Group):
                datasets.extend(self._scan_h5_datasets(item, full))
        return datasets

    def _find_diffraction(self, datasets):
        """Find diffraction: largest 3D+ array with square last two dims."""
        candidates = []
        for ds in datasets:
            if ds['ndim'] < 3:
                continue
            s = ds['shape']
            # Last two dims should be equal (square detector)
            if s[-1] != s[-2]:
                continue
            # Detector size should be reasonable (32-4096)
            if s[-1] < 32 or s[-1] > 4096:
                continue
            score = ds['size']
            name = ds['name']
            path_lower = ds['path'].lower()
            # Boost for known names
            if any(kw in path_lower for kw in
                   ['diffr', 'intensity', 'pattern', 'fmag', 'data', 'frame']):
                score *= 10
            # Penalize reconstruction outputs
            if any(kw in path_lower for kw in
                   ['recon', 'object', 'probe', 'phase', 'amplitude', 'result']):
                score *= 0.01
            candidates.append((score, ds))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def _find_positions(self, datasets, n_patterns):
        """Find positions: 2D (N,2/3) or 3D (Nangles,N,2/3) array."""
        candidates = []
        for ds in datasets:
            s = ds['shape']
            path_lower = ds['path'].lower()
            score = 100
            if any(kw in path_lower for kw in
                   ['position', 'translation', 'shift', 'coord', 'motor']):
                score *= 10

            if ds['ndim'] == 2:
                # (N, 2/3) or (2/3, N)
                if s[0] == n_patterns and s[1] in (2, 3):
                    candidates.append((score, ds))
                elif s[1] == n_patterns and s[0] in (2, 3):
                    candidates.append((score, ds))
            elif ds['ndim'] == 3:
                # (Nangles, N, 2/3) — ptycho-tomo per-angle positions
                if s[1] == n_patterns and s[2] in (2, 3):
                    candidates.append((score, ds))
                elif s[0] == n_patterns and s[2] in (2, 3):
                    candidates.append((score, ds))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def _find_mask(self, datasets, det_size):
        """Find mask: 2D array matching detector dimensions."""
        for ds in datasets:
            if ds['ndim'] != 2:
                continue
            if ds['shape'] == (det_size, det_size):
                path_lower = ds['path'].lower()
                if any(kw in path_lower for kw in ['mask', 'bad_pixel', 'valid']):
                    return ds
        # Fallback: any 2D array matching detector size
        for ds in datasets:
            if ds['ndim'] == 2 and ds['shape'] == (det_size, det_size):
                # Skip if it looks like a probe or image
                path_lower = ds['path'].lower()
                if any(kw in path_lower for kw in ['probe', 'object', 'phase']):
                    continue
                return ds
        return None

    def _find_probe(self, datasets, det_size):
        """Find probe: 2D or 3D complex array matching detector size."""
        for ds in datasets:
            path_lower = ds['path'].lower()
            if 'probe' not in path_lower:
                continue
            s = ds['shape']
            # 2D probe (Ny, Nx)
            if ds['ndim'] == 2 and s[0] == s[1]:
                return ds
            # 3D probe stack (Nproj, Ny, Nx) — e.g. ptycho-tomo
            if ds['ndim'] == 3 and s[1] == s[2] and s[1] == det_size:
                return ds
        return None

    def _find_scalar(self, f, datasets, keywords, name_hint=''):
        """Find scalar metadata by keyword matching. Returns float or None."""
        for ds in datasets:
            if ds['size'] != 1:
                continue
            path_lower = ds['path'].lower()
            if any(kw in path_lower for kw in keywords):
                try:
                    return float(f[ds['path']][()])
                except (ValueError, TypeError):
                    continue
        return None

    def load_cxi(self, path, asize=256, max_positions=None):
        """
        Load from CXI (.cxi) file -- standard coherent X-ray imaging format.

        CXI is HDF5-based. Standard paths tried:
            entry_1/instrument_1/detector_1/data        (N, H, W) intensity
            entry_1/sample_1/geometry_1/translation      (3, N) or (N, 3) metres
            entry_1/instrument_1/detector_1/mask         (H, W)
            entry_1/instrument_1/detector_1/distance     scalar metres
            entry_1/instrument_1/detector_1/x_pixel_size scalar metres
            entry_1/data_1/process_1/configuration/nrj   scalar keV
        """
        import h5py
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f'CXI file not found: {path}')

        data = {}
        with h5py.File(path, 'r') as f:
            # --- Intensity data ---
            diff_key = None
            for dk in ['entry_1/instrument_1/detector_1/data',
                        'entry_1/data_1/data', 'entry/data/data']:
                if dk in f:
                    diff_key = dk
                    break
            if diff_key is None:
                raise ValueError('CXI: intensity data not found')

            raw_data = f[diff_key]
            Npos_total = raw_data.shape[0]
            det_size = raw_data.shape[1]
            print(f'CXI: {Npos_total} positions, {det_size}x{det_size} detector')

            # --- Mask ---
            mask_raw = None
            for mk in ['entry_1/instrument_1/detector_1/mask',
                        'entry_1/data_1/mask']:
                if mk in f:
                    mask_raw = f[mk][()]
                    break

            # --- Distance ---
            z_m = None
            for zk in ['entry_1/instrument_1/detector_1/distance',
                        'entry_1/instrument_1/detector_1/z']:
                if zk in f:
                    z_m = float(f[zk][()])
                    break

            # --- Pixel size ---
            dpix = None
            for pk in ['entry_1/instrument_1/detector_1/x_pixel_size',
                        'entry_1/instrument_1/detector_1/pixel_size']:
                if pk in f:
                    dpix = float(f[pk][()])
                    break

            # --- Energy ---
            energy_keV = None
            for ek in ['entry_1/data_1/process_1/configuration/nrj',
                        'entry_1/instrument_1/source_1/energy']:
                if ek in f:
                    val = float(f[ek][()])
                    energy_keV = val / 1000.0 if val > 100 else val
                    break

            # --- Positions ---
            pos_raw = None
            for posk in ['entry_1/sample_1/geometry_1/translation',
                          'entry_1/data_1/translation',
                          'entry_1/sample_1/geometry/translation']:
                if posk in f:
                    pos_raw = f[posk][()]
                    break
            if pos_raw is None:
                raise ValueError('CXI: positions not found')

            if pos_raw.shape[0] == 3 and pos_raw.ndim == 2:
                pos_m = pos_raw.T  # (3, N) -> (N, 3)
            elif pos_raw.ndim == 2 and pos_raw.shape[1] == 3:
                pos_m = pos_raw
            else:
                pos_m = pos_raw.reshape(-1, 3)

            # --- Subsample ---
            if max_positions and Npos_total > max_positions:
                idx = np.linspace(0, Npos_total - 1, max_positions, dtype=int)
                print(f'  Subsampling: {Npos_total} -> {len(idx)} positions')
            else:
                idx = np.arange(Npos_total)
            Npos = len(idx)

            # --- Center crop ---
            c0 = (det_size - asize) // 2
            c1 = c0 + asize
            print(f'  Loading {Npos} patterns, cropping {det_size}->{asize}...')
            patterns = np.zeros((asize, asize, Npos), dtype=np.float32)
            for k, i in enumerate(idx):
                frame = raw_data[i, c0:c1, c0:c1].astype(np.float32)
                patterns[:, :, k] = np.maximum(frame, 0)
            pos_m = pos_m[idx, :]

        # Mask
        if mask_raw is not None:
            mask_crop = mask_raw[c0:c1, c0:c1]
            fmask = (mask_crop == 0).astype(np.float32)
        else:
            fmask = np.ones((asize, asize), dtype=np.float32)

        # Intensity -> magnitude, fftshift
        fmag = np.sqrt(patterns)
        fmag = np.fft.fftshift(fmag, axes=(0, 1))
        fmask = np.fft.fftshift(fmask)

        # Physical params -> pixel positions
        pixel_size_nm = 0.0
        if energy_keV and z_m and dpix:
            lambda_m = 1239.842e-9 / (energy_keV * 1e3)
            dx = lambda_m * z_m / (asize * dpix)
            pixel_size_nm = dx * 1e9
            print(f'  Energy: {energy_keV:.2f} keV, pixel size: {pixel_size_nm:.2f} nm')
            pos_xy = pos_m[:, :2]
            pos_px = pos_xy / dx
            pos_px -= pos_px.min(axis=0)
            pos_px += 1  # minimal margin
            positions = pos_px[:, ::-1].astype(np.float32)
        else:
            print('  Warning: missing physical params, using raw positions')
            positions = pos_m[:, :2].astype(np.float32)
            positions -= positions.min(axis=0)
            positions += 1  # minimal margin

        # Probe
        probe = self._default_probe((asize, asize))
        probe = self._scale_probe_to_data(probe, fmag)

        # Object size
        obj_h = int(np.ceil(positions[:, 0].max())) + asize + 2
        obj_w = int(np.ceil(positions[:, 1].max())) + asize + 2

        data = {
            'fmag': fmag, 'fmask': fmask, 'positions': positions,
            'probes': probe, 'asize': (asize, asize), 'Npos': Npos,
            'object_size': (obj_h, obj_w), 'pixel_size_nm': pixel_size_nm,
        }
        if energy_keV:
            data['energy_keV'] = energy_keV
        if z_m:
            data['z_m'] = z_m
        if dpix:
            data['det_pixel_m'] = dpix

        print(f'  Object size: {obj_h}x{obj_w}, fmag: [{fmag.min():.2f}, {fmag.max():.2f}]')
        self.current_data = data
        return data

    # ── Smart Data Mapper (cross-beamline) ─────────────────────

    def scan_file(self, path):
        """Scan file structure and auto-detect dataset roles with confidence.

        Returns dict with:
            datasets: list of {path, shape, dtype, detected_role, confidence}
            metadata: {energy_keV, distance_m, pixel_size_m}
            auto_mapping: {diffraction, positions, mask, probe}
            position_unit_guess: 'pixels'|'m'|'mm'|'um'|'nm'
            format: 'h5'|'mat'|'cxi'
        """
        import h5py
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f'File not found: {path}')

        ext = path.suffix.lower()
        fmt = 'cxi' if ext == '.cxi' else 'mat' if ext == '.mat' else 'h5'

        result = {
            'file': str(path),
            'format': fmt,
            'datasets': [],
            'metadata': {},
            'auto_mapping': {},
            'position_unit_guess': 'pixels',
        }

        with h5py.File(path, 'r') as f:
            all_ds = self._scan_h5_datasets(f)

            # Build dataset list with role detection
            for ds in all_ds:
                entry = {
                    'path': ds['path'],
                    'shape': list(ds['shape']),
                    'dtype': str(ds['dtype']),
                    'ndim': ds['ndim'],
                    'size': ds['size'],
                    'detected_role': None,
                    'confidence': 0.0,
                }
                result['datasets'].append(entry)

            # --- Auto-detect diffraction ---
            diff_ds = self._find_diffraction(all_ds)
            if diff_ds:
                n_patterns = self._count_patterns(diff_ds)
                diff_conf = self._compute_confidence(diff_ds, 'diffraction')
                for e in result['datasets']:
                    if e['path'] == diff_ds['path']:
                        e['detected_role'] = 'diffraction'
                        e['confidence'] = diff_conf
                result['auto_mapping']['diffraction'] = diff_ds['path']
            else:
                n_patterns = None

            # --- Auto-detect positions ---
            if n_patterns:
                pos_ds = self._find_positions(all_ds, n_patterns)
                if pos_ds:
                    pos_conf = self._compute_confidence(pos_ds, 'positions')
                    for e in result['datasets']:
                        if e['path'] == pos_ds['path']:
                            e['detected_role'] = 'positions'
                            e['confidence'] = pos_conf
                    result['auto_mapping']['positions'] = pos_ds['path']

                    # Guess position unit
                    pos_raw = f[pos_ds['path']][()]
                    unit, unit_conf = self._guess_position_unit(
                        pos_raw, pos_ds['path'])
                    result['position_unit_guess'] = unit
                    result['position_unit_confidence'] = unit_conf
                    result['position_columns_guess'] = self._guess_column_order(
                        pos_ds['path'])

            # --- Auto-detect metadata ---
            energy = self._find_scalar(f, all_ds,
                ['energy', 'nrj', 'photon_energy'], 'energy')
            if energy is not None:
                if energy > 1000:
                    energy /= 1000.0
                result['metadata']['energy_keV'] = round(energy, 4)

            distance = self._find_scalar(f, all_ds,
                ['distance', 'detector_distance', 'z_distance', 'ccd_dist'], 'distance')
            if distance is not None:
                if distance > 100:
                    distance /= 1000.0
                result['metadata']['distance_m'] = round(distance, 6)

            dpix = self._find_scalar(f, all_ds,
                ['pixel_size', 'x_pixel_size', 'det_pixel', 'pixelsize'], 'pixel_size')
            if dpix is not None:
                if dpix > 0.01:
                    dpix /= 1000.0
                result['metadata']['pixel_size_m'] = dpix

            # --- Auto-detect mask ---
            if diff_ds:
                det_size = diff_ds['shape'][-1]
                mask_ds = self._find_mask(all_ds, det_size)
                if mask_ds:
                    mask_conf = self._compute_confidence(mask_ds, 'mask')
                    for e in result['datasets']:
                        if e['path'] == mask_ds['path']:
                            e['detected_role'] = 'mask'
                            e['confidence'] = mask_conf
                    result['auto_mapping']['mask'] = mask_ds['path']

            # --- Auto-detect probe ---
            if diff_ds:
                det_size = diff_ds['shape'][-1]
                probe_ds = self._find_probe(all_ds, det_size)
                if probe_ds:
                    probe_conf = self._compute_confidence(probe_ds, 'probe')
                    for e in result['datasets']:
                        if e['path'] == probe_ds['path']:
                            e['detected_role'] = 'probe'
                            e['confidence'] = probe_conf
                    result['auto_mapping']['probe'] = probe_ds['path']

        return result

    # ── Directory-based loading (TIFF/NPY series) ───────────

    def scan_directory(self, path):
        """Scan a directory for image series (TIFF/NPY) + positions files.

        Returns dict matching scan_file() format for UI reuse.
        """
        dirpath = Path(path)
        if not dirpath.is_dir():
            raise ValueError(f'Not a directory: {path}')

        result = {
            'file': str(dirpath),
            'format': 'directory',
            'datasets': [],
            'metadata': {},
            'auto_mapping': {},
            'position_unit_guess': 'pixels',
            'directory_info': {},
        }

        # 1. Find image series
        IMAGE_EXTS = {'.tif', '.tiff', '.npy'}
        files_by_ext = {}
        for f in sorted(dirpath.iterdir()):
            if f.is_file():
                ext = f.suffix.lower()
                if ext in IMAGE_EXTS:
                    files_by_ext.setdefault(ext, []).append(f)

        # Pick the dominant image extension
        pattern_files = []
        pattern_ext = ''
        for ext in ['.tif', '.tiff', '.npy']:
            if ext in files_by_ext and len(files_by_ext[ext]) >= 2:
                pattern_files = files_by_ext[ext]
                pattern_ext = ext
                break

        if not pattern_files:
            raise ValueError(
                f'No image series found in {path}. '
                f'Expected multiple .tif/.tiff/.npy files.')

        # Read first file to get shape
        first_file = pattern_files[0]
        if pattern_ext == '.npy':
            sample = np.load(str(first_file))
            frame_shape = list(sample.shape)
            frame_dtype = str(sample.dtype)
        else:
            from PIL import Image
            img = Image.open(str(first_file))
            sample = np.array(img)
            frame_shape = list(sample.shape)
            frame_dtype = str(sample.dtype)

        n_patterns = len(pattern_files)

        # Add diffraction series as virtual dataset
        diff_entry = {
            'path': '__directory__/diffraction_series',
            'shape': [n_patterns] + frame_shape,
            'dtype': frame_dtype,
            'ndim': 1 + len(frame_shape),
            'size': n_patterns * int(np.prod(frame_shape)),
            'detected_role': 'diffraction',
            'confidence': 0.9,
        }
        result['datasets'].append(diff_entry)
        result['auto_mapping']['diffraction'] = diff_entry['path']

        result['directory_info'] = {
            'pattern_count': n_patterns,
            'pattern_ext': pattern_ext,
            'pattern_shape': frame_shape,
        }

        # 2. Find position files
        POS_EXTS = {'.csv', '.tsv', '.txt', '.npy', '.npz', '.dat'}
        pos_keywords = ['position', 'pos', 'coord', 'scan', 'motor', 'translation']

        for f in sorted(dirpath.iterdir()):
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext not in POS_EXTS:
                continue
            # Skip files that are part of the image series
            if ext == '.npy' and f in pattern_files:
                continue

            try:
                if ext == '.npy':
                    arr = np.load(str(f))
                elif ext == '.npz':
                    npz = np.load(str(f))
                    arr = None
                    for key in npz.files:
                        a = npz[key]
                        if a.ndim == 2 and a.shape[1] in (2, 3):
                            arr = a
                            break
                    if arr is None:
                        continue
                else:
                    arr = self._load_text_positions(str(f))

                if arr is None or arr.ndim != 2:
                    continue
                if arr.shape[1] not in (2, 3) and arr.shape[0] not in (2, 3):
                    continue
            except Exception:
                continue

            pos_entry = {
                'path': f.name,
                'shape': list(arr.shape),
                'dtype': str(arr.dtype),
                'ndim': arr.ndim,
                'size': arr.size,
                'detected_role': 'positions',
                'confidence': 0.7,
            }

            name_lower = f.stem.lower()
            if any(kw in name_lower for kw in pos_keywords):
                pos_entry['confidence'] = 0.9

            n_rows = arr.shape[0] if arr.shape[1] in (2, 3) else arr.shape[1]
            if n_rows == n_patterns:
                pos_entry['confidence'] = min(pos_entry['confidence'] + 0.1, 1.0)

            result['datasets'].append(pos_entry)
            if 'positions' not in result['auto_mapping']:
                result['auto_mapping']['positions'] = f.name

        # 3. Find mask files
        for f in sorted(dirpath.iterdir()):
            if not f.is_file():
                continue
            name_lower = f.stem.lower()
            if 'mask' not in name_lower and 'bad' not in name_lower:
                continue
            ext = f.suffix.lower()
            try:
                if ext == '.npy':
                    arr = np.load(str(f))
                elif ext in ('.tif', '.tiff'):
                    from PIL import Image
                    arr = np.array(Image.open(str(f)))
                else:
                    continue

                det_shape = tuple(frame_shape[-2:]) if len(frame_shape) >= 2 else None
                if det_shape and arr.shape == det_shape:
                    mask_entry = {
                        'path': f.name,
                        'shape': list(arr.shape),
                        'dtype': str(arr.dtype),
                        'ndim': arr.ndim,
                        'size': arr.size,
                        'detected_role': 'mask',
                        'confidence': 0.85,
                    }
                    result['datasets'].append(mask_entry)
                    if 'mask' not in result['auto_mapping']:
                        result['auto_mapping']['mask'] = f.name
            except Exception:
                continue

        print(f'  Directory scanned: {n_patterns} {pattern_ext} files, '
              f'{len(result["datasets"])-1} auxiliary files')
        return result

    def _load_text_positions(self, path):
        """Load positions from a text file with auto-delimiter detection."""
        for delimiter in [None, ',', '\t', ' ']:
            try:
                arr = np.loadtxt(path, delimiter=delimiter, comments='#')
                if arr.ndim == 2 and arr.shape[0] >= 2:
                    return arr
            except Exception:
                continue
        return None

    def load_directory_with_mapping(self, dir_path, mapping):
        """Load data from a directory of image files using explicit mapping."""
        dirpath = Path(dir_path)
        data = {}

        # 1. Load diffraction patterns
        IMAGE_EXTS = {'.tif', '.tiff', '.npy'}
        pattern_files = sorted([
            f for f in dirpath.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        ])

        if not pattern_files:
            raise ValueError(f'No image files found in {dir_path}')

        n_total = len(pattern_files)

        # Subsample
        max_pos = mapping.get('max_positions')
        if max_pos and n_total > max_pos:
            idx_sel = np.linspace(0, n_total - 1, max_pos, dtype=int)
            pattern_files = [pattern_files[i] for i in idx_sel]
        else:
            idx_sel = np.arange(n_total)

        # Read all selected patterns
        print(f'  Loading {len(pattern_files)} image files...')
        frames = []
        for f in pattern_files:
            ext = f.suffix.lower()
            if ext == '.npy':
                frame = np.load(str(f)).astype(np.float32)
            else:
                from PIL import Image
                frame = np.array(Image.open(str(f))).astype(np.float32)
            frames.append(frame)

        patterns = np.stack(frames, axis=0)  # (Npos, H, W)
        Npos = patterns.shape[0]
        det_size = patterns.shape[-1]

        # Crop
        crop_size = mapping.get('crop_size') or det_size
        c0 = (det_size - crop_size) // 2
        c1 = c0 + crop_size
        patterns = patterns[:, c0:c1, c0:c1]

        # Convert: (Npos, H, W) -> (H, W, Npos) as per cSAXS convention
        fmag = np.transpose(patterns, (1, 2, 0))
        fmag = np.maximum(fmag, 0)

        # Auto-detect intensity vs magnitude
        if fmag.max() > 1e4:
            fmag = np.sqrt(fmag)

        # Auto-detect DC position
        mid = crop_size // 2
        center_val = np.mean(fmag[mid-2:mid+2, mid-2:mid+2, :])
        corner_val = np.mean(fmag[:3, :3, :])
        if center_val > corner_val * 5:
            fmag = np.fft.fftshift(fmag, axes=(0, 1))

        data['fmag'] = fmag
        data['asize'] = (crop_size, crop_size)
        data['Npos'] = Npos

        # 2. Load positions
        pos_file = mapping.get('positions')
        if not pos_file:
            raise ValueError('No positions file specified for directory loading')

        pos_path = dirpath / pos_file
        ext = pos_path.suffix.lower()
        if ext == '.npy':
            pos_raw = np.load(str(pos_path))
        elif ext == '.npz':
            npz = np.load(str(pos_path))
            pos_raw = None
            for key in npz.files:
                a = npz[key]
                if a.ndim == 2 and a.shape[1] in (2, 3):
                    pos_raw = a
                    break
            if pos_raw is None:
                pos_raw = npz[npz.files[0]]
        else:
            pos_raw = self._load_text_positions(str(pos_path))

        if pos_raw is None:
            raise ValueError(f'Could not read positions from {pos_file}')

        # Subsample to match diffraction
        if max_pos and n_total > max_pos:
            pos_raw = pos_raw[idx_sel]

        # Normalize shape
        if pos_raw.ndim == 2:
            if pos_raw.shape[0] in (2, 3) and pos_raw.shape[1] > 3:
                pos_raw = pos_raw.T
        pos_raw = pos_raw.astype(np.float64)

        # Column selection + unit conversion
        cols = mapping.get('position_columns', [0, 1])
        pos_xy = pos_raw[:, cols]

        pos_unit = mapping.get('position_unit', 'pixels')
        energy_keV = mapping.get('energy_keV')
        z_m = mapping.get('distance_m')
        dpix = mapping.get('pixel_size_m')

        if energy_keV:
            data['energy_keV'] = energy_keV
        if z_m:
            data['z_m'] = z_m
        if dpix:
            data['det_pixel_m'] = dpix

        if pos_unit == 'pixels':
            pos_px = pos_xy
        elif energy_keV and z_m and dpix:
            lambda_m = 1239.842e-9 / (energy_keV * 1e3)
            dx = lambda_m * z_m / (crop_size * dpix)
            data['pixel_size_nm'] = dx * 1e9
            multiplier = {
                'm': 1.0, 'mm': 1e-3, 'um': 1e-6, 'nm': 1e-9,
            }.get(pos_unit, 1.0)
            pos_m = pos_xy * multiplier
            pos_px = pos_m / dx
        else:
            multiplier = {
                'm': 1.0, 'mm': 1e-3, 'um': 1e-6, 'nm': 1e-9,
            }.get(pos_unit, 1.0)
            pos_px = pos_xy * multiplier
            if np.ptp(pos_px) < 1.0:
                pos_px = pos_px / np.ptp(pos_px, axis=0).max() * 100

        pos_px = pos_px.copy()
        pos_px -= pos_px.min(axis=0)
        pos_px += 1
        data['positions'] = pos_px.astype(np.float32)

        # 3. Load mask
        mask_file = mapping.get('mask')
        if mask_file:
            mask_path = dirpath / mask_file
            ext = mask_path.suffix.lower()
            if ext == '.npy':
                mask_raw = np.load(str(mask_path))
            elif ext in ('.tif', '.tiff'):
                from PIL import Image
                mask_raw = np.array(Image.open(str(mask_path)))
            else:
                mask_raw = None

            if mask_raw is not None:
                if crop_size != det_size:
                    mask_raw = mask_raw[c0:c1, c0:c1]
                if mask_raw.max() > 1:
                    mask_raw = (mask_raw == 0).astype(np.float32)
                else:
                    mask_raw = mask_raw.astype(np.float32)
                if center_val > corner_val * 5:
                    mask_raw = np.fft.fftshift(mask_raw)
                data['fmask'] = mask_raw

        # Default probe
        probe = self._default_probe(data['asize'])
        probe = self._scale_probe_to_data(probe, data['fmag'])
        data['probes'] = probe

        # Object size
        obj_h = int(np.ceil(data['positions'][:, 0].max())) + crop_size + 2
        obj_w = int(np.ceil(data['positions'][:, 1].max())) + crop_size + 2
        data['object_size'] = (obj_h, obj_w)

        print(f'  Directory loaded: {Npos} patterns, {crop_size}x{crop_size}, '
              f'object {obj_h}x{obj_w}')
        self.current_data = data
        return data

    def load_with_mapping(self, path, mapping):
        """Load data using explicit field mapping from user.

        mapping dict keys:
            diffraction: str - HDF5 path to diffraction data
            positions: str - HDF5 path to positions
            position_unit: str - 'pixels'|'m'|'mm'|'um'|'nm'
            position_columns: list[int] - [row_col, col_col] indices (default [0,1])
            mask: str|None - HDF5 path to mask
            probe: str|None - HDF5 path to probe
            energy_keV: float|None
            distance_m: float|None
            pixel_size_m: float|None
            projection_index: int (default 0)
            crop_size: int|None (None = use detector size)
            max_positions: int|None
        """
        import h5py
        path = Path(path)
        data = {}

        with h5py.File(path, 'r') as f:
            # --- Diffraction ---
            diff_path = mapping['diffraction']
            diff_raw = f[diff_path][()]
            projection_index = mapping.get('projection_index', 0)

            if diff_raw.ndim == 4:
                n_proj = diff_raw.shape[0]
                idx = min(projection_index, n_proj - 1)
                diff_raw = diff_raw[idx]

            if diff_raw.ndim == 3:
                s = diff_raw.shape
                if s[1] == s[2]:
                    Npos_total, det_size = s[0], s[1]
                    axis_order = 'NHW'
                elif s[0] == s[1]:
                    Npos_total, det_size = s[2], s[0]
                    axis_order = 'HWN'
                else:
                    Npos_total, det_size = s[0], s[1]
                    axis_order = 'NHW'
            else:
                raise ValueError(f'Diffraction must be 3D or 4D, got {diff_raw.ndim}D')

            # Subsample
            max_pos = mapping.get('max_positions')
            if max_pos and Npos_total > max_pos:
                idx_sel = np.linspace(0, Npos_total - 1, max_pos, dtype=int)
            else:
                idx_sel = np.arange(Npos_total)
            Npos = len(idx_sel)

            # Crop
            crop_size = mapping.get('crop_size') or det_size
            c0 = (det_size - crop_size) // 2
            c1 = c0 + crop_size

            if axis_order == 'NHW':
                patterns = diff_raw[np.ix_(idx_sel,
                    np.arange(c0, c1), np.arange(c0, c1))].astype(np.float32)
                fmag = np.transpose(patterns, (1, 2, 0))
            else:
                fmag = diff_raw[c0:c1, c0:c1, :][:, :, idx_sel].astype(np.float32)

            fmag = np.maximum(fmag, 0)
            if fmag.max() > 1e4:
                fmag = np.sqrt(fmag)

            mid = crop_size // 2
            center_val = np.mean(fmag[mid-2:mid+2, mid-2:mid+2, :])
            corner_val = np.mean(fmag[:3, :3, :])
            if center_val > corner_val * 5:
                fmag = np.fft.fftshift(fmag, axes=(0, 1))

            data['fmag'] = fmag
            data['asize'] = (crop_size, crop_size)
            data['Npos'] = Npos

            # --- Positions ---
            pos_path = mapping['positions']
            pos_raw = f[pos_path][()]
            if pos_raw.ndim == 3:
                pi = min(projection_index, pos_raw.shape[0] - 1)
                pos_raw = pos_raw[pi]
            if pos_raw.ndim == 2:
                if pos_raw.shape[0] in (2, 3) and pos_raw.shape[1] == Npos_total:
                    pos_raw = pos_raw.T
            pos_raw = pos_raw[idx_sel].astype(np.float64)

            # Select columns
            cols = mapping.get('position_columns', [0, 1])
            pos_xy = pos_raw[:, cols]

            # Unit conversion
            pos_unit = mapping.get('position_unit', 'pixels')
            energy_keV = mapping.get('energy_keV')
            z_m = mapping.get('distance_m')
            dpix = mapping.get('pixel_size_m')

            if energy_keV:
                data['energy_keV'] = energy_keV
            if z_m:
                data['z_m'] = z_m
            if dpix:
                data['det_pixel_m'] = dpix

            if pos_unit == 'pixels':
                pos_px = pos_xy
            elif energy_keV and z_m and dpix:
                lambda_m = 1239.842e-9 / (energy_keV * 1e3)
                dx = lambda_m * z_m / (crop_size * dpix)
                data['pixel_size_nm'] = dx * 1e9

                multiplier = {
                    'm': 1.0, 'mm': 1e-3, 'um': 1e-6, 'nm': 1e-9,
                }.get(pos_unit, 1.0)
                pos_m = pos_xy * multiplier
                pos_px = pos_m / dx
            else:
                # No geometry info — try best effort
                multiplier = {
                    'm': 1.0, 'mm': 1e-3, 'um': 1e-6, 'nm': 1e-9,
                }.get(pos_unit, 1.0)
                pos_px = pos_xy * multiplier
                # Scale to reasonable pixel range if still physical
                if np.ptp(pos_px) < 1.0:
                    pos_px = pos_px / np.ptp(pos_px, axis=0).max() * 100

            pos_px = pos_px.copy()
            pos_px -= pos_px.min(axis=0)
            pos_px += 1
            # No auto-swap — column order already handled by position_columns
            positions = pos_px.astype(np.float32)

            data['positions'] = positions

            # --- Mask ---
            mask_path = mapping.get('mask')
            if mask_path and mask_path in f:
                mask_raw = f[mask_path][()]
                if crop_size != det_size:
                    mask_raw = mask_raw[c0:c1, c0:c1]
                if mask_raw.max() > 1:
                    fmask = (mask_raw == 0).astype(np.float32)
                else:
                    fmask = mask_raw.astype(np.float32)
                if center_val > corner_val * 5:
                    fmask = np.fft.fftshift(fmask)
                data['fmask'] = fmask

            # --- Probe ---
            probe_path = mapping.get('probe')
            if probe_path and probe_path in f:
                probe_raw = convert_complex(f[probe_path][()]).astype(np.complex128)
                if probe_raw.ndim == 3:
                    pi = projection_index if projection_index < probe_raw.shape[0] else 0
                    probe_raw = probe_raw[pi]
                data['probes'] = probe_raw
                data['has_file_probe'] = True

        # Default probe
        if 'probes' not in data:
            probe = self._default_probe(data['asize'])
            probe = self._scale_probe_to_data(probe, data['fmag'])
            data['probes'] = probe

        # Object size
        obj_h = int(np.ceil(data['positions'][:, 0].max())) + crop_size + 2
        obj_w = int(np.ceil(data['positions'][:, 1].max())) + crop_size + 2
        data['object_size'] = (obj_h, obj_w)

        self.current_data = data
        return data

    def _count_patterns(self, diff_ds):
        """Count number of diffraction patterns from dataset shape."""
        s = diff_ds['shape']
        if len(s) == 4:
            return s[1]  # (Nangles, N, H, W)
        elif len(s) == 3:
            if s[1] == s[2]:
                return s[0]  # (N, H, W)
            elif s[0] == s[1]:
                return s[2]  # (H, W, N)
            return s[0]
        return None

    def _compute_confidence(self, ds, role):
        """Compute confidence score for a dataset-role assignment."""
        path_lower = ds['path'].lower()
        name = ds.get('name', '').lower()

        ROLE_KEYWORDS = {
            'diffraction': {
                'boost': ['data', 'diffr', 'intensity', 'pattern', 'fmag', 'frame', 'dp'],
                'anti': ['recon', 'object', 'probe', 'result', 'phase', 'amplitude'],
            },
            'positions': {
                'boost': ['position', 'translation', 'scan', 'coord', 'motor',
                          'shift', 'posi', 'encoder', 'samx', 'samy', 'spy', 'spz'],
                'anti': ['object', 'probe', 'mask', 'data'],
            },
            'mask': {
                'boost': ['mask', 'bad_pixel', 'valid', 'hotpixel', 'dead'],
                'anti': ['object', 'probe', 'data'],
            },
            'probe': {
                'boost': ['probe', 'illumination', 'beam', 'aperture'],
                'anti': ['object', 'data', 'mask', 'position'],
            },
        }

        kw = ROLE_KEYWORDS.get(role, {'boost': [], 'anti': []})
        score = 0.5  # base confidence

        for b in kw['boost']:
            if b in path_lower:
                score += 0.2
                break
        for a in kw['anti']:
            if a in path_lower:
                score -= 0.3
                break

        # Shape-based boost
        s = ds['shape']
        if role == 'diffraction' and len(s) >= 3:
            if s[-1] == s[-2]:
                score += 0.15
        elif role == 'positions' and len(s) == 2:
            if s[1] in (2, 3) or s[0] in (2, 3):
                score += 0.1
        elif role == 'mask' and len(s) == 2:
            if s[0] == s[1]:
                score += 0.15

        return round(min(max(score, 0.0), 1.0), 2)

    def _guess_position_unit(self, values, path_name):
        """Guess position unit from values and path name."""
        if values.ndim > 2:
            values = values.reshape(-1, values.shape[-1])
        if values.ndim == 2:
            range_max = float(np.ptp(values, axis=0).max())
        else:
            range_max = float(np.ptp(values))

        name = path_name.lower()

        # Name-based detection
        if '_px' in name or 'pixel' in name:
            return 'pixels', 0.95
        if '_nm' in name:
            return 'nm', 0.9
        if '_um' in name or 'micron' in name:
            return 'um', 0.9
        if '_mm' in name:
            return 'mm', 0.9

        # Range-based heuristic
        if range_max > 1000:
            return 'pixels', 0.6
        elif range_max > 10:
            return 'pixels', 0.5
        elif range_max > 0.1:
            return 'mm', 0.5
        elif range_max > 1e-4:
            return 'm', 0.7
        else:
            return 'm', 0.5

    def _guess_column_order(self, path_name):
        """Guess position column order from dataset path name.

        Returns [0,1] if likely (row,col) or [1,0] if likely (x,y).
        No auto-swap heuristic — name hints only.
        Ref: Tike docs warn "try all combinations of swapping and flipping".
        """
        name = path_name.lower()
        # (row, col) order — no swap needed
        if any(h in name for h in ('_yx', '_rc', '_px', 'pixel', 'row')):
            return [0, 1]
        # (x, y) order — swap to (row, col)
        if any(h in name for h in ('_xy', 'translation', 'motor')):
            return [1, 0]
        return [0, 1]  # default: assume row,col

    def _scale_probe_to_data(self, probe, fmag):
        """Scale probe so model intensity matches measured intensity."""
        model_fft = np.fft.fft2(probe)
        model_intensity = np.sum(np.abs(model_fft) ** 2)
        measured_intensity = np.mean(np.sum(fmag ** 2, axis=(0, 1)))
        corr = measured_intensity / max(model_intensity, 1e-30)
        return probe * np.sqrt(float(corr))

    def load_npy(self, paths):
        """
        Load from individual .npy files.
        paths: dict with keys 'fmag', 'positions', optionally 'probe', 'object'
        """
        data = {}
        if 'fmag' in paths:
            data['fmag'] = np.load(paths['fmag']).astype(np.float32)
        if 'positions' in paths:
            data['positions'] = np.load(paths['positions']).astype(np.float32)
        if 'probe' in paths:
            data['probes'] = np.load(paths['probe'])
            data['has_file_probe'] = True
        if 'object' in paths:
            data['object_true'] = np.load(paths['object'])

        if 'fmag' in data:
            data['asize'] = (data['fmag'].shape[0], data['fmag'].shape[1])

        self.current_data = data
        return data

    def generate_synthetic(self, params):
        """
        Generate synthetic ptychography data using MATLAB-compatible pipeline.

        params dict keys:
            dataset_id:    int   - Image dataset (1=Mona Lisa, 5=USAF, 6=Mandrill, 7=Chip, 8=Snellen)
            asize:         int   - Probe patch size (default 128)
            energy_keV:    float - X-ray energy (default 6.2)
            material:      str   - Material formula (default 'Au')
            objheight:     float - Object height in metres (default 1e-6)
            z_m:           float - Sample-detector distance (default 5.0)
            scan_step_um:  float - Fermat step in μm (default 1.5)
            scan_lx_um:    float - Scan range X in μm (default 10.0)
            scan_ly_um:    float - Scan range Y in μm (default 10.0)
            N_photons:     int   - Peak photon count (default 1000)
            beam_fwhm_px:  float - Beam FWHM in pixels (generates Gaussian probe)
            noise_sigma:   float - Position noise std (default 0.0)
            rng_seed:      int   - Random seed (default 42)
            overlap:       float - Scan overlap fallback (default 0.75)
        """
        from synth_ptycho import SyntheticPtycho

        # Extract parameters with MATLAB-compatible defaults
        dataset_id = params.get('dataset_id', 6)
        asize = params.get('asize', 512)
        energy_keV = params.get('energy_keV', 10.0)
        material = params.get('material', 'Au')
        objheight = params.get('objheight', 1e-6)
        z_m = params.get('z_m', 2.0)
        scan_step_um = params.get('scan_step_um', 1.5)
        scan_lx_um = params.get('scan_lx_um', 10.0)
        scan_ly_um = params.get('scan_ly_um', 10.0)
        N_photons = params.get('N_photons', 1000)
        noise_sigma = params.get('noise_sigma', 0.0)
        rng_seed = params.get('rng_seed', 42)
        overlap = params.get('overlap', 0.75)
        # Accept det_pixel_size_um from UI (μm) or legacy det_pixel_m (m)
        if 'det_pixel_size_um' in params:
            det_pixel_size_m = float(params['det_pixel_size_um']) * 1e-6
        else:
            det_pixel_size_m = params.get('det_pixel_m', 75e-6)
        # Build probe based on sim_probe_type
        probe_arr = None
        mc_probe = params.get('mc_probe', None)
        if mc_probe is not None:
            probe_arr = self._mc_hist2d_to_probe(
                mc_probe, asize, energy_keV, z_m, det_pixel_size_m)
        else:
            sim_probe_type = params.get('sim_probe_type', 'gaussian')
            lambda_m = 1.2398e-9 / energy_keV
            dx_spec = lambda_m * z_m / (asize * det_pixel_size_m)

            if sim_probe_type == 'gaussian':
                beam_fwhm_px = params.get('beam_fwhm_px', None)
                if beam_fwhm_px is None:
                    legacy_sigma = params.get('probe_sigma_px', None)
                    if legacy_sigma is not None:
                        beam_fwhm_px = float(legacy_sigma) * 2.3548
                if beam_fwhm_px is not None:
                    probe_arr = self._gaussian_beam_probe(asize, float(beam_fwhm_px))
            elif sim_probe_type in ('fresnel', 'mirror'):
                f = float(params.get('sim_focal_mm', 100)) * 1e-3
                fwhm_m = float(params.get('sim_fwhm_nm', 100)) * 1e-9
                cs_ratio = float(params.get('sim_cs_ratio', 0.0))
                defocus = float(params.get('sim_defocus_um', 0)) * 1e-6
                shape = 'rect' if sim_probe_type == 'mirror' else 'circ'
                probe_arr = self._fresnel_probe(
                    (asize, asize), lambda_m, dx_spec, f,
                    fwhm_m, fwhm_m, shape=shape,
                    defocus=defocus, cs_ratio=cs_ratio)
            elif sim_probe_type == 'nfl':
                nfl_material = params.get('sim_nfl_material', 'Be')
                N_lenses = int(params.get('sim_nfl_N', 50))
                R_m = float(params.get('sim_nfl_R_um', 50)) * 1e-6
                D_m = float(params.get('sim_nfl_D_um', 300)) * 1e-6
                defocus = float(params.get('sim_defocus_um', 0)) * 1e-6
                probe_arr, _ = self._crl_probe(
                    (asize, asize), lambda_m, dx_spec,
                    material=nfl_material, N_lenses=N_lenses,
                    R_m=R_m, D_geom_m=D_m, defocus=defocus)
            elif sim_probe_type == 'aperture':
                from server.engine_adapters.base import _make_aperture_probe
                radius_frac = float(params.get('sim_aperture_radius', 0.4))
                probe_arr = _make_aperture_probe(asize, radius_frac=radius_frac)
                # Re-normalize to asize² convention
                probe_power = float(np.sum(np.abs(probe_arr) ** 2))
                if probe_power > 0:
                    probe_arr = probe_arr * (float(asize) / np.sqrt(probe_power))
            else:
                raise ValueError(f"Unknown sim_probe_type: '{sim_probe_type}'")

        gen = SyntheticPtycho.from_dataset(
            dataset_id=dataset_id,
            asize=asize,
            energy_keV=energy_keV,
            material=material,
            objheight=objheight,
            z_m=z_m,
            det_pixel_size_m=det_pixel_size_m,
            scan_step_um=scan_step_um,
            scan_lx_um=scan_lx_um,
            scan_ly_um=scan_ly_um,
            N_photons=N_photons,
            overlap=overlap,
            probe=probe_arr,
        )
        dataset = gen.generate(noise_sigma=noise_sigma, rng_seed=rng_seed)

        # Apply EIGER2 detector mask to simulation data
        from server.detector_model import eiger2_1m_mask
        fmask = eiger2_1m_mask(asize)
        fmag = dataset.fmag
        if fmask is not None:
            for ii in range(fmag.shape[2]):
                fmag[:, :, ii] *= fmask

        # Scale probe to match fmag with ortho FFT convention (engine expectation)
        probe_scaled = self._scale_probe_to_data(dataset.probe, fmag)

        data = {
            'fmag': fmag,
            'positions': dataset.positions_clean,
            'probes': probe_scaled,
            'object_init': dataset.object_init,
            'object_true': dataset.object_true,
            'asize': (asize, asize),
            'Npos': dataset.Npos,
            'pixel_size_nm': dataset.pixel_size_nm,
            'energy_keV': dataset.energy_keV,
            'z_m': z_m,
            'det_pixel_m': det_pixel_size_m,
            'avg_step_um': dataset.avg_step_um,
            'dataset_id': dataset_id,
            'material': material,
        }
        if fmask is not None:
            data['fmask'] = fmask
        self.current_data = data
        return data

    def _gaussian_beam_probe(self, asize, fwhm_px):
        """
        Generate a Gaussian probe for simulation.

        Args:
            asize: probe array size in pixels
            fwhm_px: Full Width at Half Maximum in pixels

        Returns: complex64 ndarray of shape (asize, asize), normalized so
                 sum(|probe|^2) = asize^2 (PtychoShelves convention).
        """
        sigma = fwhm_px / 2.3548  # FWHM = 2*sqrt(2*ln(2))*sigma
        half = asize // 2
        Y, X = np.mgrid[-half:asize - half, -half:asize - half]
        R2 = (X ** 2 + Y ** 2).astype(np.float64)
        amp = np.exp(-R2 / (2.0 * sigma ** 2))

        # Normalize: sum(|probe|^2) = asize^2 (PtychoShelves p.renorm)
        probe_power = float((amp ** 2).sum())
        if probe_power > 0:
            scale = float(asize) / np.sqrt(probe_power)
            amp *= scale

        return amp.astype(np.complex64)

    def _mc_hist2d_to_probe(self, mc_probe, asize, energy_keV, z_m, det_pixel_size_m):
        """
        Convert MC ray trace 2D histogram to asize x asize probe array.

        MC hist2d is on a grid x grid array with physical extent fov_h x fov_v (metres).
        Reconstruction pixel size: dx = lambda*z / (asize * det_pixel).
        Resample MC profile onto the asize x asize grid at dx resolution.

        The probe amplitude is sqrt(intensity) since hist2d is intensity (photon count).
        Phase is assumed flat (zero) -- adequate for focused beam at sample plane.

        Returns complex64 ndarray of shape (asize, asize).
        """
        from scipy.ndimage import zoom

        hist2d = np.array(mc_probe['hist2d'], dtype=np.float64)
        grid = int(mc_probe['grid'])
        fov_h = float(mc_probe['fov_h_m'])   # half-extent in metres
        fov_v = float(mc_probe['fov_v_m'])

        # Reshape flat array to 2D (grid x grid)
        hist2d = hist2d.reshape(grid, grid)

        # MC pixel size (metres)
        mc_dx = 2.0 * fov_h / grid   # H pixel
        mc_dy = 2.0 * fov_v / grid   # V pixel

        # Reconstruction pixel size (metres)
        lambda_m = 1239.842e-9 / (energy_keV * 1e3)
        recon_dx = lambda_m * z_m / (asize * det_pixel_size_m)

        # Zoom factors: mc_pixel / recon_pixel
        zoom_h = mc_dx / recon_dx
        zoom_v = mc_dy / recon_dx

        # Resample to physical scale
        resampled = zoom(hist2d, (zoom_v, zoom_h), order=3)

        # Center crop (if resampled > asize) or center pad (if resampled < asize)
        rh, rw = resampled.shape
        probe = np.zeros((asize, asize), dtype=np.float64)
        # Source start: center crop if resampled is larger
        sy = max(0, (rh - asize) // 2)
        sx = max(0, (rw - asize) // 2)
        # Dest start: center pad if resampled is smaller
        dy = max(0, (asize - rh) // 2)
        dx = max(0, (asize - rw) // 2)
        # Copy size
        ch = min(rh, asize, asize - dy)
        cw = min(rw, asize, asize - dx)
        probe[dy:dy+ch, dx:dx+cw] = resampled[sy:sy+ch, sx:sx+cw]

        # Ensure non-negative, convert to amplitude
        probe = np.maximum(probe, 0.0)
        amp = np.sqrt(probe).astype(np.float32)

        return amp.astype(np.complex64)

    def build_p_dict(self, data, engine_params):
        """
        Build the full parameter dict 'p' required by DM/ML engines.
        data: loaded data dict
        engine_params: user-specified params (number_iterations, etc.)
        """
        fmag_raw = data['fmag']
        positions = data['positions']
        asize = data['asize']
        Npos = positions.shape[0]

        # PtychoShelves renorm: normalize fmag so probe/object values stay ~O(1).
        # renorm = sqrt(prod(asize) / max_sum) where max_sum = max per-pattern intensity.
        # After: fmag = fmag_raw * renorm, with sum(fmag²) ≈ prod(asize) for brightest pattern.
        per_pattern_sums = np.sum(fmag_raw.astype(np.float64) ** 2, axis=(0, 1))
        max_sum = float(np.max(per_pattern_sums))
        if max_sum > 0:
            max_power = max_sum / np.prod(asize)
            renorm = np.sqrt(1.0 / max_power)
        else:
            renorm = 1.0
        fmag = (fmag_raw * renorm).astype(np.float32)
        Nphot = float(np.sum(per_pattern_sums))  # total photons (from raw data)

        # Probe initialization (uses renorm-normalized fmag for consistent scaling)
        probe_init = engine_params.get('probe_init', 'fresnel')
        if probe_init == 'dataset' and 'probes' in data and data['probes'] is not None:
            probe = np.array(data['probes'], dtype=np.complex128)
        elif probe_init in ('fresnel', 'mirror', 'nfl'):
            lambda_m = engine_params.get('fresnel_lambda_m', 1.2398e-10)
            defocus = engine_params.get('fresnel_defocus_m', 0.0)
            # Inject user geometry into data for auto dx_recon computation
            self._inject_geometry(data, engine_params)
            dx_override = engine_params.get('fresnel_dx_spec_override', 0)
            dx_spec = dx_override if dx_override > 0 else self._get_recon_pixel_size(data, lambda_m, asize)

            if probe_init == 'nfl':
                # Physics-based CRL/NFL model
                material = engine_params.get('nfl_material', 'Be')
                N_lenses = int(engine_params.get('nfl_N', 50))
                R_m = engine_params.get('nfl_R_um', 50.0) * 1e-6
                D_geom_m = engine_params.get('nfl_D_um', 300.0) * 1e-6
                probe, crl_info = self._crl_probe(
                    asize, lambda_m, dx_spec, material=material,
                    N_lenses=N_lenses, R_m=R_m, D_geom_m=D_geom_m,
                    defocus=defocus)
                print(f'CRL probe: f={crl_info["f_mm"]:.1f}mm, '
                      f'D_eff={crl_info["D_eff_um"]:.0f}um, '
                      f'FWHM_pred={crl_info["fwhm_pred_nm"]:.1f}nm, '
                      f'NA={crl_info["NA"]:.2e}')
            else:
                # Fresnel (ZP/lens) or Mirror (KB)
                f = engine_params.get('fresnel_focal_m', 0.1)
                fwhm_h = engine_params.get('fresnel_fwhm_h_m', 50e-9)
                fwhm_v = engine_params.get('fresnel_fwhm_v_m', 50e-9)
                cs_ratio = engine_params.get('fresnel_cs_ratio', 0.0)
                shape = 'rect' if probe_init == 'mirror' else 'circ'
                probe = self._fresnel_probe(asize, lambda_m, dx_spec, f, fwhm_h, fwhm_v,
                                            shape=shape, defocus=defocus, cs_ratio=cs_ratio)
            probe = self._scale_probe_to_data(probe, fmag)
        else:
            # Fallback: default probe
            probe = self._default_probe(asize)
            probe = self._scale_probe_to_data(probe, fmag)

        # Object initialization
        object_init_type = engine_params.get('object_init', 'ones')
        if object_init_type == 'dataset' and 'object_init' in data and data['object_init'] is not None:
            obj_init = np.array(data['object_init'], dtype=np.complex128)
        elif object_init_type == 'stxm':
            obj_init = self._stxm_object(positions, asize, fmag, probe)
        elif object_init_type == 'random':
            obj_init = self._default_object(positions, asize)
            rng = np.random.RandomState(42)
            obj_init = obj_init * (0.9 + 0.1 * rng.rand(*obj_init.shape))
        else:  # 'ones' (default) or fallback
            if 'object_init' in data and data['object_init'] is not None:
                obj_init = np.array(data['object_init'], dtype=np.complex128)
            else:
                obj_init = self._default_object(positions, asize)

        obj_h, obj_w = obj_init.shape[:2]

        # Number of probe modes
        probe_modes = engine_params.get('probe_modes', 1)

        # Reshape probe to 4D: [Ny, Nx, numprobs, probe_modes]
        if probe.ndim == 2:
            probes_4d = probe.reshape(asize[0], asize[1], 1, 1)
            if probe_modes > 1:
                probes_4d = np.tile(probes_4d, (1, 1, 1, probe_modes))
                probes_4d = self._init_probe_modes(
                    probes_4d, asize, probe_modes, engine_params
                )
        elif probe.ndim == 3:
            probes_4d = probe.reshape(asize[0], asize[1], 1, probe.shape[2])
        else:
            probes_4d = probe

        p = {
            # Data
            'fmag': fmag,
            'positions': positions,
            'scanidxs': [np.arange(1, Npos + 1)],  # 1-based MATLAB convention
            'probes': probes_4d,
            'object': [obj_init],

            # Dimensions
            'numscans': 1,
            'asize': asize,
            'probe_modes': probe_modes,
            'object_modes': engine_params.get('object_modes', 1),
            'numprobs': 1,
            'numobjs': 1,
            'numpos': Npos,
            'numpts': [Npos],
            'object_size': np.array([[obj_h, obj_w]]),
            'renorm': renorm,
            'Nphot': Nphot,

            # Sharing
            'share_probe_ID': np.array([1]),
            'share_object_ID': np.array([0]),
            'share_probe': False,

            # Reconstruction
            'number_iterations': engine_params.get('number_iterations', 50),
            'probe_change_start': engine_params.get('probe_change_start', 1),
            'average_start': engine_params.get('number_iterations', 50) + 1,
            'average_interval': 1,

            # Pipeline iteration counts (DM_ML, DM_LSQML)
            'dm_iterations': engine_params.get('dm_iterations', 300),
            'ml_iterations': engine_params.get('ml_iterations', 100),
            'lsqml_iterations': engine_params.get('lsqml_iterations', 100),

            # Constraints
            'pfft_relaxation': engine_params.get('pfft_relaxation', 0.1),
            'fmask': np.ones(fmag.shape, dtype=np.float32),

            # Probe mask
            'probe_mask_bool': True,
            'probe_mask_use_auto': False,
            'probe_mask_area': engine_params.get('probe_support_radius', 0.9),

            # Regularization
            'probe_regularization': np.array([1.0]),
            'clip_object': False,
            'remove_scaling_ambiguity': True,

            # GPU
            'use_gpu': engine_params.get('use_gpu', False),
            'use_mex': False,

            # Preview
            'preview_interval': engine_params.get('preview_interval', 0),
        }

        # ML-specific params
        if engine_params.get('engine') in ('ML', 'DM_ML'):
            p['opt_iter'] = engine_params.get('opt_iter', 50)
            p['opt_flags'] = [1, 1]
            p['opt_errmetric'] = engine_params.get('opt_errmetric', 'poisson')
            p['opt_ftol'] = 1e-3
            p['opt_xtol'] = 1e-3
            p['reg_mu'] = 0.0
            p['smooth_gradient'] = 0

        # LSQML-specific params
        if engine_params.get('engine') in ('LSQML', 'DM_LSQML'):
            p['beta_LSQ'] = engine_params.get('beta_LSQ', 0.9)
            p['beta_probe'] = engine_params.get('beta_probe', 1.0)
            p['beta_object'] = engine_params.get('beta_object', 1.0)
            p['delta_p'] = engine_params.get('delta_p', 0.1)
            p['probe_position_search'] = engine_params.get('probe_position_search', 0)

        # rPIE/ePIE-specific params
        if engine_params.get('engine') in ('rPIE', 'ePIE'):
            p['rpie_alpha'] = engine_params.get('rpie_alpha', 0.5)
            p['rpie_beta'] = engine_params.get('rpie_beta', 0.5)
            p['rpie_obj_inertia'] = engine_params.get('rpie_obj_inertia', 0.01)
            p['rpie_probe_inertia'] = engine_params.get('rpie_probe_inertia', 0.0)
            p['rpie_position_refine_start'] = int(engine_params.get('rpie_position_refine_start', 0))
            p['rpie_obj_amp_clip'] = engine_params.get('rpie_obj_amp_clip', None)
            p['rpie_track_best'] = engine_params.get('rpie_track_best', True)
            p['rpie_mode_seed_power'] = engine_params.get('rpie_mode_seed_power', 0.01)
            p['rpie_mode_start_iter'] = int(engine_params.get('rpie_mode_start_iter', 20))

        # Apply detector mask from loaded data (all engines)
        if 'fmask' in data and data['fmask'] is not None:
            fmask_data = data['fmask']
            # Expand 2D mask to match fmag shape if needed
            if fmask_data.ndim == 2 and fmag.ndim == 3:
                fmask_data = np.broadcast_to(
                    fmask_data[:, :, np.newaxis], fmag.shape
                ).copy()
            p['fmask'] = fmask_data.astype(np.float32)

        return p

    def get_data_info(self):
        """Return summary info about currently loaded data."""
        if self.current_data is None:
            return None
        d = self.current_data
        info = {
            'fmag_shape': list(d['fmag'].shape) if 'fmag' in d else None,
            'positions_shape': list(d['positions'].shape) if 'positions' in d else None,
            'asize': list(d['asize']) if 'asize' in d else None,
            'num_positions': int(d['positions'].shape[0]) if 'positions' in d else 0,
            'has_probe': 'probes' in d and d['probes'] is not None,
            'has_file_probe': d.get('has_file_probe', False),
            'has_object_true': 'object_true' in d,
        }
        if 'probes' in d and d['probes'] is not None:
            info['probe_shape'] = list(np.array(d['probes']).shape)
        if 'object_init' in d and d['object_init'] is not None:
            info['object_shape'] = list(np.array(d['object_init']).shape)
        elif 'object_true' in d:
            info['object_shape'] = list(np.array(d['object_true']).shape)
        # Simulation metadata
        for key in ('pixel_size_nm', 'energy_keV', 'avg_step_um', 'dataset_id', 'material'):
            if key in d:
                info[key] = d[key]
        # Geometry: z_m and det_pixel for recon pixel auto-computation
        if 'z_m' in d:
            info['z_m'] = d['z_m']
        if 'det_pixel_m' in d:
            info['det_pixel_um'] = d['det_pixel_m'] * 1e6  # m → μm
        elif 'det_pixel_size_m' in d:
            info['det_pixel_um'] = d['det_pixel_size_m'] * 1e6
        return info

    def preview_probe(self, engine_params):
        """Generate probe preview without starting reconstruction.

        Works with or without loaded data.  When data is loaded, uses
        its asize and scales to measured intensity.  Otherwise uses
        a default 256x256 grid.

        Returns (probe, crl_info).
        """
        data = self.current_data
        if data is not None:
            asize = data.get('asize', (128, 128))
            fmag = data.get('fmag')
        else:
            asize = (256, 256)
            fmag = None

        probe_init = engine_params.get('probe_init', 'aperture')
        crl_info = None

        if probe_init == 'aperture':
            from server.engine_adapters.tike_adapter import TikeAdapter
            radius = engine_params.get('aperture_radius_frac', 0.4)
            probe = TikeAdapter._make_aperture_probe(
                asize[0], radius_frac=float(radius)).astype(np.complex128)
        elif probe_init in ('fresnel', 'mirror', 'nfl'):
            lambda_m = engine_params.get('fresnel_lambda_m', 1.2398e-10)
            defocus = engine_params.get('fresnel_defocus_m', 0.0)
            if data is not None:
                self._inject_geometry(data, engine_params)
            dx_override = engine_params.get('fresnel_dx_spec_override', 0)
            if data is not None:
                dx_spec = dx_override if dx_override > 0 else self._get_recon_pixel_size(data, lambda_m, asize)
            else:
                # Without data, compute from user-provided geometry
                z = engine_params.get('fresnel_z_m', 5.0)
                dp = engine_params.get('fresnel_det_pixel_um', 75.0) * 1e-6
                dx_spec = dx_override if dx_override > 0 else (lambda_m * z / (asize[0] * dp))

            if probe_init == 'nfl':
                material = engine_params.get('nfl_material', 'Be')
                N_lenses = int(engine_params.get('nfl_N', 50))
                R_m = engine_params.get('nfl_R_um', 50.0) * 1e-6
                D_geom_m = engine_params.get('nfl_D_um', 300.0) * 1e-6
                probe, crl_info = self._crl_probe(
                    asize, lambda_m, dx_spec, material=material,
                    N_lenses=N_lenses, R_m=R_m, D_geom_m=D_geom_m,
                    defocus=defocus)
            else:
                f = engine_params.get('fresnel_focal_m', 0.1)
                fwhm_h = engine_params.get('fresnel_fwhm_h_m', 50e-9)
                fwhm_v = engine_params.get('fresnel_fwhm_v_m', 50e-9)
                cs_ratio = engine_params.get('fresnel_cs_ratio', 0.0)
                shape = 'rect' if probe_init == 'mirror' else 'circ'
                probe = self._fresnel_probe(asize, lambda_m, dx_spec, f, fwhm_h, fwhm_v,
                                            shape=shape, defocus=defocus, cs_ratio=cs_ratio)
        elif probe_init == 'dataset' and data is not None and 'probes' in data:
            probe = np.array(data['probes'], dtype=np.complex128)
            if probe.ndim == 4:
                probe = probe[:, :, 0, 0]
            elif probe.ndim == 3:
                probe = probe[:, :, 0]
        else:
            probe = self._default_probe(asize)

        if fmag is not None:
            probe = self._scale_probe_to_data(probe, fmag)
        return probe, crl_info

    @staticmethod
    def _inject_geometry(data, engine_params):
        """Inject user-provided geometry (z_m, det_pixel) into data dict for dx_recon.

        Only overwrites if data doesn't already have these values from the loader.
        """
        if 'z_m' not in data:
            z = engine_params.get('fresnel_z_m_si', engine_params.get('fresnel_z_m', 0))
            if z > 0:
                data['z_m'] = z
        if 'det_pixel_m' not in data:
            dp = engine_params.get('fresnel_det_pixel_m', 0)
            if dp > 0:
                data['det_pixel_m'] = dp
        # Also inject energy if missing
        if 'energy_keV' not in data:
            lam = engine_params.get('fresnel_lambda_m', 0)
            if lam > 0:
                data['energy_keV'] = 1.2398e-9 / lam

    def _get_recon_pixel_size(self, data, lambda_m, asize):
        """Get reconstruction pixel size (specimen plane) in metres.

        Uses pixel_size_nm from data if available, otherwise computes from
        detector geometry: dx = lambda * z / (asize * det_pixel).
        Falls back to engine_params fresnel_dx_spec as last resort.
        """
        # 1. Direct from data (set by loaders)
        px_nm = data.get('pixel_size_nm', 0)
        if px_nm > 0:
            return px_nm * 1e-9

        # 2. Compute from detector geometry
        z_m = data.get('z_m', 0)
        energy_keV = data.get('energy_keV', 0)
        if z_m > 0 and energy_keV > 0:
            lam = 1.2398e-9 / energy_keV
            # Try to get detector pixel from data, default 75 μm
            det_pix = data.get('det_pixel_m', 75e-6)
            dx = lam * z_m / (asize[0] * det_pix)
            return dx

        # 3. Fallback: reasonable default for hard X-ray ptychography
        return 100e-9

    def _deref(self, f, group, key):
        """Dereference HDF5 dataset (handles MATLAB reference format)."""
        ds = group[key]
        if ds.shape == (1, 1) and ds.dtype == 'object':
            return f[ds[0, 0]][()]
        return ds[()]

    @staticmethod
    def _get_xray_material(material, energy_keV):
        """Get X-ray optical constants (delta, beta) for lens material.

        Uses reference values at 8 keV and wavelength scaling:
          delta ~ lambda^2 ~ 1/E^2
          beta  ~ lambda^(3-4) (absorption), scaled via mu ~ E^(-2.8)
        Reference: Seiboth et al., J. Synchrotron Rad. 27 (2020) 1121
        """
        # Reference values at 8 keV
        # Be: Seiboth et al. directly
        # Si, Al: from CXRO Henke tables
        ref = {
            'Be': {'delta8': 5.318e-6, 'beta8': 2.071e-9, 'mu_exp': 2.8},
            'Si': {'delta8': 7.650e-6, 'beta8': 1.740e-7, 'mu_exp': 3.0},
            'Al': {'delta8': 6.850e-6, 'beta8': 1.310e-7, 'mu_exp': 3.0},
        }
        m = ref.get(material, ref['Be'])
        ratio = 8.0 / energy_keV
        delta = m['delta8'] * ratio**2
        beta = m['beta8'] * ratio**m['mu_exp']
        return delta, beta

    def _crl_probe(self, asize, lambda_m, dx_spec, material='Be',
                   N_lenses=50, R_m=50e-6, D_geom_m=300e-6,
                   defocus=0.0, upsample=4):
        """Generate CRL/NFL probe with physics-based parameters.

        The CRL transmission T(r) = exp(-N*mu*r^2/R) * exp(i*k*N*delta*r^2/R)
        is equivalent to a Gaussian aperture (from absorption) + thin lens (from
        refraction). Key: f and FWHM are COUPLED via CRL physics — not independent.

        Physical parameters:
          f = R / (2*N*delta)        — focal length
          sigma_y = sqrt(R/(2*N*mu)) — 1/e intensity aperture radius
          D_eff = 2*sqrt(pi)*sigma_y — effective aperture diameter
          w0 = sqrt(2)*sigma_y       — 1/e^2 field amplitude radius

        The focused beam FWHM follows from Gaussian optics:
          FWHM = lambda * f * sqrt(2*ln2) / (pi * w0)

        Returns (probe, info_dict) where info_dict has computed parameters.
        """
        energy_keV = 1.2398e-9 / lambda_m
        delta, beta = self._get_xray_material(material, energy_keV)
        mu = 4.0 * np.pi * beta / lambda_m  # linear absorption coeff (1/m)

        # CRL derived parameters
        f = R_m / (2.0 * N_lenses * delta)
        sigma_y = np.sqrt(R_m / (2.0 * N_lenses * mu))  # 1/e intensity radius
        D_eff = 2.0 * np.sqrt(np.pi) * sigma_y
        # w0 = 1/e^2 field radius = sqrt(2) * sigma_y
        w0_m = np.sqrt(2.0) * sigma_y
        # Focused FWHM from Gaussian optics
        fwhm_m = lambda_m * f * np.sqrt(2.0 * np.log(2.0)) / (np.pi * w0_m)
        NA = D_eff / (2.0 * f)

        # Delegate to _fresnel_probe with shape='gauss' and CRL-derived params
        # This handles pupil grid, thin lens phase, propagation, crop, normalization
        probe = self._fresnel_probe(asize, lambda_m, dx_spec, f,
                                    fwhm_m, fwhm_m, shape='gauss',
                                    defocus=defocus, upsample=upsample)

        clipped = D_geom_m > 0 and D_geom_m < D_eff
        if clipped:
            print(f'  [CRL] Note: D_geom={D_geom_m*1e6:.0f}um < D_eff={D_eff*1e6:.0f}um '
                  f'— geometric aperture clips the Gaussian (actual beam slightly wider)')

        info = {
            'f_mm': round(float(f * 1e3), 2),
            'D_eff_um': round(float(D_eff * 1e6), 1),
            'sigma_y_um': round(float(sigma_y * 1e6), 1),
            'NA': float(NA),
            'fwhm_pred_nm': round(float(fwhm_m * 1e9), 1),
            'delta': float(delta),
            'beta': float(beta),
            'mu_per_cm': round(float(mu * 1e-2), 2),
            'D_geom_clips': bool(clipped),
        }
        return probe.astype(np.complex128), info

    def _default_probe(self, asize):
        """Create default Gaussian probe with PtychoShelves normalization."""
        ny, nx = asize
        y = np.arange(ny) - ny / 2
        x = np.arange(nx) - nx / 2
        Y, X = np.meshgrid(y, x, indexing='ij')
        sigma = ny / 4
        probe = np.exp(-(X**2 + Y**2) / (2 * sigma**2)).astype(np.complex128)
        # Normalize: sum(|probe|^2) = asize^2
        probe *= ny / np.sqrt(np.sum(np.abs(probe)**2))
        return probe

    def _gaussian_probe(self, asize):
        """Flat amplitude=1 with random phase (-pi/10 ~ pi/10), cSAXS normalized."""
        ny, nx = asize
        phase = np.random.uniform(-np.pi / 10, np.pi / 10, (ny, nx))
        probe = np.exp(1j * phase).astype(np.complex128)
        # cSAXS norm: sum(|P|^2) = asize^2
        probe *= ny / np.sqrt(np.sum(np.abs(probe)**2))
        return probe

    @staticmethod
    def _prop_free_ff(win, lambda_m, z, pixsize):
        """Fresnel free-space propagation (far-field)."""
        N = win.shape[0]
        z_n = z / pixsize
        lam_n = lambda_m / pixsize
        x = np.arange(-N // 2, N - N // 2, dtype=np.float64)
        xx, yy = np.meshgrid(x, x)
        r2 = xx**2 + yy**2
        src_phase = np.exp(1j * np.pi * r2 / (lam_n * z_n))
        ft = np.fft.fft2(np.fft.fftshift(win * src_phase))
        ft = np.fft.ifftshift(ft)
        obs_phase = np.exp(1j * np.pi * lam_n * z_n * r2 / N**2)
        return -1j * obs_phase * ft

    def _fresnel_probe(self, asize, lambda_m, dx_spec, f,
                       fwhm_h_m, fwhm_v_m, shape='circ', upsample=4,
                       defocus=0.0, cs_ratio=0.0):
        """Generate Fresnel probe via zone plate / lens model.

        Copied from K4GSR-Beamline ProbeGen (ptycho/_old_tests/compare_recon.py).
        Aperture -> thin lens phase -> Fresnel propagation -> crop -> apodize -> normalize.

        shape: 'circ' = FZP/thin lens (hard edge), 'gauss' = NFL/CRL (Gaussian),
               'rect' = KB mirror (rectangular).
        cs_ratio: central stop ratio (0 = no beamstop, e.g. 0.3 = 30% of ZP blocked).
        """
        ny, nx = asize
        N = upsample * ny
        # Pupil pixel size: must use (f+defocus) so output pixel = dx_spec exactly
        # (matches MATLAB PtychoShelves ptycho_model_probe.m L101)
        prop_dist = f + defocus
        dx_pupil = prop_dist * lambda_m / (N * dx_spec)
        x = np.arange(-N // 2, N - N // 2, dtype=np.float64)
        xx, yy = np.meshgrid(x, x)
        r2 = xx**2 + yy**2

        if shape == 'gauss':
            # NFL/CRL: Gaussian apodized aperture (absorption in lens material)
            # For a Gaussian pupil E(r) = exp(-r^2/w0^2):
            #   focused FWHM = lambda*f*sqrt(2*ln2) / (pi*w0)
            #   => w0 = lambda*f*sqrt(2*ln2) / (pi*FWHM)
            fwhm_avg = (fwhm_h_m + fwhm_v_m) / 2.0
            w0_m = lambda_m * f * np.sqrt(2.0 * np.log(2.0)) / (np.pi * fwhm_avg)
            w0_pix = w0_m / dx_pupil
            r = np.sqrt(r2)
            w = np.exp(-r**2 / w0_pix**2)
        elif shape == 'circ':
            fwhm_avg = (fwhm_h_m + fwhm_v_m) / 2.0
            aperture_m = 0.886 * lambda_m * 2.0 * f / fwhm_avg
            r_pix = aperture_m / (2.0 * dx_pupil)
            r = np.sqrt(r2)
            edge_w = max(5, int(r_pix * 0.02) + 1)
            inner = r_pix - edge_w
            outer = r_pix + edge_w
            w = np.zeros_like(r)
            w[r <= inner] = 1.0
            transition = (r > inner) & (r < outer)
            w[transition] = 0.5 * (1.0 + np.cos(
                np.pi * (r[transition] - inner) / (outer - inner)))
            # Central stop (beamstop) for zone plate
            if cs_ratio > 0:
                cs_r_pix = r_pix * cs_ratio
                cs_edge = max(3, int(cs_r_pix * 0.05) + 1)
                cs_inner = cs_r_pix - cs_edge
                cs_outer = cs_r_pix + cs_edge
                w[r <= cs_inner] = 0.0
                cs_trans = (r > cs_inner) & (r < cs_outer)
                w[cs_trans] = 0.5 * (1.0 - np.cos(
                    np.pi * (r[cs_trans] - cs_inner) / (cs_outer - cs_inner)))
        else:
            aperture_h = 0.886 * lambda_m * f / fwhm_h_m
            aperture_v = 0.886 * lambda_m * f / fwhm_v_m
            hw_h = aperture_h / (2.0 * dx_pupil)
            hw_v = aperture_v / (2.0 * dx_pupil)
            edge_w_h = max(5, int(hw_h * 0.02) + 1)
            edge_w_v = max(5, int(hw_v * 0.02) + 1)
            ax = np.abs(xx[0, :])
            wh = np.zeros(N, dtype=np.float64)
            wh[ax <= hw_h - edge_w_h] = 1.0
            th = (ax > hw_h - edge_w_h) & (ax < hw_h + edge_w_h)
            wh[th] = 0.5 * (1.0 + np.cos(np.pi * (ax[th] - (hw_h - edge_w_h)) / (2 * edge_w_h)))
            ay = np.abs(yy[:, 0])
            wv = np.zeros(N, dtype=np.float64)
            wv[ay <= hw_v - edge_w_v] = 1.0
            tv = (ay > hw_v - edge_w_v) & (ay < hw_v + edge_w_v)
            wv[tv] = 0.5 * (1.0 + np.cos(np.pi * (ay[tv] - (hw_v - edge_w_v)) / (2 * edge_w_v)))
            w = wv[:, np.newaxis] * wh[np.newaxis, :]

        # Thin lens phase + Fresnel propagation
        # Lens phase uses focal length f; propagation distance = f + defocus
        # (matches MATLAB PtychoShelves ptycho_model_probe.m L126)
        lens_phase = np.exp(-1j * np.pi * r2 * dx_pupil**2 / (lambda_m * f))
        probe_hr = self._prop_free_ff(w * lens_phase, lambda_m, prop_dist, dx_pupil)

        # Crop to asize
        c = N // 2
        hy, hx = ny // 2, nx // 2
        probe = probe_hr[c - hy:c + hy, c - hx:c + hx].copy()

        # Apodization
        ax2 = np.arange(ny, dtype=np.float64) - ny / 2.0
        ax2x = np.arange(nx, dtype=np.float64) - nx / 2.0
        axx, ayy = np.meshgrid(ax2x, ax2)
        ar = np.sqrt(axx**2 + ayy**2)
        taper = np.clip((ny * 0.50 - ar) / (ny * 0.08), 0.0, 1.0)
        probe *= taper

        # cSAXS norm: sum(|P|^2) = asize^2
        power = float((np.abs(probe)**2).sum())
        if power > 0:
            probe *= ny / np.sqrt(power)
        return probe.astype(np.complex128)

    def _init_probe_modes(self, probes_4d, asize, probe_modes, engine_params):
        """
        Initialize multi-mode probe using Hermite-like basis.

        Port of MATLAB +core/prepare_initial_probes.m L79-143.

        Parameters
        ----------
        probes_4d : ndarray (Ny, Nx, 1, probe_modes)
            Probe array with mode 0 set, modes 1+ to be initialized.
        asize : array-like
            Probe size [Ny, Nx].
        probe_modes : int
            Number of probe modes.
        engine_params : dict
            Engine parameters. Uses:
            - mode_start : str ('herm' or 'rand', default 'herm')
            - mode_start_pow : list of float (default [0.02])

        Returns
        -------
        probes_4d : ndarray
            Probe array with all modes initialized and energy-normalized.
        """
        mode_start = engine_params.get('mode_start', 'herm')
        mode_start_pow = engine_params.get('mode_start_pow', [0.02])
        if isinstance(mode_start_pow, (int, float)):
            mode_start_pow = [mode_start_pow]

        # Energy distribution — prepare_initial_probes.m L85-97
        Emod = np.zeros(probe_modes)
        for jj in range(1, probe_modes):
            idx = min(jj - 1, len(mode_start_pow) - 1)
            Emod[jj] = mode_start_pow[idx]
        if np.sum(Emod) >= 1.0:
            raise ValueError(
                'Energy distribution between modes exceeds 1, '
                'see mode_start_pow'
            )
        Emod[0] = 1.0 - np.sum(Emod)  # Mode 0 gets remaining energy

        # Total energy of mode 0 — prepare_initial_probes.m L104
        fundam = probes_4d[:, :, 0, 0]
        Etot = np.sum(np.abs(fundam) ** 2)
        Emod_energy = Emod * Etot

        if mode_start == 'herm':
            # Hermite-like initialization — prepare_initial_probes.m L107-128
            from core.hermite_like import hermite_like

            # M, N from probe_modes — prepare_initial_probes.m L109-110
            M = int(np.ceil(np.sqrt(probe_modes))) - 1
            N = int(np.ceil(probe_modes / (M + 1))) - 1

            # Coordinate grids — prepare_initial_probes.m L118-120
            x = np.arange(asize[1]) - asize[1] / 2
            y = np.arange(asize[0]) - asize[0] / 2
            X, Y = np.meshgrid(x, y)

            H = hermite_like(fundam, X, Y, M, N)

            # Copy modes (H may have more modes than needed)
            for m in range(1, probe_modes):
                if m < H.shape[2]:
                    probes_4d[:, :, 0, m] = H[:, :, m]

        elif mode_start == 'rand':
            # Random initialization — prepare_initial_probes.m L103-106
            for m in range(1, probe_modes):
                probes_4d[:, :, 0, m] = fundam * (
                    2 * np.random.rand(*asize) - 1
                )
        else:
            raise ValueError(f'Unknown mode_start: {mode_start}')

        # Normalize each mode to expected energy — prepare_initial_probes.m L134-137
        for m in range(probe_modes):
            mode_energy = np.sum(np.abs(probes_4d[:, :, 0, m]) ** 2)
            if mode_energy > 0:
                probes_4d[:, :, 0, m] *= np.sqrt(
                    Emod_energy[m] / mode_energy
                )

        return probes_4d

    def _default_object(self, positions, asize):
        """Create default uniform object covering all positions + asize margin."""
        rows = positions[:, 0]
        cols = positions[:, 1]
        # Object must cover max_pos + asize (patch extracted at position)
        obj_h = int(np.ceil(rows.max())) + asize[0] + 2
        obj_w = int(np.ceil(cols.max())) + asize[1] + 2
        return np.ones((obj_h, obj_w), dtype=np.complex128)

    def _stxm_object(self, positions, asize, fmag, probe):
        """Initialize object amplitude from STXM intensity map.

        Physics: Parseval's theorem => sum(|fmag|^2) = sum(|P*O|^2) ~ |P|^2 * |O|^2
        Therefore |O| ~ sqrt(I_stxm / I_probe)
        Phase: initialized to 0 (algorithm discovers phase).
        """
        obj = self._default_object(positions, asize)
        visit_count = np.zeros(obj.shape, dtype=np.float64)
        probe_power = float(np.sum(np.abs(probe) ** 2))

        for i in range(positions.shape[0]):
            r = int(np.round(positions[i, 0]))
            c = int(np.round(positions[i, 1]))
            intensity = float(np.sum(fmag[:, :, i].astype(np.float64) ** 2))
            amplitude = np.sqrt(intensity / max(probe_power, 1e-30))
            r2, c2 = r + asize[0], c + asize[1]
            obj[r:r2, c:c2] += amplitude
            visit_count[r:r2, c:c2] += 1.0

        mask = visit_count > 0
        obj[mask] = obj[mask] / visit_count[mask]
        obj[~mask] = 1.0  # unvisited = transparent
        obj = np.clip(np.abs(obj), 0.01, 1.5).astype(np.complex128)
        return obj
