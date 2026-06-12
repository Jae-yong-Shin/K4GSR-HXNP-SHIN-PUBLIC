"""XAFS Simulation Engine using xraydb for accurate absorption coefficients.

Produces realistic XANES + EXAFS spectra with:
  - xraydb.mu_elam(): accurate mass absorption coefficients (Elam database)
  - xraydb.xray_edge(): precise edge energies
  - Parameterized EXAFS chi(k) for common elements (Cu, Fe, Ni, Au, Pt, etc.)
  - Proper normalization (pre-edge subtraction + post-edge normalization)
  - Poisson-like noise scaled by flux, concentration, and beam size
  - DCM energy resolution broadening (Si(111)/Si(311) Darwin width)
  - Self-absorption correction for concentrated/thick samples
  - Progressive streaming for live chart updates

Replaces the older experiment_engine.XAFSEngine (Larch-based) with a
lighter dependency (xraydb only, no larch.xafs import needed).
"""

import asyncio
import logging
import math
import re
import time

import numpy as np

from sim_engines.base import SimEngine

try:
    from sim_engines.ic_chain import run_ic_chain as _run_ic_chain
    _IC_CHAIN_OK = True
except Exception:  # pragma: no cover - xraydb missing
    _run_ic_chain = None
    _IC_CHAIN_OK = False

log = logging.getLogger("xafs-engine")

# ---------------------------------------------------------------------------
# Optional library import
# ---------------------------------------------------------------------------
_XRAYDB_OK = False
_xraydb = None
try:
    import xraydb
    _xraydb = xraydb
    _XRAYDB_OK = True
    log.info("xraydb loaded OK")
except ImportError:
    log.warning("xraydb not available -- XAFS engine disabled")


# ---------------------------------------------------------------------------
# Atomic masses (fallback when xraydb is not available for compound parsing)
# ---------------------------------------------------------------------------
_ATOMIC_MASS = {
    "H": 1.008, "He": 4.003, "Li": 6.941, "Be": 9.012, "B": 10.81,
    "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998, "Ne": 20.180,
    "Na": 22.990, "Mg": 24.305, "Al": 26.982, "Si": 28.086, "P": 30.974,
    "S": 32.065, "Cl": 35.453, "Ar": 39.948, "K": 39.098, "Ca": 40.078,
    "Sc": 44.956, "Ti": 47.867, "V": 50.942, "Cr": 51.996, "Mn": 54.938,
    "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38,
    "Ga": 69.723, "Ge": 72.630, "As": 74.922, "Se": 78.971, "Br": 79.904,
    "Kr": 83.798, "Rb": 85.468, "Sr": 87.62, "Y": 88.906, "Zr": 91.224,
    "Nb": 92.906, "Mo": 95.95, "Ru": 101.07, "Rh": 102.91, "Pd": 106.42,
    "Ag": 107.87, "Cd": 112.41, "In": 114.82, "Sn": 118.71, "Sb": 121.76,
    "Te": 127.60, "I": 126.90, "Ba": 137.33, "La": 138.91, "Ce": 140.12,
    "Pr": 140.91, "Nd": 144.24, "W": 183.84, "Re": 186.21, "Os": 190.23,
    "Ir": 192.22, "Pt": 195.08, "Au": 196.97, "Pb": 207.20, "Bi": 208.98,
}


# ---------------------------------------------------------------------------
# DCM energy resolution: Si(111) and Si(311) Darwin width dE/E
#   dE/E ~ 1.3e-4 for Si(111), ~0.3e-4 for Si(311)
#   Gaussian FWHM in eV = E0 * (dE/E)
#   sigma = FWHM / 2.355
# ---------------------------------------------------------------------------
_DCM_DE_OVER_E = {
    "Si(111)": 1.3e-4,
    "Si(311)": 0.28e-4,
}


