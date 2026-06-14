---
title: "B1 — bluesky-queueserver opt-in scan backend (separate-process RE Manager)"
category: tasks
status: current
updated: 2026-06-14
tags: [phase1, infra, server, bluesky, queueserver, scan, redis, re-manager, opt-in]
summary: "Phase 1 B1 (manuscript ¶31): bluesky-queueserver를 in-process RunEngine과 나란히 OPT-IN 스캔 백엔드로 도입. SCAN_BACKEND=qserver 모드 스위치, BlueskyRunner 인터페이스를 미러링하는 QueueServerRunner(별도 프로세스 RE Manager를 0MQ로 구동), /ws/scan 큐 액션 7종, 시작 프로파일(devices/plans 재사용) + 퍼미션 yaml. LOCAL E2E PASS(ophyd.sim + fakeredis). 운영 VM 비파괴 검증(격리 venv): 큐 기구 + EPICS 실장치 beam_check E2E PASS. 운영 활성화는 보류."
---
> **요약**: 기존 in-process RunEngine(`BlueskyRunner`)을 건드리지 않고, 별도 프로세스 RE Manager(bluesky-queueserver)를 OPT-IN 백엔드로 추가했다 (B1).
>
> **2026-06-14 운영 VM 비파괴 검증 — PASS**: 운영 `.venv`/서버(스캔 포트) 무접촉. 격리된 별도 평가 venv(qserver 0.0.24, tiled 0.2.11, bluesky 1.15.1)에서:
> - qserver 큐 기구 E2E (sim 경로, fakeredis, Linux killpg 정리): **ALL PASS** 13.5s, orphan 0.
> - qserver **EPICS 실장치** E2E (real soft IOC): 1차에는 미서빙 그룹(SAM/XBPM2/SCAN) 연결로 env_open이 타임아웃 → 두 가지 보강 후 **PASS** (beam_check이 큐를 통해 soft IOC에서 실행, `exit_status=completed`, 1.2s). 보강 ①`qserver_startup._console_script`: 콘솔스크립트(`start-re-manager`/`qserver-list-plans-devices`)를 `sys.executable` 기준 절대경로로 해석(PATH 미설정 launch 대응). ②`qserver_profile`: `QSERVER_EXCLUDE_DEVICES`(미서빙 device key 제외) + 연결 타임아웃 기본 2.0s(빠른 실패). 운영 활성화 시 `QSERVER_EXCLUDE_DEVICES="sample xbpm2 scanner"` + `QSERVER_CONNECT_TIMEOUT=2.0` 권장(config.env 주석 명기).
> - 운영 스캔 서버 프로세스는 검증 전후 동일, orphan 0.
>
> **회귀 기준**: `SCAN_BACKEND` 미설정 시 server.py는 정확히 종전과 동일하게 `BlueskyRunner`를 구성한다 (zero behavioral change).

# B1 — bluesky-queueserver 도입

## 0. 무엇을, 왜

manuscript ¶31이 "planned path"로 명시한 항목: 별도 프로세스 RunEngine Manager +
allowed-plans/devices registry. 운영 빔라인에서 스캔 큐잉/권한/감사 경로를 리허설하기
위함. **회귀 리스크를 0으로** 만들기 위해 in-process 경로는 그대로 두고, 새 백엔드를
env 스위치로 opt-in 하게 했다. 이 트랜치는 **LOCAL 구현 + E2E**까지이며, 운영 VM 설치는
별도 정수(integration) 세션이 수행한다 (§7 명령 명시).

## 1. 설계 (Design)

```
브라우저 /ws/scan  ──┐
NLP 에이전트       ──┼─▶ server.py: bluesky_runner (백엔드 불문 단일 변수)
                     │        ├─ SCAN_BACKEND=inprocess (기본) → BlueskyRunner  (종전과 100% 동일)
                     │        └─ SCAN_BACKEND=qserver         → QueueServerRunner
                     │                                              │ 0MQ (REManagerAPI.zmq)
                     │                                              ▼
                     │                                   start-re-manager (별도 프로세스)
                     │                                     ├─ RE Worker (multiprocessing child)
                     │                                     ├─ startup profile: scan_engine.qserver_profile
                     │                                     │    (= in-process와 동일 devices/plans)
                     │                                     └─ Redis (실서버 또는 fakeredis TCP)
```

