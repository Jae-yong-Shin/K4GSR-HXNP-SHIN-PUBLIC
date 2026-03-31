---
title: "Ptycho Test Files Archive"
category: other
status: current
updated: 2026-03-03
tags: [ptychography, testing]
summary: "30+ 테스트 스크립트 및 결과 이미지 인벤토리"
---
# Ptycho Test Files Archive

Ptycho 개발 과정에서 생성된 테스트 스크립트 및 결과 이미지 목록.
필요 시 `_old_tests/` 폴더에서 복구 가능.

---

## Production Code (삭제하면 안 됨)

| 파일 | 용도 |
|------|------|
| `fsc.py` | Fourier Shell Correlation (FSC) - 2D ptychography 해상도 추정 |
| `synth_ptycho.py` | SyntheticPtycho 데이터 생성기 (Fermat spiral, probe, object, noise) |
| `compare_probe_phase.py` | Circular(Airy) vs Rectangular(sinc) probe 비교 유틸리티 |
| `compare_recon.py` | Circ vs Rect probe reconstruction 결과 비교 유틸리티 |

---

## Test Scripts (test_*.py)

### Engine 검증 (기본)

| 파일 | 용도 | 결과 이미지 |
|------|------|------------|
| `test_dm_sanity.py` | DM forward model 일관성 최소 검증 | - |
| `test_dm_quality.py` | DM norm_error vs iteration 추적 | `test_dm_quality_result.png` |
| `test_dm_delta_fix.py` | DM divergence 원인 (MATLAB adaptive vs Python fixed) | - |
| `test_cpu_dm.py` | CPU DM vs GPU DM 비교 | `test_cpu_dm_result.png` |
| `test_epie.py` | ePIE standalone (ones init), DM/LSQML 비교 | `test_epie_result.png` |
| `test_lsqml_debug.py` | LSQML beta_object=0 디버깅 (2x2 LSQ system) | - |
| `test_lsqml_fixed.py` | LSQML decoupled fallback + ePIE50+LSQML50 | - |
| `test_compare_engines.py` | K4GSR-Beamline DM vs K4GSR-PTYCHO DM (동일 데이터) | `test_compare_engines_result.png` |

### Pipeline 검증

| 파일 | 용도 | 결과 이미지 |
|------|------|------------|
| `test_engine_pipeline.py` | LSQML standalone, DM+LSQML, N_photons 영향 | `test_engine_pipeline_result.png` |
| `test_epie_pipeline.py` | ePIE200, ePIE50+LSQML50, ePIE50+ML50 파이프라인 | `test_epie_pipeline_result.png` |
| `test_engine_runner_epie.py` | engine_runner.py 경유 ePIE 실행 확인 | - |
| `test_full_pipeline.py` | 전체 파이프라인 (Scenario A: 6.2keV/200nm, B: 10keV/50nm) | `test_pipeline_result.png` |

### MATLAB Reference

| 파일 | 용도 | 결과 이미지 |
|------|------|------------|
| `test_matlab_ref.py` | MATLAB csaxs_dataset6 데이터로 Python DM vs MATLAB DM | - |
| `test_matlab_ref2.py` | MATLAB ref + transposed fmag fix | `test_matlab_ref2_result.png` |
| `test_matlab_multimode.py` | MATLAB multi-mode 데이터 검증 | `_matlab_multimode_test.png` |

### Scenario 검증

| 파일 | 용도 | 결과 이미지 |
|------|------|------------|
| `test_direct_scenario_a.py` | Direct Scenario A (6.2keV, 200nm, DM 검증) | `test_direct_scenarioA_result.png` |
| `test_direct_scenario_b.py` | Direct Scenario B (10keV, 50nm, engine 검증) | `test_direct_scenarioB_result.png` |
| `test_scenario_b.py` | Server pipeline Scenario B (WebSocket 경유) | `test_scenario_b_result.png`, `test_scenario_b_convergence.png` |
| `test_scan_coverage.py` | Scenario A/B scan_area=1.1um (이전 0.3um보다 큰) | `test_scan_coverage_result.png` |
| `test_scenarios.py` | 4개 사용자 시나리오 pre-flight check (reconstruction 없음) | - |
| `test_server_scenarios.py` | E2E server data_loader pipeline (3 coherence scenarios) | `test_server_scenarios_result.png` |

### 50nm Beam / Multi-mode / Coherence

