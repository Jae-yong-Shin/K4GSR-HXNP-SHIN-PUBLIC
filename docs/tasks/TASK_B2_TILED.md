---
title: "B2 — Tiled data-access PoC (local serve + programmatic read-back)"
category: tasks
status: current
updated: 2026-06-14
tags: [phase1, infra, server, tiled, data-access, hdf5, nexus, scan, opt-in, poc]
summary: "Phase 1 B2 (manuscript ¶39): 기존 NeXus/HDF5 스캔 출력을 Tiled로 serve하는 LOCAL PoC. tiled serve config(pyobject HDF5 tree) + tiled.client from_uri 프로그래매틱 read-back + E2E(Tiled vs h5py 기계정밀 일치, 오펀 0). opt-in/default-OFF, production server.py 무관. 운영배포·facility 인증은 B4로 유보. Tiled 0.2.3 검증."
---
> **요약**: 빔라인이 이미 쓰고 있는 NeXus/HDF5 스캔 출력(`server/data/writer.py:NexusWriter`)을 Tiled 서버로 read-only serve하고, `tiled.client`로 프로그래매틱하게 다시 읽어오는 LOCAL PoC (B2).
> **관련 작업**: Phase 1 roadmap §4 B2 (원천: JSR manuscript ¶39), §5(운영배포·인증은 B4 유보).
> **범위 한정**: PoC + 클라이언트 데모 + E2E 까지만. 운영 VM 배포 없음, facility 인증 없음.

# B2 — Tiled 데이터 접근 PoC

## 0. 무엇을, 왜

manuscript ¶39는 Tiled를 통한 데이터 접근을 future work로 명시한다. 운영 배포는 facility
인증 정책(B4) 확정을 기다리므로, Phase 1에서는 **기존 NeXus/HDF5 스캔 출력을 Tiled로
serve하고 프로그래매틱하게 read-back하는 PoC**만 만든다 (roadmap §B2, §5).

핵심 가치는 "serve + 클라이언트 read-back 데모"이지 production 배선이 아니다. 따라서:
- 항상-켜진 엔드포인트를 production `server.py`에 추가하지 않는다 (standalone 런처).
- opt-in / default-OFF (`constants.TILED_ENABLED_DEFAULT=False`).
- 별도 optional deps (`server/requirements_tiled.txt`) — production pin set 미수정.

## 1. 발견한 실제 스캔 출력 포맷

스캔 출력은 Bluesky RunEngine이 `server/scan_engine/runner.py`에서 자동 저장하며,
실제 writer는 `server/data/writer.py:NexusWriter`다. 파일명 `YYYYMMDD_HHMMSS_<plan>_<uid8>.h5`,
저장 위치 `server/data/scans/`.

on-disk 구조 (NeXus):

```
/ (NXroot)                       attrs: NX_class, creator, file_name, file_time
  entry/ (NXentry)               attrs: scan_type, uid, num_points, start/end_time, ...
    data/ (NXdata)
      <column>      1-D f64 extensible  (sample_x, sample_y, I0, It, Fe_Ka, ...)
      xrf_spectra   2-D int32 (n_events, n_channels)
      energy_axis   1-D f64 (raster 사전할당 경로일 때)
    instrument/ (NXinstrument)
      monochromator/energy, source/{name,type,energy}, detector/, motors/
    sample/ (NXsample)
    scan/             x, y 위치 배열 (사전할당 경로)
```

라이브 스캔 경로(runner)는 이벤트마다 `create_extensible_1d`로 컬럼을 만들고
`append_value`로 누적, XRF 스펙트럼은 `xrf_spectra` 2-D에 행 추가, 종료 시 `finalize`.
`make_sample_scan.py`는 **이 경로를 그대로** 구동해 동일 구조의 파일을 만든다(소스 한 곳=NexusWriter).

## 2. 무엇을 serve했는가 (네이티브, 무변형)

Tiled 내장 HDF5 어댑터(`tiled.adapters.hdf5.HDF5Adapter`, 기본 mimetype
`application/x-hdf5` — `.h5`/`.hdf5`/`.nxs` 모두 매핑)가 위 NeXus 트리를 **그대로** 수용한다.
파일 변형/복사/재구조화 없음. `/entry/data/<column>`이 그대로 array 노드로, `/entry` attrs가
그대로 metadata로 노출된다.

### 어댑터/트리 구성

`tiled serve config`의 트리로 **pyobject 트리**를 쓴다:

- `server/data_access/tiled_tree.py:scans_tree(directory)` → 디렉터리의 각 스캔 파일을
  `HDF5Adapter.from_uris(file://.../scan.h5)`에 매핑한 `MapAdapter` 반환.
- 설정: `server/data_access/tiled_config.yml`
  ```yaml
  trees:
    - path: "/"
      tree: data_access.tiled_tree:scans_tree
      args:
        directory: "${SCANS_DIR}"      # 런처가 절대경로로 치환
  authentication:
    allow_anonymous_access: true        # 익명 READ-ONLY (로컬 PoC)
    single_user_api_key: "${API_KEY}"   # 런처가 매 실행마다 생성
  uvicorn:
    host: "${HOST}"                     # 127.0.0.1 (loopback only)
    port: ${PORT}
  ```

