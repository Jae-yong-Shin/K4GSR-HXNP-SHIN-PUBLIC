# K4GSR Hard X-ray Nanoprobe Virtual Beamline

**Korea-4GSR ID10 Hard X-ray Nanoprobe (HXNP)** virtual beamline control system with physics simulation, virtual experiments, NLP chat, and EPICS integration.

## Development Status and Branches

This repository accompanies a peer-reviewed journal submission.

- **`main` (this branch) is frozen at the paper-submission state** (application bundle version 4.37.33). It is kept as the reproducibility baseline for the paper: the code, validation data, and benchmark results here correspond to the numbers reported in the manuscript. Only documentation fixes (such as this README) are applied to `main`.
- **The [`beta`](../../tree/beta) branch carries post-submission progress** on the future work declared in the paper, including NLP agent improvements, an ion-chamber (I0/I1) physics model, WebGPU acceleration of the Monte Carlo engine, and the EPICS areaDetector integration path. **The `beta` branch is still under active development and has NOT been fully validated**: code there is functional but work-in-progress (interim benchmarks only; not yet held to the validation standard of `main`), and it may change or break without notice. The CHANGELOG and the work-list section in the `beta` README document what is being developed and what changed relative to the paper baseline.
- If you want to reproduce the paper, use `main`. If you want to preview ongoing development, see the [`beta`](../../tree/beta) branch README for the current work list and progress.

## Quick Start

The physics simulation runs entirely in the browser: simply open `virtual_beamline_nanoprobe_V4_37_bundle.html` in Chrome or Edge for the standalone virtual mode (no installation required). The Python backend adds NLP chat, EPICS Soft IOC, Bluesky scans, and server-side virtual experiments.

To run with the backend:

```bash
# 1. Create a virtual environment (Python 3.10+; 3.11 recommended)
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
python server/server.py --ca-bridge --bluesky  # Full mode (EPICS Soft IOC + Bluesky scans)
```

Then open `virtual_beamline_nanoprobe_V4_37_bundle.html` in your browser (Chrome or Edge recommended).

To enable the NLP chat, copy `server/.env.example` to `server/.env` and set an NLP backend (see below).

## NLP Chat Setup

The NLP chat feature lets you control the beamline using natural language (Korean or English).

Configure it by copying `server/.env.example` to `server/.env` and setting one of the backends below:

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

## Reproducibility (paper validation artifacts)

The validation and benchmark artifacts referenced by the accompanying paper are included in this repository:

- `paper/validation/` — Shadow4 cross-validation scripts (`shadow4_bl10.py`, `run_s4_500k.py`, `generate_fig4.py`) and reference data (`data/*.json`: SHADOW4 vs MC engine beam profiles at 5/10/20 keV, SSA 10/50/200 um, reflectivity and rocking-curve references)
- `paper/latency_results.json` and `tools/measure_latency.py` — NLP round-trip latency measurements
- `docs/nlp_benchmark/` — NLP benchmark methodology, per-backend result JSONs, the 228-case snapshot, and expert review records
- `tests/` — analytical, hybrid (wave-optics), and Shadow4-port test suites

## Project Structure

```
K4GSR-HXNP-SHIN-PUBLIC/
├── virtual_beamline_nanoprobe_V4_37_bundle.html   # Main application (open in browser)
├── virtual_beamline_nanoprobe_V4_37.html          # Source HTML (loads js/ modules; dev convenience)
├── undulator_calculator_v2.html                   # Standalone undulator spectrum calculator
├── README.md                                      # This file
├── LICENSE                                        # Apache License 2.0
├── package.json / eslint.config.js / pyproject.toml   # Lint and packaging configs
|
├── js/                               # Source JavaScript (59 domain files)
│   ├── shared/                       #   Shared utilities + constants
│   ├── optics/                       #   Undulator, DCM, mirror, KB optics
│   ├── control/                      #   Motor, EPICS, scan control
│   ├── analysis/                     #   Beam profile, fitting
│   ├── raytrace/                     #   MC ray tracing engine
│   ├── alignment/                    #   Mirror/KB alignment
│   ├── ui/                           #   Popup, panel, layout
│   ├── bluesky/                      #   Bluesky scan integration
│   ├── detector/                     #   Detector simulation
│   ├── measurement/                  #   Measurement tools
│   ├── experiment/                   #   Virtual experiments (5 types)
│   ├── tomo/                         #   Tomography preview
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
│   ├── sim_engines/                  #   XAFS / XRF / XRD / XRD-map engines
│   ├── epics/                        #   caproto Soft IOC (83 PVs)
│   ├── scan_engine/                  #   Bluesky scan engine (devices, plans, runner)
│   ├── scan_program/                 #   Scan program definitions
│   ├── hardware/                     #   Hardware controller interfaces (KOHZU, SmarAct, ...)
│   ├── config/                       #   IOC and stage configuration
│   ├── i18n/                         #   Server-side translations
│   └── data/                         #   Scan history DB + HDF5/NeXus writer
|
├── ptycho/                           # Ptychography (mirror of K4GSR-PTYCHO)
│   ├── engines/                      #   DM, ML, LSQML, ePIE engines
│   ├── server/                       #   WebSocket server (port 8765)
│   └── synth_ptycho.py               #   Synthetic data generator
|
├── paper/                            # Paper reproducibility artifacts
│   ├── validation/                   #   Shadow4 cross-validation scripts + reference data
│   └── latency_results.json          #   NLP latency measurements
|
├── tests/                            # Test suites (analytical, benchmark, diagnostics, e2e, hybrid, s4_port, js)
├── tools/                            # Latency measurement tooling
├── docs/
│   └── nlp_benchmark/                # NLP benchmark methodology, results, expert reviews
|
├── deploy/                           # Deployment scripts + config (sanitized placeholders)
├── vendor/                           # Third-party JS (uPlot, Plotly.js)
├── Scripts/                          # Build tools (bundle builder, doc index, codegen)
└── .github/workflows/                # CI
```

## Troubleshooting

### "NLP agent not available"
- Copy `server/.env.example` to `server/.env` and set the correct `NLP_ENGINE` and API key
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
- Manually open `virtual_beamline_nanoprobe_V4_37_bundle.html` in Chrome or Edge

## Roadmap

1. **Virtual Beamline** - Physics simulation + control UI
2. **EPICS Connection** - Soft IOC + CA Bridge + Bluesky scan engine
3. **Virtual Experiments** - XAFS, XRF, XRD, Ptycho feasibility check
4. **Auto Optimization** - Simulation -> approval -> real motor drive
5. **NLP/Voice Interface** - Natural language control for non-experts
6. **2029 Target** - Korea-4GSR ID10 NanoProbe commissioning deployment

## License

[Apache License 2.0](LICENSE)
