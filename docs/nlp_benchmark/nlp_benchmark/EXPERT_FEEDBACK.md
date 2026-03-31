---
title: "Expert Feedback"
category: nlp_benchmark
status: current
updated: 2026-03-05
tags: [nlp, feedback, expert]
summary: "전문가 리뷰 2명: 228 vExp 테스트, 10개 우선 패턴"
---
# NLP Expert Feedback Analysis

> **목적**: 전문가 서베이 결과를 체계적으로 분류하여 NLP 에이전트 시스템 프롬프트 및 후처리 개선에 활용
> **갱신 정책**: 새 리뷰어 결과가 추가될 때마다 통계 및 분류 업데이트

---

## 1. 리뷰어별 통계

| Reviewer | Model | Date | OK | Wrong | Missing | Unnecessary | Total |
|----------|-------|------|----|-------|---------|-------------|-------|
| Daseul Ham | Qwen/Qwen3-32B | 2026-03-01 | 154 (67.5%) | 33 (14.5%) | 34 (14.9%) | 7 (3.1%) | 228 |
| Changwan Ha | Qwen/Qwen3-32B | 2026-03-01 | 153 (67.1%) | 26 (11.4%) | 45 (19.7%) | 4 (1.8%) | 228 |
| **평균** | | | **153.5 (67.3%)** | **29.5 (12.9%)** | **39.5 (17.3%)** | **5.5 (2.4%)** | **228** |

**Expert satisfaction rate**: 67.3% (평균 153.5/228 OK)
- 자동 벤치마크 통과율(96.9%)과의 괴리 = **도메인 전문성 기반 판단의 중요성**
- "자동 PASS"인데 전문가가 Wrong/Missing으로 판정한 항목 = 벤치마크 개선 필요

### 1.1 리뷰어별 관점 차이

| 관점 | Daseul Ham | Changwan Ha |
|------|-----------|-------------|
| 핵심 초점 | 데이터 품질 (노출 시간, 통계) | 빔라인 운영 안전 & 추적성 |
| Exposure time 지적 | ~25건 (최빈출) | 0건 |
| 단위 미명시 확인 | 1건 | 4건 (강하게 요구) |
| 에너지 변경/정렬 | ~12건 | ~18건 (가장 빈출) |
| 실행 전 설명 의무 | 암시적 | 명시적 (~15건) |
| 실험 전략 제안 | 있음 | 있음 (핫스팟 우선 접근) |
| 로그/추적성 | 없음 | 있음 (~3건) |

---

## 2. 피드백 패턴 분류 (Priority 순)

### P1: Exposure Time 누락 (최빈출, ~25건)

**문제**: 거의 모든 스캔 관련 액션에서 exposure time이 명시되지 않음
**영향받는 테스트**: scan_01~09, align_02, batt_01/02/05, semi_02, bio_02, mat_01, edge_03/04, held_01/05/13, explan_03, cmulti_08, heavyel_01, geo_03 등
**Expert 원문**: "exposure time 명시", "exposure time도 물어봐줘"

**개선 방안**:
- [ ] 시스템 프롬프트에 규칙 추가: "스캔 액션 생성 시 exposure time을 반드시 물어볼 것"
- [ ] 후처리(Layer 5): quickRaster/quickXanes/quickXafs 등 스캔 함수 호출 시 exposure time 파라미터 확인
- [ ] confirmation_required=true로 설정하여 유저에게 스캔 파라미터 확인 요청

### P2: 에너지 변경 시 정렬 기준 (Alignment Criteria, ~12건)

**문제**: 에너지를 변경할 때 빔 정렬을 다시 해야 하는지 기준이 불명확
**영향받는 테스트**: scan_02, held_02, batt_02, semi_02, korean_05/09, seq_02/03, vexp_14/18/35/36, cmulti_07, colloquial_02
**Expert 원문**: "Energy scan할때 정렬 유무의 기준을 명확히 해야한다", "현 에너지에서 차이가 2 keV 이상이면 정렬 필요"

