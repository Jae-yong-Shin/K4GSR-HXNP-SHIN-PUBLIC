---
title: "Coherence Model"
category: other
status: current
updated: 2026-03-03
tags: [ptychography, coherence, physics]
summary: "다중 모드 코히어런스: NanoMAX 기준, van Cittert-Zernike, Hermite"
---
# Multi-mode Coherence Model for Ptychography

## Technical Reference for K4GSR-PTYCHO Migration

This document describes the partial coherence (multi-mode) model implemented in
K4GSR-Beamline's ptychography simulation pipeline. It is intended as a complete
technical reference so that another Claude session can implement the same features
in the K4GSR-PTYCHO project (real beamline data reconstruction).

---

## 1. Overview

### What was implemented

A complete partial coherence pipeline for ptychographic CDI at the K4GSR BL10
NanoProbe beamline, comprising:

1. **Coherence parameter calculation** based on the NanoMAX criterion
   (Bjorling et al., Opt. Express 28, 5069, 2020), accounting for KB mirror
   acceptance aperture, SSA size, and source parameters.
2. **Multi-mode forward model** (data synthesis) using Hermite-Gaussian probe
   modes with geometrically decaying power, following the PtychoShelves
   convention where power is embedded in the probe amplitude.
3. **Multi-mode reconstruction** in DM, ML, and LSQML engines with proper
   incoherent summation and mode-specific update rules.
4. **Multi-mode probe initialization** using Hermite polynomial modulation
   (not random phase), with correct power normalization.

### Why

At 4th-generation synchrotrons, even with undulator sources of very low
emittance, partial coherence effects can degrade ptychographic reconstruction
quality when the SSA (Secondary Source Aperture) is opened beyond the
coherent limit. Multi-mode reconstruction recovers lost information by
decomposing the mutual coherence function into orthogonal probe modes.

### Source code locations (K4GSR-Beamline)

| File | Role |
|------|------|
| `js/experiment/05_ptycho_sim.js` lines 953-1157 | JS coherence model (NanoMAX criterion, mode generation) |
| `ptycho/synth_ptycho.py` lines 822-968 | Multi-mode forward model (data synthesis) |
| `ptycho/engines/gpu/DM.py` | DM reconstruction with multi-mode probe |
| `ptycho/engines/ML.py` + `engines/ml/gradient_ptycho.py` | ML refinement with multi-mode |
| `ptycho/engines/gpu/LSQML.py` | LSQML engine with multi-mode + coupled LSQ step |
| `ptycho/server/data_loader.py` | Probe initialization and p_dict construction |
| `ptycho/server/engine_runner.py` | Engine dispatch and multi-mode probe repacking |
| `ptycho/engines/gpu/shared/modulus_constraint.py` | `get_reciprocal_model()` for incoherent sum |
| `docs/knowledge/60_coherence_theory.md` | Extended theory document |

---

## 2. Physics: NanoMAX Coherence Criterion

### Reference

Bjorling et al., "Ptychographic characterization of a coherent nanofocused
X-ray beam", Optics Express 28(4), 5069-5076 (2020).

### 2.1 Van Cittert-Zernike Theorem

For an extended incoherent source of RMS size `sigma_source`, the transverse
coherence length at distance R is:

```
xi = lambda * R / (2 * pi * sigma_source)
```

Key insight: coherence improves with smaller source, longer distance, and
longer wavelength.

### 2.2 KB Mirror Projected Aperture

The KB mirrors accept only the portion of the beam that falls within their
projected aperture:

```
A_KB = L_mirror * sin(theta_graze)
```

K4GSR BL10 parameters:

| Parameter | KBH (horizontal) | KBV (vertical) |
|-----------|-------------------|----------------|
| Mirror length | 100 mm | 300 mm |
| Grazing angle | 3 mrad | 3 mrad |
| Projected aperture | 0.300 mm | 0.900 mm |
| Distance from source | 149.90 m | 149.69 m |
| Distance from SSA | 91.90 m | 91.69 m |

### 2.3 Coherent Source Sigma

The maximum effective source size (at the SSA plane) that fills the KB
aperture coherently:

```
sigma_coh = lambda * L_SSA_to_KB / (2 * pi * A_KB)
```

This defines the coherent limit. When the effective source is smaller than
`sigma_coh`, the KB aperture is coherently illuminated (single mode).

Numerical values at 10 keV (lambda = 0.124 nm):

| Axis | L_SSA_to_KB (m) | A_KB (mm) | sigma_coh (um) | SSA_coh (um) |
|------|-----------------|-----------|----------------|--------------|
| H | 91.90 | 0.300 | 6.04 | 20.9 |
| V | 91.69 | 0.900 | 2.01 | 7.0 |

Where `SSA_coh = 2 * sqrt(3) * sigma_coh` is the rectangular aperture full
width that corresponds to the coherent source sigma.

### 2.4 Effective Source Sigma

The effective source seen by the KB mirrors is limited by whichever is
smaller -- the beam itself or the SSA:

```
sigma_beam_at_SSA = sqrt(sigma_source^2 + (sigma_div * R_SSA)^2)
sigma_SSA = SSA_full_width / (2 * sqrt(3))     [rectangular aperture RMS]
sigma_eff = min(sigma_beam_at_SSA, sigma_SSA)
```

IMPORTANT: SSA is a rectangular aperture. The RMS of a uniform distribution
over width W is `W / (2*sqrt(3))`, NOT `W / 2.355` (which is Gaussian
FWHM-to-sigma).

### 2.5 Mode Count Per Axis

```
M_H = max(1, sigma_eff_H / sigma_coh_H)
M_V = max(1, sigma_eff_V / sigma_coh_V)
M_total = M_H * M_V
N_modes = ceil(M_total)
f_coh = min(1.0, 1.0 / M_total)
```

### 2.6 K4GSR BL10 Numbers Table (10 keV)

Source parameters: E_RING=4 GeV, emittance_H=58 pm*rad, emittance_V=5.8 pm*rad,
SSA at 58 m from source.

```
SSA(um) | sigEff_H(um) | sigEff_V(um) | M_H  | M_V  | M_total | N_modes | f_coh
--------|--------------|--------------|------|------|---------|---------|------
     5  |  1.44        |  1.44        | 1.00 | 1.00 |   1.0   |    1    | 1.000
     7  |  2.02        |  2.02        | 1.00 | 1.01 |   1.0   |    1    | 0.995
    10  |  2.89        |  2.89        | 1.00 | 1.44 |   1.4   |    2    | 0.696
    30  |  8.66        |  3.03        | 1.43 | 1.51 |   2.2   |    3    | 0.463
    50  | 14.43        |  3.03        | 2.39 | 1.51 |   3.6   |    4    | 0.278
   100  | 17.70        |  3.03        | 2.93 | 1.51 |   4.4   |    5    | 0.227
  open  | 17.70        |  3.03        | 2.93 | 1.51 |   4.4   |    5    | 0.227
```

Note: V-axis (KBV 300mm) is the bottleneck: sigma_beam_V(3.03 um) >
sigma_coh_V(2.01 um), so even without SSA, V already has ~1.5 modes at 10 keV.

### 2.7 Liouville's Theorem Warning

**NEVER use focused beam size to compute f_coh.** Coherent fraction is a
phase-space invariant: focusing reduces beam size but increases divergence,
preserving the emittance (and hence f_coh). Using the 50 nm focused spot
instead of the ~18 um source at SSA gives f_coh ~ 1.0 always, which is wrong.

---

## 3. Forward Model: Multi-mode Data Generation

### Reference file: `ptycho/synth_ptycho.py`, lines 822-968

### 3.1 PtychoShelves MATLAB Convention

Power is embedded in probe amplitude, not carried as a separate weight array.
The measured intensity is a uniform (unweighted) incoherent sum:

```
I(q) = sum_k |FFT(P_k * O)|^2       (uniform sum, weight = 1 for all modes)
```

This matches MATLAB PtychoShelves `+detector/+virtual/load_data.m` line 251:
```matlab
diffraction = sum(diffraction, 4);   % uniform sum over modes
```

### 3.2 Mode Power Distribution (Emod)

Power fractions follow a geometric decay:

```python
Emod = np.zeros(n_modes)
Emod[0] = 1.0
for k in range(1, n_modes):
    Emod[k] = (1.0 - f_coh) ** k
Emod /= Emod.sum()   # normalize so sum = 1
```

Each probe mode is then scaled so that:

```
||P_k||^2 = Emod[k] * Etot
```

where `Etot = sum(|P_0_original|^2)` is the total power of the original
single-mode probe. This is the MATLAB PtychoShelves convention from
`+core/prepare_initial_probes.m` lines 133-135:

```matlab
p.probes(:,:,prnum,prmode) = p.probes(:,:,prnum,prmode) ...
    * sqrt(Emod(prmode) / sum(sum(abs(p.probes(:,:,prnum,prmode)).^2)));
```

### 3.3 Hermite-Gaussian Mode Generation

Higher modes are generated by modulating the base probe with Hermite
polynomials on a normalized coordinate grid:

```python
# Probe extent estimation (sigma from FWHM)
sig_y = FWHM_y / 2.355
sig_x = FWHM_x / 2.355

# Normalized coordinates
yy = (arange(Ny) - Ny/2) / sig_y
xx = (arange(Nx) - Nx/2) / sig_x
YY, XX = meshgrid(yy, xx, indexing='ij')

# Hermite order pairs for modes 1, 2, 3, ...
herm_orders = [(1,0), (0,1), (1,1), (2,0), (0,2),
               (2,1), (1,2), (2,2), (3,0), (0,3)]

# Mode k:
ny_ord, nx_ord = herm_orders[k-1]
hy = hermite_poly(ny_ord, YY)
hx = hermite_poly(nx_ord, XX)
modulation = hy * hx
mode_k = probe * modulation
# then normalize: ||mode_k||^2 = Emod[k] * Etot
```

The Hermite polynomials use the probabilist's convention:
- H_0(x) = 1
- H_1(x) = x
- H_2(x) = x^2 - 1
- H_3(x) = x^3 - 3x
- Recurrence: H_{n+1}(x) = x * H_n(x) - n * H_{n-1}(x)

Full implementation in `synth_ptycho.py` function `_hermite_poly()`.

### 3.4 Noise Model

After computing multi-mode intensity:

```
I_total = sum_k |FFT(P_k * O_patch)|^2
```

A normalization factor `corr` is computed (two-pass model):
- Pass 1: Compute I_max_all and I_sum_all across all positions
- Pass 2: Apply `I_counts = I * corr`, then Poisson noise, then `fmag = sqrt(noisy)`

The probe output is scaled by `sqrt(corr)` to match the fmag scale.

---

## 4. Reconstruction: Multi-mode Probe Initialization

### Reference file: `ptycho/server/data_loader.py`, `build_p_dict()` method

### 4.1 Current Implementation (data_loader.py)

The current `build_p_dict()` in K4GSR-Beamline initializes higher probe modes
as scaled copies with random phase (legacy code from before the Hermite model
was fully validated):

```python
# Current (NOT recommended for multi-mode):
for m in range(1, probe_modes):
    scale = 0.3 ** m
    rand_phase = np.exp(2j * np.pi * np.random.rand(*asize))
    probes_4d[:, :, 0, m] = probes_4d[:, :, 0, 0] * scale * rand_phase
```

### 4.2 Recommended: Hermite Mode Initialization

For K4GSR-PTYCHO, use the Hermite-Gaussian initialization from `synth_ptycho.py`:

```python
def init_probe_modes(probe_0, n_modes, f_coh=0.5, mode_start_pow=0.02):
    """
    Initialize multi-mode probe array using Hermite-Gaussian modes.

    Args:
        probe_0:  [Ny, Nx] complex, single-mode probe
        n_modes:  int, number of modes
        f_coh:    float, coherent fraction (0 to 1)
        mode_start_pow: float, initial power fraction for higher modes
                        (default 0.02 = 2% of total per higher mode)

    Returns:
        probes: [Ny, Nx, n_modes] complex
    """
    Ny, Nx = probe_0.shape
    Etot = float(np.sum(np.abs(probe_0)**2))

    # Power fractions (geometric decay from coherent fraction)
    Emod = np.zeros(n_modes)
    Emod[0] = 1.0
    for k in range(1, n_modes):
        Emod[k] = (1.0 - f_coh) ** k
    Emod /= Emod.sum()

    # For initial reconstruction, use a conservative power distribution:
    # mode_start_pow per higher mode, rest goes to mode 0
    Emod_init = np.zeros(n_modes)
    Emod_init[0] = 1.0 - mode_start_pow * (n_modes - 1)
    for k in range(1, n_modes):
        Emod_init[k] = mode_start_pow
    Emod_init = np.maximum(Emod_init, 0)
    Emod_init /= Emod_init.sum()

    probes = np.zeros((Ny, Nx, n_modes), dtype=np.complex128)

    # Mode 0: original probe, power-normalized
    probes[:, :, 0] = probe_0 * np.sqrt(Emod_init[0] * Etot / max(Etot, 1e-30))

    # Estimate probe sigma from FWHM
    amp = np.abs(probe_0)
    # ... (same sigma estimation as synth_ptycho.py lines 866-870)

    # Hermite orders
    herm_orders = [(1,0), (0,1), (1,1), (2,0), (0,2),
                   (2,1), (1,2), (2,2), (3,0), (0,3)]

    for k in range(1, n_modes):
        ny_ord, nx_ord = herm_orders[min(k-1, len(herm_orders)-1)]
        # ... Hermite modulation (same as synth_ptycho.py lines 890-901)
        # Normalize: ||mode_k||^2 = Emod_init[k] * Etot
        probes[:, :, k] = mode_k * np.sqrt(Emod_init[k] * Etot / pk_power)

    return probes
```

### 4.3 Critical Anti-patterns

**DO NOT use random phase initialization for probe modes.**
Random phase modes collapse to the dominant mode during reconstruction because
the random phase has no spatial structure for the algorithm to differentiate.

**DO NOT use in-iteration SVD orthogonalization in DM.**
Adding SVD orthogonalization (`np.linalg.svd` on the probe stack) inside the
DM iteration loop causes divergence. The DM overlap constraint already provides
sufficient mode separation. SVD orthogonalization is appropriate ONLY in LSQML
(where it is not currently implemented either, but could be added post-convergence).

**DO use the `mode_start_pow` parameter (default 0.02).**
Starting higher modes at 2% power lets the algorithm gradually discover the
correct mode distribution. Starting too high (e.g., equal power) causes
instability; too low (e.g., 1e-6) prevents modes from developing.

### 4.4 MATLAB Reference

PtychoShelves `+core/prepare_initial_probes.m`:
- Uses `p.mode_start = 'herm'` for Hermite initialization
- `Emod(prmode) = p.mode_start_pow ^ (prmode-1)` with default `mode_start_pow = 0.02`
- Normalization: `||P_k||^2 = Emod[k] * Etot`

---

## 5. Engine-Specific Notes

### 5.1 DM (Difference Map) -- `engines/gpu/DM.py`

**Multi-mode support**: Full. The probe is stored as `[Ny, Nx, Nmodes]`
internally (3D). The DM engine:

1. Forms exit waves per mode: `psi_m = obj_view * probes[:, :, m]`
2. Forward FFT per mode: `Psi_m = fwd_fourier_proj(psi_m, mode)`
3. Incoherent sum for modulus constraint: `aPsi = sqrt(sum_m |Psi_m|^2)`
   via `get_reciprocal_model(Psi_list)` in `shared/modulus_constraint.py`
4. Modulus constraint applies the same ratio `modF / aPsi` to ALL modes
5. Back-propagate and DM update per mode independently
6. Overlap constraint: probe update per mode, object update sums over modes
7. **Probe power normalization**: After each iteration, total probe power
   (sum over all modes) is rescaled to match the initial value, preventing
   probe-object scaling drift.

**Key parameter**: `p['probe_modes']` (integer, default 1). When > 1,
`data_loader.py:build_p_dict()` constructs 4D probe `[Ny, Nx, 1, n_modes]`
and `engine_runner.py` reshapes to 3D `[Ny, Nx, n_modes]` before calling DM.

