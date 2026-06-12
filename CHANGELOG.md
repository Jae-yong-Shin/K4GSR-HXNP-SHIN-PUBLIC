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

## Development-line sync — 2026-06-12 (versions 4.37.45 → 4.38.5)

This tranche lands the items previously listed in the README as "in implementation
on the development line": the WebGPU MC engine (phases 1+2), the EIGER2 data-path
evaluation, event-driven PV streaming, the transmission-XANES IC measurement
simulation, the NLP D-series hardening, and the beamline-layout export. Adapted
from the development line's per-version changelog; references to internal task
documents and infrastructure are omitted or generalized.

### [4.38.5] — 2026-06-12

#### Validated (A3 follow-up — XAFSmass cross-check, the program named in the manuscript)
- `paper/validation/run_xafsmass_crosscheck.py` + `data/xafsmass_crosscheck.json`: the project's xraydb-ported ion-chamber response model is cross-validated against XAFSmass (Klementiev & Chernikov 2016) `calculate_flux` — the reference implementation the manuscript cites as its example. The two programs use different documented conventions (XAFSmass: single carrier, total-absorption energy deposit, Chantler tables, W = 36/26 eV; xraydb chain: both carriers, E*att_photo + Ec*att_incoh, Elam tables, W = 34.8/26.4 eV — the raw flux-per-uA ratio of 2.4-3.1x is fully explained by them). After algebraic reconciliation of the conventions the agreement is 0.994-0.997 (0.3-0.6%, the Chantler-vs-Elam table difference level) across N2/Ar and 7.1-15 keV. ALL PASS at the 2% gate.
- Remaining gap, stated explicitly: "calibrated against measured ion-chamber currents" requires real hardware currents and stays future work.

### [4.38.4] — 2026-06-12

#### Added (A1 phase 2 — GPU-resident MC chain: 1M rays 2.1 s -> 33-45 ms, 46-63x)
- Profile-first measurement of the phase-1 CPU continuation (~950 ms at 1M rays: SSA hybrid ~130 + applyKBMC ~108 + Fresnel hybrid ~46 + element-loop/statistics/binning ~690-800 ms) -> the dominant cost was the per-ray loops and final statistics, not the collective FFTs (`paper/validation/profile_mc_cont.py`).
- `js/raytrace/05_mc_gpu.js`: sample-plane targets now run a fully GPU-resident multi-pass chain ("full mode", 4 submit/readback round trips, 6 WGSL entry points in one module): P1 source->SSA clip (+footprint stats) -> P1b unweighted SSA footprint histogram (u32 atomics, integer parity with the CPU histogram) -> CPU wavefront (engine-owned `_hybridProfile1D` FFT + `_cdfBuild`) -> P2 per-ray inverse-CDF SSA kicks + KB-slit clip + sinc^2 rejection sampling + KB-V/KB-H `applyKBMC` port with the EXACT ellipsoid conic + drift to sample -> P2b KB footprint histograms -> CPU wavefront for the Fresnel hybrid -> P3 per-ray `_applyHybridFresnel` application + all moment sums -> P4 weighted histograms via overflow-proof fixed-point u32 atomics. Downloads are ~1 MB of partials + 43 KB of histograms instead of the 32 MB per-ray readback.
- KB ellipsoid conic in f32 (phase-1 limitation lifted): algebraically exact pole-frame regrouping with the 2-decade cancellation precomputed in f64 host constants. Gated by a dedicated precision self-test (`window._mcGpuConicTest`): GPU conic vs CPU f64 `_kbConicAngle` expressed as sample-plane position error — KB-V RMS 0.198 nm (max 0.78 nm), KB-H RMS 0.059 nm (max 0.28 nm), gate < 1 nm vs the ~50 nm focal spot. Runs automatically on first use per conic configuration (cached); falls back to hybrid mode with the reason on failure.
- Non-sample-plane targets and unsupported configurations keep the phase-1 hybrid mode; CPU fallback ladder, opt-in toggle and default behavior unchanged. Full mode limited to nR <= maxStorageBufferBindingSize/32 (4.19M rays at the default 128 MiB).