def _apply_dcm_broadening(energies, mu, E0, dcm_type="Si(111)"):
    """Apply DCM energy resolution broadening via Gaussian convolution.

    The monochromator has finite energy resolution dE = E * (dE/E).
    This broadens sharp XANES features (white line, pre-edge peaks).
    EXAFS oscillations at high k are less affected.

    Args:
        energies: relative energy array (E - E0, eV)
        mu: normalized mu(E) array
        E0: edge energy in eV
        dcm_type: "Si(111)" or "Si(311)"

    Returns:
        mu_broadened: convolved mu(E) array
    """
    de_over_e = _DCM_DE_OVER_E.get(dcm_type, 1.3e-4)
    fwhm_eV = E0 * de_over_e  # FWHM in eV at the edge energy
    sigma_eV = fwhm_eV / 2.355

    # Skip if resolution is finer than energy step (no visible effect)
    e_step = abs(energies[1] - energies[0]) if len(energies) > 1 else 1.0
    if sigma_eV < e_step * 0.3:
        return mu

    # Build Gaussian kernel
    # Kernel width: +/- 4*sigma
    hw = int(4.0 * sigma_eV / e_step) + 1
    kernel_x = np.arange(-hw, hw + 1) * e_step
    kernel = np.exp(-0.5 * (kernel_x / sigma_eV) ** 2)
    kernel /= kernel.sum()

    # Convolve (mode='same' preserves array length)
    mu_broadened = np.convolve(mu, kernel, mode='same')
    return mu_broadened


# ---------------------------------------------------------------------------
# Self-absorption correction (Booth-Bridges / Troger formula)
#   For thick concentrated samples, fluorescence photons are re-absorbed
#   before escaping the sample. This suppresses the edge jump and distorts
#   XANES features.
#
#   Correction factor: mu_true = mu_meas * (1 + mu_bg/mu_f * alpha)
#   where alpha depends on geometry (45 deg typical).
#
#   Simplified model: edge_jump_ratio = (mu_above - mu_below) / mu_total
#   If ratio > ~0.1, self-absorption is significant.
# ---------------------------------------------------------------------------
def _apply_self_absorption(mu_norm, energies, absorber, edge_type,
                           ppm, sample_type, parsed_formula):
    """Apply self-absorption correction for concentrated samples.

    For dilute samples (ppm < 1000) or powder, correction is negligible.
    For solid concentrated samples, the edge jump is artificially reduced
    and white-line features are suppressed.

    Args:
        mu_norm: normalized mu(E) array
        energies: relative energy array (E - E0, eV)
        absorber: absorber element symbol
        edge_type: "K", "L3", etc.
        ppm: concentration in ppm
        sample_type: "solid" or "powder"
        parsed_formula: dict of {element: count}

    Returns:
        mu_corrected: corrected mu(E) array
        sa_factor: self-absorption distortion factor (0 = no effect, 1 = max)
    """
    # Self-absorption is negligible for dilute samples
    wt_frac = ppm / 1.0e6
    if wt_frac < 0.001 or sample_type == "powder":
        return mu_norm, 0.0

    # Estimate edge jump ratio (fraction of total absorption from absorber)
    # For pure element: ratio ~ 0.5-0.9 (strong self-absorption)
    # For dilute: ratio ~ 0.001 (negligible)
    total_mass = _compound_mass(parsed_formula)
    absorber_count = parsed_formula.get(absorber, 1.0)
    M_abs = _get_atomic_mass(absorber)
    abs_wt_frac = absorber_count * M_abs / max(total_mass, 1.0)
    effective_conc = abs_wt_frac * wt_frac

    # Self-absorption factor: 0 to 1
    # Significant when effective_conc > 0.01 (1%)
    # Use smooth sigmoid transition
    sa_factor = 1.0 / (1.0 + math.exp(-10.0 * (effective_conc - 0.05)))

    if sa_factor < 0.01:
        return mu_norm, 0.0

    # Apply distortion: suppress features above the edge
    # Self-absorption compresses the dynamic range of mu(E)
    # mu_distorted = mu / (1 + alpha * mu) where alpha ~ sa_factor
    alpha = sa_factor * 0.5  # scale factor for distortion strength
    mu_corrected = mu_norm / (1.0 + alpha * np.maximum(mu_norm, 0.0))

    # Re-normalize: pre-edge=0, post-edge=1
    pre_mask = energies < -20.0
    post_mask = (energies > 50.0) & (energies < 150.0)
    if pre_mask.sum() < 2:
        pre_mask = energies < 0
    if post_mask.sum() < 2:
        post_mask = energies > 50.0

    pre_val = mu_corrected[pre_mask].mean() if pre_mask.any() else mu_corrected[0]
    post_val = mu_corrected[post_mask].mean() if post_mask.any() else mu_corrected[-1]
    edge_step = post_val - pre_val
    if abs(edge_step) > 1e-15:
        mu_corrected = (mu_corrected - pre_val) / edge_step

    return mu_corrected, sa_factor


