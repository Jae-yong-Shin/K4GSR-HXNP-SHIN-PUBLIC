"""
Full pipeline test: preview_synthetic -> generate_synthetic -> reconstruction
Tests two scenarios:
  A) Known-good params from compare_recon.py (6.2keV, 200nm beam, overlap=0.75)
  B) JS-realistic params (10keV, 50nm beam, asize=256, z=1m) — mimics _buildSynthParams()
"""
import asyncio
import json
import time
import sys
import base64
import struct
from pathlib import Path

import numpy as np

try:
    import websockets
except ImportError:
    print("pip install websockets")
    sys.exit(1)

WS_URL = "ws://localhost:8765"

# ── Scenario A: known-good (compare_recon.py verified: error=0.061) ──
PARAMS_A = {
    "label": "A: Known-good (6.2keV, 200nm, overlap=0.75)",
    "dataset_id": 6,
    "material": "Au",
    "energy_keV": 6.2,
    "objheight": 1e-6,
    "asize": 128,
    "z_m": 5.0,
    "det_pixel_m": 75e-6,
    "overlap": 0.75,             # no scan_step_um -> derive from overlap
    "scan_lx_um": 3.0,           # limit scan area for speed
    "scan_ly_um": 3.0,
    "N_photons": 1000,
    "noise_sigma": 0.0,
    "mc_probe": {
        "fwhm_h_m": 200e-9,
        "fwhm_v_m": 200e-9,
        "focal_length_m": 0.3,
        "defocus_m": 0.0,
    }
}

# ── Scenario B: JS-realistic (mimics _buildSynthParams output) ──
# energy=10keV, beam=50nm, asize=256, z=1m
# scan_step_um = beamMax * 0.4 / 1000 = 50 * 0.4 / 1000 = 0.02 um
PARAMS_B = {
    "label": "B: JS-realistic (10keV, 50nm, asize=256, z=1m)",
    "dataset_id": 6,
    "material": "Au",
    "energy_keV": 10.0,
    "objheight": 1e-6,
    "asize": 256,
    "z_m": 1.0,
    "det_pixel_m": 75e-6,
    "scan_step_um": 0.02,        # 20nm step, ~60% overlap with 50nm beam
    "scan_lx_um": 0.3,           # 300nm range
    "scan_ly_um": 0.3,
    "N_photons": 1000,
    "noise_sigma": 0.0,
    "mc_probe": {
        "fwhm_h_m": 50e-9,
        "fwhm_v_m": 80e-9,       # asymmetric KB
        "focal_length_m": 0.205,  # avg of KBV(0.31) + KBH(0.10)
        "defocus_m": 0.0,
    }
}


def decode_raw_complex(raw_b64, shape):
    """Decode base64 raw complex data."""
    data = base64.b64decode(raw_b64)
    n = shape[0] * shape[1]
    floats = struct.unpack(f'<{n*2}f', data)
    arr = np.zeros((shape[0], shape[1]), dtype=np.complex64)
    for i in range(n):
        arr.flat[i] = complex(floats[2*i], floats[2*i+1])
    return arr


async def recv_msg(ws):
    """Receive next non-log message."""
    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        if msg.get("type") == "log":
            continue
        return msg