#### Changed
- `js/raytrace/01_mc_engine.js`: pure code motion — `_hybridFF1D` split into `_hybridProfile1D` + histogram/sampling, `_inverseCdfSample` CDF construction extracted as `_cdfBuild`; both exposed for the GPU host path. CPU behavior unchanged (re-validated against the frozen pre-refactor baseline).
- `paper/validation/run_mc_gpu_check.py`: adds the conic precision gate (8192 rays/mirror, RMS < 1 nm), a 4M-ray demo gate, a full-mode assertion for sample-plane GPU runs, and a per-stage timing breakdown table.

#### Validated
- `run_mc_gpu_check.py` at 5/10/20 keV, production settings, NVIDIA Ampere (Chromium WebGPU): **125 gates = 109 PASS + 16 PASS(stat) + 0 FAIL**. 1M means (12 reps/side): sigma <= 1.51 %, FWHM <= 2.70 %, fluxRatio <= 0.22 % vs CPU. Element-level T_cum parity covers the FULL 20-element chain: worst |dev| 0.065 %. 4M demo completes at all energies (52-73 ms).
- End-to-end timing at 1M rays: CPU 2064-2157 ms, phase-1 GPU ~1.0 s, **phase-2 GPU 33-45 ms (46-63x vs CPU)**; 4M in 52-73 ms. Results: `paper/validation/data/mc_gpu_check_results.json`. Independently re-run by the integrating session (same machine): 125 gates, 0 FAIL.

### [4.38.3] — 2026-06-12