# ---------------------------------------------------------------------------
# Built-in EXAFS scattering paths for common absorbers
# Format: list of (R_angstrom, sigma2, amplitude_N, phi0)
#   R     = interatomic distance
#   sigma2 = Debye-Waller factor (A^2)
#   N_amp  = coordination number * |f(k)| amplitude factor
#   phi0   = phase shift offset (radians)
# ---------------------------------------------------------------------------
_EXAFS_PATHS = {
    "Cu": [
        (2.556, 0.0085, 6.0, 1.0),     # Cu-Cu 1st shell (FCC NN)
        (3.615, 0.0120, 12.0, 1.2),    # Cu-Cu 2nd shell
        (4.427, 0.0150, 24.0, 1.5),    # Cu-Cu 3rd shell
    ],
    "Fe": [
        (2.482, 0.0070, 8.0, 0.8),     # Fe-Fe BCC 1st shell
        (2.866, 0.0090, 6.0, 1.1),     # Fe-Fe BCC 2nd shell
    ],
    "Ni": [
        (2.492, 0.0060, 12.0, 1.0),    # Ni-Ni FCC 1st shell
        (3.524, 0.0100, 6.0, 1.3),     # Ni-Ni FCC 2nd shell
    ],
    "Au": [
        (2.884, 0.0090, 12.0, 1.2),    # Au-Au FCC 1st
        (4.079, 0.0130, 6.0, 1.4),     # Au-Au FCC 2nd
    ],
    "Pt": [
        (2.775, 0.0065, 12.0, 1.1),    # Pt-Pt FCC 1st
        (3.924, 0.0100, 6.0, 1.3),     # Pt-Pt FCC 2nd
    ],
    "Ti": [
        (2.896, 0.0100, 6.0, 0.9),     # Ti-O (rutile-like)
        (3.296, 0.0120, 2.0, 1.0),     # Ti-Ti
    ],
    "Mn": [
        (2.870, 0.0080, 6.0, 0.9),     # Mn-O (oxide-like)
    ],
    "Co": [
        (2.507, 0.0065, 12.0, 1.0),    # Co-Co FCC/HCP 1st
        (3.544, 0.0100, 6.0, 1.2),     # Co-Co 2nd
    ],
    "Zn": [
        (2.664, 0.0090, 4.0, 0.8),     # Zn-O (wurtzite-like)
    ],
    "Cr": [
        (2.498, 0.0075, 8.0, 0.9),     # Cr-Cr BCC 1st
        (2.884, 0.0095, 6.0, 1.1),     # Cr-Cr BCC 2nd
    ],
    "V": [
        (2.622, 0.0080, 8.0, 0.8),     # V-V BCC 1st
    ],
    "Se": [
        (2.374, 0.0070, 2.0, 0.7),     # Se-Se chain
        (3.436, 0.0110, 4.0, 1.0),     # Se-Se inter-chain
    ],
    "Sr": [
        (2.580, 0.0100, 6.0, 1.0),     # Sr-O (perovskite)
        (3.905, 0.0130, 8.0, 1.2),     # Sr-Ti (perovskite)
    ],
    "Mo": [
        (2.725, 0.0060, 8.0, 1.0),     # Mo-Mo BCC 1st
        (3.147, 0.0085, 6.0, 1.2),     # Mo-Mo BCC 2nd
    ],
    "Ag": [
        (2.889, 0.0085, 12.0, 1.1),    # Ag-Ag FCC 1st
        (4.086, 0.0120, 6.0, 1.3),     # Ag-Ag FCC 2nd
    ],
}