| 파일 | 용도 | 결과 이미지 |
|------|------|------------|
| `test_sinc_probe.py` | KB sinc probe shape + DM+ML convergence | `sinc_probe_recon_result.png` |
| `test_ssa_coherence_recon.py` | SSA coherence model, 5가지 SSA 조건별 reconstruction | `ssa_coherence_recon_comparison.png` |
| `test_50nm_multimode.py` | 50nm single-mode vs multi-mode forward + recon | - |
| `test_50nm_extended.py` | 50nm 확장 (큰 scan area, f_coh=0.3, 6 scenarios) | `_50nm_extended.png` |
| `test_50nm_verify.py` | 50nm DM->ML (fermat + raster, 4 scenarios) | `_50nm_verify.png` |
| `test_50nm_highflux.py` | 50nm multi-mode + high flux (1e8, BL10 조건) | `_50nm_highflux.png` |
| `test_50nm_highflux_all.py` | High-flux 전체 검증 (6 scenarios, 개별 이미지) | `_highflux_S[1-6].png`, `_highflux_all.png` |

### Parameter Chain / Quality / FSC

| 파일 | 용도 | 결과 이미지 |
|------|------|------------|
| `test_param_chain.py` | 오프라인 parameter chain + quality assessment 검증 | - |
| `test_ptycho_conditions.py` | Ptychography validity 조건 (oversampling, overlap 등) | - |
| `test_split_fsc.py` | Split-data Phase FSC 해상도 추정 | `_split_fsc_comparison.png` |

### Server / WebSocket 통합

| 파일 | 용도 | 결과 이미지 |
|------|------|------------|
| `test_js_flow.py` | JS workflow WebSocket 전체 흐름 테스트 | - |
| `test_recon_direct_vs_server.py` | Direct engine vs server pipeline 동일성 검증 | - |

---

## Diagnostic Scripts (_*.py)

| 파일 | 용도 | 결과 이미지 |
|------|------|------------|
| `_test_memory_batch.py` | GPU default, memory estimation, batched CPU DM 검증 (10 unit tests) | - |
| `_test_e2e_recon.py` | E2E engine_runner (GPU default, memory guard, stop/cleanup, 4 tests) | - |
| `_recon_dm_ml_test.py` | DM+ML reconstruction 테스트 (브라우저 동작 미러링) | - |
| `_recon_quality_test.py` | Reconstruction quality 빠른 확인 (probe phase 포함) | - |
| `_recon_verify.py` | Synthetic data + MC probe -> DM recon -> GT 비교 검증 | - |
| `inspect_mat.py` | MATLAB .mat 파일 내용 검사 유틸리티 | - |
| `inspect_mat2.py` | MATLAB .mat 파일 상세 검사 (2차 버전) | - |
| `_run_scenario_a.py` | Scenario A 실행기: 6.2keV, 200nm, asize=128, 1e8 photons | `_scenario_a_1e8_result.png` |
| `_run_scenario_b.py` | Scenario B 실행기: 10keV, 50nm, asize=256, 1e8 photons | `_scenario_b_1e8_result.png` |
| `_crop_compare_a.py` | Scenario A center crop + GT 비교 | `_scenario_a_crop_compare.png` |
| `_compare_scenario_a_full.py` | Scenario A DM200+ML50 종합 비교 (2x5 grid) | `_scenario_a_full_compare.png` |
| `_compare_scenario_b_full.py` | Scenario B DM200+ML50 종합 비교 | `_scenario_b_full_compare.png` |
| `_quick_dm_vs_epie.py` | DM vs ePIE 빠른 진단 | `_dm_vs_epie_diagnostic.png` |
| `_check_overlap.py` | Probe vs scan step overlap 진단 | `_overlap_diagnostic.png` |
| `_inspect_matlab_multimode.py` | MATLAB multi-mode probe 구조 분석 | - |
| `_check_matlab_positions.py` | MATLAB positions vs object 확인 | - |
| `_analyze_matlab_modes.py` | MATLAB probe mode 분석 (modes, phase, weights) | - |
| `_check_matlab_fmag_modes.py` | MATLAB fmag single/multi-mode 확인 | - |
| `_check_matlab_params.py` | MATLAB HDF5 시뮬레이션 파라미터 추출 | - |

---

## PNG Result Images

