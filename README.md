# K4GSR Hard X-ray Nanoprobe Virtual Beamline

**Korea-4GSR ID10 Hard X-ray Nanoprobe (HXNP)** virtual beamline control system with physics simulation, virtual experiments, NLP chat, and EPICS integration.

## Quick Start

### One-Click Start (Windows)

1. Download or clone this repository
2. Double-click one of the start scripts:

| Script | Mode | What it runs |
|--------|------|-------------|
| **`start_server.bat`** | Standalone | WebSocket server + NLP chat + browser |
| **`start_server_full.bat`** | Full | Above + EPICS Soft IOC + Bluesky scans |

3. On first run, the script will automatically:
   - Find (or install) Python 3.11
   - Create an isolated virtual environment (`.venv`)
   - Install all dependencies
   - Guide you through NLP chat setup (API key)
   - Start the server and open the browser

### One-Click Start (Mac/Linux)

```bash
chmod +x start_server.sh

# Standalone mode:
./start_server.sh

# Full mode (EPICS + Bluesky):
./start_server.sh --full
```

### Manual Start

```bash
# 1. Create virtual environment
python -m venv .venv

# 2. Activate it
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r server/requirements.txt

# 4. Start the server
python server/server.py                        # Standalone
python server/server.py --ca-bridge --bluesky  # Full mode
```

Then open `virtual_beamline_nanoprobe_V4_36_bundle.html` in your browser.

## NLP Chat Setup

The NLP chat feature lets you control the beamline using natural language (Korean or English).

On first run, `start_server.bat` will ask you to choose an NLP backend. You can also configure it manually by editing `server/.env`:

### Option 1: Groq (Recommended - Free, Fast)

1. Get a free API key at https://console.groq.com/keys
2. Edit `server/.env`:
   ```
   NLP_ENGINE=groq
   GROQ_API_KEY=gsk_your_key_here
   GROQ_MODEL=llama-3.3-70b-versatile
   ```

### Option 2: Google Gemini (Free Tier)

1. Get a free API key at https://aistudio.google.com/apikey
2. Edit `server/.env`:
   ```
   NLP_ENGINE=gemini
   GOOGLE_API_KEY=your_key_here
   GEMINI_MODEL=gemini-2.0-flash
   ```

### Option 3: Ollama (Free, Offline, Local)

1. Install Ollama from https://ollama.com
2. Pull a model: `ollama pull qwen2.5:7b`
3. Edit `server/.env`:
   ```
   NLP_ENGINE=ollama
   OLLAMA_URL=http://localhost:11434
   OLLAMA_MODEL=qwen2.5:7b
   ```

### Option 4: vLLM (Self-hosted, GPU)

1. Set up vLLM server with a model (e.g., Qwen3-32B)
2. Edit `server/.env`:
   ```
   NLP_ENGINE=vllm
   VLLM_URL=http://localhost:8000
   VLLM_MODEL=Qwen/Qwen3-32B
   ```

### Option 5: DeepSeek (API)

1. Get an API key at https://platform.deepseek.com
2. Edit `server/.env`:
   ```
   NLP_ENGINE=deepseek
   DEEPSEEK_API_KEY=your_key_here
   DEEPSEEK_MODEL=deepseek-chat
   ```

### Option 6: OpenAI (GPT-4o)

1. Get an API key at https://platform.openai.com/api-keys
2. Edit `server/.env`:
   ```
   NLP_ENGINE=openai
   OPENAI_API_KEY=sk-your_key_here
   OPENAI_MODEL=gpt-4o-mini
   ```

### Option 7: Anthropic Claude (Highest Quality)

1. Get an API key at https://console.anthropic.com/settings/keys
2. Edit `server/.env`:
   ```
   NLP_ENGINE=claude
   ANTHROPIC_API_KEY=sk-ant-your_key_here
   CLAUDE_MODEL=claude-sonnet-4-5-20250929
   ```

### Disable NLP

To run the server without NLP chat, set:
```
NLP_ENGINE=
```

## Features

- **Physics Simulation**: Monte Carlo ray tracing (80,000 rays), undulator spectrum, DCM/mirror/KB optics
- **Beam Visualization**: 2D beam profile, 1D cuts, power density, heat load analysis
- **Alignment Tools**: Half-cut, pitch optimization, rocking curve, rotation center correction
- **NLP Chat**: Natural language beamline control in Korean/English (7 LLM backends)
- **EPICS Integration**: caproto Soft IOC (83 PVs), Channel Access bridge, WebSocket server
- **Bluesky Scans**: Energy scan, XAFS, raster scan, alignment scans with real-time streaming
- **Virtual Experiments**: XAFS, XRF 2D imaging, powder XRD, XRD Map, Ptychography preview
- **Analysis Tools**: Beam profile fitting, knife-edge analysis, FWHM measurement

## K4GSR Ecosystem

This project is part of the **K4GSR 3-project ecosystem**:

| Project | Purpose | Phase |
|---------|---------|-------|
| **K4GSR-Beamline** (this) | Virtual beamline control + simulation | Before experiment |
| **K4GSR-PTYCHO** | Ptychography 2D reconstruction from real data | After data acquisition |
| **K4GSR-TOMO** | Tomography 3D reconstruction from ptycho stack | After reconstruction |

**Workflow**: User request -> Virtual simulation (feasibility check) -> User approval -> Real beam alignment

## Beamline Specifications

| Parameter | Value |
|-----------|-------|
| Storage Ring | Korea-4GSR, 4.0 GeV, 400 mA |
| Source | IVU24 Undulator (24 mm period, 123 periods) |
| Energy Range | 5 - 25 keV |
| Monochromator | DCM Si(111) / Si(311) |
| Focusing | KB mirrors (50 nm target) |
| Beam Size | ~50 nm (nanoprobe) |