# ---------------------------------------------------------------------------
# Chemical formula parser
# ---------------------------------------------------------------------------
def parse_formula(formula):
    """Parse chemical formula string into element counts.

    Examples:
        'Cu'      -> {'Cu': 1.0}
        'Cu2O'    -> {'Cu': 2.0, 'O': 1.0}
        'Fe2O3'   -> {'Fe': 2.0, 'O': 3.0}
        'SrTiO3'  -> {'Sr': 1.0, 'Ti': 1.0, 'O': 3.0}
    """
    result = {}
    for match in re.finditer(r'([A-Z][a-z]?)(\d*\.?\d*)', formula):
        el = match.group(1)
        n = float(match.group(2)) if match.group(2) else 1.0
        result[el] = result.get(el, 0) + n
    return result


def _get_atomic_mass(element):
    """Get atomic mass for an element symbol."""
    if _XRAYDB_OK:
        try:
            return _xraydb.atomic_mass(element)
        except Exception:
            pass
    return _ATOMIC_MASS.get(element, 40.0)


def _compound_mass(parsed):
    """Total molar mass from parsed formula dict."""
    total = 0.0
    for el, n in parsed.items():
        total += n * _get_atomic_mass(el)
    return total


# ---------------------------------------------------------------------------
# EXAFS chi(k) calculation
# ---------------------------------------------------------------------------
def _calc_exafs_chi(k_arr, paths):
    """Calculate EXAFS chi(k) from a list of scattering paths.

    Uses the standard EXAFS equation (simplified, no curved-wave corrections):
        chi(k) = sum_i  N_i * S0^2 * f_i(k) / (k * R_i^2)
                       * exp(-2*R_i/lambda(k))
                       * exp(-2*sigma_i^2*k^2)
                       * sin(2*k*R_i + phi_i(k))

    Args:
        k_arr: numpy array of k values (A^-1)
        paths: list of (R, sigma2, N_amp, phi0) tuples

    Returns:
        chi: numpy array of chi(k) values
    """
    S02 = 0.9  # amplitude reduction factor
    chi = np.zeros_like(k_arr)

    for R, sigma2, N_amp, phi0 in paths:
        # Mean free path: simplified Sevillano model
        k_safe = np.maximum(k_arr, 0.05)
        lam = 1.0 / (0.04 + 0.1 * k_safe)

        # Simplified backscattering amplitude
        fk = 0.5 / (1.0 + 0.02 * k_safe * k_safe)

        # Phase shift (linear model + offset)
        phi_k = phi0 - 0.2 * k_safe

        # EXAFS equation
        amp = (N_amp * S02 * fk / (k_safe * R * R)
               * np.exp(-2.0 * R / lam)
               * np.exp(-2.0 * sigma2 * k_safe * k_safe))

        chi += amp * np.sin(2.0 * k_safe * R + phi_k)

    return chi


# ---------------------------------------------------------------------------
# Core XAFS computation (runs in executor)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Normalization (shared by the synthetic path and the ion-chamber path)
# ---------------------------------------------------------------------------
def _normalize_mu(energies, mu_raw, e_start):
    """Pre-edge subtraction + edge-step normalization.

    Extracted verbatim from the original _compute_xafs normalization block so
    the default path stays byte-identical; the ion-chamber measurement path
    reuses the exact same logic on mu_obs = ln(I0/I1).
    """
    # Pre-edge: average below -30 eV
    pre_mask = energies < (e_start + 20.0)
    if pre_mask.sum() < 3:
        pre_mask = energies < 0
    pre_val = mu_raw[pre_mask].mean() if pre_mask.any() else mu_raw[0]

    # Post-edge: average from +50 to +150 eV (the post-edge plateau)
    post_mask = (energies > 50.0) & (energies < 150.0)
    if post_mask.sum() < 3:
        post_mask = energies > 50.0
    post_val = mu_raw[post_mask].mean() if post_mask.any() else mu_raw[-1]

    edge_step = post_val - pre_val
    if abs(edge_step) < 1e-15:
        edge_step = 1.0  # prevent division by zero

    return (mu_raw - pre_val) / edge_step


