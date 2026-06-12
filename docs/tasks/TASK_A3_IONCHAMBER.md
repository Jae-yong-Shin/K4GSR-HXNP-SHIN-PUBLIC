---
title: "A3 — Ion-Chamber Response Model (XAFSmass/xraydb) JS Porting Recipe"
category: tasks
status: current
updated: 2026-06-12
tags: [phase1, ion-chamber, physics-engine, xraydb, simioc, porting]
summary: "Phase 1 A3 포팅 레시피. Ground truth = xraydb.ionchamber_fluxes (XAFSmass 동등 물리). 소스에서 추출한 수식 체인, W-value/mu 출처, JS 포팅에 필요한 가스 mu 테이블과 icCurrent() API 스케치, 완료 기준(레퍼런스 대비 <=1%)."
---

# A3 — Ion-Chamber Response Model: Porting Recipe

> Roadmap: `docs/tasks/TASK_PHASE1_ROADMAP.md` §3/§4 A3. Branch: `feature/phase1-engine`.
> Ground truth program: `xraydb.ionchamber_fluxes` (xraydb 4.5.8, Matt Newville) — JSR ¶49가
> 인용한 XAFSmass flux calculator(Klementiev & Chernikov 2016)와 동일 물리.
> 프로그램 기반 원칙: 수식은 논문 추측이 아니라 **xraydb 소스에서 직접 추출**했고,
> 레퍼런스 스크립트가 매 격자점에서 closed-form vs 프로그램 출력 일치(<1e-12)를 assert한다.

## 1. 추출한 수식 체인 (소스 인용)

출처: `site-packages/xraydb/xray.py` :: `ionchamber_fluxes()` (xraydb 4.5.8, lines 1048-1188).

```
mu_k        = material_mu(gas, E, kind=k)        # k in {photo, incoh, total}
              # 선형감쇠계수 [1/cm] = density * sum_elem(frac*mass*mu_elam(elem,E,k)) / mass_tot
              # Elam 테이블; materials.py lines 75-125
atten_total = 1 - exp(-L_cm * mu_total)                          # xray.py:1175
atten_photo = atten_total * mu_photo / mu_total                  # xray.py:1176
atten_incoh = atten_total * mu_incoh / mu_total                  # xray.py:1177
E_compton   = ComptonEnergies(E).electron_mean                   # xray.py:1159
              # Klein-Nishina 단면적 적분의 사전 표 + 선형보간; xraydb.py:394-408
W           = ionization_potential(gas)   # eV/ion-pair; xray.py:632-672
N_carriers  = 2                           # 전자+이온 둘 다 수집 (both_carriers=True 기본)

I [A] = flux_in [ph/s] * e * N_carriers * (E*atten_photo + E_compton*atten_incoh) / W
        # xray.py:1180-1181 의 역산. e = 1.602176634e-19 C
```

혼합 가스: mu_k 와 W 를 분율 가중 평균 (xray.py:1161-1173). Coherent 산란은
빔 감쇠(atten_total)에는 포함되지만 전류 생성에는 기여하지 않는다.

## 2. W-value / mu 출처

- W (유효 이온화 퍼텐셜, eV/ion-pair): Knoll, *Radiation Detection and Measurement* Table 5-1
  + ICRU Report 31 (1979). 사용값: **N2=34.8, He=41.3, Ar=26.4, air=33.8** (`xray.py:632-672`).
- mu: Elam 테이블 (`mu_elam`), xraydb materials DB 기본 밀도 [g/cm3]:
  **N2=1.25e-3, He=1.786e-4, Ar=1.784e-3, air=1.225e-3** (약 1 atm). 압력 스케일: mu는
  밀도에 선형 → `mu *= P/P0`.
- E_compton (Compton 산란 전자 평균 에너지): xraydb sqlite 내 사전 계산 표 + 선형보간.
  5-25 keV에서 47.6-1076.8 eV (photo 항 대비 작지만 He처럼 photo가 약한 가스에서 비중 증가).

## 3. Python 레퍼런스 (완료)

- 스크립트: `paper/validation/run_ionchamber_reference.py` — 모든 수치를
  `ionchamber_fluxes()` 직접 호출로 산출 (역산: volts=1, sensitivity=1 A/V → current 1 A).
- 데이터: `paper/validation/data/ionchamber_reference.json` — N2/He/Ar/air, L=10 cm,
  5..25 keV step 0.5 (41점): atten_total/photo/incoh, **current_A_per_1e10phps**,
  **flux_phps_per_nA**, compton_electron_mean_eV, 메타데이터(버전/W/밀도/수식 노트).