**규칙 정리**:
| 에너지 변화 | 정렬 필요 여부 | 근거 |
|------------|-------------|------|
| dE < 2 keV | 불필요 (DCM만 조정) | 미러 반사율/초점 변화 미미 |
| dE >= 2 keV | 필요 (runFullAlignment) | 미러 반사율/고조파 변화 유의 |
| 현재 에너지 → 목표 에너지 | 절대차 기준 | 현재 설정 기준으로 판단 |

**개선 방안**:
- [ ] 시스템 프롬프트에 정렬 규칙 명시: "|dE| >= 2 keV → runFullAlignment() 포함, < 2 keV → 생략 가능"
- [ ] 에너지 변경 + XANES/XAFS 조합 시 자동으로 정렬 필요성 판단
- [ ] explanation에서 "에너지 차이가 X keV이므로 정렬 필요/불필요" 명시

### P3: 스캔 파라미터 확인 (Scan Parameters, ~10건)

**문제**: scan step, range, point 수 등을 유저에게 확인하지 않고 기본값 사용
**영향받는 테스트**: scan_04/06/09, param_01/02, env_01, vexp_03/08/30
**Expert 원문**: "scan step 물어봐줘", "빔 사이즈 확인 후 scan step 결정", "밀도 높은 측정이라는 말이 scan step을 작게 한다는 의미인지"

**핵심 원칙**: scan step ≈ beam size (Nyquist 기준)
- beam size 50nm → step 50nm 이하
- beam size 1um → step 0.5~1um

**개선 방안**:
- [ ] 시스템 프롬프트: "래스터/라인스캔 시 step size를 빔 사이즈 기준으로 설정. 모호하면 물어볼 것"
- [ ] quickRaster/quickLineScan에 step size 파라미터 명시

### P4: 다원소 XRF 에너지 선택 (~8건)

**문제**: 다원소 동시 XRF 시 에너지를 가장 높은 흡수단 이상으로 설정하지 않음
**영향받는 테스트**: sample_01, bio_01, vexp_12, vexp_17, batt_01, mat_02
**Expert 원문**: "Ni K-edge보다 높은 에너지에서 측정해야", "아연 K-edge보다 높은 에너지에서 측정해야"

**규칙**:
```
다원소 XRF 에너지 = max(모든 목표 원소의 absorption edge) + ~1 keV
예: Ni(8.333)+Co(7.709)+Mn(6.539) → 에너지 = 8.333 + 1 ≈ 9.5 keV
```

**개선 방안**:
- [ ] 시스템 프롬프트에 다원소 XRF 에너지 규칙 추가
- [ ] 후처리(Layer 5): 복수 원소 언급 시 에너지 자동 검증

### P5: Focusing Optics & Beam Size (~6건)

**문제**: "나노 XRF", "고해상도" 요청 시 집속 광학계 선정/정렬을 빠뜨림
**영향받는 테스트**: align_03, multi_01, bio_01, semi_01, korean_05, vexp_08
**Expert 원문**: "빔 사이즈를 물어보거나 focusing optics를 무엇을 쓸지 물어봐야함", "나노 XRF라고 명시했기 때문에 nanometer로 집속해야한다"

**개선 방안**:
- [ ] 시스템 프롬프트: "나노빔/고해상도 요청 시 KB/ZP/CRL 중 focusing optics 선정 필요"
- [ ] confirmation으로 빔 사이즈 물어보기: "원하시는 빔 사이즈가 어떻게 되나요?"

### P6: Setup vs Execute 구별 (~3건)

**문제**: "셋업해줘" = 준비(파라미터 설정)인데, 모델이 즉시 실행(queueStart)까지 수행
**영향받는 테스트**: vexp_01, vexp_03, vexp_08
**Expert 원문**: "셋업해주라는 말은 측정하라는 것이 아닌 측정 시작 준비하라는 의미"

**개선 방안**:
- [ ] 시스템 프롬프트에 "셋업/세팅/준비 = queueStart() 제외, 파라미터만 설정" 규칙
- [ ] "시작/측정/찍어/돌려" = 실행 포함(queueStart)

### P7: Mirror Coating 변경 (Pt 측정 시, ~3건)

**문제**: Pt L3-edge XANES/XRF 시 미러 코팅에 의한 간섭 경고 없음
**영향받는 테스트**: edge_07, sigest_05
**Expert 원문**: "Mirror coating material를 Rh으로 바꾸면 돼"