**No SVD orthogonalization in DM iterations.** This is intentional; adding it
caused divergence in testing.

### 5.2 ML (Maximum Likelihood) -- `engines/ML.py` + `ml/gradient_ptycho.py`

**Multi-mode support**: Full. The probe is stored as 4D `[Ny, Nx, numprobs, probe_modes]`.

The gradient computation in `gradient_ptycho.py`:

1. Extracts all probe modes: `probe_all = probes[:, :, prnum, :]` -> `[Ny, Nx, n_modes]`
2. Forward model per (object_mode, probe_mode) pair:
   ```python
   for obmode in range(object_modes):
       for prmode in range(n_probe_modes):
           psiq = fft2(obj_proj * probe_m)     # no fnorm division
           Iq_all += |psiq|^2                   # incoherent sum
   ```
3. Poisson log-likelihood: `func -= sum(fmask * (fmag2 * log(alpha*Iq) - alpha*Iq))`
4. Gradient per mode:
   ```python
   chir = ifft2(fmask * (alpha - fmag2/Iq) * psiq)    # no fnorm
   grado += 2 * conj(probe_m) * chir                    # object gradient
   gradp += 2 * conj(object) * chir                     # probe gradient per mode
   ```

**fnorm bug fix (CRITICAL)**: The original MATLAB code divides probe by
`fnorm = sqrt(asize^2)` in the forward model and multiplies by `fnorm` in the
backward pass. In our port, we removed this because:
- DM uses `FFT(O*P)` directly (no fnorm)
- SyntheticPtycho generates fmag WITHOUT fnorm normalization
- Keeping fnorm caused `Iq = |FFT(O*P)|^2 / fnorm^2` to be 16384x too small
  vs fmag^2, making the Poisson `fmag^2/Iq` term explode and causing
  amplitude blowup (|ob| max reaching 3-500x ground truth)

The fix: Remove `/fnorm` from probe_m (line 130) AND `*fnorm` from chir
(line 174) in `gradient_ptycho.py`. After fix, DM, LSQML, and ML all produce
|ob| max = 1.41 (matching ground truth).

### 5.3 LSQML -- `engines/gpu/LSQML.py`

**Multi-mode support**: Full. Same probe format as DM: `[Ny, Nx, Nmodes]`.

Key multi-mode behaviors:

1. **Forward model**: Same as DM -- exit wave per mode, incoherent sum for
   modulus constraint.
2. **Residual per mode**: `chi_m = constrained_m - Psi_m` for each mode
3. **Object gradient sums over modes**: `dO += chi_rs_m * conj(P_m)`
4. **Object update divided by Nmodes**: Line 238-239:
   ```python
   obj_update += dO * beta_object_all[ii] / Nmodes
   ```
   This prevents overshoot when multiple modes contribute to the same gradient.
   (MATLAB LSQML.m line 302: `beta_object /= par.probe_modes`)
5. **Optimal LSQ step (2x2 coupled system)**: Uses mode-0 approximation for
   computing `beta_probe` and `beta_object` via the coupled normal equation
   (Odstrcil 2018 eq. 16-17):
   ```
   [AA1+lam,  AA2  ] [beta_O]   [Atb1]
   [AA2*,   AA4+lam] [beta_P] = [Atb2]
   ```
   With Tikhonov `lam = 0.5`, MAX_BETA = 1.0.
6. **Imbalance fallback**: When AA1/AA4 > 1000 (e.g., flat initial object with
   structured probe), fall back to decoupled estimates to prevent suppression
   of the weaker channel.

**SVD orthogonalization**: Could be added here (not in DM) as a post-convergence
step, but is not currently implemented.

### 5.4 ePIE -- `engines/gpu/ePIE.py`

**Single-mode only** currently. Multi-mode ePIE would require extending the
exit wave formation and update rules, which is possible but not yet done.

---

## 6. Verification Results

Testing with high-flux conditions: 1e8 photons, 10 keV, ~50 nm beam,
Mandrill phantom (dataset_id=6), asize=128, 144 scan positions.

Engine pipeline: DM(300 iter) -> LSQML(100 iter) unless noted.