# ---------------------------------------------------------------------------
# Ion-chamber measurement path (opt-in via params.ic;
# design doc docs/tasks/TASK_XANES_IC_SIM.md section 3a)
# ---------------------------------------------------------------------------
def _apply_ic_measurement(energies, E_abs, mu_norm, ic_cfg, flux_in, e_start):
    """Pass the noiseless spectrum through the I0/sample/I1 chamber chain.

    Maps mu_norm -> sample optical thickness mu_t(E) = mut_pre +
    delta_mut*mu_norm, runs ic_chain.run_ic_chain on the absolute energy
    grid, and re-normalizes the observable mu_obs = ln((I0-dark)/(I1-dark))
    with the engine's standard normalization path.

    Returns:
        (mu_obs_norm, ic_summary dict for the expt_result message)
    """
    if not _IC_CHAIN_OK:
        raise RuntimeError("ic_chain unavailable (xraydb missing)")

    sample = ic_cfg.get("sample") or {}
    delta_mut = float(sample.get("delta_mut", 1.0))
    mut_pre = float(sample.get("mut_pre", 0.8))
    mu_t = mut_pre + delta_mut * mu_norm

    dwell = ic_cfg.get("dwell_s", 1.0)
    dwell = None if dwell is None else float(dwell)
    dark = float(ic_cfg.get("dark_A", 1.0e-12))
    seed = ic_cfg.get("seed", 42)

    res = _run_ic_chain(
        E_abs, mu_t, flux_in, dwell_s=dwell,
        i0=ic_cfg.get("i0"), i1=ic_cfg.get("i1"),
        dark0_A=dark, dark1_A=dark,
        ratio_prefocus=float(ic_cfg.get("ratio_prefocus", 1.0)),
        seed=seed)

    mu_obs_norm = _normalize_mu(energies, res["mu_obs"], e_start)

    meta = res["meta"]
    ic_summary = {
        "enabled": True,
        "i0_A_range": [float(res["I0_A"].min()), float(res["I0_A"].max())],
        "i1_A_range": [float(res["I1_A"].min()), float(res["I1_A"].max())],
        "flux_at_sample_range": [float(res["flux_at_sample"].min()),
                                 float(res["flux_at_sample"].max())],
        "i0": meta["i0"],
        "i1": meta["i1"],
        "dwell_s": meta["dwell_s"],
        "dark_A": dark,
        "flux_in": float(np.max(flux_in)),
        "ratio_prefocus": meta["ratio_prefocus"],
        "seed": meta["seed"],
        "delta_mut": delta_mut,
        "mut_pre": mut_pre,
        "mu_t_range": [float(mu_t.min()), float(mu_t.max())],
        "chain_note": ("flux->air->I0(xraydb chain)->air->sample->air->I1; "
                       "y = normalized mu_obs = ln((I0-dark)/(I1-dark)); "
                       "Poisson noise on absorbed photons per dwell"),
    }
    return mu_obs_norm, ic_summary


