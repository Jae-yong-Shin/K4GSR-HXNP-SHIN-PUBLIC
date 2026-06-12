"""Transmission-XAFS ion-chamber measurement chain (I0 -> sample -> I1).

Vectorized (numpy) forward simulation of the observable measurement chain of a
transmission XAFS beamline:

    flux(E) -> air -> [I0 chamber: current + transmission] -> air
            -> sample T_s(E) = exp(-mu_t(E)) -> air(sample->detector)
            -> [I1 chamber: current]
    mu_obs(E) = ln((I0 - dark0) / (I1 - dark1))

Physics is the xraydb 4.5.8 ``ionchamber_fluxes`` chain, extracted verbatim
from ``site-packages/xraydb/xray.py:1048-1188`` (program-based principle; see
``docs/tasks/TASK_A3_IONCHAMBER.md`` section 1 -- the A3-verified formula
chain) and vectorized over the energy grid:

    mu_k        = material_mu(gas, E, kind=k) * pressure_atm     # [1/cm]
    atten_total = 1 - exp(-L_cm * mu_total)                      # xray.py:1175
    atten_photo = atten_total * mu_photo / mu_total              # xray.py:1176
    atten_incoh = atten_total * mu_incoh / mu_total              # xray.py:1177
    E_compton   = compton_energies(E).electron_mean              # xray.py:1159
    W           = ionization_potential(gas)                      # [eV/pair]
    I [A] = flux [ph/s] * QCHARGE * N_carriers
            * (E*atten_photo + E_compton*atten_incoh) / W        # xray.py:1180-1181

Mixed gases use fraction-weighted mu and W (xray.py:1161-1173); coherent
scattering attenuates the beam (atten_total) but generates no current.
Air segments: T_air = exp(-material_mu('air', E) * L_cm).
Pressure: mu is linear in density -> mu *= P/P0 (A3 section 2).

Noise model (documented approximation, design doc R6): Poisson statistics on
the number of photons absorbed in each chamber per dwell -- the conversion
photon -> electron/ion pairs -> charge is taken as deterministic (Fano factor,
amplifier bandwidth and 1/f noise are NOT modeled; xraydb has no noise model
and the no-guessing principle forbids inventing one). Dark current is added
as a constant offset and subtracted with a perfect estimate in mu_obs.

Dependencies: numpy + xraydb only. Import-safe: if xraydb is missing the
module still imports; ``run_ic_chain`` then raises RuntimeError.
"""

import logging

import numpy as np

log = logging.getLogger("ic-chain")

# ---------------------------------------------------------------------------
# Optional xraydb import (import-safe)
# ---------------------------------------------------------------------------
XRAYDB_OK = False
_material_mu = None
_ionization_potential = None
_xdb = None
QCHARGE = 1.602176634e-19  # [C] == scipy.constants.e == xraydb.utils.QCHARGE

try:
    from xraydb import material_mu as _material_mu
    from xraydb import ionization_potential as _ionization_potential
    from xraydb.xray import get_xraydb as _get_xraydb
    try:
        from xraydb.utils import QCHARGE as _XQ
        QCHARGE = _XQ  # bit-identical to xraydb's own constant
    except ImportError:
        pass
    XRAYDB_OK = True
except ImportError:
    log.warning("xraydb not available -- ic_chain disabled")


def _xraydb_handle():
    """Lazy singleton XrayDB handle (for compton_energies)."""
    global _xdb
    if _xdb is None:
        _xdb = _get_xraydb()
    return _xdb