### 6.1 Scenario Table

| ID | Description | f_coh | N_modes (gen) | N_modes (recon) | norm_error |
|----|-------------|-------|---------------|-----------------|------------|
| S1 | Coherent, single-mode | 1.0 | 1 | 1 | 0.070 |
| S2 | Coherent, multi-mode recon | 1.0 | 1 | 3 | 0.073 |
| S3 | Partial coh, single-mode recon | 0.5 | 3 | 1 | 0.142 |
| S4 | Partial coh, multi-mode recon | 0.5 | 3 | 3 | 0.095 |
| S5 | Low coh, single-mode recon | 0.2 | 5 | 1 | 0.285 |
| S6 | Low coh, multi-mode recon | 0.2 | 5 | 5 | 0.175 |

### 6.2 Key Validations

- **S3 > S1**: Partial coherence degrades single-mode reconstruction (0.142 > 0.070). Confirmed.
- **S4 < S3**: Multi-mode reconstruction recovers partial coherence loss (0.095 < 0.142). Confirmed.
- **S5 > S3**: Lower coherence further degrades quality (0.285 > 0.142). Confirmed.
- **S6 < S5**: Multi-mode helps even at low coherence (0.175 < 0.285). Confirmed.
- **S2 ~ S1**: Multi-mode recon on coherent data does not significantly hurt (0.073 ~ 0.070). Confirmed.

### 6.3 Notes on Photon Count

Multi-mode benefit is measurable only at high photon counts (>= 1e8 per position).
At low photon counts (1e4), multi-mode reconstruction does not improve over
single-mode because per-mode photon statistics are too poor.

Required photons scale approximately as: `N_required ~ N_modes * N_single_mode`.

---

## 7. What K4GSR-PTYCHO Needs to Implement

### 7.1 Context Differences

K4GSR-Beamline is a simulation-only virtual beamline with a JS frontend.
K4GSR-PTYCHO reconstructs real beamline data, is Python-only, and has no JS.

Key differences for the coherence model:

| Aspect | K4GSR-Beamline | K4GSR-PTYCHO |
|--------|----------------|--------------|
| Coherence params source | JS `_ptychoCoherentFraction()` | Beamline metadata / user input |
| SSA size | `state.ssaH`, `state.ssaV` | EPICS PV or HDF5 metadata |
| Mirror specs | Hardcoded in JS | Config file or metadata |
| Probe input | Synthetic (Gaussian / PSI) | Measured or ptychographic |
| Data format | Synthetic fmag (numpy) | HDF5 experimental data |

### 7.2 Implementation Checklist

1. **Python `coherence_calculator.py`** -- Port of JS `_ptychoCoherentFraction()`:
   - Input: energy_keV, SSA size (um), KB mirror lengths, grazing angle,
     source emittance, distances
   - Output: f_coh, N_modes, M_H, M_V, sigma_coh per axis
   - Must use rectangular aperture RMS: `sigma_SSA = W / (2*sqrt(3))`

2. **Multi-mode probe initialization** in data_loader or a new module:
   - Hermite-Gaussian modes (not random phase)
   - `mode_start_pow = 0.02` per higher mode
   - Power normalization: `||P_k||^2 = Emod[k] * Etot`

3. **Engine parameter routing**:
   - `probe_modes` in reconstruction config
   - Build p_dict with 4D probe: `[Ny, Nx, 1, n_modes]`
   - ML accepts 4D directly; DM/LSQML reshape to 3D `[Ny, Nx, n_modes]`
     in `engine_runner.py`

4. **Quality assessment update**:
   - Report coherence info (f_coh, N_modes) in reconstruction results
   - Suggest multi-mode if f_coh < 0.5 and reconstruction grade is MARGINAL/POOR

5. **Beamline metadata integration**:
   - Read SSA size from HDF5 `/entry/instrument/SSA/size` or equivalent
   - Read energy from existing path `/entry/instrument/energy`
   - Auto-calculate f_coh and suggest N_modes before reconstruction

---

## 8. Key Bug Fixes Applied

These fixes are already in K4GSR-Beamline/ptycho/ and MUST be synced to
K4GSR-PTYCHO before multi-mode work begins.

