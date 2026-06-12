# Changelog — `beta` branch

## Changes on `beta` relative to the paper baseline (`main`, 4.37.33)

This branch carries post-submission progress on the future work declared in the paper
(Phase 1 roadmap). Code here is functional but work-in-progress: each entry states
exactly what was validated and how, and nothing here is yet held to the full
validation standard of `main`. The paper-reproducibility baseline remains `main`.

> **Infrastructure note**: the C1 tests (and the A3 Python reference generator) run
> against EPICS/areaDetector infrastructure and the `xraydb` package that are NOT
> included in this repository. The TASK documents under `docs/tasks/` describe the
> IOC setup needed to reproduce them. The A3 JavaScript model itself is standalone
> (browser/node, no dependencies).

## A3 — Ion-chamber response model (I0/I1) [2026-06-12]

### Added
- `js/optics/07_ion_chamber.js` — JavaScript port of all 8 features of
  `xraydb.ionchamber_fluxes` (xraydb 4.5.8; same physics as the XAFSmass flux
  calculator, Klementiev & Chernikov 2016, *J. Synchrotron Rad.* 23):
  gases N2/He/Ar/air at materials-DB densities, weight-fraction gas mixtures
  (mu and W), photo/incoherent/total attenuation split (coherent scattering
  attenuates the beam but creates no current), Compton electron mean-energy
  table with interpolation, W-values (Knoll Table 5-1 / ICRU 31), both
  directions (`icCurrent` flux→A and `icFluxFromCurrent` A→incident+transmitted
  flux, plus `icTransmittedFraction`), `pressure_atm` scaling, and the
  `both_carriers` switch.
- `js/optics/00_gasmu_tables.js` — gas linear-attenuation tables
  (photo/incoh/total, 5–25 keV, step 0.1 keV) generated from xraydb 4.5.8 Elam
  tables, with log-log interpolation (off-grid error ≤ 7.8e-5 vs `material_mu`).
- `paper/validation/run_ionchamber_reference.py` — Python reference generator
  (requires `xraydb`); asserts its closed-form chain matches the
  `ionchamber_fluxes` program output at every grid point.
- `paper/validation/run_ionchamber_js_check.js` +
  `paper/validation/data/ionchamber_reference.json` — JS-vs-reference check.
- `paper/validation/run_ionchamber_scenarios.js` — 6 beamline-operations
  scenarios (operating point, XAFS energy scan, I0/sample/I1 chain, gas
  selection, pressure tuning, commissioning inverse).
- `docs/tasks/TASK_A3_IONCHAMBER.md` — porting recipe + validation record.

### Validated
- Full reference grid (4 gases × 41 energies): max relative error ≤ 4.9e-8
  vs the xraydb reference (criterion 1e-2); flux↔current round-trip ≤ 3.4e-16.
- 6 operations scenarios ALL PASS, plus live cross-checks against fresh python
  xraydb 4.5.8 calls (mixture, off-grid energy, pressure; rel. err ≤ 1.5e-6).
- Not yet wired into the SimIOC PV chain (`BL10:IC1:Current` still uses the
  baseline placeholder); wiring is scheduled for a later merge.

## C1 — areaDetector ADSim detector data path (ophyd + Bluesky) [2026-06-12]

### Added
- `server/scan_engine/ad_devices.py` — ophyd device for an ADSimDetector IOC
  (`SingleTrigger` + `DetectorBase`, `HDF5Plugin` +
  `FileStoreHDF5IterativeWrite`): detector DATA path (driver → NDFileHDF5 →
  HDF5 file) separated from the CONTROL path (CA PVs); Bluesky events carry
  datum references, never frames. Includes the CA-environment isolation helper
  (`ensure_adsim_ca_env`, host:port `EPICS_CA_ADDR_LIST` entries so one process
  reaches both the production soft IOC and the isolated ADSim IOC) and HDF5
  plugin priming. Import-safe without ophyd installed.
- `server/test_adsim_bluesky.py` — E2E test: `count` and `grid_scan` document
  streams + h5py file verification, plus budget-limited throughput load bursts.
- `server/test_adsim_scenarios.py` — 5 operations scenarios: back-to-back runs,
  abort mid-scan, IOC restart resilience, concurrent CA reader, and a hybrid
  dual-IOC `grid_scan` (production soft-IOC motor + ADSim detector in one scan).
- `docs/tasks/TASK_C1_ADSIM.md` — IOC build/boot configuration, E2E results,
  load-test data, scenario evidence.

### Validated
- E2E: `count(num=5)` and 3×3 `grid_scan` PASS with correct document-stream
  counts and HDF5 contents verified by h5py.
- Load ceiling measured for the single-writer NDFileHDF5 path: ~2.0 GB/s
  sustained to tmpfs (storage bottleneck removed) and 0.6–0.8 GB/s to VM disk;
  EIGER2-class rates (multiple GB/s) will require a parallel writer (Odin
  evaluation is the declared next step).
- 5 operations scenarios ALL PASS, including the hybrid dual-IOC scan that
  drives a production soft-IOC motor and the isolated ADSim detector from one
  RunEngine process.

---

NLP future-work items (D1–D3) are not part of this tranche and will arrive in a
later `beta` update.
