---
title: "Ptycho Migration Tasks"
category: other
status: current
updated: 2026-03-03
tags: [ptychography, migration]
summary: "K4GSR-PTYCHO <-> Beamline 동기화 작업 목록"
---
# K4GSR-PTYCHO: Multi-mode Coherence Implementation Tasks

Reference: `K4GSR-Beamline/ptycho/docs/COHERENCE_MODEL.md`
Source code reference: `K4GSR-Beamline/ptycho/` (simulation codebase)

---

## Prerequisites

- K4GSR-PTYCHO location: `<PROJECTS_DIR>\K4GSR-PTYCHO\`
- Python environment: `ptycho_env` (conda), Python 3.11
- GPU: NVIDIA RTX 3060 Ti, CuPy 14.0.0
- K4GSR-Beamline reference: `<PROJECTS_DIR>\K4GSR-Beamline\ptycho\`
- MATLAB reference data: `K4GSR-PTYCHO/matlab_ref/`

**CRITICAL**: Do NOT modify K4GSR-Beamline files. Only read them as reference.

---

## Task 1: Sync Engine Bug Fixes (HIGH PRIORITY)

### Motivation

K4GSR-Beamline/ptycho/ has accumulated several critical bug fixes that are not
yet in K4GSR-PTYCHO. These MUST be synced before multi-mode work begins,
because multi-mode reconstruction will fail or produce incorrect results
without them.

### Files to sync

| Source (K4GSR-Beamline/ptycho/) | Target (K4GSR-PTYCHO/) | Key changes |
|----------------------------------|------------------------|-------------|
| `engines/gpu/DM.py` | `engines/gpu/DM.py` | Multi-mode probe support (3D), incoherent sum via `get_reciprocal_model`, probe power normalization |
| `engines/gpu/LSQML.py` | `engines/gpu/LSQML.py` | 2x2 coupled LSQ step (`_get_optimal_lsq_step`), multi-mode forward/backward, object update `/Nmodes` |
| `engines/ML.py` | `engines/ML.py` | GPU support via get_xp(), 4D probe shape [Ny,Nx,numprobs,probe_modes] |
| `engines/ml/gradient_ptycho.py` | `engines/ml/gradient_ptycho.py` | fnorm bug fix (removed `/fnorm` from probe and `*fnorm` from chir), multi-mode gradient loop |
| `engines/ml/cgmin1.py` | `engines/ml/cgmin1.py` | No major changes, sync for consistency |
| `engines/gpu/shared/modulus_constraint.py` | `engines/gpu/shared/modulus_constraint.py` | `get_reciprocal_model()` for multi-mode incoherent sum |

### Procedure

1. **Before copying**: Check if K4GSR-PTYCHO has local modifications not in
   K4GSR-Beamline. Use `diff` to compare.
2. **Copy files**: Replace target files with source files.
3. **Verify imports**: K4GSR-PTYCHO may have different import paths. Check
   that all `from .xxx import` and `sys.path.insert` statements work.
4. **Run existing tests**: Ensure single-mode reconstruction still works after
   sync (regression test with MATLAB reference data).

### Critical bug details

**ML fnorm fix** (`gradient_ptycho.py`):
- Line 130: Must be `probe_m = probe_all[:, :, prmode]` (no `/ fnorm`)
- Line 174: Must be `chir = ifft2(fmask * (...) * psiq)` (no `* fnorm`)
- Without this fix: object amplitude blows up to 3-500x ground truth

**LSQML 2x2 coupled** (`LSQML.py`):
- Function `_get_optimal_lsq_step()` implements coupled 2x2 normal equation
- Tikhonov lambda = 0.5, MAX_BETA = 1.0
- Imbalance fallback when AA1/AA4 > 1000
- Without this fix: beta_object hits cap and reconstruction diverges

**DM multi-mode** (`DM.py`):
- Probe internally stored as `[Ny, Nx, Nmodes]`
- `get_reciprocal_model(Psi_list)` computes `sqrt(sum |Psi_m|^2)`
- Object update sums `|P_m|^2` over all modes for illumination denominator
- Probe power normalization each iteration (prevents drift)

### WARNING: sys.path pollution

`K4GSR-Beamline/ptycho/server/data_loader.py` line 9 does:
```python
sys.path.insert(0, str(PROJECT_ROOT))
```
This injects `K4GSR-Beamline/ptycho/` into sys.path. If K4GSR-PTYCHO imports
anything from the Beamline's data_loader, ALL subsequent engine imports will
resolve to the Beamline copy, silently shadowing K4GSR-PTYCHO's own engines.

**Diagnosis**: After importing, check:
```python
import sys
print(sys.modules.get("engines.gpu.LSQML", {None: None}).__file__)
```

If it points to `K4GSR-Beamline/ptycho/engines/...`, you have the pollution
problem. Fix: either keep both codebases in sync, or refactor the import to
use absolute paths.

---

## Task 2: Add Coherence Parameter Input

### Motivation

K4GSR-PTYCHO reconstructs real beamline data. Coherence parameters must come
from beamline metadata (SSA size, energy, mirror specs), not from the JS
simulation. This task adds a Python implementation of the NanoMAX criterion.

### Implementation

Create `K4GSR-PTYCHO/utils/coherence_calculator.py` (or appropriate location
per project structure):

```python
def compute_coherent_fraction(energy_keV, ssa_h_um, ssa_v_um,
                               kb_h_len_m=0.100, kb_v_len_m=0.300,
                               graze_rad=3e-3, R_ssa_m=58.0,
                               kb_h_pos_m=149.90, kb_v_pos_m=149.69,
                               emit_x=58e-12, emit_y=5.8e-12,
                               sigma_src_h_m=19.5e-6, sigma_src_v_m=4.0e-6):
    """
    NanoMAX criterion: compute f_coh, N_modes from beamline parameters.

    Reference: Bjorling et al., OE 28, 5069 (2020)
    See COHERENCE_MODEL.md Section 2 for full derivation.
    """
    # See COHERENCE_MODEL.md Appendix A.1 for complete implementation
    ...