### 핵심 파일

| 파일 | 역할 |
|------|------|
| `server/scan_engine/qserver_runner.py` | `QueueServerRunner` — `BlueskyRunner`의 public 인터페이스를 **그대로 미러링**(start/status/state/submit/submit_async/abort/pause/resume/list_plans/shutdown) + 큐 네이티브 메서드. RE Manager를 0MQ로 구동 |
| `server/scan_engine/qserver_startup.py` | RE Manager 기동 헬퍼: existing_plans_and_devices.yaml 생성, `start-re-manager` argv 빌드, fakeredis TCP 서버 기동/실 Redis 도달성 체크 |
| `server/scan_engine/qserver_profile/__init__.py` | RE Manager **시작 프로파일**(importable 모듈). `RE` + devices + plans 정의. in-process 엔진과 **동일한 `create_devices()` + `scan_engine.plans`** 재사용 |
| `server/scan_engine/qserver_profile/user_group_permissions.yaml` | 로컬 PoC용 **permissive** 퍼미션 (primary 그룹에 전체 plan/device 허용) |
| `server/constants.py` | `SCAN_BACKEND_DEFAULT`, `QSERVER_ZMQ_PORT/INFO_PORT`, `QSERVER_REDIS_PORT`, poll/timeout |
| `server/requirements_qserver.txt` | **격리된 옵션 deps** (production `requirements.txt` 핀셋 미수정) |
| `server/test_qserver_e2e.py` | 실행 가능한 blocking-assert E2E + zero-regression 유닛 |

### 인터페이스 패리티 (검증됨)

`QueueServerRunner`는 `BlueskyRunner`의 **모든 public 메서드를 구현**한다 (누락 0건).
추가로 큐 네이티브: `env_open/env_close, queue_add/queue_start/queue_stop/queue_clear/queue_get, history_get, stop`.
`status()`는 `BlueskyRunner.status()`와 **동일한 키**(state/plan/uid/event_count/last_error/devices_connected/auto_save/data_dir)에
`'backend':'qserver'` + `'queue':{manager_state, items_in_queue, items_in_history, running_item_uid, re_state, ...}`를 더한다.

### submit (single-plan 패리티) 매핑

| BlueskyRunner | QueueServerRunner (RE Manager 호출) |
|---------------|-------------------------------------|
| `submit(plan, **p)` | `environment_open`(필요 시) → `item_add(BPlan(plan, **p))` → `queue_start` |
| `abort()` | `queue_stop` → (RE running이면) `re_pause` → `wait_for_idle_or_paused` → `re_abort` (실패 시 `re_halt` 폴백) |
| `pause()` | `re_pause` |
| `resume()` | `re_resume` |

> **abort 주의**: RE Manager의 `re_abort/re_stop/re_halt`는 **PAUSED 상태의 RunEngine**에만 작동한다. 따라서 실행 중 즉시 중단은 반드시 `re_pause → re_abort` 순서. (이 점을 처음 놓쳐서 abort가 긴 plan의 자연 종료를 21.9s 기다렸고, 수정 후 2.0s 내 실제 중단 확인.)

### `state` 매핑 (qserver manager_state → idle|connecting|running|paused|error)

`idle→idle`, `paused→paused`, `executing_queue/executing_task/starting_queue→running`,
`creating_environment/closing_environment/destroying_environment/initializing→connecting`.
도달 불가/호출 예외 시 `last_error` 보존 + `error`.

## 2. 모드 스위치 (server.py)

- `SCAN_BACKEND` env (기본 `'inprocess'`, `constants.SCAN_BACKEND_DEFAULT`)를 **task-start 시점**(config.env 로드 후)에 읽는다.
- **`inprocess`(또는 미설정)**: `BlueskyRunner(ws_callback=broadcast_scan_event, connect_timeout=_bs_timeout)` — 종전 코드 블록 그대로. **회귀-critical 경로, 무변경.**
- **`qserver`**: 동일 시그니처로 `QueueServerRunner` 구성. deps 없으면 `sys.exit(1)`로 명확히 실패.
- 변수명 `bluesky_runner` 유지 → `scan_handler`는 백엔드-불문.
- `deploy/config.env`에 `SCAN_BACKEND="inprocess"` (기본 OFF, 문서화).