**개선 방안**:
- [ ] 시스템 프롬프트: "Pt 측정 시 미러 코팅을 Rh stripe으로 변경 필요" 경고 규칙
- [ ] explanation에 코팅 간섭 가능성 명시

### P8: XRF/XRD 동시 측정 가능성 (~3건)

**문제**: XRF→XRD 전환 시 "검출기 교체 30분" 안내하지만, 실제로는 동시 가능
**영향받는 테스트**: vexp_11, explan_05
**Expert 원문**: "XRF와 XRD 검출기 위치가 다르기 때문에 동시에 측정이 가능"

**개선 방안**:
- [ ] 시스템 프롬프트: "이 빔라인은 XRF/XRD 검출기가 동시 장착. 검출기 교체 불필요"
- [ ] Ptycho + XRF도 동시 가능 (scanning 기반이므로)

### P9: Info vs Action 구별 (~5건)

**문제**: 정보 질문에 대해 실제 액션을 생성하는 경우
**영향받는 테스트**: held_15, robust_10, info_03, realuser_11
**Expert 원문**: "energy를 변경하는게 아니라 값을 물어본 것", "에너지를 설정합니다라고 하면 안됨"

**패턴**:
| 표현 | 의도 | 올바른 응답 |
|------|------|-----------|
| "~를 얼마로 해야 해?" | 정보 요청 | actions: [], explanation으로 답변 |
| "~가 얼마야?" | 현재 상태 질문 | actions: [], 현재값 안내 |
| "~로 해줘/맞춰줘" | 실행 요청 | 실제 액션 생성 |

**개선 방안**:
- [ ] 시스템 프롬프트에 info-only 패턴 명시

### P10: XRD 관련 세부 (~4건)

**문제**: XRD 요청 시 Bragg angle, q-range 관련 안내 부족
**영향받는 테스트**: batt_05, semi_02, vexp_34, vexp_49
**Expert 원문**: "bragg angle을 설정해야함", "q range를 계산하여 알려줘", "XANES 후 XRD = 단일 패턴, 래스터 아님"

**핵심 구분**:
- "XRD 해줘" (단독) → 단일 패턴 수집 (setupVirtualExperiment(powder_xrd))
- "2D XRD 맵핑" → quickRaster + XRD 검출기
- "XRD 패턴 한 장" → 단일 패턴
- XANES 후 "XRD도" → 단일 패턴 (래스터 X)

**개선 방안**:
- [ ] 시스템 프롬프트에 XRD 유형 구분 규칙 추가
- [ ] q-range 계산 기능 구현 (에너지 → 접근 가능한 q 범위)

---

## 3. OK 판정이지만 개선 제안이 있는 항목

일부 OK 판정 항목에서도 전문가가 개선 제안을 남김:

| Test ID | 제안 내용 | 분류 |
|---------|----------|------|
| scan_01 | scan step, energy scan range, exposure time 명시 | P1+P3 |
| scan_03 | 에너지 8.5 keV 설정 이유 필요 | 에너지 선택 근거 |
| geo_02 | 라인이 대각선인지 raster인지 확인 | 모호성 해소 |
| held_10 | motor position limit 확인 후 가능 여부 판단 | 안전성 |
| explan_04 | 실제 motor 속도, backlash, exposure time 고려한 시간 계산 | 시간 추정 정확도 |
| explan_07 | 예상 시간 계산 후 우선순위 선택 요청 | 의사결정 지원 |
| explan_08 | 매니저에게 문의하라고도 안내 | 물리적 교체 한계 |
| realuser_04 | 집속 빔 사이즈 축소 외 다른 방법도 고려 | 대안 제시 |
| realuser_07 | 이전 스캔 결과 전용 UI 필요 | 기능 요청 |
| realuser_08 | 상대 이동량을 빔 사이즈 기준으로 | P5 연관 |
| reject_02 | 범위 밖 원소 → 대안 원소 추천 | 대안 제시 |
| reject_08 | 향후 microscope 연결 시 시료 사진 가능 | 미래 기능 |
| korean_05 | 원하는 빔 사이즈와 에너지를 물어봐 | P5 |
| vexp_15 | XRF 매핑 후 신호 좋은 곳에서 XANES | 실험 전략 |
| vexp_32 | in-situ vs ex-situ 구분 필요 | 실험 유형 |
| safety_01 | 중지하고 셔터도 닫아줘 | 안전 강화 |