### 왜 SQL `catalog` + `tiled register`가 아니라 pyobject 트리인가 (정확한 gap)

검증한 Tiled 0.2.3에서 정석 디렉터리 플로우(`catalog` 트리 + `tiled register <url> <dir>`)는
**중첩 HDF5 container data-source를 register 단계에서 거부**한다:

```
POST /api/v1/register/ -> HTTP 422
[{'type': 'model_attributes_type', 'loc': ['body'],
  'msg': 'Input should be a valid dictionary or object to extract fields from',
  'input': '{"ancestors":[""],"metadata":{"NX_class":"NXroot",...},
            "structure_family":"container",
            "data_sources":[{"structure_family":"container",
                             "structure":{"keys":["entry"]}, ... "mimetype":"application/x-hdf5"}]}'}]
```

CLI(`tiled register`)와 Python API(`tiled.client.register.register`) 둘 다 동일 422.
원인은 register 엔드포인트가 `structure:{keys:[...]}` 형태의 container data-source 본문을
받지 못하는 0.2.3 직렬화 한계다(파일 자체나 우리 레이아웃 문제가 아니라 catalog-register 경로 버그).

→ **pyobject `MapAdapter` 경로는 catalog DB/register를 우회**하면서도 **동일한 네이티브 파일을
충실히 serve**한다. 따라서 PoC는 pyobject 트리를 채택했다. 네이티브 catalog 경로가 필요해지면
(B4 운영 배포 시) ① Tiled 상위 버전에서 register 422 해소 여부 재확인, 또는 ② 파일 등록을
container가 아니라 leaf 단위로 하는 어댑터 옵션 사용을 검토할 것 (아래 §6 참고).

폴백 불필요: 네이티브 HDF5를 무변형으로 serve했고 read-back이 기계정밀로 일치하므로
"재구조화 복사본/배열 디렉터리" 폴백은 쓰지 않았다.

## 3. 클라이언트 read-back 결과 (deliverable)

`server/data_access/tiled_demo.py`: `from_uri`로 접속 → catalog 엔트리(런) 나열 → 한 런 열기
→ `/entry/data` 컬럼들을 numpy로 read → 요약 출력. 예시 출력:

```
Tiled catalog: 1 run(s) -> ['20260614_141959_raster_scan_b2tiled']
--- run: 20260614_141959_raster_scan_b2tiled ---
  scan_type = raster   uid = b2tiled0   num_points = 48
  /entry/data columns: ['Fe_Ka','I0','It','sample_x','sample_y','xrf_spectra']
    Fe_Ka        shape=(48,)     dtype=float64  min=1.106 max=829.4 mean=182.7
    I0           shape=(48,)     dtype=float64  ...
    xrf_spectra  shape=(48, 256) dtype=int32    sum=27539 (2-D)
Programmatic read-back OK: arrays are plain numpy (no HDF5 parsing on the client).
```

## 4. E2E 결과 + 타이밍

`server/test_tiled_e2e.py` (standalone 실행 + pytest 둘 다). 단계: 실제 스캔 파일 생성
(NexusWriter 라이브 경로) → `tiled serve config` 서브프로세스 spawn → 클라이언트 ≥1 런 나열
→ 알려진 데이터셋 numpy read → **Tiled-over-HTTP 값을 h5py-direct 소스 값과 대조** →
metadata 보존 확인 → teardown + 오펀 0 단언 → 생성 파일 정리 → 타이밍 출력.

검증 환경: Windows, Python 3.11.4, Tiled 0.2.3.

| 항목 | 결과 |
|------|------|
| catalog 런 수 | ≥1 (E2E는 자기 생성 런 타깃) |
| float 컬럼 (sample_x/y, I0, It, Fe_Ka) max abs diff | **0.000e+00** (tol 1e-9) |
| `xrf_spectra` int32 | **exact match** (shape+dtype 동일) |
| NeXus `/entry` metadata (scan_type/uid/num_points) | 보존 |
| 오펀 프로세스 (teardown 후) | **0** |
| 생성 파일 정리 | 예 |
| 생성 파일 크기 | ~0.145 MB (48 events × 256 ch) |

타이밍(초): generate 0.03 / server_start ~2.8 / client_read+assert ~1.1 / teardown ~0.15 /
**total ~4.1**. pytest: `1 passed in ~4.1s`.

> df 노트: PoC 생성 파일은 작다(<1 MB)라 디스크 영향 무시 가능. >50 MB 생성 시 E2E가
> teardown에서 제거하며 df-style 노트를 출력하도록 가드했다.

## 5. 설치 / 실행