# ---------------------------------------------------------------------------
# Default chamber configs (design doc TASK_XANES_IC_SIM.md section 3b)
# ---------------------------------------------------------------------------
DEFAULT_I0 = {
    "gas": "N2",
    "length_cm": 10.0,
    "pressure_atm": 1.0,
    "air_before_cm": 5.0,
    "air_after_cm": 2.0,
}
DEFAULT_I1 = {
    "gas": "N2",
    "length_cm": 10.0,
    "pressure_atm": 1.0,
    "air_path_cm": 0.0,
}
DEFAULT_DARK_A = 1.0e-12  # [A] design doc section 3b


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------
def _gas_components(gas):
    """Resolve a gas spec into [(mu_name, frac, ion_pot), ...].

    Replicates xraydb's ionchamber_fluxes gas handling exactly
    (xray.py:1141-1153): ionization_potential is looked up on the ORIGINAL
    name, then 'N2'/'O2' are mapped to the material-DB names for mu.
    """
    if isinstance(gas, str):
        gas = {gas: 1.0}
    comps = []
    total = 0.0
    for gname, frac in gas.items():
        ionpot = _ionization_potential(gname)
        if gname == "N2":
            gname = "nitrogen"
        elif gname == "O2":
            gname = "oxygen"
        elif gname == "He":
            gname = "helium"
        elif gname == "Ar":
            gname = "argon"
        total += frac
        comps.append((gname, frac, ionpot))
    return comps, total


def gas_attenuation(gas, energies_eV, length_cm, pressure_atm=1.0):
    """Fraction-weighted attenuation terms for a (possibly mixed) chamber gas.

    Returns dict with vectorized arrays over energies_eV:
      atten_total / atten_photo / atten_incoh  (xray.py:1175-1177)
      mu_total/mu_photo/mu_incoh [1/cm, pressure-scaled], ion_pot [eV/pair]
    """
    if not XRAYDB_OK:
        raise RuntimeError("xraydb not available")
    E = np.asarray(energies_eV, dtype=np.float64)
    comps, total = _gas_components(gas)

    mu_photo = np.zeros_like(E)
    mu_incoh = np.zeros_like(E)
    mu_total = np.zeros_like(E)
    ion_pot = 0.0
    for gname, frac, ionpot in comps:
        w = frac / total
        mu_photo += _material_mu(gname, energy=E, kind="photo") * w
        mu_total += _material_mu(gname, energy=E, kind="total") * w
        mu_incoh += _material_mu(gname, energy=E, kind="incoh") * w
        ion_pot += ionpot * w

    # pressure scaling: mu linear in density (A3 section 2, S5-verified)
    mu_photo = mu_photo * pressure_atm
    mu_incoh = mu_incoh * pressure_atm
    mu_total = mu_total * pressure_atm

    atten_total = 1.0 - np.exp(-length_cm * mu_total)
    atten_photo = atten_total * mu_photo / mu_total
    atten_incoh = atten_total * mu_incoh / mu_total

    return {
        "atten_total": atten_total,
        "atten_photo": atten_photo,
        "atten_incoh": atten_incoh,
        "mu_total": mu_total,
        "mu_photo": mu_photo,
        "mu_incoh": mu_incoh,
        "ion_pot": ion_pot,
    }


def compton_electron_mean(energies_eV):
    """Mean Compton-scattered electron energy [eV] (xraydb table + linear interp)."""
    if not XRAYDB_OK:
        raise RuntimeError("xraydb not available")
    E = np.asarray(energies_eV, dtype=np.float64)
    return np.asarray(_xraydb_handle().compton_energies(E).electron_mean,
                      dtype=np.float64)


def chamber_response(energies_eV, gas, length_cm, pressure_atm=1.0,
                     both_carriers=True, with_compton=True):
    """Ion-chamber response [A per (ph/s)] and transmission, vectorized.

    response(E) = QCHARGE * N_carriers * (E*atten_photo + Ec*atten_incoh) / W
    so that I [A] = flux_in [ph/s] * response(E)   (xray.py:1180-1181 inverted).

    Returns (response_A_per_phps, atten dict).
    """
    att = gas_attenuation(gas, energies_eV, length_cm, pressure_atm)
    E = np.asarray(energies_eV, dtype=np.float64)
    ncarriers = 2 if both_carriers else 1
    ec = compton_electron_mean(E) if with_compton else 0.0
    absorbed_energy = ncarriers * (E * att["atten_photo"]
                                   + ec * att["atten_incoh"])
    response = QCHARGE * absorbed_energy / att["ion_pot"]
    return response, att


