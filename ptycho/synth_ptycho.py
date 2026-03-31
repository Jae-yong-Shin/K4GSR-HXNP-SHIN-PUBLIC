"""
synth_ptycho.py
===============
Python port of PtychoShelves synthetic ptychography data generator.

Ported faithfully from:
  +scans/+positions/matlab_pos.m          (Fermat spiral positions)
  +detector/+virtual/create_object.m      (object encoding)
  +detector/+virtual/private/
      generate_virtual_object.m           (object images)
  +detector/+virtual/load_data.m          (forward model + noise)

Key algorithmic differences from a naive generator:
  - Fermat spiral:  r = step * 0.57 * sqrt(ir),  ir = 1, 2, ...
                    phi = 2π × golden_ratio  (≈ 10.166 rad)
                    (MATLAB: phi = 2*pi*(1+sqrt(5))/2 + b*pi, b=0)
  - Probe:          loaded from probe_PSI.mat and cropped to asize
  - Object:         complex phase transmission
                    exp(i * 2π/λ * (iβ − δ) * (1 − obj) * h)
  - Noise:          photons_per_pixel × scan_area  (MATLAB convention)
                    OR peak N_photons normalization  (simple mode)

Usage
-----
    from synth_ptycho import SyntheticPtycho, load_object_true

    obj = load_object_true('matlab_posref_comparison_ds5.mat')

    gen = SyntheticPtycho(
        object    = obj,
        asize     = 128,
        overlap   = 0.75,       # determines Fermat step (see note below)
        N_photons = 1000,
    )
    data = gen.generate(noise_sigma=3.0, rng_seed=42)

Note on step / overlap
----------------------
The MATLAB Fermat uses p.scan.step in physical units (metres).
You can supply step in physical units (μm) via `scan_step_um` together
with `energy_keV`, `z_m`, `det_pixel_size_m`.  The pixel size is then
computed as:
    pixel_size_m = λ × z / (asize × det_pixel_size)
and the step is converted: step_px = scan_step_um × 1e-6 / pixel_size_m.

Alternatively supply `scan_step_px` directly (pixel units), or set
`overlap` to derive the step from the probe FWHM.

Reference experimental parameters (MATLAB template_artificial_data.m):
    energy = 6.2 keV, z = 5 m, asize = 128 px, det_pixel_size = 75 μm
    → pixel_size ≈ 104 nm/px
    scan.step = 1.5 μm → ~14 px

Minimum scan positions
----------------------
Minimum MIN_POS = 144 (≥ 12×12) positions are enforced.  If the requested
step would give fewer positions within the scan range, step is reduced
automatically (actual_ovlp > requested overlap).
"""

import numpy as np
import scipy.io
import h5py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

# ── default path to test images ──────────────────────────────────────────────
_DEFAULT_IMGS = Path(__file__).parent / "data" / "imgs"

# Fallback: PtychoShelves location (if data/imgs doesn't exist)
_FALLBACK_IMGS = (
    Path(__file__).parent.parent
    / "Tomography algorithm"
    / "cSAXS_ptycho"
    / "cSAXS_matlab_ptycho_package"
    / "utils"
    / "imgs"
)

def _get_imgs_path(custom_path=None):
    """Resolve image directory path."""
    if custom_path:
        return Path(custom_path)
    if _DEFAULT_IMGS.exists():
        return _DEFAULT_IMGS
    if _FALLBACK_IMGS.exists():
        return _FALLBACK_IMGS
    return _DEFAULT_IMGS  # will fail later with clear error


# ── Dataset definitions (MATLAB generate_virtual_object.m) ───────────────────
DATASETS = {
    1: {'name': 'Mona Lisa',      'file': 'ML512.jpg',         'channel': 0},
    5: {'name': 'USAF-1951',      'file': 'USAF-1951.png',     'channel': 0, 'invert': True, 'threshold': 128},
    6: {'name': 'Mandrill',       'file': 'mandrill.png',       'channel': None},  # grayscale
    7: {'name': 'Chip Phantom',   'file': 'chip_phantom.png',   'channel': 0},
    8: {'name': 'Snellen Chart',  'file': 'Snellen_chart.png',  'channel': 3, 'threshold': 50, 'downsample': 2},
}