## 3. /ws/scan 액션 (추가)

기존 `submit/abort/pause/resume/status/list_plans/list_history/get_scan_data/download_h5`는 **그대로** `bluesky_runner`로 라우팅(무변경).
아래 큐 액션 7종 추가. 활성 백엔드가 큐 메서드를 구현하지 않으면(= in-process) **큐를 가짜로 만들지 않고** 명확한 안내 메시지 반환.

| Action | 필드 | 응답 type | 백엔드 |
|--------|------|-----------|--------|
| `queue_add` | `plan_name`, `params` | `queue_item_added` | qserver |
| `queue_start` | (없음) | `queue_started` | qserver |
| `queue_stop` | (없음) | `queue_stopped` | qserver |
| `queue_clear` | (없음) | `queue_cleared` | qserver |
| `queue_status` | (없음) | `queue_status` | qserver |
| `queue_get` | (없음) | `queue_contents` | qserver |
| `history` | (없음) | `queue_history` | qserver |

- in-process 백엔드에서 위 액션 호출 시:
  `{"type":"scan_error", "message":"queue actions require SCAN_BACKEND=qserver (active backend has no queue)", "action":"<action>"}`.
- 게이팅 기준: 런너가 해당 메서드를 `hasattr` 하고 `status()['backend']=='qserver'` 일 때만 실행.

### ws_callback으로 스트리밍되는 것 (이 트랜치 범위)

백그라운드 status 폴러(0.5s)가 RE Manager `status()`를 diff하여, **브라우저가 이미 소비하는 동일한 `{'type':'scan_event', ...}` 봉투**로 다음을 emit한다:
- `doc_type='start'` — 큐 아이템 실행 시작(manager_state→executing/running_item_uid 등장),
- `doc_type='stop'`  — history에 새 아이템 등장(run 종료),
- `doc_type='status'` — 큐 길이/manager_state 전이.

**스트리밍되지 않는 것(문서화된 후속)**: per-event Bluesky 문서(descriptor/event)는 B1에서 forward하지 않는다. RE Manager가 별도 프로세스이고 매 이벤트 문서를 0MQ console로 재방출하는 것은 이 PoC에 과중하다. 큐 UI에는 start/stop/status 전이로 충분하며, full document streaming(0MQ console_monitor 구독 → descriptor/event 파싱)은 후속 작업.

## 4. 시작 프로파일 (startup profile)

- importable 모듈 `scan_engine.qserver_profile` 사용 (**`--startup-dir` 아님**).
  - **Windows 함정**: `--startup-dir` 로더는 `__file__`을 백슬래시 경로로 패치하는데 `C:\Users` 의 `\U`가 unicodeescape SyntaxError를 유발한다. `--startup-module`은 이 패치를 거치지 않아 안전. (실측으로 확인.)
- 디바이스 경로 토글 `QSERVER_DEVICE_PATH`:
  - `epics`(기본): `scan_engine.devices.create_devices` + `connect_devices` 재사용 → in-process 엔진과 **완전히 동일한 ophyd 디바이스** → allowed-plans/devices가 일치. **운영 경로.**
  - `sim`: `ophyd.sim` det/motor (EPICS 불필요). Windows에서 EPICS-CA가 불안정할 때 **큐 메커니즘 증명**용. (full real-device E2E는 운영 VM으로 deferred.)
- plan 래퍼: 프로젝트 plan들은 `devices` dict를 첫 인자로 받지만 qserver는 dict를 전달 못 하므로, 모듈 레벨 `DEVICES`를 클로저로 잡는 **얇은 래퍼**를 plan 이름 그대로 노출(`energy_scan` → `submit('energy_scan', ...)`와 1:1).
- `existing_plans_and_devices.yaml`은 기동 시 `qserver-list-plans-devices --startup-module ...`로 **현재 프로파일에 맞춰 재생성**(항상 활성 디바이스 경로와 일치).
- 퍼미션: `user_group_permissions.yaml` (primary 그룹 전체 허용). 하드닝(allow-list/sandbox/auth)은 B4(시설 보안 정책)로 deferred.