def air_transmission(energies_eV, length_cm):
    """T_air(E) = exp(-material_mu('air', E) * L_cm) at 1 atm DB density."""
    if not XRAYDB_OK:
        raise RuntimeError("xraydb not available")
    if length_cm <= 0.0:
        return np.ones(np.asarray(energies_eV).shape, dtype=np.float64)
    mu_air = _material_mu("air", energy=np.asarray(energies_eV,
                                                   dtype=np.float64),
                          kind="total")
    return np.exp(-mu_air * length_cm)


def _poisson_factor(n_expected, rng):
    """Multiplicative Poisson noise factor: Poisson(N)/N per point.

    N is the expected number of absorbed photons per dwell; the relative
    fluctuation 1/sqrt(N) propagates linearly to charge and hence current.
    Points with N <= 0 get factor 0 (no photons -> no signal).
    """
    n = np.asarray(n_expected, dtype=np.float64)
    factor = np.zeros_like(n)
    pos = n > 0
    # Generator.poisson supports lam up to ~9.2e18 (int64); clip defensively.
    # NOTE: legacy np.random.RandomState.poisson is limited by C long
    # (32-bit on Windows, lam < ~2.1e9) -- pass a np.random.Generator.
    lam = np.minimum(n[pos], 9.0e18)
    factor[pos] = rng.poisson(lam).astype(np.float64) / n[pos]
    return factor