---

## 4. 도메인 전문가 인사이트 (수용 권장)

전문가의 코멘트에서 NLP 시스템에 반영해야 할 **빔라인 운영 지식**:

### 4.1 물리 규칙
1. **다원소 XRF**: 에너지 > max(모든 target edge) + ~1keV
2. **정렬 기준**: |dE| >= 2keV → 재정렬 필수
3. **KB 초점거리**: 에너지 변해도 불변 (기하학적 결정)
4. **Pt 측정**: Rh 코팅 stripe으로 변경 필수
5. **scan step ≈ beam size** (Nyquist sampling)
6. **XRF+XRD 동시 가능**: 검출기 위치 다름
7. **Ptycho+XRF 동시 가능**: scanning 기반

### 4.2 운영 프로토콜
1. **"셋업" ≠ "측정"**: 셋업 = 파라미터 준비, 측정 = 실행
2. **Exposure time**: 모든 스캔에 필수 파라미터
3. **빔 안정성**: BPM 데이터 기반, % 변화로 표시, 임계값 설정
4. **상대 이동**: "좀 더" = beam size 대비 이동량 결정
5. **에너지 설정 근거**: "왜 이 에너지인가" 설명 필수
6. **오염 확인**: point XANES보다 XRF mapping이 적합 (빔이 작으면 포인트에 오염이 없을 수 있음)
7. **Phase 분석**: 2D XRD 매핑 아닌 normal XRD (단일 패턴)
8. **XANES 후 XRD**: 래스터 아닌 단일 패턴 수집
9. **단위 미명시 시 확인 의무** (Ha): 단위 없이 숫자만 제시 시 임의 추론 금지, 반드시 확인 [2명 동의]
10. **액션 설명 의무** (Ha): 실행하는 액션에 대해 어떤 장치가 어떻게 변경되는지 설명
11. **실험 로그 추적성** (Ha): 빔 상태/설정 정보를 기록하여 나중에 로그 확인 가능하도록
12. **불균일 시료 핫스팟 전략** (Ha): 환경/지질/생물 시료 → XRF 맵핑으로 핫스팟 찾기 → XANES [2명 동의]
13. **Ag L3-edge 대안 오류 수정**: Ag L3=3.351keV는 빔라인 최소 5keV 미만이므로 대안 불가. 잘못된 추천 금지

### 4.3 UX 개선 제안
1. **이전 스캔 결과 전용 UI**: "이전 스캔 결과 보여줘" 명령 지원
2. **q-range 계산기**: 에너지/검출기 → 접근 가능 q범위 표시
3. **시간 추정 정확도**: motor 속도, backlash, exposure time 반영
4. **범위 밖 원소 대안 추천**: "O K-edge 불가 → 산소 결합 상태는 금속 측 XANES로 간접 확인 가능"
5. **실행 전 빔 상태 표시** (Ha): 현재 에너지/빔 크기/설정을 explanation에 포함

---

## 5. 구현 우선순위 (Action Items)

### Phase 1: 시스템 프롬프트 개선 (즉시 적용 가능)

| # | 항목 | 영향 범위 | 난이도 |
|---|------|---------|--------|
| 1 | Exposure time 질문 규칙 | ~25건 | 낮음 |
| 2 | 정렬 기준 (dE >= 2keV) | ~12건 | 낮음 |
| 3 | 다원소 XRF 에너지 규칙 | ~8건 | 낮음 |
| 4 | Setup vs Execute 구별 | ~3건 | 낮음 |
| 5 | Info vs Action 구별 | ~5건 | 낮음 |
| 6 | Pt 측정 시 Rh 코팅 경고 | ~3건 | 낮음 |
| 7 | XRD 유형 구분 (단일/래스터) | ~4건 | 낮음 |
| 8 | XRF/XRD 동시 측정 가능 안내 | ~3건 | 낮음 |

