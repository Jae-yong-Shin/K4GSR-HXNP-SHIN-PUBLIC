# K4GSR BL10 Deployment Scripts

Linux production server deployment and management scripts.

## Architecture

```
Windows PC (dev)  -->  GitHub  -->  Linux Server (prod)  <-->  KOHZU Hardware
                                        |
                                   vLLM Workstation (NLP)
```

## Quick Start

```bash
# 1. Initial setup (run once on Linux server, as root)
sudo bash deploy/setup_production.sh

# 2. Start services
bash deploy/beamline_ctl.sh start

# 3. Check status
bash deploy/beamline_ctl.sh status

# 4. Deploy updates from GitHub
bash deploy/deploy.sh
```

## Files

| File | Purpose |
|------|---------|
| `config.env` | Central configuration (all scripts read this) |
| `setup_production.sh` | One-time server setup (packages, venv, systemd) |
| `deploy.sh` | GitHub pull + dependency update + restart |
| `beamline_ctl.sh` | Service management (start/stop/status/logs/health) |
| `systemd/k4gsr-ioc.service` | Soft IOC systemd service template |
| `systemd/k4gsr-server.service` | Main server systemd service template |

## Configuration

All settings are in `config.env`. No hardcoded values in any script.

Key settings:
- `SERVER_MODE`: `standalone` / `full` / `hybrid`
- `EPICS_IOC_ADDR_LIST`: EPICS CA address list
- `VLLM_HOST`: Remote vLLM workstation IP
- `INSTALL_DIR`: Where the repo is cloned on the server
- `SERVICE_USER`: Linux user that runs the services

## beamline_ctl.sh Commands

```bash
bash deploy/beamline_ctl.sh start    # Start IOC + server
bash deploy/beamline_ctl.sh stop     # Stop all
bash deploy/beamline_ctl.sh restart  # Stop + start
bash deploy/beamline_ctl.sh status   # Port checks + connectivity
bash deploy/beamline_ctl.sh logs     # Tail all logs
bash deploy/beamline_ctl.sh logs ioc # Tail specific log
bash deploy/beamline_ctl.sh health   # WebSocket + CA + vLLM checks
```

## Service Modes

| Mode | What runs | Use case |
|------|-----------|----------|
| `standalone` | server.py only (PVStore) | Development, no EPICS |
| `full` | soft_ioc + server.py (CA bridge + Bluesky) | Standard operation |
| `hybrid` | soft_ioc + KOHZU IOC + server.py | Real hardware connected |