- 대표값: N2 @10 keV 10 cm → 흡수율 4.73%, 3.98e-8 A per 1e10 ph/s.
  Ar @10 keV → 흡수율 67.6%, 8.10e-7 A per 1e10 ph/s.

## 4. JS 포팅에 필요한 것

1. **가스 mu 테이블** (photo/incoh/total 3종 × N2/He/Ar/air, 5-25 keV):
   기존 패턴 그대로 — `js/optics/00_optconst_tables.js` (DABAX 테이블, 2701pts) +
   `Scripts/generate_optconst.py`. 새 생성 스크립트(예: `Scripts/generate_gas_mu.py`)가
   xraydb `material_mu(gas, E, kind)`를 격자 덤프 → `js/optics/00_gasmu_tables.js`
   (또는 기존 테이블 파일에 추가). 보간은 log-log 선형 권장(Elam 자체가 log-log spline).
2. **Compton 전자 평균 에너지 표**: 레퍼런스 JSON의 `compton_electron_mean_eV` 41점을
   그대로 내장 + 선형보간 (xraydb도 `np.interp` 선형보간 사용 — 동일 동작).
3. **W-value 상수**: §2의 4개 값 하드코딩 (출처 주석 필수).

## 5. JS API 스케치

```javascript
// js/optics/ 또는 js/experiment/ — ES5 (var/function), 이모지 금지
function icCurrent(flux_phps, gas, length_cm, E_keV) {
  // gas: 'N2' | 'He' | 'Ar' | 'air'
  var E_eV = E_keV * 1000;
  var muT = _gasMu(gas, E_eV, 'total');   // [1/cm] (1 atm 기본밀도)
  var muP = _gasMu(gas, E_eV, 'photo');
  var muI = _gasMu(gas, E_eV, 'incoh');
  var aT = 1 - Math.exp(-length_cm * muT);
  var aP = aT * muP / muT;
  var aI = aT * muI / muT;
  var Ec = _comptonElectronMean(E_eV);    // [eV]
  var W = IC_W_VALUES[gas];               // [eV/ion-pair]
  return flux_phps * 1.602176634e-19 * 2 * (E_eV * aP + Ec * aI) / W;  // [A]
}
```

SimIOC 배선: `js/control/02_epics.js:223`의 현 placeholder
(`photonFlux(state.energy) * 1.6e-19`)를
`icCurrent(sampleFlux(), 'N2', 10, state.energy)`로 교체 (sampleFlux = 시료 flux SSOT,
cold-start gating 유지). PV: `BL10:IC1:Current`.

## 6. 완료 기준

- JS `icCurrent()`가 `paper/validation/data/ionchamber_reference.json` 대비
  **전 격자(4가스 × 41 에너지)에서 오차 <=1%**.
- 검증 스크립트는 paper/validation 패턴 (node로 JS 실행 → JSON 대조).
- 완료 시 CHANGELOG entry + `docs/knowledge/02_physics_overview.md` 갱신
  + `python Scripts/build_doc_index.py` (INDEX 갱신; 본 kickoff 커밋은 신규 파일만
  포함하므로 INDEX/CHANGELOG 동기화는 머지 세션에서 수행).

## 7. 진행 현황

| 일자 | 작업 | 상태 |
|------|------|------|
| 2026-06-12 | Python 레퍼런스 + JSON + 본 레시피 (xraydb 4.5.8 ground truth) | 완료 |
| 2026-06-12 | `Scripts/generate_gas_mu.py` → `js/optics/00_gasmu_tables.js` (4가스 × photo/incoh/total, 5–25 keV step 0.1, log-log interp; off-grid 오차 ≤7.8e-5) | 완료 |
| 2026-06-12 | `js/optics/07_ion_chamber.js`: `icCurrent` / `icFluxFromCurrent` / `icTransmittedFraction` — 혼합가스(분율가중 mu·W), Compton 41점표+선형보간, `opts.pressure_atm`, `opts.both_carriers`, `opts.with_compton` | 완료 |
| 2026-06-12 | 검증 `paper/validation/run_ionchamber_js_check.js`: 전 격자(4×41) max rel err ≤4.9e-8 (기준 1e-2), round-trip ≤3.4e-16, 혼합/압력/off-grid 스폿체크 vs fresh xraydb PASS | 완료 |
| 2026-06-12 | 시나리오 검증 `paper/validation/run_ionchamber_scenarios.js`: 빔라인 운영 시나리오 6종 (S1~S6) + live xraydb 교차검증 2점 — 전체 PASS (§8) | 완료 |
| | SimIOC 배선 (`02_epics.js` BL10:IC1:Current → `icCurrent(sampleFlux(),'N2',10,state.energy)`) — 다른 브랜치 pending 변경과 충돌 방지 위해 **머지 세션에서 수행** | 예정 |