```

### Input sources for real data

| Parameter | Source | Example |
|-----------|--------|---------|
| energy_keV | HDF5 `/entry/instrument/energy` | 10.0 |
| ssa_h_um, ssa_v_um | EPICS PV `K4GSR:ID10:SSA:H_GAP` / metadata | 50.0 |
| kb_h_len_m | Config file (fixed per beamline) | 0.100 |
| kb_v_len_m | Config file | 0.300 |
| graze_rad | Config file | 0.003 |
| emit_x, emit_y | Ring parameters (fixed) | 58e-12 |

### Integration with data_loader

When loading HDF5 data, check for SSA metadata:
```python
# In data_loader load_h5():
for ssa_key in ['entry/instrument/SSA/size', 'instrument/SSA/h_gap']:
    if ssa_key in f:
        data['ssa_h_um'] = float(f[ssa_key][()])
```

If SSA metadata is available, auto-calculate:
```python
coh = compute_coherent_fraction(data['energy_keV'], data['ssa_h_um'], ...)
if coh['f_coh'] < 0.5:
    print(f"[INFO] f_coh={coh['f_coh']:.3f}, suggest N_modes={coh['N_modes']}")
```

---

## Task 3: Multi-mode Probe Initialization in data_loader

### Motivation

Higher probe modes must be initialized with Hermite-Gaussian structure (not
random phase) for reconstruction to converge. This matches the MATLAB
PtychoShelves convention.

### Implementation

Add to `data_loader.py` (or create a new `utils/probe_modes.py`):

```python
def init_hermite_modes(probe_0, n_modes, f_coh, mode_start_pow=0.02):
    """
    Initialize multi-mode probe using Hermite-Gaussian modulation.

    See COHERENCE_MODEL.md Section 4 and Appendix A.2 for details.

    Args:
        probe_0:  [Ny, Nx] complex, single-mode probe
        n_modes:  int, number of modes (>= 1)
        f_coh:    float, coherent fraction (0 to 1)
        mode_start_pow: float, initial power per higher mode (default 0.02)

    Returns:
        probes: [Ny, Nx, n_modes] complex128
    """
    # See COHERENCE_MODEL.md Appendix A.2 for complete implementation
    ...
```

### Modify `build_p_dict()` in data_loader

Replace the current random-phase initialization:

```python
# BEFORE (bad: random phase):
rand_phase = np.exp(2j * np.pi * np.random.rand(*asize))
probes_4d[:, :, 0, m] = probes_4d[:, :, 0, 0] * scale * rand_phase

# AFTER (good: Hermite modes):
from utils.coherence_calculator import compute_coherent_fraction
from utils.probe_modes import init_hermite_modes  # or inline

if probe_modes > 1:
    f_coh = engine_params.get('coherent_fraction', 0.5)
    probes_3d = init_hermite_modes(probe_2d, probe_modes, f_coh,
                                    mode_start_pow=0.02)
    probes_4d = probes_3d.reshape(asize[0], asize[1], 1, probe_modes)