### 8.1 ML fnorm Bug (`engines/ml/gradient_ptycho.py`)

**Root cause**: Original MATLAB divides probe by `fnorm = sqrt(asize^2) = 128`
in the forward model. Our synth_ptycho generates fmag WITHOUT this fnorm.
Keeping `/fnorm` caused intensity to be 16384x too small, making Poisson
`fmag^2/Iq` term explode.

**Fix**: In `gradient_ptycho.py`:
- Line 130: `probe_m = probe_all[:, :, prmode]` (no `/ fnorm`)
- Line 174: `chir = ifft2(fmask * (alpha - fmag2/Iq) * psiq)` (no `* fnorm`)

**Verification**: After fix, all engines produce |ob| max = 1.41 matching GT.

### 8.2 LSQML 2x2 Coupled LSQ Step (`engines/gpu/LSQML.py`)

**Root cause**: Old decoupled 1D formula `clip(numer/denom, 0, 2.0) * beta_LSQ`
caused divergence because beta_object hit the 2.0 cap.

**Fix**: MATLAB-equivalent 2x2 coupled system in `_get_optimal_lsq_step()`:
- Tikhonov regularization `lam = 0.5`
- MAX_BETA = 1.0
- Imbalance fallback when AA1/AA4 > 1000
- Decoupled floor: coupled beta >= decoupled beta (prevents suppression)

### 8.3 DM Multi-mode Broadcasting (`engines/gpu/DM.py`)

**Changes**:
- Probe stored as 3D `[Ny, Nx, Nmodes]` with per-mode exit wave and update
- `get_reciprocal_model()` for incoherent sum over modes
- Probe power normalization after each iteration (prevents probe-object drift)
- Object update sums |P_m|^2 illumination over all modes
- Single-mode input/output backward compatibility (squeeze back to 2D)

### 8.4 sys.path Pollution Warning

`K4GSR-Beamline/ptycho/server/data_loader.py` line 9:
```python
sys.path.insert(0, str(PROJECT_ROOT))  # inserts K4GSR-Beamline/ptycho/
```

When K4GSR-PTYCHO imports `_BLDataLoader` from the Beamline codebase, this
path injection causes ALL subsequent `from engines.gpu.LSQML import LSQML`
to resolve to the **Beamline copy**, NOT K4GSR-PTYCHO's copy.

Diagnosis: Check `sys.modules["engines.gpu.LSQML"].__file__` to verify
which file is actually loaded.

**Both codebases' engine files must be kept in sync**, or the import path
must be fixed to avoid pollution.

---

## Appendix A: Algorithm Pseudocode

### A.1 NanoMAX Coherent Fraction (Python)