#### Added (A1 — opt-in WebGPU acceleration of the MC ray-tracing engine, phase 1)
- `js/raytrace/05_mc_gpu.js`: WebGPU compute port of the per-ray segment of `mcRayTrace` (source phase-space sampling + per-ray energy + undulator envelope, drifts, WB slit clip, M1/M2 `applyMirrorMC` with the DABAX `OPTCONST_TABLES` reflectivity, two-crystal Guigay thick-Bragg DCM) in a single dispatch, one thread per ray. The SSA/KB coherent-hybrid elements and all statistics stay on the CPU through `_mcTraceFromRays` (the engine's own code), so every number users read is produced by the same code path as the CPU engine. DCM deviation parameters are algebraically regrouped into small-quantity form (exact identities, no approximation) to survive f32.
- Opt-in wiring, default behavior unchanged: `state.mcGpuEnabled` (default false), View-menu "MC Engine: CPU / GPU (beta)" toggle, async API `mcRayTraceGPU(td, nR)`, automatic CPU fallback when WebGPU or the element configuration is unsupported. GPU RNG is a counter-based per-ray PCG: GPU vs CPU equivalence is statistical, not bitwise.
- `paper/validation/run_mc_gpu_check.py` + `data/mc_gpu_check_results.json` + frozen pre-refactor CPU baseline `data/mc_gpu_cpu_baseline_pre_refactor.json`.

#### Validated
- 114 gates = 102 PASS + 12 PASS(stat) + 0 FAIL at 5/10/20 keV. Per-element T_cum CPU-vs-GPU parity |dev| <= 0.15% at 1M rays (DCM <= 0.08%); GPU source->M2 segment ~22x faster than CPU at 1M (50 ms vs ~1.1 s); end-to-end ~2.1x (CPU continuation dominates, Amdahl — addressed in phase 2 above).

### [4.38.2] — 2026-06-12

(Server-side eval tooling only — no JS/bundle change.)

#### Added (C2 — EIGER2 data-path evaluation, extends the C1 "Odin evaluation" next step)
- `server/detector_eval/eiger2_stream_sim.py`: DECTRIS SIMPLON-style stream simulator — ZMQ PUSH frame fan-out + PUB control broadcast. Synthetic EIGER2-1M-like frames (1062x1028, Poisson background + Bragg-like spots + powder ring + gap bands), compressed by the HDF5 filter pipeline itself (`read_direct_chunk`) so blobs are byte-exact bitshuffle-LZ4 / LZ4 / gzip filter streams; startup self-test round-trips a blob through `write_direct_chunk` + h5py read (CRC32).
- `server/detector_eval/writer_bench.py`: consumer/writer benchmark — `null` (transport ceiling), `single` (one chunked-HDF5 writer), `shard` (N writer processes via ZMQ round-robin, N shard files + VDS master, the odin-data topology). Direct chunk writes (zero recompression), fsync-closed timing windows, CRC32 read-back verification + global-order checks through the VDS master, ENOSPC budget rule.
- `server/detector_eval/run_vm1_bench.sh` + `README.md`: sequential benchmark matrix driver (13 runs, seconds each, deletes data after measuring) and usage doc.
- `paper/validation/data/eiger2_writer_bench.json`: measured results (operations VM, 2026-06-12).

#### Validated (operations VM, 8 vCPU/16 GB, loopback TCP only, production services untouched)
- Cross-check against C1: this harness's uncompressed single-writer disk result (0.75 GB/s) falls inside the C1 NDFileHDF5 disk range (0.56-0.81 GB/s); tmpfs 1.72 vs C1 2.0 GB/s (this run fsync-inclusive).
- bslz4 direct-chunk-write single writer: 2.95 GB/s raw-equivalent to disk (3.9x over uncompressed), 7.73 GB/s to tmpfs; 2-shard: 5.92 GB/s disk (2.0x), 14.14 GB/s tmpfs; 4-shard plateaus (storage/CPU saturation). 500 Hz EIGER2-1M pacing sustained by a single disk writer with zero queue growth. All runs CRC-verified; per-run data deleted.

### [4.38.1] — 2026-06-12

#### Fixed (scan-stage hardware fixes absorbed from the operations deployment)
- `server/hardware/picoscale.py`: disconnected-channel handling — channels without a sensor report None and the UI shows '--' instead of error values; OSError-safe library load.
- `server/hardware/smaract_mcs2.py`: ch0 closed-loop hold via `set_property HOLD_TIME=INT_MAX` + `move_raw(secondary=0)` (move_to() internally overwrites HOLD_TIME, so it cannot be used for indefinite hold); amplifier auto-enable on connect (MCS2 boots with AMPLIFIER_ENABLED=False — without this, moves "succeed" at the SDK level but the piezo never receives drive voltage).
- `server/hardware/mcs2_bridge_server.py` (bridge host): matching bridge-side support for the hold/disconnected-channel protocol; i64 property support.
- `server/nano_scanner_service.py`: per-channel sensor-presence reporting.

### [4.38.0] — 2026-06-12 — MINOR

#### Changed (release: Phase-1 integration bundle)
- Bundle pair renamed `virtual_beamline_nanoprobe_V4_37.html` / `_bundle.html` -> `virtual_beamline_nanoprobe_V4_38.html` / `_bundle.html`; all active references updated. `APP_VERSION` 4.37.40 -> 4.38.0 (`js/shared/01_constants.js`).
- Clean bundle rebuild from the dev HTML + all js/ modules (`build.py --bundle`), aggregating the merged Phase-1 work 4.37.45-4.37.57: A2 xrt layout export (`js/optics/08_layout_export.js`), A3 ion-chamber JS port + IC1 integration, B3 event-push PV broadcast, C1 ADSim detector path, NLP D-series + owner-decision conventions, and the XANES IC measurement chain + browser toggle (`_buildXafsICParams`, `icLiveChain`).

### [4.37.57] — 2026-06-12

#### Added (XANES IC measurement toggle, browser side)
- XAFS Expt panel gains an opt-in "IC I0/I1" measurement mode (checkbox + dwell input, default off): when enabled, `_buildXafsICParams()` (js/experiment/07_experiment_run.js) assembles `params.ic` from the IC1 popup state (I0 chamber: gas/length/pressure/air path) and the detector-popup ion-chamber tab (I1), with `ratio_prefocus` taken live from `icLiveChain()` so the I0 chamber at 149.45 m sees the pre-KB unfocused-beam flux. The simulated observable becomes the normalized mu_obs = ln(I0/I1) with per-dwell Poisson shot noise (server ic_chain). Completion line shows the I0/I1 currents in uA.
- Contract checks: `paper/validation/run_xafs_ic_params_check.js` (stub-browser assembly, 8/8) writes the exact JS-built params JSON which `run_xafs_ic_params_check.py` feeds through the real `XAFSEngine.run()` (12/12).

### [4.37.56] — 2026-06-12

#### Added (XANES ion-chamber measurement simulation, server side)
- `server/sim_engines/ic_chain.py`: vectorized transmission-XAFS measurement chain (flux -> air -> I0 chamber -> air -> sample T=exp(-mu_t) -> air -> I1 chamber) calling xraydb 4.5.8 directly with the A3-verified formula chain. Poisson shot noise on absorbed photons per dwell + dark current; noiseless mode for validation.
- `server/sim_engines/xafs_engine.py`: opt-in `params.ic` wiring — the synthetic Gaussian noise block is replaced by the physical I0/I1 measurement (observable y = normalized mu_obs = ln((I0-dark)/(I1-dark))), applied after self-absorption + DCM broadening. Default path (ic absent/false) is UNCHANGED. `server/sim_engines/test_ic_chain.py` added.

#### Validated
- (a) noiseless identity reconstruction max 7.8e-16; (b) direct xraydb.ionchamber_fluxes cross-check, 5 energies x 2 gases, worst rel err 1.1e-16; (c) Fe K-edge SNR scales sqrt(10) with 10x dwell (dev 0.0%). Default path byte-identical (3 cases, ndarray.tobytes md5) vs pre-change baseline; off/on message-shape compatibility (off identical; on additive only).

### [4.37.55] — 2026-06-12

#### Fixed (NLP owner-decision recheck residuals)
- motor_03 ("시료 X를 100 이동해"): new `_recover_from_empty` backstop recovers a relative sample move for bare relative requests; unit-less numbers use the operator default (micrometers); absolute forms are excluded and left to the LLM path.
- analysis_01: oxidation/chemical-state intent (산화 상태/oxidation state/valence + in-range elements) now maps to quickXanes per element.

### [4.37.54] — 2026-06-12

#### Added (B3 — event-driven PV streaming)
- Event-triggered PV push with burst coalescing replaces the periodic 10 Hz `/ws/pv` broadcast loop in CA-bridge modes. `CABridge` gains an optional `on_change(pv, value)` hook fired from the caproto monitor callbacks; `server.py` hands it off to the asyncio loop via `call_soon_threadsafe` and a new `pv_event_push_loop()` flushes ONE batched message per coalescing window (env `PV_PUSH_COALESCE_MS`, default 50 ms; leading-edge flush so an isolated change goes out immediately). Idle connections receive only a full-snapshot keepalive every `PV_PUSH_SNAPSHOT_S` seconds (default 5). Wire format identical to the old loop — browser unchanged. Fallback: `PV_PUSH_MODE=periodic` restores the old loop; the standalone PVStore sim always stays periodic (its 10 Hz tick is the event source). New `tests/test_pv_event_push.py`.

#### Validated
- Unit test (real `pv_event_push_loop`/`_send_pv_batch`/`_pv_snapshot` code paths): 1000 rapid changes on 5 PVs in 1.25 s -> 25 messages (40x coalescing); every final value delivered; idle keepalives only when idle; entry key set identical to a live capture from the old loop; isolated-event delivery <1 ms; broken-hook isolation. Live smoke in 3 configurations (standalone / CA-bridge event / CA-bridge periodic). Measured remote put-to-update median 47 ms vs the 91 ms polling baseline.

### [4.37.53] — 2026-06-12

#### Changed (NLP owner-decision conventions)
- RELATIVE-BY-DEFAULT move convention: bare "N 이동" with no absolute marker is a relative move; direction words set the sign.
- EXECUTE-FIRST convention: element+technique clear -> run with defaults + inline change offer, do not ask (rule 9 exception + execute-first few-shots).
- Motor-specific auto-tune few-shot (quickAutoTune); adaptive-scan few-shot + deterministic backstop (적응형/adaptive + element -> quickAdaptiveScan); line-scan/fly-scan grading repairs.

### [4.37.52] — 2026-06-12

#### Added (IC1 ion chamber — beamline integration of the A3 model)
- `js/shared/01_constants.js`: new component `ic1` at 149.45 m — between the KB slit and KB-V, upstream of the focusing pair. State config: `ic1Gas/ic1LenCm/ic1PressAtm/ic1AirBeforeCm/ic1AirAfterCm`.
- `js/ui/02_layout_svg.js`: dedicated `_svgIC` icon (gas chamber with HV collection plates).
- `js/optics/07_ion_chamber.js` `icLiveChain()`: live physics chain KBslit -> air -> IC1 -> air -> KB -> sample. The chamber sees the PRE-focus beam: sample-plane SSOT is scaled back by the MC element-trace ratio (measured x12.3 at 10 keV, ~300 uA on N2 10 cm). IC/air losses propagate to the focused sample flux.
- `js/ui/10_motor_jog.js`: live IC1 current readout in the top beam-monitor bar (E/Flux/IC1); click opens the IC1 panel.
- `js/ui/05_modal.js`: IC1 panel (gas N2/He/Ar/air, length, pressure, air-path controls + full chain readout) and a Detector-popup "ION CHAMBER (I1) MODE" section.
- `js/control/02_epics.js`: SimIOC `BL10:IC1:Current` now driven by `icLiveChain()` (was a flux*e placeholder).

#### Changed (sample-flux single source of truth)
- `sampleFlux()` single API (js/raytrace/02_propagation.js) = THE sample-plane flux for every display/simulator. Authoritative model = MC chain via photonFlux: SPECTRA-validated acceptance-lookup seed x band reweighting x MC survival. propagateBeam demoted to the per-element Propagation Log (its hmirror case lacks M1/M2 focusing -> ~300x SSA over-clip; documented).
- `js/optics/01_undulator.js` license-position comment: fLinFxy2 documented as an independent implementation of the published equations (Kim 1989; Tanaka & Kitamura 2001; Tanaka 2021) with SPECTRA used as validation reference only.

### [4.37.51] — 2026-06-12

#### Fixed (NLP regression triage — 20 regressions classified by feeding paper-run responses through the deterministic layers)
- 9 deterministic misfires fixed in `server/nlp_agent.py`: quickAutoTune/quickRelAlign whitelisted in the alignment-intent guard; the energy-set guard preserves read-only display steps; explicit "N keV" honored before the element-edge floor; experiment-start block re-appends ONE trailing queueStart; `_recover_from_empty` honors explicit XAFS/EXAFS wording; info-question markers cannot inject executable plans.
- Systematic llm-drift: prompt-budget output floor 1300 -> 1100 tokens (the base prompt was starving single-intent prompts of their task example group).

#### Validated
- Recheck run (107 cases): the 10 triage-targeted cases ALL PASS; protected 22/22 intact; 228-common equivalent 218/228 (95.6%). Unit pins: D2 17/17, D3 9/9, xanes_alignment 12/12.

### [4.37.50] — 2026-06-12

#### Added (C1 operations-scenario validation)
- `server/test_adsim_scenarios.py`: five PASS/FAIL scenarios against the ADSim IOC with the IOC lifecycle managed by the script itself: S1 back-to-back runs, S2 abort mid-scan (partial HDF5 readable), S3 IOC restart resilience (same ophyd device reconnects), S4 concurrent CA reader during a 100-frame run, S5 hybrid dual-IOC `grid_scan` (production soft-IOC motor + ADSim detector in one RunEngine).

#### Validated
- All 5 scenarios PASS on the operations VM (2026-06-12); production services untouched (same PIDs before/after).

### [4.37.49] — 2026-06-12

#### Added (C1 — ADSim detector data path; superseded record, already summarized in the C1 section below)
- `server/scan_engine/ad_devices.py`, `server/test_adsim_bluesky.py` — see the C1 section below for the consolidated description and load-test results.

### [4.37.48] — 2026-06-12

#### Added (D1 — seven-language few-shot expansion)
- `server/nlp_agent.py` `_TRANSLATED_USER_UTTERANCES`: Chinese (zh) added with the FULL 38-key utterance set; Arabic/Hindi/Thai completed from 13 to 38 keys each. Technical tokens (element symbols, edge names, units, numbers, device names) stay untranslated.

#### Fixed (dynamic-prompt budget)
- The token budget counted only example groups — the few-shot block and mode/language tail blocks were appended after the check, overflowing the LLM context window in the worst 4-intent case. The few-shot block is now computed before the group loop and reserved; chars/token ratio calibrated against /tokenize measurements.

### [4.37.47] — 2026-06-11

#### Added (D2 — expert-identified priority areas P1-P10, all deterministic post-processing)
- Advisory-notes channel appended AFTER the commentary filter (which had been erasing prompt-compliant advisory text). Five note helpers: exposure-time statement for every scan (P1), Nyquist step-size flags vs the 50 nm focused beam (P3), Pt L3-edge vs Pt mirror coating -> Rh stripe recommendation (P7), accessible 2-theta/q-range at the detector distance (P10), focusing-optic confirmation for sub-micron requests (P5).
- `_needs_realign(e_from, e_to)` (P2): the dE >= 1 keV re-alignment guard generalized to mirror-coating boundary crossings (Pt L3 11.564 / Rh K 23.22 keV, read from the engine's reflectivity breakpoints, not guessed).
- P4 multi-element XRF excitation floor (energy raised above max requested edge); P9 pure-question action stripper; P6 setup-vs-execute (setup keywords suppress queueStart); P8 co-mounted detector fix (SDD and EIGER2 measure simultaneously; removed the false 30-min swap warning).
- `tests/test_nlp_d2_s5_areas.py`: 17-check deterministic pin suite (17/17 PASS, no LLM required).

### [4.37.46] — 2026-06-11

#### Fixed (D3 completion — vLLM rerun regressions traced to a single root cause)
- `server/nlp_agent.py` `_build_dynamic_prompt`: example-group token budget — multi-intent prompts overflowed the vLLM context window, truncating responses mid-JSON. The base prompt always ships; groups are added smallest-first within the budget.
- `_recover_from_empty`: optimization-intent guard recovers `optimizeBeamline` (priority parsed from wording) instead of degrading into a blind raster; powder-XRD preset backstop.
- `VLLMBackend.chat`: truncation telemetry (`finish_reason == 'length'` logs a loud warning).

#### Validated
- Benchmark categories optimize/battery/workflow/experiment_preset (the 4 manuscript failure categories): **22/22 PASS (100%)** on vLLM Qwen3-32B; the paper run scored 18/22 on the same cases. All four paper-cited failures (opt_03, batt_04, workflow_01, vexp_03) now PASS with zero regressions. `tests/test_nlp_d3_recovery.py` 9/9 PASS.

### [4.37.45] — 2026-06-11

#### Added
- `tests/test_nlp_d3_recovery.py`: pinned regression suite (no LLM needed) for the D3 fixes plus guard regressions.

#### Fixed (D3 — the 4/228 NLP benchmark failures cited in the manuscript)
- `_recover_from_empty`: extracts ALL in-range elements (with energy-range check) so sequential requests recover the in-range scan; recovers a default XRF raster preset when no element is named; normalizes Korean element names ("철"→Fe).
- Trace-level exception for contamination checks (≤ ~100 ppm): `optimizeBeamline` (signal estimation) is generated FIRST instead of a blind raster.
- Confirmation enforcement pinned by regression test (actions present -> confirmation forced True).

---

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

The NLP future-work items (D1–D3) and the remaining work-list items landed with
the development-line sync above (4.37.45 → 4.38.5).