def _compute_xafs(formula, absorber, edge_type, e_start, e_end, e_step,
                  ppm, flux, sample_type,
                  spot_h_nm=50.0, spot_v_nm=50.0, dcm_type="Si(111)",
                  ic_cfg=None, ic_flux=None):
    """Compute XAFS mu(E) spectrum with beamline-aware physics.

    Includes:
      - xraydb mu_elam for accurate absorption coefficients
      - Beam size effect on S/N ratio (larger beam = more photons = less noise)
      - DCM energy resolution broadening (Si(111)/Si(311) Darwin width)
      - Self-absorption correction for concentrated thick samples

    Returns:
        energies: numpy array of relative energies (E - E0, eV)
        mu_norm: numpy array of normalized mu(E)
        E0: edge energy in eV
        N: number of energy points
        extra: dict with diagnostic info (dcm_fwhm_eV, sa_factor, noise_sigma,
            and 'ic' = ion-chamber summary dict when ic_cfg is given else None)
    """
    # --- Get edge energy from xraydb ---
    edge_info = _xraydb.xray_edge(absorber, edge_type)
    E0 = edge_info[0]  # energy in eV (xray_edge returns (energy, fyield, jump))

    # --- Generate energy array ---
    energies = np.arange(e_start, e_end + e_step * 0.49, e_step)
    E_abs = E0 + energies  # absolute energies in eV
    # Ensure all energies are positive
    valid = E_abs > 100.0
    energies = energies[valid]
    E_abs = E_abs[valid]
    N = len(energies)

    # --- Calculate compound absorption coefficient ---
    parsed = parse_formula(formula)
    total_mass = _compound_mass(parsed)

    # Compute mu(E) for the full compound (weighted by mass fraction)
    mu_compound = np.zeros(N, dtype=np.float64)
    for el, count in parsed.items():
        try:
            mu_el = _xraydb.mu_elam(el, E_abs)  # cm^2/g
        except Exception:
            continue
        M_el = _get_atomic_mass(el)
        wt_frac = count * M_el / max(total_mass, 1.0)
        mu_compound += wt_frac * mu_el

    # --- Separate absorber contribution for ppm scaling ---
    # The absorber sees the full edge jump; other elements provide smooth background.
    mu_absorber = np.zeros(N, dtype=np.float64)
    try:
        mu_absorber = _xraydb.mu_elam(absorber, E_abs)
    except Exception:
        pass

    # Absorber mass fraction in compound
    absorber_count = parsed.get(absorber, 1.0)
    M_absorber = _get_atomic_mass(absorber)
    absorber_wt_frac = absorber_count * M_absorber / max(total_mass, 1.0)

    # Build spectrum:
    #   - Background: matrix mu (non-absorber) at full density
    #   - Signal: absorber mu scaled by ppm concentration
    ppm_scale = ppm / 1.0e6

    # Matrix contribution (everything except absorber edge)
    mu_matrix = mu_compound - absorber_wt_frac * mu_absorber
    mu_bg = mu_matrix * 0.1  # scale background for visibility

    # Absorber signal scaled by ppm
    mu_signal = absorber_wt_frac * mu_absorber * ppm_scale

    mu_raw = mu_bg + mu_signal

    # --- Normalize ---
    mu_norm = _normalize_mu(energies, mu_raw, e_start)

    # --- Add EXAFS oscillations ---
    paths = _EXAFS_PATHS.get(absorber, [])
    if paths:
        # Convert energy above edge to k (in A^-1)
        # k = 0.5123 * sqrt(E - E0)  where E-E0 is in eV
        above_edge = energies > 0
        dE = np.maximum(energies[above_edge], 0.1)
        k = 0.5123 * np.sqrt(dE)

        chi = _calc_exafs_chi(k, paths)

        # Scale chi amplitude so EXAFS oscillations are visible
        # chi modulates the normalized absorption above the edge
        mu_norm[above_edge] *= (1.0 + chi)

    # --- Add XANES white-line feature (Lorentzian near edge) ---
    # White line: enhanced absorption right at the edge
    near_edge = (energies > -5) & (energies < 30)
    if near_edge.any():
        dE_wl = energies[near_edge]
        # Lorentzian centered at ~2 eV above edge
        white_line = 0.15 / (1.0 + ((dE_wl - 2.0) / 3.0) ** 2)
        mu_norm[near_edge] += white_line

    # --- Self-absorption correction (before noise, after EXAFS/XANES) ---
    # `parsed` already computed above (line ~376)
    mu_norm, sa_factor = _apply_self_absorption(
        mu_norm, energies, absorber, edge_type,
        ppm, sample_type, parsed)

    # --- DCM energy resolution broadening ---
    # Convolve with Gaussian kernel matching monochromator bandwidth
    de_over_e = _DCM_DE_OVER_E.get(dcm_type, 1.3e-4)
    dcm_fwhm_eV = E0 * de_over_e
    mu_norm = _apply_dcm_broadening(energies, mu_norm, E0, dcm_type)

    # --- Add noise (Poisson-like, scaled by flux, ppm, and beam size) ---
    # Noise model: sigma ~ 1/sqrt(N_photons)
    #   N_photons ~ flux * dwell * beam_area * concentration
    # Beam area in um^2 (convert from nm): larger beam = more photons
    beam_area_um2 = (spot_h_nm / 1000.0) * (spot_v_nm / 1000.0)
    # Reference: 50x50 nm = 0.0025 um^2
    # Scale relative to reference beam
    area_factor = max(beam_area_um2 / 0.0025, 0.01)

    ic_summary = None
    if ic_cfg:
        # --- Ion-chamber measurement chain (opt-in via params.ic) ---
        # Replaces the synthetic noise: the observable becomes the
        # normalized mu_obs = ln((I0-dark)/(I1-dark)) of the I0/I1 chain,
        # applied after self-absorption + DCM broadening so the chambers
        # measure the beamline-resolved spectrum. Poisson shot noise per
        # dwell lives inside the chain (ic_chain.run_ic_chain).
        mu_norm, ic_summary = _apply_ic_measurement(
            energies, E_abs, mu_norm, ic_cfg,
            ic_flux if ic_flux is not None else 1.0e11, e_start)
        noise_sigma = 0.0  # synthetic noise not applied on this path
    else:
        # (default path -- UNCHANGED, byte-identical regression-checked)
        noise_sigma = 1.0 / math.sqrt(max(flux * ppm_scale * 1e-4 * area_factor, 1.0))
        noise_sigma = min(noise_sigma, 0.02)  # cap noise level
        rng = np.random.RandomState(42)
        noise = rng.normal(0, noise_sigma, N) * 0.5
        mu_norm += noise

    extra = {
        "dcm_type": dcm_type,
        "dcm_fwhm_eV": dcm_fwhm_eV,
        "sa_factor": sa_factor,
        "noise_sigma": noise_sigma,
        "beam_area_um2": beam_area_um2,
        "ic": ic_summary,
    }
    return energies, mu_norm, float(E0), N, extra