### Phase 2: 후처리 로직 추가 (코드 수정 필요)

| # | 항목 | 파일 | 난이도 |
|---|------|------|--------|
| 1 | 에너지 범위 검증 + 정렬 자동 판단 | nlp_agent.py | 중간 |
| 2 | 스캔 파라미터 완성도 검증 | nlp_agent.py | 중간 |
| 3 | 다원소 에너지 자동 보정 | nlp_agent.py | 중간 |
| 4 | q-range 계산기 | 신규 함수 | 높음 |

### Phase 3: 기능 확장 (장기)

| # | 항목 | 설명 |
|---|------|------|
| 1 | 이전 스캔 결과 UI | scan history viewer |
| 2 | 빔 안정성 모니터링 | BPM 기반 % 표시 |
| 3 | 시간 추정 정밀화 | motor 속도/backlash 반영 |
| 4 | 범위 밖 원소 대안 추천 | 간접 분석 방법 안내 |

---

## 6. 벤치마크 테스트 개선 필요 항목

전문가 리뷰에서 **자동 벤치마크가 PASS했으나 전문가가 부적절하다고 판단**한 항목들:

| Test ID | Auto | Expert | 개선 필요 내용 |
|---------|------|--------|--------------|
| sample_01 | PASS | Wrong | 다원소 XRF 에너지 검증 추가 |
| edge_07 | PASS | Wrong | Pt 코팅 간섭 검증 추가 |
| explan_05 | PASS | Wrong | Ptycho+XRF 동시 가능 검증 |
| analysis_03 | FAIL | Wrong | Phase 분석 → normal XRD 검증 |
| implicit_02 | PASS | Wrong | 오염 검출 → XRF 매핑 우선 검증 |
| vexp_01 | PASS | Wrong | Setup vs Execute 검증 |
| vexp_11 | PASS | Wrong | XRF/XRD 동시 가능 검증 |
| robust_08 | PASS | Wrong | 다원소 매핑 인식 검증 |
| held_15 | PASS | Unnecessary | info-only 판별 검증 |

→ 이 항목들의 expect 조건을 전문가 의견에 맞게 업데이트 필요

---

## 7. 리뷰어 추가 가이드

새 리뷰어 결과 JSON이 도착하면:

1. `docs/nlp_benchmark/reviews/review_{Name}_{Date}.json` 에 저장
2. 섹션 1 통계 테이블에 행 추가
3. 비OK 항목을 기존 패턴(P1~P10)에 매핑하여 빈도 업데이트
4. 새로운 패턴이 발견되면 P11+ 추가
5. 2명 이상 동의한 피드백은 **확정 개선사항**으로 승격
6. 리뷰어 간 의견이 다른 항목은 별도 표로 관리

### 피드백 수용 기준

| 조건 | 수용 여부 |
|------|----------|
| 2+ 리뷰어 동의 | 즉시 수용 |
| 1 리뷰어 + 물리적 근거 명확 | 수용 |
| 1 리뷰어 + 주관적 선호 | 보류 (추가 의견 대기) |
| 기존 규칙과 충돌 | 논의 필요 |

---

## Appendix A: 전체 비OK 항목 목록

### Wrong Action (33건)