```

### Critical anti-patterns

- **DO NOT** use `np.random.rand()` for mode phase initialization. Modes collapse.
- **DO NOT** add SVD orthogonalization in DM iterations. It causes divergence.
- **DO** use `mode_start_pow=0.02` (2% power per higher mode). Starting too
  high causes instability; too low prevents mode development.
- **DO** verify that `sum(||P_k||^2) = Etot` (total power preserved).

---

## Task 4: Engine Parameter Routing

### Motivation

The reconstruction config must correctly route the `probe_modes` parameter
through data_loader, engine_runner, and into each engine.

### Parameter flow

```
User config: {"probe_modes": 3, "coherent_fraction": 0.5}
    |
    v
data_loader.build_p_dict():
    p['probe_modes'] = 3
    p['probes'] shape = [Ny, Nx, 1, 3]   (4D, MATLAB convention)
    |
    v
engine_runner:
    probes_in = p['probes'][:, :, 0, :]   -> [Ny, Nx, 3]  (for DM/LSQML)
    OR
    p['probes'] stays 4D                  (for ML)
    |
    v
Engine:
    DM:    probes [Ny, Nx, 3] -> per-mode exit wave + incoherent sum
    ML:    probes [Ny, Nx, 1, 3] -> probe_all = probes[:,:,prnum,:] -> per-mode gradient
    LSQML: probes [Ny, Nx, 3] -> per-mode forward, mode-0 beta estimation
```

### engine_runner.py modifications

In `_run_dm_gpu()` and `_run_lsqml()`:
```python
# Already handles multi-mode:
probes = p['probes']
if probes.ndim == 4:
    probes_in = probes[:, :, 0, :] if probes.shape[3] > 1 else probes[:, :, 0, 0]
```

After engine returns, repack:
```python
if pr.ndim == 3:
    p_out['probes'] = pr.reshape(pr.shape[0], pr.shape[1], 1, pr.shape[2])
```

This is already implemented in K4GSR-Beamline's engine_runner.py. Sync this
file as well.

### WebSocket config message

For the K4GSR-PTYCHO web UI, the reconstruction config should accept:
```json
{
    "engine": "DM_LSQML",
    "number_iterations": 300,
    "lsqml_iterations": 100,
    "probe_modes": 3,
    "coherent_fraction": 0.5
}
```

---

## Task 5: Quality Assessment Update

### Motivation

When multi-mode reconstruction is available, the quality assessment should
report coherence-related information and suggest multi-mode when appropriate.

### Modifications to `_assess_quality()` in engine_runner.py

```python
# Add to quality dict:
quality['probe_modes'] = n_probe_modes
quality['coherent_fraction'] = p_out.get('coherent_fraction', None)

# Suggest multi-mode if single-mode and grade is poor:
if n_probe_modes == 1 and quality['grade'] in ('MARGINAL', 'POOR'):
    # Check if SSA metadata suggests partial coherence
    f_coh = p_out.get('coherent_fraction', None)
    if f_coh is not None and f_coh < 0.5:
        quality['recommendations'].append(
            f'Single probe mode with f_coh={f_coh:.3f}. '
            f'Multi-mode reconstruction (N_modes={int(np.ceil(1/f_coh))}) '
            'may improve quality.'
        )
    else:
        quality['recommendations'].append(
            'Single probe mode used. If SSA is open (>50um), '
            'multi-mode reconstruction may improve quality.'
        )
```

### Mode power distribution in results

After reconstruction completes, report the actual mode power distribution:
```python
if probes_full.ndim >= 3:
    mode_powers = []
    for m in range(n_probe_modes):
        if probes_full.ndim == 4:
            pm = probes_full[:, :, 0, m]
        else:
            pm = probes_full[:, :, m]
        mode_powers.append(float(np.sum(np.abs(pm)**2)))
    total = sum(mode_powers)
    quality['mode_powers'] = [round(p/total, 4) for p in mode_powers]
```

This tells the user how power was distributed across modes after reconstruction
(should converge toward the geometric decay Emod if multi-mode is needed).

---

## Task 6: Testing

### 6.1 Regression test (single-mode)

After syncing engine files (Task 1), verify that existing single-mode
reconstruction still matches MATLAB reference:

```bash
cd <PROJECTS_DIR>\K4GSR-PTYCHO
conda activate ptycho_env
python tests/compare_matlab_dm.py
python tests/compare_matlab_lsqml.py
```

Expected: Object correlation r > 0.85, probe correlation r > 0.99.

### 6.2 Multi-mode synthetic test

Use K4GSR-Beamline's synthetic data generator to create test data:

```python
# In K4GSR-PTYCHO test script:
import sys
sys.path.insert(0, r'<PROJECTS_DIR>\K4GSR-Beamline\ptycho')
from synth_ptycho import SyntheticPtycho