### Probe 비교
| 이미지 | 생성 스크립트 | 내용 |
|--------|-------------|------|
| `probe_comparison.png` | `compare_probe_phase.py` | Circ vs Rect probe amp/phase 비교 |
| `compare_circ_vs_rect_probe.png` | `compare_probe_phase.py` | Circ vs Rect probe 상세 비교 |
| `compare_recon_circ_vs_rect.png` | `compare_recon.py` | Circ vs Rect probe reconstruction 비교 |
| `fresnel_recon_result.png` | `test_sinc_probe.py` | Fresnel sinc probe DM+ML 결과 |
| `sinc_probe_recon_result.png` | `test_sinc_probe.py` | Sinc probe reconstruction 결과 |

### Scenario 결과
| 이미지 | 생성 스크립트 | 내용 |
|--------|-------------|------|
| `_scenario_a_1e8_result.png` | `_run_scenario_a.py` | Scenario A 1e8 photons 결과 |
| `_scenario_a_crop_compare.png` | `_crop_compare_a.py` | Scenario A center crop GT 비교 |
| `_scenario_a_full_compare.png` | `_compare_scenario_a_full.py` | Scenario A DM200+ML50 종합 |
| `_scenario_b_1e8_result.png` | `_run_scenario_b.py` | Scenario B 1e8 photons 결과 |
| `_scenario_b_full_compare.png` | `_compare_scenario_b_full.py` | Scenario B DM200+ML50 종합 |

### 50nm / Multi-mode / Highflux
| 이미지 | 생성 스크립트 | 내용 |
|--------|-------------|------|
| `_50nm_verify.png` | `test_50nm_verify.py` | 50nm 4 scenarios (DM->ML) |
| `_50nm_extended.png` | `test_50nm_extended.py` | 50nm 확장 6 scenarios |
| `_50nm_highflux.png` | `test_50nm_highflux.py` | 50nm high flux 결과 |
| `_highflux_S[1-6].png` | `test_50nm_highflux_all.py` | 개별 scenario 결과 |
| `_highflux_all.png` | `test_50nm_highflux_all.py` | 6 scenarios 종합 |
| `_matlab_multimode_test.png` | `test_matlab_multimode.py` | MATLAB multi-mode 검증 |
| `ssa_coherence_recon_comparison.png` | `test_ssa_coherence_recon.py` | SSA coherence 5조건 비교 |
| `_split_fsc_comparison.png` | `test_split_fsc.py` | Split-data FSC 해상도 추정 |

### Engine 비교
| 이미지 | 생성 스크립트 | 내용 |
|--------|-------------|------|
| `test_compare_engines_result.png` | `test_compare_engines.py` | BL DM vs PTYCHO DM |
| `test_cpu_dm_result.png` | `test_cpu_dm.py` | CPU DM vs GPU DM |
| `test_dm_quality_result.png` | `test_dm_quality.py` | DM norm_error 추적 |
| `test_engine_pipeline_result.png` | `test_engine_pipeline.py` | LSQML/DM+LSQML 파이프라인 |
| `test_epie_result.png` | `test_epie.py` | ePIE standalone |
| `test_epie_pipeline_result.png` | `test_epie_pipeline.py` | ePIE 파이프라인 |
| `_dm_vs_epie_diagnostic.png` | `_quick_dm_vs_epie.py` | DM vs ePIE 진단 |
| `_overlap_diagnostic.png` | `_check_overlap.py` | Overlap 진단 |

### Pipeline / Server
| 이미지 | 생성 스크립트 | 내용 |
|--------|-------------|------|
| `test_pipeline_result.png` | `test_full_pipeline.py` | Full pipeline A+B |
| `test_scenario_b_result.png` | `test_scenario_b.py` | Server Scenario B |
| `test_scenario_b_convergence.png` | `test_scenario_b.py` | Scenario B convergence |
| `test_scan_coverage_result.png` | `test_scan_coverage.py` | Scan coverage |
| `test_matlab_ref2_result.png` | `test_matlab_ref2.py` | MATLAB ref |
| `test_server_scenarios_result.png` | `test_server_scenarios.py` | Server 3 scenarios |
| `test_direct_scenarioA_result.png` | `test_direct_scenario_a.py` | Direct Scenario A |
| `test_direct_scenarioB_result.png` | `test_direct_scenario_b.py` | Direct Scenario B |

---

## 파일 위치

- **Production code**: `ptycho/` (삭제 금지)
- **Archive**: `ptycho/_old_tests/` (테스트 스크립트 + 결과 이미지)
- **이 문서**: `ptycho/docs/TEST_FILES_ARCHIVE.md`