# ── Refractive index table (Henke CXRO database values) ─────────────────────
# Format: {material: {energy_keV: (delta, beta)}}
# Pre-computed from http://henke.lbl.gov/ for common materials at common energies
_REF_INDEX_TABLE = {
    'Au': {
        6.2:  (4.6596e-5, 5.2813e-6),
        8.0:  (2.8200e-5, 3.6927e-6),
        8.7:  (2.3870e-5, 3.0510e-6),
        10.0: (1.8100e-5, 2.2570e-6),
        12.4: (1.1800e-5, 1.3800e-6),
    },
    'Si': {
        6.2:  (5.4890e-6, 7.7240e-8),
        8.0:  (3.3080e-6, 1.7510e-7),
        10.0: (2.1190e-6, 4.7270e-8),
        12.4: (1.3760e-6, 2.0090e-8),
    },
    'SiO2': {
        6.2:  (6.7230e-6, 8.2280e-8),
        8.0:  (4.0500e-6, 1.5010e-7),
        10.0: (2.5920e-6, 4.7540e-8),
        12.4: (1.6840e-6, 2.0900e-8),
    },
    'Cu': {
        6.2:  (2.3400e-5, 3.0670e-6),
        8.0:  (1.4100e-5, 2.1380e-6),
        8.97: (1.1200e-5, 5.1600e-6),  # above K-edge
        10.0: (9.0470e-6, 5.7310e-7),
        12.4: (5.8780e-6, 2.9810e-7),
    },
    'W': {
        6.2:  (5.1760e-5, 7.1170e-6),
        8.0:  (3.1200e-5, 4.1180e-6),
        10.0: (2.0000e-5, 5.2150e-6),
        12.4: (1.2990e-5, 2.6700e-6),
    },
    'Pt': {
        6.2:  (5.3300e-5, 5.1960e-6),
        8.0:  (3.2100e-5, 3.6100e-6),
        10.0: (2.0580e-5, 4.1280e-6),
        12.4: (1.3360e-5, 2.1640e-6),
    },
}


def get_ref_index(formula: str, energy_keV: float) -> tuple:
    """
    Get refractive index (delta, beta) for a material at given energy.

    Port of MATLAB +utils/get_ref_index.m
    Uses built-in table with interpolation. Falls back to Henke web query.

    Returns: (delta, beta)  where n = 1 - delta + i*beta
    """
    formula = formula.strip()

    # Try built-in table with nearest energy interpolation
    if formula in _REF_INDEX_TABLE:
        table = _REF_INDEX_TABLE[formula]
        energies = sorted(table.keys())

        # Exact match
        if energy_keV in table:
            return table[energy_keV]

        # Interpolate between nearest energies
        if energy_keV <= energies[0]:
            return table[energies[0]]
        if energy_keV >= energies[-1]:
            return table[energies[-1]]

        # Find bracketing energies
        for i in range(len(energies) - 1):
            if energies[i] <= energy_keV <= energies[i + 1]:
                e0, e1 = energies[i], energies[i + 1]
                d0, b0 = table[e0]
                d1, b1 = table[e1]
                # Log-linear interpolation (refractive index scales ~1/E²)
                t = (energy_keV - e0) / (e1 - e0)
                delta = np.exp(np.log(d0) * (1 - t) + np.log(d1) * t)
                beta = np.exp(np.log(max(b0, 1e-15)) * (1 - t) + np.log(max(b1, 1e-15)) * t)
                return (delta, beta)

    # Fallback: try Henke web query
    try:
        return _henke_web_query(formula, energy_keV)
    except Exception:
        pass

    raise ValueError(
        f"No refractive index data for '{formula}' at {energy_keV} keV. "
        f"Available materials: {list(_REF_INDEX_TABLE.keys())}"
    )


def _henke_web_query(formula: str, energy_keV: float) -> tuple:
    """Query Henke CXRO database (http://henke.lbl.gov/) for refractive index."""
    import urllib.request
    import urllib.parse

    energy_eV = int(energy_keV * 1000)
    params = urllib.parse.urlencode({
        'Material': 'Enter+Formula',
        'Formula': formula,
        'Density': -1,
        'Scan': 'Energy',
        'Min': energy_eV,
        'Max': energy_eV,
        'Npts': 1,
        'Output': 'Text+File',
    })

    url = 'http://henke.lbl.gov/cgi-bin/getdb.pl'
    req = urllib.request.Request(url, data=params.encode('ascii'))
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode('ascii', errors='ignore')

    # Parse response to find .dat file URL
    idx = html.find('/tmp')
    if idx < 0:
        raise RuntimeError('Could not parse Henke response')
    dat_path = html[idx:].split('.')[0] + '.dat'

    dat_url = f'http://henke.lbl.gov{dat_path}'
    with urllib.request.urlopen(dat_url, timeout=10) as resp:
        dat = resp.read().decode('ascii', errors='ignore')

    lines = dat.strip().split('\n')
    # Line 0: density, Line 2+: energy delta beta
    parts = lines[2].split()
    delta = float(parts[1])
    beta = float(parts[2])
    return (delta, beta)


