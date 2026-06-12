---
title: "C1 — ADSim Detector Data Path (areaDetector + ophyd + Bluesky)"
category: tasks
status: current
updated: 2026-06-12
tags: [phase1, detector, areadetector, adsim, ophyd, bluesky, hdf5, epics, vm1, load-test]
summary: "Phase-1 C1: VM1 ADSimDetector IOC(CA 5080 loopback) + ophyd SingleTrigger/HDF5 디바이스 + Bluesky count/grid_scan E2E PASS + HDF5 처리량 한계 실측(램디스크 vs 디스크) + 운영 시나리오 5종 검증(back-to-back/abort/IOC재기동/동시리더/hybrid dual-IOC) ALL PASS. 다음: Odin 평가, beamline_ctl.sh 등록, /ws/scan 노출."
---

> **요약**: 미래 EIGER2/Pilatus 통합(¶27/28)의 리허설로, ADSimDetector IOC의 검출기 **데이터 경로**(driver → NDFileHDF5 → HDF5 파일)를 제어 경로(CA PV)와 분리된 형태로 Bluesky 문서 스트림에 편입. E2E PASS, 처리량 한계 실측 완료.
> **관련 작업**: Phase-1 roadmap §4 C1 (`docs/tasks/TASK_PHASE1_ROADMAP.md`, `feature/phase1-nlp` 브랜치에 있음), B1 queueserver 설계 시 함께 참조.
> **역할 분리(중요)**: `js/detector/01_eiger.js`(브라우저 JS 시뮬)는 가상실험 **시각화**(XRD 이미지/XRF 스펙트럼 표시)용으로 유지. ADSim 경로는 **제어 스택 리허설**용. 서로 대체하지 않음 (roadmap §3 결정).

# C1 — ADSim 검출기 데이터 경로

## 1. IOC 구성 (VM1, kickoff 2026-06-12)

| 항목 | 값 |
|------|-----|
| areaDetector | R3-12-1 prebuilt, `/usr/local/epics/EPICS_R7.0/modules/synApps/support/areaDetector-R3-12-1/` |
| IOC 부팅 디렉토리 | `~/ADSim_build/iocSim/` (`st.cmd` + `envPaths`) |
| 바이너리 | `$AREA_DETECTOR/ADSimDetector/iocs/simDetectorIOC/bin/linux-x86_64/simDetectorApp` |
| PV prefix | `BL10:SIM1:` (`cam1:` / `image1:` / `HDF1:`) |
| **CA 격리** | CA 서버 포트 **5080, 127.0.0.1 전용** (`EPICS_CAS_INTF_ADDR_LIST`), beacon 5081 — 운영 soft IOC(5064/5065) 무접촉 |
| PVA 격리 | QSRV 5085/5086 loopback (Sydor 5075/5076 무접촉) |
| 드라이버 | simDetector 1024x1024, UInt8 기본, QSIZE=20, MAX_THREADS=4 |
| 플러그인 | NDStdArrays(image1, CA waveform) + NDFileHDF5(HDF1) |
| LazyOpen | `HDF1:LazyOpen=1` (st.cmd dbpf) — 첫 프레임 전 Capture arm 허용 |
| 데이터/로그 | `~/ADSim_build/data/`, `~/ADSim_build/logs/ioc.log` |

**시작/종료** (서비스 미등록 — 수동, KOHZU IOC와 같은 `tail -f /dev/null` 패턴):
```bash
cd ~/ADSim_build/iocSim
nohup bash -c "tail -f /dev/null | /usr/local/epics/EPICS_R7.0/modules/synApps/support/areaDetector-R3-12-1/ADSimDetector/iocs/simDetectorIOC/bin/linux-x86_64/simDetectorApp st.cmd" > ~/ADSim_build/logs/ioc.log 2>&1 &
# 종료: pkill -f simDetectorApp
```

## 2. ophyd 디바이스 (`server/scan_engine/ad_devices.py`)