| # | ID | Cat | Prompt (요약) | Expert 피드백 | 패턴 |
|---|-----|-----|-------------|-------------|------|
| 1 | sample_01 | scientist | NMC622 Ni/Mn/Co XRF | 에너지 > Ni K-edge | P4 |
| 2 | mask_02 | attenmask | 고정 마스크 갭 변경 | fixed mask 갭 변경 가능 여부 확인 | 기능확인 |
| 3 | info_03 | info | 빔 프로파일 보여줘 | 어디에서의 profile인지 물어보기 | P9 |
| 4 | opt_05 | optimize | Cu 신호 얼마나? | 실제 XRF 찍어보고 신호값 제공 | 기능확장 |
| 5 | cmulti_02 | complex_multi | Se XAFS 측정 | Se인데 Si 언급 오류 | 모델오류 |
| 6 | cmulti_07 | complex_multi | 어테뉴에이터+Cr XANES | 정렬 액션 누락 | P2 |
| 7 | robust_07 | robustness | quickXafs Cu K | 에너지 차이 1.021keV | P2 |
| 8 | robust_08 | robustness | Cu,Fe,Zn 다원소 매핑 | XRF 매핑 의미 인식 실패 | P4 |
| 9 | edge_07 | edgecase | Pt L3 XANES | Rh 코팅으로 변경 | P7 |
| 10 | explan_05 | experiment_plan | ptycho+XRF 동시? | 동시 가능 | P8 |
| 11 | explan_09 | experiment_plan | XRF 맵 시간 계산 | 200x200x0.1s/60 = 66.7분 | 계산오류 |
| 12 | analysis_03 | analysis_intent | 상 분석 | normal XRD, 2D 맵핑 아님 | P10 |
| 13 | seq_03 | sequential | Pb+As XANES | 중간 에너지 정렬 1회로 충분 | P2 |
| 14 | realuser_11 | real_user | 빔 안정성 | BPM+% threshold | 기능확장 |
| 15 | implicit_02 | implicit_technique | Cu 오염 확인 | XRF 매핑이 더 적합 | 전략 |
| 16 | vexp_01 | experiment_preset | Cu XAFS 셋업 | 셋업≠실행 | P6 |
| 17 | vexp_08 | experiment_preset | 나노 XRF 세팅 | 원소/빔사이즈/range 물어볼 것 | P5 |
| 18 | vexp_11 | experiment_planning | XRF→XRD 검출기 교체? | 동시 가능 | P8 |
| 19 | vexp_12 | experiment_planning | 페로브스카이트 Pb+결정상 | 에너지 > Pb L3 | P4 |
| 20 | vexp_14 | experiment_planning | Mn/Co/Ni 순차 정렬? | 현재→Mn 에너지차 기준 정렬 | P2 |
| 21 | vexp_17 | experiment_planning | Au/TiO2 | Ti 산화상태 불가 명시 | 정보제공 |
| 22 | vexp_18 | experiment_planning | Ce→Fe 정렬? | 현재E→Ce간 정렬 필요 | P2 |
| 23 | vexp_22 | ptycho_experiment | 10keV ptycho | SSA 축소 잘못됨 | 모델오류 |
| 24 | vexp_23 | ptycho_experiment | 반도체 50nm | Si edge 아님, 높은 에너지/tomo | 전략 |
| 25 | vexp_29 | technique_selection | 나노 이미지 | XRF 매핑+nano beam | 전략 |
| 26 | vexp_34 | multi_technique | Ni XANES+XRD | XRD = 단일패턴, 래스터 아님 | P10 |
| 27 | vexp_35 | multi_technique | Fe XAFS+XRF | dE>2keV 정렬 필요 | P2 |
| 28 | vexp_46 | experiment_edge | Ag K-edge | 범위 초과 명시 | 정보제공 |
| 29 | vexp_49 | experiment_edge | XRD 5keV | q-range 계산 제공 | P10 |
| 30 | reject_06 | rejection | Ag K-edge | 대안 없음 명확히 | 정보제공 |
| 31 | blknow_01 | bl_knowledge | 에너지 범위 | 범위 기준 일관성 | 정보정확 |
| 32 | blknow_02 | bl_knowledge | KB 초점거리 | 에너지 무관 (기하학적) | 물리지식 |
| 33 | blknow_05 | bl_knowledge | 최소 빔사이즈 | SSA 10um ≠ 집속빔 10um | 물리지식 |

### Missing Action (34건)