async def run_scenario(ws, params, dm_iter=200, ml_iter=50):
    """Run full pipeline for one parameter set. Returns result dict."""
    label = params.pop("label", "?")
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    # Compute expected dx
    lam = 1239.842e-9 / (params["energy_keV"] * 1e3)
    dx_nm = lam * params["z_m"] / (params["asize"] * params["det_pixel_m"]) * 1e9
    print(f"  dx={dx_nm:.2f}nm, probe_field={params['asize']*dx_nm:.0f}nm")

    # ── Step 1: preview_synthetic ──
    print("\n  [1] preview_synthetic...")
    t0 = time.time()
    await ws.send(json.dumps({"type": "preview_synthetic", "params": params}))
    resp = await recv_msg(ws)
    dt = time.time() - t0
    if resp["type"] != "preview_ready":
        print(f"  FAIL: expected preview_ready, got {resp['type']}: {resp.get('error','')}")
        return None
    npos = resp.get("info", {}).get("num_positions", 0)
    preview = resp.get("preview", {})
    print(f"  OK: {npos} positions, {dt:.2f}s")

    # Decode probe
    probe = None
    if "raw_probe" in preview:
        probe = decode_raw_complex(preview["raw_probe"], preview["raw_probe_shape"])
        amp = np.abs(probe)
        center = amp.shape[0] // 2
        h_fwhm = (amp[center, :] >= amp.max() * 0.5).sum()
        v_fwhm = (amp[:, center] >= amp.max() * 0.5).sum()
        print(f"  Probe: {probe.shape}, FWHM H={h_fwhm}px({h_fwhm*dx_nm:.1f}nm) V={v_fwhm}px({v_fwhm*dx_nm:.1f}nm)")

    # Decode object
    if "raw_object" in preview:
        obj_prev = decode_raw_complex(preview["raw_object"], preview["raw_object_shape"])
        print(f"  Object: {obj_prev.shape}, |O| range=[{np.abs(obj_prev).min():.3f}, {np.abs(obj_prev).max():.3f}]")

    # ── Step 2: generate_synthetic ──
    print("\n  [2] generate_synthetic...")
    t0 = time.time()
    await ws.send(json.dumps({"type": "generate_synthetic", "params": params}))
    resp = await recv_msg(ws)
    dt = time.time() - t0
    if resp["type"] != "data_loaded":
        print(f"  FAIL: expected data_loaded, got {resp['type']}: {resp.get('error','')}")
        return None
    npos2 = resp.get("info", {}).get("num_positions", "?")
    print(f"  OK: {npos2} positions, fmag in {dt:.2f}s")

    # ── Step 3: Reconstruction ──
    print(f"\n  [3] Reconstruction (DM {dm_iter} + ML {ml_iter})...")
    t0 = time.time()
    await ws.send(json.dumps({
        "type": "start_reconstruction",
        "params": {
            "engine": "DM_ML",
            "dm_iterations": dm_iter,
            "ml_iterations": ml_iter,
            "use_gpu": True,
        }
    }))

    last_error = None
    final_obj = None
    final_probe = None

    while True:
        msg = await recv_msg(ws)
        mtype = msg.get("type", "")

        if mtype == "reconstruction_started":
            gpu_str = "[GPU]" if msg.get("use_gpu") else "[CPU]"
            print(f"  Started: {msg.get('engine','')} {gpu_str}")

        elif mtype == "pipeline_stage_change":
            print(f"  -> {msg.get('engine','')} ({msg.get('total_iterations','')} iter)")

        elif mtype == "iteration_update":
            it = msg.get("iteration", 0)
            if "error" in msg and isinstance(msg["error"], (int, float)):
                last_error = msg["error"]
            if "raw_object" in msg:
                final_obj = decode_raw_complex(msg["raw_object"], msg["raw_object_shape"])
            if "raw_probe" in msg:
                final_probe = decode_raw_complex(msg["raw_probe"], msg["raw_probe_shape"])
            if it % 50 == 0 or it <= 2:
                err_str = f"{last_error:.4e}" if last_error is not None else "-"
                print(f"  iter {it}: error={err_str}")

        elif mtype == "reconstruction_complete":
            dt = time.time() - t0
            fe = msg.get("final_error")
            print(f"  Complete: {dt:.1f}s, final_error={fe}")
            break

        elif mtype == "error":
            err_msg = msg.get("error", "")
            if "already running" in err_msg.lower():
                print(f"  Waiting for previous reconstruction...")
                await asyncio.sleep(2)
                # Retry
                await ws.send(json.dumps({
                    "type": "start_reconstruction",
                    "params": {
                        "engine": "DM_ML",
                        "dm_iterations": dm_iter,
                        "ml_iterations": ml_iter,
                        "use_gpu": True,
                    }
                }))
                continue
            print(f"  ERROR: {err_msg}")
            return None

    # ── Quality check ──
    result = {
        "label": label, "npos": npos, "dx_nm": dx_nm,
        "probe_preview": probe, "final_obj": final_obj, "final_probe": final_probe,
        "last_error": last_error, "params": params,
    }

    if final_obj is not None:
        oa = np.abs(final_obj)
        print(f"  Recon |obj|: [{oa.min():.3f}, {oa.max():.3f}]")
        if 0.5 < oa.max() < 2.0:
            print(f"  Amplitude: OK")
        else:
            print(f"  Amplitude: WARNING (expected ~1.0)")

    return result


async def main():
    print("Ptycho Full Pipeline Test")
    print("=" * 60)

    async with websockets.connect(WS_URL, max_size=100_000_000) as ws:
        # Ping
        await ws.send(json.dumps({"type": "ping"}))
        resp = await recv_msg(ws)
        gpu = resp.get("gpu_available", False)
        print(f"Server: GPU={'ON' if gpu else 'OFF'}, version={resp.get('version', '?')}")

        # Run both scenarios
        res_a = await run_scenario(ws, dict(PARAMS_A), dm_iter=200, ml_iter=50)
        res_b = await run_scenario(ws, dict(PARAMS_B), dm_iter=200, ml_iter=50)

    # ── Save comparison image ──
    results = [r for r in [res_a, res_b] if r is not None]
    if not results:
        print("\nNo results to plot.")
        return

    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        n = len(results)
        fig, axes = plt.subplots(n, 4, figsize=(16, 4 * n + 1))
        if n == 1:
            axes = axes[np.newaxis, :]

        for i, r in enumerate(results):
            dx = r["dx_nm"]

            # Probe preview (amplitude)
            ax = axes[i, 0]
            if r["probe_preview"] is not None:
                ax.imshow(np.abs(r["probe_preview"]), cmap='hot')
            ax.set_title(f'Probe |P| (preview)\n{r["label"][:30]}', fontsize=9)
            ax.axis('off')

            # Probe preview (phase)
            ax = axes[i, 1]
            if r["probe_preview"] is not None:
                ax.imshow(np.angle(r["probe_preview"]), cmap='hsv', vmin=-np.pi, vmax=np.pi)
            ax.set_title('Probe Phase', fontsize=9)
            ax.axis('off')

            # Recon object
            ax = axes[i, 2]
            if r["final_obj"] is not None:
                ax.imshow(np.abs(r["final_obj"]), cmap='gray')
                oa = np.abs(r["final_obj"])
                ax.set_title(f'Recon |obj|\n|O| max={oa.max():.3f}', fontsize=9)
            ax.axis('off')

            # Recon object phase
            ax = axes[i, 3]
            if r["final_obj"] is not None:
                ax.imshow(np.angle(r["final_obj"]), cmap='hsv', vmin=-np.pi, vmax=np.pi)
                err = r["last_error"]
                ax.set_title(f'Recon Phase\nerr={err:.2e}' if err else 'Recon Phase', fontsize=9)
            ax.axis('off')

        fig.suptitle('Ptycho Pipeline: Data Flow + Reconstruction Verification', fontsize=13, fontweight='bold')
        plt.tight_layout()
        out_path = Path(__file__).parent / "test_pipeline_result.png"
        plt.savefig(out_path, dpi=150)
        plt.close()
        print(f"\nResult image: {out_path}")
    except ImportError:
        print("(matplotlib not available)")

    print("\n" + "=" * 60)
    print("ALL SCENARIOS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