- `ADSimDetector` = `SingleTrigger` + `DetectorBase`, `cam = SimDetectorCam('cam1:')`, `hdf5 = HDF5Plugin + FileStoreHDF5IterativeWrite('HDF1:')`.
  - 표준 NSLS-II 패턴 그대로 동작 — 단순화(직접 EpicsSignal staging)로 후퇴할 필요 없었음.
  - stage: NDFileHDF5 **Stream** capture(run당 1파일), trigger당 datum 문서 1개. 이벤트에는 프레임이 아니라 datum 참조만 흐름(데이터/제어 경로 분리).
  - `cam.stage_sigs`: `num_images=1`, `array_callbacks=1`. `hdf5.stage_sigs`: `num_capture=0`(unstage가 capture=0으로 파일 닫음).
- **CA 환경 (필수)**: IOC가 loopback:5080이므로 클라이언트에서
  `EPICS_CA_ADDR_LIST`에 `127.0.0.1:5080` 항목 + `EPICS_CA_AUTO_ADDR_LIST=NO`.
  - `ensure_adsim_ca_env()`가 기존 항목을 보존하며 append → **같은 프로세스가 운영 5064 IOC와 ADSim 5080 IOC를 동시에 사용 가능** (pyepics/libca host:port 주소 지원). `EPICS_CA_SERVER_PORT`는 프로세스 전역 오버라이드라 의도적으로 건드리지 않음 (server.py 안에서 쓰면 운영 CA가 전부 5080으로 가버림).
  - libca는 첫 CA 연결 시 env를 스냅샷 → 반드시 **첫 연결 전에** 호출.
- **UnprimedPlugin / "must collect an array first"**: IOC측은 LazyOpen=1로 해결, ophyd측은 `prime_hdf5_plugin()`(stock `HDF5Plugin.warmup()`, IOC 부팅 후 1회 throwaway 프레임)으로 해결. 이미 프레임을 본 플러그인이면 no-op.
- env 오버라이드: `ADSIM_PREFIX`(기본 `BL10:SIM1:`), `ADSIM_DATA_DIR`(기본 `~/ADSim_build/data`), `ADSIM_CA_PORT`(기본 5080).
- ophyd 부재 시 import-safe (`HAVE_OPHYD`), 팩토리 `get_adsim_detector()`가 RuntimeError로 안내.

```python
from scan_engine.ad_devices import ensure_adsim_ca_env, get_adsim_detector
ensure_adsim_ca_env()            # 첫 CA 연결 전에
det = get_adsim_detector()       # connect + prime
RE(count([det], num=5))          # -> HDF5 1파일 5프레임 + datum 5개
```

## 3. E2E 결과 (2026-06-12, VM1, `server/test_adsim_bluesky.py`) — **ALL PASS**

| Run | 문서 스트림 | HDF5 검증 (h5py) |
|-----|------------|------------------|
| `count([det], num=5)` | start=1 descriptor=1 resource=1 **datum=5 event=5** stop=1, exit_status=success | `(5, 1024, 1024)` uint8, 6.3 MB, `/entry/data/data` |
| `grid_scan` 3x3 (ophyd.sim motor1/motor2) | start=1 descriptor=1 resource=1 **datum=9 event=9** stop=1, exit_status=success | `(9, 1024, 1024)` uint8, 10.5 MB |

- 연결+프라이밍 3.4 s. ophyd 1.11.0 / bluesky 1.14.6 / h5py 3.16.0 / pyepics 3.5.9 (`~/K4GSR-Beamline/.venv`).
- 운영 서비스 무접촉 확인: soft_ioc(:5064, PID 819310) / server.py(:8001, PID 819866) / simulation_server(:8002, PID 822671) 전후 동일.

## 4. 처리량 한계 실측 (load test)

조건: Continuous acquire(AcquireTime=0, AcquirePeriod=0) + NDFileHDF5 Stream(non-blocking, queue 20), 1024x1024 프레임, **NumCapture 예산 제한**(타깃 여유공간의 40% 이내; ramdisk 3 GB / disk 6 GB). VM1 4 cores / 16 GB(tmpfs 7.8 GB). 측정: 드라이버 ArrayCounter 증분 x 프레임 바이트 / 측정창, HDF5 파일 크기 / 측정창, DroppedArrays. [근거: 실측 2026-06-12]