## 5. E2E 결과

- 스크립트: `server/test_qserver_e2e.py` (`python server/test_qserver_e2e.py`, exit 0 == 전 단계 PASS).
- **디바이스 경로**: `ophyd.sim` (det/motor). **Redis**: fakeredis `TcpFakeServer` (별도 프로세스 RE Manager가 실 TCP로 접속 — 프로세스 간 동작 확인). → 큐 메커니즘 결정론적 증명. **full real-device(epics + soft IOC) E2E는 운영 VM으로 deferred.**
- 결과 (로컬, 2026-06-14, Python 3.11.4 Windows):

| 단계 | 결과 | timing |
|------|------|--------|
| zero-regression (SCAN_BACKEND 미설정 → BlueskyRunner, status 원형 키) | PASS | — |
| 1. `start()` (RE Manager 서브프로세스 + fakeredis 기동, API 응답) | PASS | 12.6 s |
| 2. `env_open()` → worker_environment_exists=True | PASS | 1.5 s |
| 3. `queue_add('count', det, num=3)` → items_in_queue=1 | PASS | <0.1 s |
| 4. `queue_start()` → 완료까지 폴 → history 1건 exit_status='completed' | PASS | 0.6 s |
| 5. abort: 긴 count(num=200) add → start → `abort()` → idle 복귀, history exit=aborted/failed | PASS | 2.0 s (실제 중단, 자연종료 대기 아님) |
| 6. `env_close()` → worker_environment_exists=False | PASS | 0.9 s |
| 7. `shutdown()` → 서브프로세스+fakeredis 제거, **orphan 0** | PASS | 0.4 s |

전체 ~18.6 s. **ALL E2E ASSERTIONS PASSED.**

> **수정한 버그(중요)**: RE Manager의 RE Worker는 multiprocessing child로 돈다. 부모(`start-re-manager`)에 `terminate()`만 하면 Windows에서 워커가 **orphan**으로 남아 0MQ/redis 포트와 환경을 잡고 있었다 (다음 기동 시 `items_in_history` 누수). `_kill_process_tree`(Windows `taskkill /F /T`, POSIX `killpg`)로 트리 전체를 정리하도록 수정 → orphan 0 확인.

### zero-regression assertion 결과

`SCAN_BACKEND` 미설정 시 server.py 구성 분기가 **`BlueskyRunner`를 산출**하고, `status()`가 원형 키 집합(`state/plan/uid/event_count/last_error/devices_connected/auto_save/data_dir`)을 가지며 **`'backend'` 키가 없음**을 단언 → PASS. (live in-process 스캔은 soft IOC 불요 — 구성 분기만 검증.)

## 6. 한계 (Limitations)

- **fakeredis는 LOCAL/PoC 전용**: 재시작 간 영속성 없음. 운영은 실 `redis-server` 사용(`QSERVER_USE_FAKEREDIS=0`).
- **per-event document streaming 미구현**(§3). start/stop/status 전이만 forward.
- **sim 경로 E2E만 실행**: full real-device(epics + caproto soft IOC) E2E는 운영 VM으로 deferred.
- 퍼미션 permissive(하드닝 = B4).
- fakeredis 종료 시 socketserver의 무해한 "connection reset" 트레이스가 stderr에 한 줄 찍힐 수 있음(teardown noise, assertion 이후).
- list_plans는 환경이 열려 있어야 plan 목록 반환(닫혀 있으면 빈 리스트).

## 7. 운영 VM ROLLOUT — **DEFERRED (정수 세션이 실행)**

> 이 트랜치는 운영 VM을 **건드리지 않는다**. 아래는 정수 세션용 참조 절차(호스트/경로는 배포 환경에 맞춰 치환).

### 7.1 사전 조건 (Ubuntu 22.04)