def load_dataset_image(dataset_id: int, imgs_path=None) -> np.ndarray:
    """
    Load a test image by dataset ID (MATLAB generate_virtual_object.m port).

    Returns: 2D float32 array normalized to [0, 1], representing thickness map.
    """
    from PIL import Image

    imgs_path = _get_imgs_path(imgs_path)

    if dataset_id not in DATASETS:
        avail = ', '.join(f'{k}: {v["name"]}' for k, v in DATASETS.items())
        raise ValueError(
            f"Dataset {dataset_id} not found. Available: {{{avail}}}"
        )

    info = DATASETS[dataset_id]
    img_path = imgs_path / info['file']
    if not img_path.exists():
        raise FileNotFoundError(f"Image not found: {img_path}")

    img = Image.open(img_path)

    # Convert to grayscale float
    img_arr = np.array(img)
    if info.get('channel') is not None and img_arr.ndim >= 3:
        img_arr = img_arr[:, :, info['channel']]
    elif img_arr.ndim == 3:
        img_arr = img_arr.mean(axis=2)

    obj = img_arr.astype(np.float64)

    # Dataset-specific processing (matching MATLAB exactly)
    if info.get('invert'):
        obj = 255.0 - obj

    if info.get('threshold') is not None:
        # Binary mask for sharp edges
        binary = (obj < info['threshold']).astype(np.float64) if dataset_id == 5 else \
                 (obj > info['threshold']).astype(np.float64)
        # Blend with normalized continuous map for smooth phase variation
        vmax = obj.max()
        cont = obj / vmax if vmax > 0 else obj
        obj = 0.7 * binary + 0.3 * cont
    else:
        vmax = obj.max()
        if vmax > 0:
            obj = obj / vmax

    if info.get('downsample'):
        ds = info['downsample']
        obj = obj[::ds, ::ds]

    return obj.astype(np.float32)


def create_complex_object(
    thickness_map: np.ndarray,
    object_size: tuple,
    energy_keV: float = 6.2,
    material: str = 'Au',
    objheight: float = 1e-6,
) -> np.ndarray:
    """
    Convert thickness map to complex transmission object.

    Port of MATLAB create_object.m:
        ref_index = get_ref_index(material, energy)
        delta, beta = ref_index
        lambda = hc / E
        obj = rot90(exp(i * 2pi/lambda * (i*beta - delta) * (1 - thickness) * h), 2)

    Args:
        thickness_map: 2D float [0,1] from load_dataset_image()
        object_size: (height, width) target object size in pixels
        energy_keV: X-ray energy
        material: chemical formula
        objheight: object height in metres

    Returns: complex64 object array
    """
    delta, beta = get_ref_index(material, energy_keV)
    lambda_m = 1239.842e-9 / (energy_keV * 1e3)  # hc / E [m]

    # MATLAB: repmat(object, 5, 5) — tile to avoid void space
    tiled = np.tile(thickness_map, (5, 5))

    # crop_pad to object_size
    obj = _crop_pad_center(tiled, object_size)

    # MATLAB: exp(i * (2*pi/lambda) * (i*beta - delta) * (1 - obj) * objheight)
    phase_factor = (2 * np.pi / lambda_m) * (1j * beta - delta) * (1 - obj) * objheight
    complex_obj = np.exp(1j * phase_factor)

    # MATLAB: rot90(obj, 2)
    complex_obj = np.rot90(complex_obj, 2)

    return complex_obj.astype(np.complex64)

# Warn if fewer than this many positions are generated
_WARN_POS = 30


# ── data container ────────────────────────────────────────────────────────────

@dataclass
class PtychoDataset:
    fmag:            np.ndarray   # [Ny, Nx, Npos] float32
    positions_clean: np.ndarray   # [Npos, 2] float32  (row, col) in pixels
    positions_noisy: np.ndarray   # [Npos, 2] float32
    position_noise:  np.ndarray   # [Npos, 2] float32
    probe:           np.ndarray   # [Ny, Nx] complex64  (ground truth)
    object_init:     np.ndarray   # [obj_h, obj_w] complex64 (initial guess = ones)
    object_true:     np.ndarray   # [obj_h, obj_w] complex64

    # Metadata
    asize:     int
    overlap:   float      # actual overlap (from NN distances)
    N_photons: int        # peak photons (or equivalent)
    Npos:      int
    avg_step:  float      # average nearest-neighbour step (px)
    probe_fwhm: float     # estimated probe FWHM (px)

    # Physical unit metadata (0.0 if not provided)
    pixel_size_nm: float = 0.0   # real-space pixel size in nm
    energy_keV:    float = 0.0   # X-ray energy in keV
    avg_step_um:   float = 0.0   # average NN step in μm (0 if pixel_size unknown)