| 대상 | dtype | 측정창 | driver fps | driver 생성 MB/s | HDF5 write MB/s | dropped |
|------|-------|--------|-----------|------------------|-----------------|---------|
| ramdisk(tmpfs) | UInt8 | 1.5 s | 3817 | 4003 | **1987** | 2553 |
| ramdisk(tmpfs) | UInt16 | 1.5 s | 2333 | 4892 | **1986** | 2038 |
| ramdisk(tmpfs) | Float32 | 1.5 s | 1304 | 5471 | **1983** | 1202 |
| VM disk | UInt8 | 10.7 s | 3902 | 4092 | **558** | 35892 |
| VM disk | UInt16 | 7.4 s | 2298 | 4820 | **807** | 14087 |
| VM disk | Float32 | 9.6 s | 1501 | 6295 | **627** | 12783 |

**해석 (정직한 한계 보고)**:
- **현 경로의 천장 = NDFileHDF5 단일 writer**: 스토리지 병목을 제거(tmpfs)하면 dtype 무관 **~2.0 GB/s**에서 포화. VM 가상디스크로는 **0.56~0.81 GB/s**.
- 드라이버(simDetector)는 메모리 내 4~6.3 GB/s 프레임 생성 가능 — 병목은 생성이 아니라 **파일 쓰기**. dropped = non-blocking free-run에서 writer가 못 따라간 프레임 수(의도된 측정 설계).
- **주의(측정 한계)**: ramdisk 측정창은 1.5 s(3 GB 예산 / 2 GB/s — tmpfs 7.8 GB 제약), 3개 dtype에서 일관된 값이라 신뢰 가능하나 장시간 지속치는 아님. disk 수치는 호스트 페이지캐시 영향 포함(fsync 미측정), HDF5 무압축. GB/s는 애초에 기대치 아님 — 로드맵용 현 경로 한계 실측이 목적.
- **결론**: EIGER2급(수 GB/s) 데이터 레이트는 이 단일 NDFileHDF5 경로로 불가 → **Odin 병렬 writer 평가 필요**(§6). 본 표가 비교 기준선.

**부하테스트 중 발견한 함정 (재발 방지)**:
- **NDFileHDF5에 ENOSPC 절대 금지**: 무제한(NumCapture=0) 버스트가 tmpfs를 가득 채움 → HDF5 close 실패 → IOC가 삭제된 파일의 fd를 물고 있어 공간 미반환 → 후속 버스트 전부 0 프레임 → **IOC segfault** (areaDetector R3-12-1, 2026-06-12 실측). 해결: 버스트마다 NumCapture를 여유공간 40% 이내로 예산 제한(`test_adsim_bluesky.py load_burst`) — 물리적으로 ENOSPC 불가.
- IOC가 죽어가는 중 `ophyd .set().wait()`는 UnknownStatusFailure로 hang/crash — acquire 정지는 put + RBV 폴링(`_stop_acquire`)으로.

## 5. Scenario validation (운영 시나리오 검증, 2026-06-12) — **ALL 5 PASS**

`server/test_adsim_scenarios.py` (VM1에서 실행). E2E(§3)가 검증한 데이터 경로 위에서 **운영 동작** 5종을 검증. IOC 수명주기는 스크립트가 직접 관리(시작 시 fresh start, S3 내부 kill+restart, 종료 시 kill — process group 단위라 `tail -f /dev/null` 고아 없음). RunEngine은 전 시나리오 공유 **단일 세션**.

