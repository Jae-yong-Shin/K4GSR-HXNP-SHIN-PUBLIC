---
title: "XBPM2 T4U IOC Setup Guide"
category: knowledge
status: current
updated: 2026-03-21
tags: [xbpm2, epics, ioc, quadem, sydor, hardware]
summary: "VM1에서 Sydor T4U quadEM EPICS Direct IOC를 빌드하고 실행하는 절차"
---
# XBPM2 T4U quadEM IOC Setup (VM1)

## Prerequisites
- EPICS Base 7.0.8.1 (already installed: `~/epics-R7.0.8.1`)
- VM1 eth3: <YOUR_VM_IP>/24 (SW4 네트워크, T4U at <YOUR_DEVICE_IP>)
- T4U가 Fixed IP <YOUR_DEVICE_IP>로 설정되어 있어야 함

## 1. synApps + quadEM 빌드

```bash
cd ~

# 1.1 필요 패키지 설치 (이미 KOHZU IOC 빌드 시 대부분 설치됨)
sudo apt-get install -y libreadline-dev re2c

# 1.2 synApps 어셈블 스크립트 다운로드
wget https://raw.githubusercontent.com/EPICS-synApps/support/master/assemble_synApps.sh

# 1.3 EPICS_BASE 경로 설정
# assemble_synApps.sh 열어서 EPICS_BASE 줄을 다음으로 수정:
#   EPICS_BASE=/home/<USER>/epics-R7.0.8.1
chmod +x assemble_synApps.sh
# nano assemble_synApps.sh  # EPICS_BASE 경로 수정

# 1.4 실행 (전체 synApps 다운로드 + 빌드 준비)
./assemble_synApps.sh full

# 1.5 quadEM을 Sydor 버전으로 교체
cd synApps/support
cd quadEM && git checkout master && cd ..

# 1.6 configure/RELEASE 수정
# quadEM/configure/RELEASE에서:
#   QUADEM = $(SUPPORT)/quadEM
#   CAMAC, MOTOR, DXP, DXPSITORO, GALIL, SOFTGLUE, SOFTGLUEZYNC, XPRESS3, OPCUA 주석처리

# 1.7 asyn CONFIG_SITE에서 TIRPC=YES 설정
# <asyn dir>/configure/CONFIG_SITE 열어서 TIRPC=YES 주석 해제

# 1.8 빌드
cd ~/synApps/support
make release
make
```

## 2. IOC 설정

```bash
cd ~/synApps/support/quadEM/iocBoot/iocT4UDirect_EM
```

### T4UDirect_EM.cmd 수정

```
# PV prefix: BL10:XBPM2:
epicsEnvSet("PREFIX", "BL10:")
epicsEnvSet("RECORD", "XBPM2:")

# T4U IP address (SW4 network)
epicsEnvSet("QTHOST", "<YOUR_DEVICE_IP>")

# Base port (default is fine)
# epicsEnvSet("QTBASEPORT", "...")
```

### st.cmd 수정

첫 줄이 quadEMTestApp 바이너리를 가리키는지 확인:
```
#!../../bin/linux-x86_64/quadEMTestApp
```

## 3. IOC 실행

```bash
cd ~/synApps/support/quadEM/iocBoot/iocT4UDirect_EM

# 백그라운드 실행 (stdin EOF 방지)
nohup bash -c "tail -f /dev/null | ./st.cmd" > ~/xbpm2_ioc.log 2>&1 &

# 로그 확인
tail -f ~/xbpm2_ioc.log
```

## 4. PV 확인

```bash
# .venv 활성화
source ~/.venv/bin/activate

# PV 읽기 테스트
export EPICS_CA_ADDR_LIST="127.0.0.1"
export EPICS_CA_AUTO_ADDR_LIST=NO

caproto-get BL10:XBPM2:Current1 BL10:XBPM2:Current2 BL10:XBPM2:Current3 BL10:XBPM2:Current4
caproto-get BL10:XBPM2:PositionX BL10:XBPM2:PositionY
caproto-get BL10:XBPM2:SumAll
caproto-get BL10:XBPM2:Range
```

## 5. CA Bridge 연동

server.py 시작 시 XBPM2 IOC도 자동 연결:
```bash
python server/server.py --ca-bridge --bluesky --exclude-groups SAM XBPM2
```

`EPICS_CA_ADDR_LIST`에 XBPM2 IOC 포트 추가 필요:
```
EPICS_IOC_ADDR_LIST="127.0.0.1:5070 127.0.0.1:5072 127.0.0.1:5064"
```

## Troubleshooting

### IOC 빌드 실패
- `re2c` 패키지 누락: `sudo apt-get install re2c`
- `TIRPC` 관련: asyn CONFIG_SITE에서 `TIRPC=YES` 설정 확인

### PV 연결 안됨
- T4U 전원 확인 + ping <YOUR_DEVICE_IP>
- IOC 로그에서 "Connected to T4U" 메시지 확인
- CA ADDR_LIST에 IOC 포트 포함되었는지 확인

### 멀티 IOC CA 문제
- KOHZU IOC 때와 동일한 패턴: 명시적 유니캐스트 사용
- soft_ioc(5064) 먼저 시작 → KOHZU(5070) → XBPM2(5072) 순서