```bash
# (a) 옵션 deps 설치 (production 핀셋과 격리된 파일)
cd <PROJECT_DIR>                   # 운영 VM의 코드 체크아웃 경로
source server/.venv/bin/activate   # 또는 프로젝트 venv 경로
pip install -r server/requirements_qserver.txt

# (b) 실 Redis 서버 (apt, sudo 필요)
sudo apt-get update && sudo apt-get install -y redis-server
sudo systemctl enable --now redis-server
redis-cli ping                    # -> PONG. qserver는 QSERVER_REDIS_PORT를 쓰므로
                                  # config.env에 맞춰 redis 포트를 맞추거나
                                  # QSERVER_REDIS_PORT를 redis 포트에 맞출 것.

# (c) caproto soft IOC가 떠 있어야 epics 디바이스 경로가 연결됨
#     (beamline_ctl.sh가 이미 기동: soft_ioc.py). 확인:
caget BL10:DCM:Theta.RBV 2>/dev/null || echo "soft IOC 미기동 → beamline_ctl.sh start"
```

### 7.2 활성화 (env만 — 새 systemd 서비스 불필요)

RE Manager는 **server.py가 `QueueServerRunner`를 통해 서브프로세스로 기동/정리**하므로
별도 beamline_ctl 서비스 등록이 **필수는 아니다**. `deploy/config.env`에서 백엔드만 전환:

```bash
# deploy/config.env 편집
SCAN_BACKEND="qserver"
# (선택) QSERVER_DEVICE_PATH="epics"   # 기본 epics
# (선택) QSERVER_USE_FAKEREDIS="0"     # 실 redis 강제
# (선택) QSERVER_REDIS_PORT=...        # apt redis 포트에 맞출 때
```

`beamline_ctl.sh`가 `config.env`를 env로 export하여 `server/server.py`를 기동하므로,
재시작만 하면 백엔드가 전환된다:

```bash
bash deploy/beamline_ctl.sh restart
bash deploy/beamline_ctl.sh status
# 서버 로그에서 기대: "Initializing scan engine (backend=qserver, RE Manager)..." +
#                     "bluesky-queueserver RE Manager ready"
```

### 7.3 (선택) 명시적 서비스 블록 — `start-re-manager`를 beamline_ctl이 직접 관리하고 싶을 때

server.py가 서브프로세스로 RE Manager를 관리하는 것이 기본이지만, **운영상 RE Manager를
독립 수명주기로 두고 싶다면** `deploy/beamline_ctl.sh`에 아래 패턴으로 서비스를 추가하고
server.py는 기존 0MQ 주소로 접속만 하게 할 수 있다 (이 경우 QueueServerRunner.start()의
서브프로세스 기동을 건너뛰는 모드가 추가로 필요 — 후속 작업). 참조 명령:

```bash
# 큐서버 시작 (cmd_start의 server 블록과 동형: nohup + PID 파일 + 로그)
QS_LOG="${LOG_DIR}/re_manager.log"; QS_PID="${PID_DIR}/re_manager.pid"
nohup bash -c "cd '$INSTALL_DIR' && PYTHONPATH='$INSTALL_DIR/server' \
  start-re-manager \
    --startup-module scan_engine.qserver_profile \
    --zmq-control-addr tcp://127.0.0.1:60615 \
    --zmq-info-addr tcp://127.0.0.1:60625 \
    --zmq-publish-console ON \
    --redis-addr 127.0.0.1:6379 \
    --user-group-permissions server/scan_engine/qserver_profile/user_group_permissions.yaml \
    --existing-plans-devices server/data/qserver_existing_plans_and_devices.yaml" \
  >> "$QS_LOG" 2>&1 &
echo $! > "$QS_PID"

# 큐서버 중지 (cmd_stop의 서비스 루프에 're_manager' 추가 + 트리 정리)
pkill -9 -f "start-re-manager" 2>/dev/null || true
```

> 단, 7.2(env 전환)가 권장 경로다. 7.3은 RE Manager 독립 운영이 필요할 때만.

## 8. 진행 현황

| 일자 | 상태 |
|------|------|
| 2026-06-14 | B1 LOCAL 구현 + E2E PASS(ophyd.sim + fakeredis), zero-regression PASS, 운영 VM 비파괴 검증(격리 venv, EPICS-path beam_check PASS) | 완료(LOCAL+검증) |
| (정수 세션) | 운영 VM: requirements_qserver 설치 + redis-server + SCAN_BACKEND=qserver 전환 + epics-path 운영 적용 | 대기 |
| (후속) | per-event document streaming(0MQ console_monitor), 브라우저 큐 UI | 예정 |