```bash
# 설치 (production requirements.txt와 분리된 optional deps)
pip install -r server/requirements_tiled.txt
#   = tiled[server,client]>=0.2.3,<0.3 + dask (HDF5 어댑터 필수) + h5py/numpy/psutil
#   검증된 정확 버전: tiled 0.2.3, dask 2026.6.0, h5py 3.15.1, numpy 2.4.2

# 샘플 스캔 1개 생성 (없으면)
python -m data_access.make_sample_scan          # cwd = server/

# 로컬 serve (loopback, 익명 READ-ONLY). Ctrl-C 종료.
python -m data_access.tiled_serve --port 8010    # cwd = server/

# 클라이언트 read-back 데모 (self-host 또는 --url 접속)
python -m data_access.tiled_demo --ensure-sample

# E2E
python server/test_tiled_e2e.py        # 또는: pytest server/test_tiled_e2e.py -v
```

## 6. 한계 / 유보 (명시)

- **facility 인증 = B4 유보.** 여기서는 익명 READ-ONLY + loopback 바인드뿐이다. 인증/sandbox/
  접근정책은 facility 보안 정책 확정 후 B4에서 구현한다 (roadmap §5). 이 설정을 공유 호스트/운영 VM에
  그대로 배포 금지.
- **LOCAL only.** 127.0.0.1 바인드. 네트워크 노출 없음.
- **opt-in / default-OFF.** production `server.py`는 이 모듈을 import하지도 시작하지도 않는다.
- **catalog-register HDF5 gap (Tiled 0.2.3).** §2 참조 — 정석 SQL catalog register 경로가
  중첩 HDF5 container를 422로 거부. PoC는 pyobject 트리로 우회. 운영(B4)에서 네이티브 catalog가
  필요하면 상위 Tiled 버전 재확인 또는 leaf-단위 등록 옵션 검토.
- **per-event 문서 스트리밍 아님.** Tiled는 *저장된 결과 파일*을 serve한다(라이브 이벤트 스트림이
  아님; 그건 /ws/scan + B3 event-push의 역할).

## 7. 운영 배포(B4)로 유보된 절차 (정수 세션용)

> 아래는 **지금 실행하지 않는다**. B4(인증 정책 확정) 후 정수 세션이 수행한다.
> 운영 VM 코드 병합 + facility 인증 설계 확정이 선결조건. 호스트/경로는 배포 환경에 맞춰 치환.

```bash
# (전제) Tiled PoC 코드가 운영 VM으로 병합/pull된 상태. 운영 VM 코드 경로 = <PROJECT_DIR>.

# 1. optional deps 설치 (운영 VM .venv, Python 3.11)
cd <PROJECT_DIR> && source .venv/bin/activate
pip install -r server/requirements_tiled.txt

# 2. (B4) 인증 설정 추가 — tiled_config.yml의 authentication 블록을 facility 인증으로 교체.
#    allow_anonymous_access를 끄고 authenticator(예: PAM/OIDC) + tiled_admins + secret_keys 추가.
#    (현재 PoC config는 익명 READ라 운영 부적합 — B4에서 교체.)

# 3. serve 디렉터리를 운영 실제 스캔 출력 경로로 지정 + loopback 외 바인드 정책 결정(B4).
#    예 (여전히 loopback, 정수 세션이 reverse-proxy/인증 뒤에 둘 것):
cd <PROJECT_DIR>/server && source ../.venv/bin/activate
nohup python -m data_access.tiled_serve \
  --scans-dir <PROJECT_DIR>/server/data/scans \
  --host 127.0.0.1 --port 8010 > tiled_b2.log 2>&1 &

# 4. 스모크: 클라이언트 read-back (API key는 런처 로그에서 확인)
python -m data_access.tiled_demo --url http://127.0.0.1:8010 --api-key <KEY-from-log>

# 5. 종료 (오펀 없이): 런처를 정상 종료(SIGINT)하면 _kill_process_tree가 트리 회수.
#    수동: pkill -f "data_access.tiled_serve" ; pkill -f "tiled serve config"
```

> 주의: deploy/beamline_ctl.sh 서비스로 등록하는 것도 B4 결정사항(인증·노출 정책 확정 후).
> 현재는 서비스 미등록 — 항상-켜짐 금지.

## 8. 파일

| 파일 | 역할 |
|------|------|
| `server/data_access/tiled_tree.py` | pyobject 트리 빌더 (`scans_tree` → MapAdapter of HDF5Adapter) |
| `server/data_access/tiled_config.yml` | `tiled serve config` 템플릿 (익명 READ, loopback) |
| `server/data_access/tiled_serve.py` | `TiledServer` 런처 (서브프로세스 + readiness + reaper, opt-in) |
| `server/data_access/tiled_demo.py` | 클라이언트 read-back 데모 (deliverable) |
| `server/data_access/make_sample_scan.py` | NexusWriter 라이브 경로로 실제 스캔 파일 생성 |
| `server/test_tiled_e2e.py` | E2E (Tiled vs h5py 기계정밀, 오펀 0, 타이밍) |
| `server/requirements_tiled.txt` | 격리된 optional deps |
| `server/constants.py` | `TILED_*` 상수 추가 |