## Server Architecture

| Port | Service | Description |
|------|---------|-------------|
| 8001 | Main WebSocket | PV, NLP chat, Bluesky scan, Virtual experiments |
| 8002 | Simulation | xraylib/pyFAI-based experiment simulation |
| 8765 | Ptycho (K4GSR-PTYCHO) | Ptychography reconstruction server |
| 5064 | EPICS Soft IOC | Channel Access (caproto) |

### WebSocket Endpoints (port 8001)

| Endpoint | Description |
|----------|-------------|
| `/ws/pv` | PV read/write/subscribe |
| `/ws/chat` | NLP chat |
| `/ws/scan` | Bluesky scan control |
| `/ws/expt` | Virtual experiment control |

## Project Structure

```
K4GSR-Beamline/
├── start_server.bat                  # One-click start (Windows)
├── start_server.sh                   # One-click start (Mac/Linux)
├── start_server_full.bat             # Full mode (EPICS + Bluesky)
├── virtual_beamline_*_bundle.html    # Main application (open in browser)
├── README.md                         # This file
|
├── js/                               # Source JavaScript (59 domain files)
│   ├── shared/                       #   Shared utilities + constants
│   ├── optics/                       #   DCM, mirror, KB optics
│   ├── control/                      #   Motor, EPICS, scan control
│   ├── analysis/                     #   Beam profile, fitting
│   ├── raytrace/                     #   MC ray tracing engine
│   ├── alignment/                    #   Mirror/KB alignment
│   ├── ui/                           #   Popup, panel, layout
│   ├── bluesky/                      #   Bluesky scan integration
│   ├── detector/                     #   Detector simulation
│   ├── measurement/                  #   Measurement tools
│   ├── experiment/                   #   Virtual experiments (5 types)
│   ├── tutorial/                     #   Tutorial system
│   └── nlp/                          #   NLP chat UI
|
├── server/                           # Python backend
│   ├── server.py                     #   Main WebSocket server (port 8001)
│   ├── pv_store.py                   #   PV value store + motor simulation
│   ├── nlp_agent.py                  #   NLP agent (7 LLM backends)
│   ├── ca_bridge.py                  #   Channel Access bridge
│   ├── simulation_server.py          #   Simulation server (port 8002)
│   ├── experiment_engine.py          #   Virtual experiment engine
│   ├── science_advisor.py            #   Science advisory NLP
│   ├── sim_engines/                  #   Experiment simulation engines
│   │   ├── xafs_engine.py            #     XAFS simulation
│   │   ├── xrf_engine.py             #     XRF 2D imaging
│   │   ├── xrd_engine.py             #     Powder XRD
│   │   └── xrdmap_engine.py          #     XRD mapping
│   ├── epics/                        #   EPICS soft IOC
│   │   └── soft_ioc.py               #     caproto-based IOC (83 PVs)
│   ├── scan_engine/                  #   Bluesky scan engine
│   │   ├── devices.py, plans.py      #     ophyd devices + scan plans
│   │   └── runner.py                 #     Scan execution runner
│   └── data/                         #   Data processing
│       ├── scan_db.py                #     Scan history database
│       └── writer.py                 #     HDF5/NeXus data writer
|
├── ptycho/                           # Ptychography (mirror of K4GSR-PTYCHO)
│   ├── engines/                      #   DM, ML, LSQML, ePIE engines
│   ├── server/                       #   WebSocket server (port 8765)
│   └── synth_ptycho.py               #   Synthetic data generator
|
├── vendor/                           # Third-party JS libraries
│   ├── uplot-1.6.31.min.js           #   uPlot charting
│   └── plotly-basic-2.27.0.min.js    #   Plotly.js (experiment plots)
|
├── Scripts/                          # Build tools (dev only)
│   ├── build.py                      #   Bundle builder + validator
│   └── publish_main.bat              #   Publish master -> main
|
└── docs/                             # Documentation (dev only)
    ├── architecture/                 #   Project structure, agent roles
    ├── knowledge/                    #   Physics, UI, alignment docs
    ├── onboarding/                   #   Setup guides
    ├── tasks/                        #   Task tracking, session logs
    └── nlp_benchmark/                #   NLP backend benchmark results
```

## Troubleshooting

### "NLP agent not available"
- Check that `server/.env` exists and has the correct `NLP_ENGINE` and API key
- Run `pip install httpx python-dotenv` in the virtual environment
- Restart the server

### "Port 8001 already in use"
- Close any previously running server instances
- Or use a different port: `python server/server.py --port 8002`

### Dependencies fail to install
- Make sure you're using Python 3.10 or newer
- Try: `pip install --upgrade pip` then retry
- On Windows, some packages may need Visual C++ Build Tools

### Browser doesn't open automatically
- Manually open `virtual_beamline_nanoprobe_V4_36_bundle.html` in Chrome or Edge

## Roadmap

1. **Virtual Beamline** - Physics simulation + control UI
2. **EPICS Connection** - Soft IOC + CA Bridge + Bluesky scan engine
3. **Virtual Experiments** - XAFS, XRF, XRD, Ptycho feasibility check
4. **Auto Optimization** - Simulation -> approval -> real motor drive
5. **NLP/Voice Interface** - Natural language control for non-experts
6. **2029 Target** - Korea-4GSR ID10 NanoProbe commissioning deployment

## License

[Apache License 2.0](LICENSE)

## Contributors

- **Jae-yong Shin** - Project lead, UI/Physics development