# ---------------------------------------------------------------------------
# Full measurement chain
# ---------------------------------------------------------------------------
def run_ic_chain(energies_eV, mu_t, flux_in, dwell_s=None,
                 i0=None, i1=None,
                 dark0_A=DEFAULT_DARK_A, dark1_A=DEFAULT_DARK_A,
                 ratio_prefocus=1.0, both_carriers=True, with_compton=True,
                 seed=42, rng=None):
    """Run the full I0 -> sample -> I1 measurement chain on an energy grid.

    Args:
        energies_eV: array of ABSOLUTE photon energies [eV]
        mu_t:        array, sample optical thickness mu*t per point
        flux_in:     incident flux [ph/s], scalar or array (SSOT ideal flux;
                     this chain applies air/IC losses exactly once -- R1)
        dwell_s:     dwell time per point [s]; None -> noiseless
        i0:          I0 chamber config {gas, length_cm, pressure_atm,
                     air_before_cm, air_after_cm} (DEFAULT_I0)
        i1:          I1 chamber config {gas, length_cm, pressure_atm,
                     air_path_cm} (DEFAULT_I1)
        dark0_A/dark1_A: dark currents [A], added to measured currents and
                     subtracted (perfect estimate) in mu_obs
        ratio_prefocus: geometric fraction of the SSOT flux seen by the I0
                     chamber (located before the KB focusing; design doc 3a-2)
        both_carriers: count electron+ion (N_carriers=2) like xraydb default
        with_compton: include Compton-electron term like xraydb default
        seed/rng:    noise RNG; noiseless when dwell_s is None or both
                     seed and rng are None. rng must be a np.random.Generator
                     (np.random.default_rng) -- NOT a legacy RandomState,
                     whose poisson() overflows for lam > ~2.1e9 on Windows

    Returns dict of vectorized outputs (all arrays over the energy grid):
        I0_A, I1_A           measured currents incl. noise + dark [A]
        I0_ideal_A, I1_ideal_A  noiseless dark-free currents [A]
        mu_obs               ln((I0_A-dark0)/(I1_A-dark1))
        mu_obs_ideal         ln(I0_ideal/I1_ideal)
        flux_at_sample       flux arriving at the sample (before sample) [ph/s]
        flux_at_i1           flux entering the I1 chamber [ph/s]
        T_sample, T_i0, T_i1, T_airB, T_airA, T_air_s2d   transmitted fractions
        resp0_A_per_phps, resp1_A_per_phps   chamber responses [A/(ph/s)]
        n_abs0, n_abs1       expected absorbed photons per dwell (None if
                             noiseless)
        meta                 config echo dict
    """
    if not XRAYDB_OK:
        raise RuntimeError("xraydb not available -- cannot run ic chain")

    E = np.asarray(energies_eV, dtype=np.float64)
    mu_t = np.asarray(mu_t, dtype=np.float64)
    if E.shape != mu_t.shape:
        raise ValueError("energies_eV and mu_t must have the same shape")
    flux_in = np.broadcast_to(np.asarray(flux_in, dtype=np.float64),
                              E.shape).astype(np.float64)

    cfg0 = dict(DEFAULT_I0)
    cfg0.update(i0 or {})
    cfg1 = dict(DEFAULT_I1)
    cfg1.update(i1 or {})

    # --- chamber responses + attenuations ---
    resp0, att0 = chamber_response(E, cfg0["gas"], cfg0["length_cm"],
                                   cfg0.get("pressure_atm", 1.0),
                                   both_carriers, with_compton)
    resp1, att1 = chamber_response(E, cfg1["gas"], cfg1["length_cm"],
                                   cfg1.get("pressure_atm", 1.0),
                                   both_carriers, with_compton)
    T_i0 = 1.0 - att0["atten_total"]
    T_i1 = 1.0 - att1["atten_total"]

    # --- air segments ---
    T_airB = air_transmission(E, cfg0.get("air_before_cm", 0.0))
    T_airA = air_transmission(E, cfg0.get("air_after_cm", 0.0))
    T_air_s2d = air_transmission(E, cfg1.get("air_path_cm", 0.0))

    # --- sample ---
    T_sample = np.exp(-mu_t)

    # --- flux chain (design doc 3a steps 2-5) ---
    # I0 chamber sits before the KB focusing: sees ratio_prefocus of SSOT.
    flux_i0 = flux_in * ratio_prefocus * T_airB
    # Sample sees the full (focused) SSOT flux minus upstream losses;
    # KB focusing itself is already inside the SSOT (no double counting, R1).
    flux_at_sample = flux_in * T_airB * T_i0 * T_airA
    flux_after_sample = flux_at_sample * T_sample
    flux_at_i1 = flux_after_sample * T_air_s2d

    # --- ideal (noiseless, dark-free) currents ---
    I0_ideal = flux_i0 * resp0
    I1_ideal = flux_at_i1 * resp1

    # --- noise (Poisson on absorbed photons per dwell) ---
    if rng is None and seed is not None:
        rng = np.random.default_rng(seed)
    noisy = (dwell_s is not None) and (rng is not None)
    n_abs0 = n_abs1 = None
    if noisy:
        n_abs0 = flux_i0 * att0["atten_total"] * float(dwell_s)
        n_abs1 = flux_at_i1 * att1["atten_total"] * float(dwell_s)
        I0_meas = I0_ideal * _poisson_factor(n_abs0, rng) + dark0_A
        I1_meas = I1_ideal * _poisson_factor(n_abs1, rng) + dark1_A
    else:
        I0_meas = I0_ideal + dark0_A
        I1_meas = I1_ideal + dark1_A

    # --- observable: dark-corrected log ratio ---
    eps = 1.0e-30  # guard for saturated / dark-floor points (thick sample)
    num = np.maximum(I0_meas - dark0_A, eps)
    den = np.maximum(I1_meas - dark1_A, eps)
    mu_obs = np.log(num / den)
    mu_obs_ideal = np.log(np.maximum(I0_ideal, eps)
                          / np.maximum(I1_ideal, eps))

    return {
        "I0_A": I0_meas,
        "I1_A": I1_meas,
        "I0_ideal_A": I0_ideal,
        "I1_ideal_A": I1_ideal,
        "mu_obs": mu_obs,
        "mu_obs_ideal": mu_obs_ideal,
        "flux_at_sample": flux_at_sample,
        "flux_at_i1": flux_at_i1,
        "T_sample": T_sample,
        "T_i0": T_i0,
        "T_i1": T_i1,
        "T_airB": T_airB,
        "T_airA": T_airA,
        "T_air_s2d": T_air_s2d,
        "resp0_A_per_phps": resp0,
        "resp1_A_per_phps": resp1,
        "n_abs0": n_abs0,
        "n_abs1": n_abs1,
        "meta": {
            "i0": cfg0,
            "i1": cfg1,
            "dark0_A": dark0_A,
            "dark1_A": dark1_A,
            "ratio_prefocus": ratio_prefocus,
            "both_carriers": both_carriers,
            "with_compton": with_compton,
            "dwell_s": dwell_s,
            "seed": seed if noisy else None,
            "noisy": noisy,
        },
    }