| # | 시나리오 | 결과 | 핵심 증거 (2026-06-12 실측) |
|---|---------|------|------------------------------|
| S1 | Back-to-back: 한 RE 세션에서 `count(num=3)` 5연속 | **PASS** | 서로 다른 HDF5 5개, 모두 (3,1024,1024); 매 run 후 Capture=0 · NumCaptured=3 · FileNumber_RBV=1 (잔류 상태 없음); run별 datum point 0..2; 파일 mtime 단조 증가 |
| S2 | Abort mid-scan: `count(num=50)`을 정확히 5 이벤트 후 pause → `RE.abort()` | **PASS** | exit_status=abort + RE idle 복귀; partial HDF5 정상 open — **정확히 5프레임** 보존(6.3 MB); IOC 응답 유지(caget Manufacturer_RBV OK); 후속 count(3) 성공 |
| S3 | IOC restart resilience: kill → 재기동, **같은 ophyd 디바이스 객체**로 count(3) | **PASS** | CA dead 확인 후 재기동: CA-ready 5.1 s, 디바이스 재연결 5.1 s (부팅 기준, `wait_for_connection(timeout=30)` 1회); HDF5 플러그인 re-prime 후 count(3) 성공 — 객체 재생성 불필요(CA 자동 재연결) |
| S4 | Concurrent reader: 100프레임 count 중 **별도 프로세스**(caproto threading client)가 5 Hz로 `ArrayCounter_RBV` 폴링 (같은 loopback CA) | **PASS** | 100프레임 5.5 s 완료(105.9 MB, h5py 검증); 폴러 28샘플 · CA timeout 0 · 카운터 단조 증가 4→101 |
| S5 | **Hybrid dual-IOC** (zero-change 전략 핵심): 운영 soft-IOC 모터 `BL10:DET:Z`(:5064) + ADSim 검출기(:5080)를 **한 grid_scan**으로 | **PASS** | 3 이벤트 모두 모터 readback + 검출기 datum 포함(readback 0.05/1.05/2.05 mm); 스캔 후 모터 원위치(0.0) 복원 — caget delta **0.0 ≤ 1 MRES**(1e-6) |

**노트**:
- **S5 = 논문 Phase-2 hybrid 모드의 실증**: 하나의 RunEngine 프로세스가 서로 다른 CA 포트의 두 IOC(운영 5064 + 격리 5080)를 동시 구동. `EPICS_CA_ADDR_LIST="127.0.0.1 127.0.0.1:5080"`(host:port 엔트리), `EPICS_CA_SERVER_PORT` 무접촉.
- DET:Z 초기 위치 0.0이 소프트 리밋 하한(LLM=0)과 같아 ±1 mm 윈도우를 리밋 안쪽으로 시프트(center 1.05 mm — 스크립트가 자동 처리). 스캔 후 0.0 복원 검증.
- S1 "sequential file numbering"의 실체: `FileStoreHDF5IterativeWrite`는 run마다 FileNumber를 0으로 재스테이징하고 **새 uuid 파일명**(`<uuid>_000000.h5`, run당 1파일)을 쓰는 설계. 순차성은 ① 5개 파일명 distinct ② mtime 단조 증가 ③ run별 datum point 0..2 ④ FileNumber_RBV가 매 run 동일값(1)으로 복귀(증분 잔류 없음)로 검증.
- ophyd는 **caproto control layer**로 동작 — `server/epics`(soft-IOC 패키지)가 sys.path에서 pyepics를 가리기 때문(§3 E2E와 동일 구성). 스크립트의 ad-hoc caget도 caproto threading client (`import epics` 금지, 스크립트 주석 참조).
- abort 시 bluesky가 `RequestAbort` traceback을 로그로 출력하는 것은 **정상 동작**(실패 아님).
- **운영 무접촉 재확인**: soft_ioc(:5064, PID 819310) / server.py(:8001, PID 819866) / simulation_server(:8002, PID 822671) — PID·시작시각 전후 동일, 5080 리스너 소멸 확인. 유일한 운영 PV 쓰기 = `BL10:DET:Z`(시뮬레이션 모터, 복원 검증 완료).
- 아티팩트: 시나리오당 HDF5 1개 보존(`~/ADSim_build/data/`), 나머지 삭제 — S1 `dce3695c…`, S2 partial `d6596f07…`(5프레임), S3 `ae13d565…`, S4 `87145ffd…`(100프레임), S5 `1d6608f9…`.

## 6. 다음 단계

1. **Odin 평가** (C2 선행 조사): EIGER2 실장비는 Odin data writer 경로 — ADSim HDF5(NDFileHDF5 단일 스레드) 대비 병렬 writer 구조 비교. VM1 측정치가 비교 기준선.
2. **beamline_ctl.sh 등록**: ADSim IOC를 정식 서비스로 (현재 수동 패턴). 운영 포트(5064/8001/8002)와의 격리 검증 포함.
3. **/ws/scan 노출**: `scan_engine/runner.py`의 디바이스 셋에 `get_adsim_detector()` 편입(옵션 플래그) → 브라우저에서 검출기 포함 스캔 큐잉. B1 queueserver 설계와 함께.
4. Bluesky 문서 스트림의 datum → 브라우저 썸네일/라이브 프리뷰 (B2 Tiled PoC와 연계).
