---
title: "Ptycho CLAUDE.md"
category: other
status: current
updated: 2026-03-03
tags: [ptychography, agent]
summary: "K4GSR-PTYCHO AI Agent 지침: 폴더 구조, 코딩 규칙"
---
# K4GSR-PTYCHO — Ptychography Reconstruction

## Purpose
Reconstruct complex 2D images (object + probe) from X-ray diffraction patterns.
Upstream project that generates input data for K4GSR-TOMO.

## Status: Complete (< 0.3% error vs MATLAB)

## Output Format
- `stack_object_complex`: shape (Nlayers, Nw, Nangles) complex128
- Saved as HDF5/NPZ, consumed by K4GSR-TOMO for sinogram generation

## Folder Structure
```
K4GSR-PTYCHO/
├── engines/
│   ├── DM.py          # Difference Map engine (CPU)
│   ├── ML.py          # Maximum Likelihood engine (CPU)
│   ├── dm/            # DM sub-modules
│   ├── ml/            # ML sub-modules
│   └── gpu/           # LSQML GPU engine (CuPy, RTX 3060 Ti)
├── server/            # WebSocket server + utilities
├── web/               # Frontend UI (HTML + JS)
├── utils/             # FFT, gradient, shift utilities
├── tests/             # Comparison test scripts
├── matlab_ref/        # MATLAB reference .mat / .npy files
├── results/           # Reconstruction results + history
└── synth_ptycho.py    # Synthetic data generator
```

## Key Parameters (GPU_engines_test.m baseline)
- asize = [128, 128]
- use_gpu = True (RTX 3060 Ti, CuPy 14.0.0)
- DM: 50 iter, pfft_relaxation=0.1, probe_support_radius=0.9
- ML: 50 iter, accelerated_gradients_start=5
- LSQML: 50 iter (GPU)

## Runtime Environment
- conda env: **ptycho_env**
- Python: `C:\Users\owner\miniconda3\envs\ptycho_env\python.exe`
- Packages: numpy, scipy, matplotlib, h5py, websockets, cupy-cuda12x, pillow

## Verification Results (2026-02-17)
- Python DM:    Object r=0.594, Probe r=0.998 (1.2s)
- Python LSQML: Object r=0.872, Probe r=0.9997 (1.4s)
- MATLAB DM GPU: Object r=0.334, Probe r=0.903 (12s)
- MATLAB ML GPU: Object r=0.328, Probe r=0.908 (14s)

## Porting Conventions
- cSAXS PtychoShelves convention: sum(|probe|^2) = asize^2
- FFT: fmag = fftshift(sqrt(|FFT2|^2))
- clip_object = False (quality degradation when True)

## Code Placement Rules

New code MUST go in the correct domain folder. Never create files at the project root.

| Domain | Folder | What belongs here |
|--------|--------|-------------------|
| **Reconstruction engines** | `engines/` | DM, ML, LSQML algorithm code. Sub-modules in `engines/dm/`, `engines/ml/`, `engines/gpu/`. Shared GPU ops in `engines/gpu/shared/` |
| **Server / backend** | `server/` | WebSocket handlers, engine runner, data loading, history, batch queue, image encoding. One file per responsibility |
| **Frontend** | `web/` | HTML in `web/`, JS modules in `web/js/`. Follow K4GSR-Beamline pattern: numbered files (01_state, 02_ws, 03_controls...) |
| **Math / signal utils** | `utils/` | FFT, shift, gradient, filter operations. Pure functions, no side effects |
| **Core projections** | `core/` | get_projections, set_projections — object patch extraction/update |
| **Math primitives** | `math/` | norm2, mean2, sum2 — basic array reductions |
| **Data generation** | root `synth_ptycho.py` | Synthetic ptychography data generator (legacy location) |
| **Tests** | `tests/` | Validation & comparison scripts |
| **Static assets** | `data/imgs/` | Sample images, probe references |
| **MATLAB refs** | `matlab_ref/` | Reference .mat/.npy for comparison only |
| **Results** | `results/` | Output images + `results/history/` for run history |

### Decision guide for new files:
- **New engine or algorithm variant** → `engines/` (or `engines/gpu/` for GPU)
- **New server endpoint or handler** → `server/`
- **New UI feature (JS)** → `web/js/` with next number in sequence
- **New visualization/rendering** → `server/image_encoder.py` (server-side) or `web/js/colormaps.js` (client-side)
- **New utility function** → `utils/` if pure math/signal, `server/` if server-specific

### Frontend conventions (K4GSR-Beamline pattern):
- Global state: `STATE.xxx` in `01_state.js`
- WebSocket messages: handler in `02_ws.js` `handleMessage()` switch
- UI controls: `03_controls.js`
- Viewer/canvas rendering: `04_viewer.js` or `colormaps.js`
- CSS: embedded in `ptycho_ui.html` `<style>`, use `:root` variables (--bg, --ac, --pr, --gn, --rd)
- No external frameworks. Vanilla JS only

### Naming conventions:
- Python: snake_case functions/files, cSAXS terminology (fmag, asize, probe, object)
- JS: camelCase functions, STATE keys match server message field names
- WebSocket messages: `{ type: 'snake_case_action', ... }` matching server handler names