| # | ID | Cat | Prompt (요약) | Expert 피드백 | 패턴 |
|---|-----|-----|-------------|-------------|------|
| 1 | motor_03 | motor | 시료 X 100 이동 | 단위 표시 | 정보제공 |
| 2 | scan_02 | scan | 철 XANES | 정렬 기준+exposure time | P1+P2 |
| 3 | scan_04 | scan | 라인스캔 | 대각선 확인+exposure+step | P3 |
| 4 | scan_06 | scan | 적응형 에너지 스캔 | 변수 의미 설명 | P3 |
| 5 | scan_09 | scan | 5x5 래스터 | point/step+exposure time | P1+P3 |
| 6 | align_02 | alignment | 철 XRF 2D 맵 | exposure time | P1 |
| 7 | align_03 | alignment | 전체 빔 정렬 | 에너지/빔사이즈/optics 물어보기 | P5 |
| 8 | align_04 | alignment | M1 자동 정렬 | target pitch/half-cut | 도메인 |
| 9 | multi_01 | multi | 12keV+정렬+프로파일 | 빔 사이즈 물어보기 | P5 |
| 10 | opt_02 | optimize | Fe XRF 최적 분해능 | 에너지 먼저→빔사이즈 | P5 |
| 11 | opt_04 | optimize | ptycho 최적 조건 | coherence 0.3 근거 | 도메인 |
| 12 | param_01 | param | 2D XRD 매핑 | exposure time+bragg peak | P1+P10 |
| 13 | param_02 | param | 철 XRF 2D 맵 | exposure time | P1 |
| 14 | sample_02 | scientist | Au L3 XRF 50ppm | flux→신호 계산 | P1 |
| 15 | batt_01 | battery | NMC XRF 맵핑 | XRF 신호→exposure time | P1 |
| 16 | batt_02 | battery | LiFePO4 Fe XAFS | 정렬 기준+exposure time | P1+P2 |
| 17 | batt_05 | battery | 양극재 XRD 맵 | exposure time+bragg angle | P1+P10 |
| 18 | semi_01 | semiconductor | Cu 배선 XRF | 에너지 > Cu K-edge | P4 |
| 19 | semi_02 | semiconductor | nano-XRD 15keV | 정렬+exposure+bragg | P1+P2+P10 |
| 20 | env_01 | environment | Pb XRF+XANES | beam size→step | P3 |
| 21 | bio_01 | biology | Fe+Zn nano XRF | 에너지>Zn K+nano optics | P4+P5 |
| 22 | explan_02 | experiment_plan | SrTiO3 단결정 | XRD도 필요할 수 있음 | 전략 |
| 23 | held_02 | heldout | 9.5keV 설정 | 정렬 필요성 물어보기 | P2 |
| 24 | korean_09 | korean_variant | 망간 XAFS | 정렬 액션 누락 | P2 |
| 25 | sigest_02 | signal_est | Au 10ppm 신호 | XRF/XRD 둘다 예측 | 기능확장 |
| 26 | sigest_04 | signal_est | Mn 500ppm 검출한계 | 투과 검출한계도 | 기능확장 |
| 27 | qact_02 | question_action | SSA 50um | vertical gap도 | 파라미터 |
| 28 | heavyel_02 | heavy_element | W XRF 맵핑 | (코멘트 없음) | - |
| 29 | vexp_02 | experiment_preset | 분말 XRD | WAXS+detector distance | 도메인 |
| 30 | vexp_03 | experiment_preset | 2D XRF 셋업 | 원소 먼저 물어보기 | P3 |
| 31 | vexp_05 | experiment_preset | 결정상 분포 | 결정면 물어보기 | P3 |
| 32 | vexp_30 | technique_selection | Cr 10ppm 검출 | XRF 매핑 필요 | 전략 |
| 33 | vexp_36 | multi_technique | Mn/Co/Ni+XRF | dE>2keV 정렬 | P2 |
| 34 | seq_02 | sequential | Mn+Co XANES | 정렬 누락 | P2 |

### Unnecessary Action (7건)

| # | ID | Cat | Expert 피드백 | 패턴 |
|---|-----|-----|-------------|------|
| 1 | opt_03 | optimize | Ti L3 불가능 에너지 언급 불필요 | 정보과잉 |
| 2 | atten_02 | attenmask | material=None이면 thickness=0 중복 | 중복액션 |
| 3 | held_15 | heldout | 에너지 질문인데 변경 실행 | P9 |
| 4 | robust_10 | robustness | "설정합니다" 후 불가능이라 모순 | P9 |
| 5 | blknow_03 | bl_knowledge | Si K-edge 불필요 언급 | 정보과잉 |
| 6 | vexp_06 | experiment_preset | "주의" 불필요 | 정보과잉 |
| 7 | vexp_39 | multi_technique | Pb K-edge 범위 초과 불필요 언급 | 정보과잉 |