## 8. Scenario validation (빔라인 운영 시나리오 6종)

단위 검증(§6, 격자 일치)에 이어 **운영 워크플로우 단위**로 모델을 검증.
스크립트: `paper/validation/run_ionchamber_scenarios.js` (node, 전 시나리오 blocking assert,
하나라도 실패 시 exit 1). 실행: `node paper/validation/run_ionchamber_scenarios.js`.

| # | 시나리오 | 조건 | PASS 기준 | 결과 | 핵심 수치 |
|---|----------|------|-----------|------|----------|
| S1 | IC1 운영점 | sampleFlux SSOT 6.3e12 ph/s @10 keV, N2 10 cm 1 atm | 1 nA < I < 100 uA AND 레퍼런스 격자 보간 대비 ≤1e-6 | PASS | I0 = **25.097 uA** (rel err 9.1e-9) |
| S2 | XAFS 에너지 스캔 | Cu K-edge 영역 8.70~9.30 keV step 0.02 (off-grid 31점), N2 10 cm | 전류 곡선 strict 단조감소 + 점간 step < 2% (N2는 이 영역에 edge 없음) | PASS | 단조감소, max step 0.468%/20 eV |
| S3 | I0/I1 투과 셋업 | I0=N2 10 cm → 시료 T_s=0.3 → I1=Ar 10 cm @9 keV | I1→입사 flux 역재구성 오차 < 1e-9 AND I1/I0 = T_N2·T_s·(흡수에너지/W 비) 해석식 일치 < 1e-12 | PASS | I1/I0 = 4.774, 체인 오차 2.2e-16, 해석식 일치 0.0 |
| S4 | 가스 선택 | @20 keV, N2/Ar/air 동일 flux 비교 | Ar/N2 전류비 > 5 (고에너지에서 Ar 사용 동기) | PASS | Ar/N2 = **37.21** (ref I: Ar 3.2958e-7 / N2 8.8582e-9 A per 1e10 ph/s) |
| S5 | 압력 튜닝 | Ar 0.2/0.5/1.0 atm @15 keV | 흡수율 sub-linear (atten/P strict 감소) + 전류 strict 증가 + 0.2 atm = closed form 1-exp(-0.2·mu·L) < 1e-12 | PASS | atten/P: 0.342→0.324→0.298, closed form rel diff 0.0 |
| S6 | 커미셔닝 역산 | 측정 I0 = 10 nA, N2 10 cm @12 keV | icFluxFromCurrent → icCurrent round trip < 1e-12 | PASS | 입사 flux = **3.7001e9 ph/s** (10 nA당, T=0.9719), round trip 0.0, ref flux_phps_per_nA 대비 1.3e-8 |

**Live xraydb 교차검증** (시나리오 점 2개, 상수는 하니스에 명령어와 함께 내장,
python 3.11.4 + xraydb 4.5.8 — 레퍼런스/테이블 생성과 동일 설치본):

| 점 | xraydb 호출 | I rel err | trans rel err | 기준 |
|----|------------|-----------|---------------|------|
| S2 N2 @8.98 keV 1 atm (양쪽 격자 모두 off-grid) | `material_mu('nitrogen', 8980, kind=k)` + closed-form 체인 (체인은 같은 점에서 `ionchamber_fluxes(...)` 프로그램 출력과 reldiff 0.0 재확인) | 1.5e-6 | 1.9e-7 | 1e-4 |
| S5 Ar @15 keV 0.5 atm | `material_mu('argon', 15000, density=0.001784*0.5, kind=k)` (xraydb에 압력 인자 없음 → 프로그램이 스케일 밀도에서 계산한 mu; mu는 밀도에 선형) + 동일 체인 | 1.9e-11 | 1.9e-9 | 1e-4 |

결론: 6/6 시나리오 + live 교차검증 전체 PASS. 운영 관점 대표값 —
IC1(N2 10 cm) @10 keV에서 시료 flux 6.3e12 ph/s → 25.1 uA,
@12 keV 10 nA → 3.70e9 ph/s, 고에너지(20 keV)에서는 Ar이 N2 대비 37배 전류
(낮은 flux에서도 신호 확보; XAFSmass/xraydb와 동일 물리).