gen = SyntheticPtycho.from_dataset(
    dataset_id=6, asize=128, energy_keV=10.0,
    N_photons=int(1e8), scan_lx_um=10, scan_ly_um=10,
    N_modes=3, coherent_fraction=0.5,
)
data = gen.generate(noise_sigma=0.0, rng_seed=42)
```

Then reconstruct with K4GSR-PTYCHO's engines and compare against the S1-S6
table in COHERENCE_MODEL.md Section 6.

### 6.3 Verification criteria (S1-S6 scenarios)

| Scenario | Expected norm_error | Condition |
|----------|---------------------|-----------|
| S1: coh=1.0, recon 1 mode | < 0.10 | Baseline |
| S3: coh=0.5 gen 3 modes, recon 1 mode | > S1 | Partial coh degrades |
| S4: coh=0.5 gen 3 modes, recon 3 modes | < S3 | Multi-mode helps |
| S5: coh=0.2 gen 5 modes, recon 1 mode | > S3 | Lower coh = worse |
| S6: coh=0.2 gen 5 modes, recon 5 modes | < S5 | Multi-mode helps |

### 6.4 MATLAB reference data

If available at `K4GSR-PTYCHO/matlab_ref/`, compare multi-mode probe modes
against MATLAB PtychoShelves `prepare_initial_probes.m` output.

---

## Important Warnings Summary

1. **DO NOT add SVD orthogonalization in DM iterations** -- causes divergence.
   SVD is acceptable only in LSQML as a post-processing step.

2. **DO NOT use random phase for probe mode initialization** -- modes will
   collapse to the dominant mode. Always use Hermite-Gaussian modulation.

3. **ALWAYS use Hermite modes for initialization** -- matching PtychoShelves
   `mode_start = 'herm'` convention.

4. **High photon count (>= 1e8) needed** for multi-mode benefit to be
   measurable. At low photon counts (1e4), per-mode statistics are too poor.

5. **sys.path pollution**: `data_loader.py` inserts `K4GSR-Beamline/ptycho/`
   into sys.path, which can shadow K4GSR-PTYCHO's own engine files. Check
   `sys.modules["engines.gpu.LSQML"].__file__` after importing.

6. **fnorm consistency**: If your data pipeline uses a different FFT
   normalization than K4GSR-Beamline's, the ML gradient will be wrong.
   Verify that `fmag^2` and `|FFT(P*O)|^2` are on the same scale.

7. **Object update in LSQML**: When using multi-mode, divide the accumulated
   object gradient by `Nmodes` to prevent overshoot (MATLAB convention:
   `beta_object /= par.probe_modes`).

8. **Probe power normalization in DM**: After each iteration, rescale total
   probe power to match the initial value. Without this, probe and object
   undergo reciprocal scaling drift.

---

## File Dependency Map

```
coherence_calculator.py (NEW)
    Used by: data_loader.py (auto-calculate f_coh from metadata)

probe_modes.py (NEW) -- or inline in data_loader.py
    Used by: data_loader.py (Hermite mode initialization)

data_loader.py (MODIFIED)
    - build_p_dict(): use Hermite init instead of random phase
    - load_h5(): read SSA metadata
    - generate_synthetic(): pass N_modes, coherent_fraction

engine_runner.py (MODIFIED or SYNCED)
    - Probe 4D -> 3D reshape for DM/LSQML
    - Probe 3D -> 4D repack after engine
    - Quality assessment with coherence info

engines/gpu/DM.py (SYNCED from Beamline)
    - Multi-mode probe loop
    - get_reciprocal_model() for incoherent sum
    - Probe power normalization

engines/gpu/LSQML.py (SYNCED from Beamline)
    - 2x2 coupled LSQ step
    - Multi-mode forward/backward
    - Object update / Nmodes

engines/ML.py (SYNCED from Beamline)
    - GPU support
    - 4D probe handling

engines/ml/gradient_ptycho.py (SYNCED from Beamline)
    - fnorm bug fix
    - Multi-mode gradient loop

engines/gpu/shared/modulus_constraint.py (SYNCED from Beamline)
    - get_reciprocal_model()
```