# ── loaders ───────────────────────────────────────────────────────────────────

def load_object_true(mat_path) -> np.ndarray:
    """
    Load object_true from a MATLAB v7.3 .mat file (h5py).
    Returns complex64 ndarray.
    """
    mat_path = Path(mat_path)
    with h5py.File(mat_path, 'r') as f:
        v = f['object_true'][()]
        if v.dtype.names and 'real' in v.dtype.names:
            return (v['real'] + 1j * v['imag']).T.astype(np.complex64)
        return v.T.astype(np.complex64)


def load_probe_PSI(asize: int, imgs_path=None) -> np.ndarray:
    """
    Load probe from probe_PSI.mat (PtychoShelves utils/imgs/),
    crop / pad to asize × asize, and normalize to PtychoShelves convention.

    PtychoShelves normalizes the probe so that:
        sum(|probe|²) = asize²   (p.renorm convention in initialize_ptycho.m)
    MATLAB probe_init always has total_power = asize² = 16384 for asize=128.

    Returns complex64.
    """
    imgs_path = _get_imgs_path(imgs_path)
    probe_path = imgs_path / 'probe_PSI.mat'
    d = scipy.io.loadmat(str(probe_path))
    probe = d['probe'].astype(np.complex64)   # (192, 192)
    if probe.shape[0] != asize or probe.shape[1] != asize:
        probe = _crop_pad_center(probe, (asize, asize))

    # Normalize: sum(|probe|²) = asize²  (PtychoShelves p.renorm convention)
    # Without this, raw probe_PSI has power ~496644 vs MATLAB's 16384 → 30× mismatch
    probe_power = float((np.abs(probe) ** 2).sum())
    if probe_power > 0:
        scale = float(asize) / np.sqrt(probe_power)
        probe = (probe * scale).astype(np.complex64)

    return probe


def estimate_probe_fwhm(probe: np.ndarray) -> float:
    """Estimate probe FWHM (px) from its real-space amplitude."""
    amp = np.abs(probe)
    amp_flat = amp.ravel()
    half_max = amp.max() * 0.5
    # Count pixels above half-max → area → effective radius → FWHM
    n_above = float((amp_flat >= half_max).sum())
    r_eff = np.sqrt(n_above / np.pi)
    return 2.0 * r_eff   # FWHM ≈ 2 × effective radius


def _crop_pad_center(arr: np.ndarray, out_shape: Tuple[int, int]) -> np.ndarray:
    """Crop or zero-pad 2-D array centred on the array centre."""
    in_h, in_w = arr.shape[:2]
    out_h, out_w = out_shape
    out = np.zeros((out_h, out_w) + arr.shape[2:], dtype=arr.dtype)
    sh = min(in_h, out_h)
    sw = min(in_w, out_w)
    sr0 = (in_h - sh) // 2
    sc0 = (in_w - sw) // 2
    dr0 = (out_h - sh) // 2
    dc0 = (out_w - sw) // 2
    out[dr0:dr0 + sh, dc0:dc0 + sw] = arr[sr0:sr0 + sh, sc0:sc0 + sw]
    return out


# ── generator ─────────────────────────────────────────────────────────────────