# ---------------------------------------------------------------------------
# XAFS Engine class
# ---------------------------------------------------------------------------
class XAFSEngine(SimEngine):
    """XAFS simulation engine using xraydb for accurate absorption coefficients."""

    @staticmethod
    def available():
        return _XRAYDB_OK

    @staticmethod
    def name():
        return "xafs"

    async def run(self, ws, params, beamline):
        """Run XAFS simulation and stream results via websocket.

        Args:
            ws: websocket connection
            params: {formula, absorber, edge, eStart, eEnd, eStep, ppm, sampleType}
            beamline: {energy_keV, flux, spot_h_nm, spot_v_nm, ...}
        """
        t0 = time.time()
        self.reset()

        # ── Parse parameters ──
        formula = params.get("formula", "Cu")
        absorber = params.get("absorber", "Cu")
        edge_type = params.get("edge", "K")
        e_start = float(params.get("eStart", -50))
        e_end = float(params.get("eEnd", 300))
        e_step = float(params.get("eStep", 0.5))
        ppm = float(params.get("ppm", 10000))
        sample_type = params.get("sampleType", "solid")

        flux = float(beamline.get("flux", 1e10))
        beamline_keV = float(beamline.get("energy_keV", 10.0))
        spot_h_nm = float(beamline.get("spot_h_nm", 50.0))
        spot_v_nm = float(beamline.get("spot_v_nm", 50.0))
        # DCM type: default Si(111), could be extended to Si(311)
        dcm_type = params.get("dcm_type", "Si(111)")

        # ── Ion-chamber measurement chain (opt-in, default off) ──
        # params.ic: truthy dict enables the I0/I1 chain; ic.enabled=False
        # (or ic absent) keeps the existing synthetic-noise behavior.
        ic_cfg = params.get("ic") or None
        if ic_cfg is True:
            ic_cfg = {}
        if isinstance(ic_cfg, dict) and not ic_cfg.get("enabled", True):
            ic_cfg = None
        if ic_cfg is not None and not _IC_CHAIN_OK:
            log.warning("params.ic requested but ic_chain unavailable -- "
                        "falling back to synthetic noise")
            ic_cfg = None
        ic_flux = None
        if ic_cfg is not None:
            # flux for the chain: ic override > beamline SSOT > 1e11 fallback
            ic_flux = float(ic_cfg.get("flux", beamline.get("flux", 1e11)))

        # ── Validate absorber edge ──
        try:
            edge_info = _xraydb.xray_edge(absorber, edge_type)
            E0 = edge_info[0]
        except Exception:
            await self.send_error(ws,
                "Unknown edge: %s %s. Check element symbol and edge name." %
                (absorber, edge_type))
            return

        # ── Beamline energy range check ──
        # K4GSR ID10 NanoProbe: IVU24 undulator, 5-30 keV
        BL_E_MIN_EV = 5000.0
        BL_E_MAX_EV = 30000.0
        E0_scan_max = E0 + e_end   # highest absolute energy in scan

        beamline_warning = None
        if E0 < BL_E_MIN_EV:
            beamline_warning = (
                "WARNING: %s %s-edge (%.0f eV = %.3f keV) is below the "
                "beamline range (5-30 keV). The K4GSR ID10 IVU24 undulator "
                "cannot produce X-rays at this energy. "
                "Simulation results are shown for reference only."
                % (absorber, edge_type, E0, E0 / 1000)
            )
        elif E0_scan_max > BL_E_MAX_EV:
            beamline_warning = (
                "WARNING: %s %s-edge scan extends to %.0f eV (%.1f keV), "
                "beyond the beamline maximum (30 keV). "
                "Partial scan may be feasible; high-energy portion is "
                "outside the operational range."
                % (absorber, edge_type, E0_scan_max, E0_scan_max / 1000)
            )

        if beamline_warning:
            log.warning(beamline_warning)
            await self.send_progress(ws, 0.02, beamline_warning)

        await self.send_progress(ws, 0.05,
            "XAFS: %s %s %s-edge (E0=%.1f eV), computing..." %
            (formula, absorber, edge_type, E0))

        if self._cancelled:
            return

        # ── Run heavy computation in executor ──
        loop = asyncio.get_event_loop()

        def _compute():
            return _compute_xafs(
                formula, absorber, edge_type,
                e_start, e_end, e_step,
                ppm, flux, sample_type,
                spot_h_nm=spot_h_nm,
                spot_v_nm=spot_v_nm,
                dcm_type=dcm_type,
                ic_cfg=ic_cfg, ic_flux=ic_flux,
            )

        try:
            energies, mu_norm, E0, N, extra = await loop.run_in_executor(None, _compute)
        except Exception as exc:
            await self.send_error(ws,
                "XAFS computation failed: %s" % str(exc))
            return

        if self._cancelled:
            return

        # ── Stream data in batches ──
        batch_size = 20
        data_all = []

        for i in range(0, N, batch_size):
            if self._cancelled:
                return

            batch_end = min(i + batch_size, N)
            batch = []
            for j in range(i, batch_end):
                batch.append({
                    "x": float(energies[j]),
                    "y": float(mu_norm[j]),
                })
            data_all.extend(batch)

            frac = batch_end / N
            await self.send_data(ws, "xafs", batch, progress=frac)
            await asyncio.sleep(0.02)  # yield to event loop for live updates

        # ── Send final result ──
        info = {
            "formula": formula,
            "absorber": absorber,
            "edge": edge_type,
            "E0_eV": E0,
            "n_points": N,
            "ppm": ppm,
            "engine": "xraydb",
            "beam_h_nm": spot_h_nm,
            "beam_v_nm": spot_v_nm,
            "dcm_type": extra.get("dcm_type", dcm_type),
            "dcm_fwhm_eV": extra.get("dcm_fwhm_eV", 0.0),
            "self_absorption": extra.get("sa_factor", 0.0),
            "noise_sigma": extra.get("noise_sigma", 0.0),
        }
        if beamline_warning:
            info["beamline_warning"] = beamline_warning
            info["beamline_range_keV"] = [BL_E_MIN_EV / 1000, BL_E_MAX_EV / 1000]
        # Ion-chamber summary: extra top-level 'ic' block + info.ic_enabled
        # ONLY when the chain ran (legacy clients see an unchanged message
        # when ic is off; {x,y} batch points are identical either way).
        result_kwargs = {"data": data_all, "info": info}
        ic_summary = extra.get("ic")
        if ic_summary:
            info["ic_enabled"] = True
            result_kwargs["ic"] = ic_summary
        await self.send_result(ws, "xafs", **result_kwargs)

        elapsed = time.time() - t0
        await self.send_done(ws, elapsed)

        log.info("XAFS done: %s %s %s-edge, %d pts, %.2fs "
                 "(beam=%.0fx%.0fnm, DCM=%s/%.2feV, SA=%.2f, noise=%.4f)",
                 formula, absorber, edge_type, N, elapsed,
                 spot_h_nm, spot_v_nm,
                 dcm_type, extra.get("dcm_fwhm_eV", 0),
                 extra.get("sa_factor", 0),
                 extra.get("noise_sigma", 0))