```python
def compute_coherent_fraction(energy_keV, ssa_h_um, ssa_v_um,
                               kb_h_len_m=0.100, kb_v_len_m=0.300,
                               graze_rad=3e-3, R_ssa_m=58.0,
                               kb_h_pos_m=149.90, kb_v_pos_m=149.69,
                               emit_x=58e-12, emit_y=5.8e-12):
    """Compute coherent fraction using NanoMAX criterion."""
    import numpy as np

    lambda_m = 1239.842e-9 / (energy_keV * 1e3)

    # Source parameters (approximate for 4GSR)
    sigma_src_h = np.sqrt(emit_x * beta_x)  # or use photonSrc model
    sigma_src_v = np.sqrt(emit_y * beta_v)
    sigma_div_h = emit_x / sigma_src_h
    sigma_div_v = emit_y / sigma_src_v

    # Beam at SSA
    sigma_beam_h = np.sqrt(sigma_src_h**2 + (sigma_div_h * R_ssa_m)**2)
    sigma_beam_v = np.sqrt(sigma_src_v**2 + (sigma_div_v * R_ssa_m)**2)

    # KB projected apertures
    A_KB_H = kb_h_len_m * np.sin(graze_rad)
    A_KB_V = kb_v_len_m * np.sin(graze_rad)

    # SSA -> KB distances
    L_ssa_to_kbh = kb_h_pos_m - R_ssa_m
    L_ssa_to_kbv = kb_v_pos_m - R_ssa_m

    # Coherent source sigma
    sigma_coh_h = lambda_m * L_ssa_to_kbh / (2 * np.pi * A_KB_H)
    sigma_coh_v = lambda_m * L_ssa_to_kbv / (2 * np.pi * A_KB_V)

    # Effective source sigma (SSA-limited)
    sqrt3 = np.sqrt(3)
    sigma_ssa_h = ssa_h_um * 1e-6 / (2 * sqrt3)
    sigma_ssa_v = ssa_v_um * 1e-6 / (2 * sqrt3)
    sigma_eff_h = min(sigma_beam_h, sigma_ssa_h)
    sigma_eff_v = min(sigma_beam_v, sigma_ssa_v)

    # Mode count
    M_H = max(1.0, sigma_eff_h / sigma_coh_h)
    M_V = max(1.0, sigma_eff_v / sigma_coh_v)
    M_total = M_H * M_V
    N_modes = int(np.ceil(M_total))
    f_coh = min(1.0, 1.0 / M_total)

    return {
        'f_coh': f_coh, 'N_modes': N_modes,
        'M_H': M_H, 'M_V': M_V, 'M_total': M_total,
        'sigma_coh_h_um': sigma_coh_h * 1e6,
        'sigma_coh_v_um': sigma_coh_v * 1e6,
        'sigma_eff_h_um': sigma_eff_h * 1e6,
        'sigma_eff_v_um': sigma_eff_v * 1e6,
    }
```

### A.2 Hermite-Gaussian Probe Mode Init (Python)

```python
def hermite_poly(n, x):
    """Probabilist's Hermite polynomial H_n(x)."""
    if n == 0: return np.ones_like(x)
    if n == 1: return x.copy()
    h_prev2 = np.ones_like(x)
    h_prev1 = x.copy()
    for k in range(2, n + 1):
        h_cur = x * h_prev1 - (k - 1) * h_prev2
        h_prev2, h_prev1 = h_prev1, h_cur
    return h_prev1


def init_hermite_modes(probe_0, n_modes, f_coh, mode_start_pow=0.02):
    """Build [Ny, Nx, n_modes] probe array from base probe."""
    Ny, Nx = probe_0.shape
    Etot = float(np.sum(np.abs(probe_0)**2))

    # Conservative initial power distribution
    Emod = np.zeros(n_modes)
    Emod[0] = max(0, 1.0 - mode_start_pow * (n_modes - 1))
    Emod[1:] = mode_start_pow
    Emod /= Emod.sum()

    probes = np.zeros((Ny, Nx, n_modes), dtype=np.complex128)
    probes[:, :, 0] = probe_0 * np.sqrt(Emod[0])

    # Estimate sigma from probe amplitude
    amp = np.abs(probe_0)
    thresh = amp.max() * 0.5
    above_h = np.where(amp.sum(axis=1) > thresh * Nx * 0.01)[0]
    above_w = np.where(amp.sum(axis=0) > thresh * Ny * 0.01)[0]
    sig_y = max(float(above_h[-1] - above_h[0]) / 2.355, 3.0)
    sig_x = max(float(above_w[-1] - above_w[0]) / 2.355, 3.0)

    yy = (np.arange(Ny) - Ny / 2.0) / sig_y
    xx = (np.arange(Nx) - Nx / 2.0) / sig_x
    YY, XX = np.meshgrid(yy, xx, indexing='ij')

    herm_orders = [(1,0),(0,1),(1,1),(2,0),(0,2),
                   (2,1),(1,2),(2,2),(3,0),(0,3)]

    for k in range(1, n_modes):
        idx = min(k - 1, len(herm_orders) - 1)
        ny_ord, nx_ord = herm_orders[idx]
        modulation = hermite_poly(ny_ord, YY) * hermite_poly(nx_ord, XX)
        mode_k = probe_0 * modulation
        pk_power = float(np.sum(np.abs(mode_k)**2))
        if pk_power > 0:
            mode_k *= np.sqrt(Emod[k] * Etot / pk_power)
        probes[:, :, k] = mode_k

    return probes
```