class SyntheticPtycho:
    """
    Synthetic ptychography dataset generator — Python port of PtychoShelves.

    Parameters
    ----------
    object         : np.ndarray - complex64 ground-truth object [obj_h, obj_w].
                     Use load_object_true() for MATLAB-generated objects.
    probe          : np.ndarray or None - complex64 probe [asize, asize].
                     If None, probe_PSI.mat is loaded from PtychoShelves.
    asize          : int - probe / diffraction patch size in pixels
    overlap        : float - target scan overlap (0 to 0.95).
                     Ignored if scan_step_px or scan_step_um is provided.
    scan_step_px   : float or None - Fermat step parameter in pixels.
                     Equivalent to p.scan.step in MATLAB (before 0.57 factor).
                     Overridden by scan_step_um if physical params are given.
    scan_step_um   : float or None - Fermat step in micrometres (physical).
                     Requires energy_keV, z_m, det_pixel_size_m to be set.
    scan_lx_um     : float or None - scan range along x in μm.  If None,
                     scan range is derived from object dimensions.
    scan_ly_um     : float or None - scan range along y in μm.
    energy_keV     : float - X-ray photon energy in keV (for pixel size calc).
                     Default 0 = physical unit conversion disabled.
    z_m            : float - sample-to-detector distance in metres.
    det_pixel_size_m: float - detector pixel pitch in metres.
    N_photons      : int - peak photons for fmag normalisation (simple mode).
                     Only used when photons_per_pixel is None.
    photons_per_pixel : float or None - MATLAB-style dose normalisation.
                     total_dose = photons_per_pixel * scan_area_px².
                     If None, peak N_photons normalisation is used.
    probe_sigma_px : float - Gaussian fallback probe sigma (px) used only
                     when probe=None AND probe_PSI.mat cannot be found.
    scan_margin    : int - extra margin from object boundary
    imgs_path      : path to PtychoShelves utils/imgs/ (for probe_PSI.mat)
    """

    def __init__(
        self,
        object:             np.ndarray,
        probe:              Optional[np.ndarray] = None,
        asize:              int   = 128,
        overlap:            float = 0.75,
        scan_step_px:       Optional[float] = None,
        scan_step_um:       Optional[float] = None,
        scan_lx_um:         Optional[float] = None,
        scan_ly_um:         Optional[float] = None,
        energy_keV:         float = 0.0,
        z_m:                float = 5.0,
        det_pixel_size_m:   float = 75e-6,
        N_photons:          int   = 1000,
        photons_per_pixel:  Optional[float] = None,
        probe_sigma_px:     float = 25.0,
        scan_margin:        int   = 0,
        imgs_path:          Optional[str] = None,
    ):
        self.object_true   = object.astype(np.complex64)
        self.asize         = int(asize)
        self.Ny = self.Nx  = self.asize
        self.overlap       = float(overlap)
        self.N_photons     = int(N_photons)
        self.photons_per_pixel = photons_per_pixel
        self.scan_margin   = int(scan_margin)
        self._imgs_path    = imgs_path

        # Physical experiment parameters
        self.energy_keV        = float(energy_keV)
        self.z_m               = float(z_m)
        self.det_pixel_size_m  = float(det_pixel_size_m)
        self._scan_lx_um       = float(scan_lx_um) if scan_lx_um is not None else None
        self._scan_ly_um       = float(scan_ly_um) if scan_ly_um is not None else None

        # Resolve scan step: μm → px > direct px > derived from overlap
        ps = self.pixel_size_m   # None if energy_keV == 0
        if scan_step_um is not None and ps is not None:
            self.scan_step_px = scan_step_um * 1e-6 / ps
        elif scan_step_px is not None:
            self.scan_step_px = float(scan_step_px)
        else:
            self.scan_step_px = None   # derived from overlap later

        # ── load / build probe ────────────────────────────────────────────
        if probe is not None:
            self.probe = probe.astype(np.complex64)
        else:
            try:
                self.probe = load_probe_PSI(self.asize, self._imgs_path)
            except Exception:
                # Gaussian fallback when probe_PSI.mat is not available
                Y, X = np.mgrid[-self.Ny//2:self.Ny//2, -self.Nx//2:self.Nx//2]
                R2 = (X**2 + Y**2).astype(np.float32)
                amp = np.exp(-R2 / (2.0 * probe_sigma_px**2)).astype(np.float32)
                self.probe = amp.astype(np.complex64)

        # keep original amplitude (do NOT normalise here).
        # In MATLAB: probe is scaled together with fmag by sqrt(corr_ratio)
        # inside the forward simulation.  We replicate this in generate().

        # ── probe FWHM ────────────────────────────────────────────────────
        self.probe_fwhm = estimate_probe_fwhm(self.probe)

    @classmethod
    def from_dataset(
        cls,
        dataset_id:     int   = 6,
        asize:          int   = 128,
        energy_keV:     float = 6.2,
        material:       str   = 'Au',
        objheight:      float = 1e-6,
        z_m:            float = 5.0,
        det_pixel_size_m: float = 75e-6,
        scan_step_um:   Optional[float] = 1.5,
        scan_lx_um:     Optional[float] = 10.0,
        scan_ly_um:     Optional[float] = 10.0,
        N_photons:      int   = 1000,
        photons_per_pixel: Optional[float] = None,
        overlap:        float = 0.75,
        imgs_path:      Optional[str] = None,
        probe_sigma_px: Optional[float] = None,
        probe:          Optional[np.ndarray] = None,
    ):
        """
        Create SyntheticPtycho from a dataset ID (MATLAB-compatible).

        This replicates the MATLAB test pipeline:
            test_data.m -> template_artificial_data.m -> create_object.m -> load_data.m

        Default parameters match MATLAB GPU_engines_test.m:
            dataset=6 (mandrill), asize=128, energy=6.2keV, material=Au,
            z=5m, scan_step=1.5um, scan_lx=scan_ly=10um

        Args:
            dataset_id: Image dataset (1=Mona Lisa, 5=USAF, 6=Mandrill,
                        7=Chip, 8=Snellen). See DATASETS dict.
            asize: Probe/diffraction patch size in pixels
            energy_keV: X-ray photon energy
            material: Chemical formula for refractive index
            objheight: Object height in metres (thickness)
            z_m: Sample-to-detector distance in metres
            det_pixel_size_m: Detector pixel pitch in metres
            scan_step_um: Fermat spiral step in micrometres
            scan_lx_um: Scan range X in micrometres
            scan_ly_um: Scan range Y in micrometres
            N_photons: Peak photon count (for noise-free scaling)
            photons_per_pixel: MATLAB-style dose (None = no Poisson noise)
            overlap: Fallback overlap if scan_step_um is None
            imgs_path: Custom path to images directory
            probe: Explicit probe array (e.g. from MC ray trace), asize x asize
        """
        # 1. Load thickness map from image
        thickness = load_dataset_image(dataset_id, imgs_path)

        # 2. Compute object size from scan geometry
        pixel_size_m = 1239.842e-9 / (energy_keV * 1e3) * z_m / (asize * det_pixel_size_m)
        if scan_lx_um is not None and scan_ly_um is not None:
            scan_w_px = scan_lx_um * 1e-6 / pixel_size_m
            scan_h_px = scan_ly_um * 1e-6 / pixel_size_m
            obj_w = int(np.ceil(scan_w_px)) + asize + 20
            obj_h = int(np.ceil(scan_h_px)) + asize + 20
        else:
            obj_h = int(asize * 2.5)
            obj_w = int(asize * 2.5)

        object_size = (obj_h, obj_w)

        # 3. Create complex object (MATLAB create_object.m)
        complex_obj = create_complex_object(
            thickness, object_size,
            energy_keV=energy_keV,
            material=material,
            objheight=objheight,
        )

        # 4. Build SyntheticPtycho instance
        kwargs = dict(
            object=complex_obj,
            asize=asize,
            overlap=overlap,
            scan_step_um=scan_step_um,
            scan_lx_um=scan_lx_um,
            scan_ly_um=scan_ly_um,
            energy_keV=energy_keV,
            z_m=z_m,
            det_pixel_size_m=det_pixel_size_m,
            N_photons=N_photons,
            photons_per_pixel=photons_per_pixel,
            imgs_path=imgs_path,
        )
        if probe is not None:
            kwargs['probe'] = probe
        elif probe_sigma_px is not None:
            kwargs['probe_sigma_px'] = probe_sigma_px
        return cls(**kwargs)

    # ── physical unit helpers ─────────────────────────────────────────────────

    @property
    def pixel_size_m(self) -> Optional[float]:
        """
        Real-space pixel size in metres.
        Computed from the far-field geometry:
            pixel_size = λ · z / (asize · det_pixel_size)
        Returns None when energy_keV is 0 (physical units disabled).
        """
        if self.energy_keV <= 0:
            return None
        lambda_m = 1239.842e-9 / (self.energy_keV * 1e3)   # hc / E  [m]
        return lambda_m * self.z_m / (self.asize * self.det_pixel_size_m)

    @property
    def pixel_size_nm(self) -> float:
        """Real-space pixel size in nanometres (0.0 if energy_keV not set)."""
        ps = self.pixel_size_m
        return float(ps) * 1e9 if ps is not None else 0.0

    def um_to_px(self, value_um: float) -> float:
        """Convert micrometres to pixels using the current pixel_size_m."""
        ps = self.pixel_size_m
        if ps is None:
            raise RuntimeError(
                "Physical unit conversion requires energy_keV > 0."
            )
        return value_um * 1e-6 / ps

    # ── Fermat spiral positions (MATLAB port) ─────────────────────────────────

    def _fermat_positions(self, scan_range: Tuple[float, float]) -> np.ndarray:
        """
        Port of +scans/+positions/matlab_pos.m  (case 'fermat').

        scan_range = (row_max, col_max) — full rectangular scan region.
        Positions are centered at (row_max/2, col_max/2) and converted to
        0-based row/col coordinates.

        MATLAB formula:
            phi = 2*pi*(1+sqrt(5))/2         golden angle ≈ 10.166 rad
            r   = step * 0.57 * sqrt(ir)     ir = 1, 2, ...
            if |r*sin(ir*phi)| > ly/2: skip
            if |r*cos(ir*phi)| > lx/2: skip
            xy = [r*sin(ir*phi), r*cos(ir*phi)]  (centred)

        Minimum _MIN_POS positions enforced by reducing step if needed.
        """
        ly, lx = float(scan_range[0]), float(scan_range[1])

        # -- determine Fermat step_px -----------------------------------------
        if self.scan_step_px is not None:
            step = float(self.scan_step_px)
        else:
            step = self.probe_fwhm * (1.0 - self.overlap)

        # MATLAB golden angle
        phi = 2.0 * np.pi * (1.0 + np.sqrt(5.0)) / 2.0   # ≈ 10.1664 rad
        n_max = 10000   # matches MATLAB p.scan.n_max default

        positions = []
        for ir in range(1, n_max + 1):
            r = step * 0.57 * np.sqrt(ir)
            y = r * np.sin(ir * phi)
            x = r * np.cos(ir * phi)
            if abs(y) > ly / 2.0:
                continue
            if abs(x) > lx / 2.0:
                continue
            positions.append([y, x])
            # stop when the bounding circle has grown well past the rectangle
            if r > np.sqrt((lx / 2) ** 2 + (ly / 2) ** 2) * 1.5:
                break

        positions = np.array(positions, dtype=np.float32)

        if len(positions) < _WARN_POS:
            import warnings
            warnings.warn(
                f'Only {len(positions)} scan positions generated '
                f'(overlap={self.overlap:.0%}, step={step:.1f}px, '
                f'probe_fwhm={self.probe_fwhm:.1f}px). '
                'Consider using higher overlap or a larger object.',
                UserWarning, stacklevel=4,
            )

        # convert from centred coordinates to 0-based (row, col)
        positions[:, 0] += ly / 2.0
        positions[:, 1] += lx / 2.0

        return positions

    # ── forward model ─────────────────────────────────────────────────────────

    def _simulate_diffraction(
        self, positions: np.ndarray, rng
    ) -> np.ndarray:
        """
        Forward model (port of load_data.m, farfield case):
            exit_wave  = probe × obj_patch
            diffraction = fftshift(|fft2(exit_wave)|²)

        Noise:
          photons_per_pixel mode  → total_dose = photons_per_pixel × scan_area
                                    scale all patterns then Poisson
          N_photons mode          → scale each pattern so peak = N_photons,
                                    then Poisson
        """
        Npos = len(positions)
        obj  = self.object_true
        probe = self.probe
        Ny, Nx = self.Ny, self.Nx
        obj_h, obj_w = obj.shape[:2]

        # 2-pass forward model (port of MATLAB load_data.m, farfield case).
        # MATLAB convention: fmag has DC at CORNER (no fftshift).
        # LSQML uses fft2_safe = np.fft.fft2 → DC at CORNER.
        #
        # corr_ratio (normalisation) requires global max/sum across ALL
        # positions, so we need two passes:
        #   Pass 1 — deterministic: FFT + |.|^2, accumulate scalars only
        #   Pass 2 — stochastic:    recompute FFT, apply corr, Poisson noise
        # This avoids storing Npos full-size arrays (psi_list + intensities),
        # reducing peak memory from O(3*Npos*H*W) to O(Npos*H*W) (fmag only).
        # RNG state is untouched in Pass 1, so Pass 2 Poisson sequence is
        # identical to the original single-pass implementation.

        def _intensity_at(pos):
            """exit_wave intensity |FFT(probe * obj_patch)|^2 for one position."""
            r = int(np.clip(int(round(float(pos[0]))), 0, obj_h - Ny))
            c = int(np.clip(int(round(float(pos[1]))), 0, obj_w - Nx))
            Psi = np.fft.fft2(probe * obj[r:r + Ny, c:c + Nx], norm='ortho')
            return np.abs(Psi) ** 2

        # ── Pass 1: compute normalisation statistics (scalars only) ───────
        I_max_all = 0.0
        I_sum_all = 0.0
        for pos in positions:
            I = _intensity_at(pos)
            I_max_all = max(I_max_all, float(I.max()))
            I_sum_all += float(I.sum())

        # ── noise model (port of MATLAB load_data.m) ──────────────────────
        # MATLAB no-noise:
        #   corr_ratio = max_value / max(diffraction)
        #   probe *= sqrt(corr_ratio)
        # MATLAB Poisson:
        #   corr_ratio = total_dose / sum(diffraction)
        #   probe *= sqrt(mean(corr_ratio))
        if self.photons_per_pixel is not None:
            scan_area = float((obj_h - Ny) * (obj_w - Nx))
            total_dose = self.photons_per_pixel * scan_area
            corr = total_dose / max(I_sum_all, 1e-30)
            peak_photons = int(round(I_max_all * corr))
        else:
            corr = float(self.N_photons) / max(I_max_all, 1e-30)
            peak_photons = self.N_photons

        # ── Pass 2: recompute FFT, apply corr + Poisson, write fmag ──────
        fmag = np.zeros((Ny, Nx, Npos), dtype=np.float32)
        for ii, pos in enumerate(positions):
            I = _intensity_at(pos)
            I_counts = np.maximum(I * corr, 0.0)
            noisy = rng.poisson(I_counts.astype(np.float64)).astype(np.float32)
            fmag[:, :, ii] = np.sqrt(noisy)

        # ── scale probe consistent with fmag (MATLAB convention) ─────────
        # probe_out = probe * sqrt(corr)  → |probe_out|² ∝ corr × |probe|²
        # This ensures |FFT2(probe_out * obj)|² and fmag² share the same scale
        probe_out = (probe * np.sqrt(float(corr))).astype(np.complex64)

        return fmag, peak_photons, probe_out

    # ── public API ────────────────────────────────────────────────────────────

    def generate(
        self,
        noise_sigma: float = 3.0,
        rng_seed:    int   = 42,
    ) -> PtychoDataset:
        """
        Generate synthetic dataset.

        Parameters
        ----------
        noise_sigma : position noise std-dev in pixels
        rng_seed    : RNG seed

        Returns
        -------
        PtychoDataset
        """
        rng = np.random.default_rng(rng_seed)

        obj_h, obj_w = self.object_true.shape[:2]
        default_scan_h = float(obj_h - self.Ny - self.scan_margin * 2)
        default_scan_w = float(obj_w - self.Nx - self.scan_margin * 2)

        # Physical scan range override (μm → px, clamped to object bounds)
        ps = self.pixel_size_m
        if self._scan_ly_um is not None and ps is not None:
            scan_h = min(self._scan_ly_um * 1e-6 / ps, default_scan_h)
        else:
            scan_h = default_scan_h

        if self._scan_lx_um is not None and ps is not None:
            scan_w = min(self._scan_lx_um * 1e-6 / ps, default_scan_w)
        else:
            scan_w = default_scan_w

        scan_range = (scan_h, scan_w)

        positions_clean = self._fermat_positions(scan_range)
        if self.scan_margin > 0:
            positions_clean += self.scan_margin

        Npos = len(positions_clean)

        # actual average step (nearest neighbour)
        diffs = []
        for i in range(Npos):
            d = np.sqrt(
                ((positions_clean - positions_clean[i]) ** 2).sum(axis=1)
            )
            d[i] = np.inf
            diffs.append(float(d.min()))
        avg_step = float(np.mean(diffs))
        actual_overlap = 1.0 - avg_step / max(self.probe_fwhm, 1e-6)

        # simulate diffraction (returns probe scaled by sqrt(corr_ratio))
        fmag, peak_photons, probe_scaled = self._simulate_diffraction(
            positions_clean, rng
        )

        # position noise
        noise = rng.normal(0, noise_sigma, positions_clean.shape).astype(
            np.float32
        )
        positions_noisy = positions_clean + noise
        positions_noisy[:, 0] = np.clip(
            positions_noisy[:, 0], 0, scan_range[0]
        )
        positions_noisy[:, 1] = np.clip(
            positions_noisy[:, 1], 0, scan_range[1]
        )

        object_init = np.ones(self.object_true.shape, dtype=np.complex64)

        # Physical unit metadata
        ps_nm = self.pixel_size_nm
        avg_step_um = avg_step * ps_nm * 1e-3 if ps_nm > 0 else 0.0  # px→nm→μm

        return PtychoDataset(
            fmag             = fmag,
            positions_clean  = positions_clean,
            positions_noisy  = positions_noisy,
            position_noise   = noise,
            probe            = probe_scaled,   # scaled to match fmag amplitude
            object_init      = object_init,
            object_true      = self.object_true,
            asize            = self.Ny,
            overlap          = actual_overlap,
            N_photons        = peak_photons,
            Npos             = Npos,
            avg_step         = avg_step,
            probe_fwhm       = self.probe_fwhm,
            pixel_size_nm    = ps_nm,
            energy_keV       = self.energy_keV,
            avg_step_um      = avg_step_um,
        )
