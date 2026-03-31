"""
test_js_flow.py - Test the full JS ptycho workflow via WebSocket
Mimics exactly what 05_ptycho_sim.js does:
  1. Connect to ws://localhost:8765
  2. Ping -> check GPU
  3. preview_synthetic -> quick preview (object + probe)
  4. generate_synthetic -> full data with fmag
  5. start_reconstruction -> DM+ML pipeline -> verify convergence
"""
import asyncio
import json
import sys
import time
import base64
import struct
import numpy as np

try:
    import websockets
except ImportError:
    print("ERROR: pip install websockets")
    sys.exit(1)


def decode_raw_complex(b64_str):
    """Decode interleaved float32 base64 -> complex array (same as JS _decodeRawComplex)."""
    raw = base64.b64decode(b64_str)
    arr = np.frombuffer(raw, dtype=np.float32)
    return arr[0::2] + 1j * arr[1::2]


async def test_js_flow():
    url = "ws://localhost:8765"
    print(f"[1] Connecting to {url} ...")
    try:
        ws = await asyncio.wait_for(websockets.connect(url, max_size=200_000_000), timeout=5)
    except Exception as e:
        print(f"FAIL: Cannot connect to ptycho server: {e}")
        print("  Start server: python server/ptycho_server.py")
        return False

    results = {}

    # -- Step 1: Ping --
    print("[2] Ping ...")
    await ws.send(json.dumps({"type": "ping"}))
    # Server may send log messages first; skip them
    gpu = False
    for _ in range(20):
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if msg.get("type") == "pong":
            gpu = msg.get("gpu_available", False)
            print(f"    Pong OK. GPU={'ON' if gpu else 'OFF'}, v{msg.get('version', '?')}")
            break
        elif msg.get("type") == "log":
            continue
    else:
        print("FAIL: Never received pong")
        await ws.close()
        return False

    # -- Params (mimics _buildSynthParams from JS) --
    params = {
        "dataset_id": 6,
        "material": "Au",
        "energy_keV": 10.0,
        "objheight": 1e-6,
        "asize": 128,
        "scan_step_um": 0.02,
        "scan_lx_um": 0.5,
        "scan_ly_um": 0.5,
        "z_m": 2.0,
        "N_photons": 1000,
        "noise_sigma": 0.0,
        "rng_seed": 42,
        # KB Fresnel probe params (sinc beam from rectangular aperture)
        "mc_probe": {
            "fwhm_h_m": 50e-9,
            "fwhm_v_m": 50e-9,
            "focal_length_m": 0.2,
            "defocus_m": 0.0,
        },
        "probe_fwhm_nm": 50,
        "dx_nm": 6.2,
        "det_pixel_m": 75e-6,
    }

    # -- Step 2: Preview Synthetic (quick, no fmag) --
    print("[3] preview_synthetic (quick preview) ...")
    t0 = time.time()
    await ws.send(json.dumps({"type": "preview_synthetic", "params": params}))
    preview_ok = False
    for _ in range(50):
        raw = await asyncio.wait_for(ws.recv(), timeout=30)
        msg = json.loads(raw)
        mtype = msg.get("type", "?")
        if mtype == "preview_ready":
            dt = time.time() - t0
            preview = msg.get("preview", {})
            info = msg.get("info", {})
            npos = info.get("num_positions", 0)
            has_obj = "raw_object" in preview
            has_probe = "raw_probe" in preview
            print(f"    Preview OK ({dt:.1f}s): Npos={npos}, has_object={has_obj}, has_probe={has_probe}")
            if has_obj:
                obj_data = decode_raw_complex(preview["raw_object"])
                obj_shape = preview.get("raw_object_shape", [])
                print(f"    Object: shape={obj_shape}, |obj| range=[{np.min(np.abs(obj_data)):.4f}, {np.max(np.abs(obj_data)):.4f}]")
            if has_probe:
                probe_data = decode_raw_complex(preview["raw_probe"])
                probe_shape = preview.get("raw_probe_shape", [])
                print(f"    Probe:  shape={probe_shape}, |P| max={np.max(np.abs(probe_data)):.4f}")
            preview_ok = True
            break
        elif mtype == "error":
            print(f"    ERROR: {msg.get('error', '?')}")
            break
        elif mtype == "log":
            continue
    if not preview_ok:
        print("FAIL: preview_synthetic failed")
        await ws.close()
        return False

    # -- Step 3: Generate Synthetic (full fmag) --
    print("[4] generate_synthetic (full fmag computation) ...")
    t0 = time.time()
    await ws.send(json.dumps({"type": "generate_synthetic", "params": params}))

    data_loaded = False
    timeout_at = time.time() + 120
    while time.time() < timeout_at:
        raw = await asyncio.wait_for(ws.recv(), timeout=120)
        msg = json.loads(raw)
        mtype = msg.get("type", "?")
        if mtype == "data_loaded":
            dt = time.time() - t0
            info = msg.get("info", {})
            npos = info.get("num_positions", 0)
            preview = msg.get("preview", {})
            has_obj = "raw_object" in preview
            has_probe = "raw_probe" in preview
            print(f"    Data loaded ({dt:.1f}s): Npos={npos}, has_object={has_obj}, has_probe={has_probe}")
            if has_obj:
                obj_data = decode_raw_complex(preview["raw_object"])
                obj_shape = preview.get("raw_object_shape", [])
                print(f"    Object: shape={obj_shape}, |obj| range=[{np.min(np.abs(obj_data)):.4f}, {np.max(np.abs(obj_data)):.4f}]")
                results["preview_object"] = obj_data
            if has_probe:
                probe_data = decode_raw_complex(preview["raw_probe"])
                probe_shape = preview.get("raw_probe_shape", [])
                print(f"    Probe:  shape={probe_shape}, |P| max={np.max(np.abs(probe_data)):.4f}")
            data_loaded = True
            break
        elif mtype == "synth_progress":
            frac = msg.get("fraction", 0)
            print(f"    Progress: {msg.get('msg', '')} ({frac*100:.0f}%)")
        elif mtype == "data_load_error":
            print(f"    ERROR: {msg.get('error', '?')}")
            break
        elif mtype == "log":
            pass

    if not data_loaded:
        print("FAIL: generate_synthetic timed out or failed")
        await ws.close()
        return False

    # -- Step 4: Start Reconstruction (DM+ML pipeline) --
    recon_params = {
        "engine": "DM_ML",
        "use_gpu": gpu,
        "dm_iterations": 100,
        "ml_iterations": 20,
    }
    print(f"[5] start_reconstruction (DM {recon_params['dm_iterations']} + ML {recon_params['ml_iterations']}) ...")
    t0 = time.time()
    await ws.send(json.dumps({"type": "start_reconstruction", "params": recon_params}))

    recon_complete = False
    last_error = None
    error_history = []
    timeout_at = time.time() + 300  # 5 min max
    while time.time() < timeout_at:
        raw = await asyncio.wait_for(ws.recv(), timeout=300)
        msg = json.loads(raw)
        mtype = msg.get("type", "?")

        if mtype == "reconstruction_started":
            engine = msg.get("engine", "?")
            total = msg.get("total_iterations", 0)
            print(f"    Started: {engine} ({total} iter), GPU={msg.get('use_gpu', False)}")

        elif mtype == "pipeline_stage_change":
            stage = msg.get("stage", "?")
            engine = msg.get("engine", "?")
            total = msg.get("total_iterations", 0)
            print(f"    Stage {stage}: {engine} ({total} iter)")

        elif mtype == "iteration_update":
            iteration = msg.get("iteration", 0)
            err = msg.get("error")
            if isinstance(err, (int, float)):
                error_history.append(err)
                last_error = err
            # Print every 20th iteration
            if iteration % 20 == 0 or iteration <= 2:
                err_str = f", error={err:.6f}" if isinstance(err, (int, float)) else ""
                has_obj = "raw_object" in msg
                has_probe = "raw_probe" in msg
                print(f"    Iter {iteration}{err_str}, has_preview={has_obj}")

        elif mtype == "reconstruction_complete":
            dt = time.time() - t0
            total_time = msg.get("total_time_sec", dt)
            eh = msg.get("error_history", error_history)
            if eh:
                error_history = eh

            # Decode final result
            if "raw_object" in msg:
                obj_final = decode_raw_complex(msg["raw_object"])
                obj_shape = msg.get("raw_object_shape", [])
                amp_max = np.max(np.abs(obj_final))
                amp_median = np.median(np.abs(obj_final))
                print(f"    Complete ({total_time:.1f}s)")
                print(f"    Final object: shape={obj_shape}, |obj| max={amp_max:.4f}, median={amp_median:.4f}")
                results["final_object"] = obj_final
            else:
                print(f"    Complete ({total_time:.1f}s), no final object in message")

            if "raw_probe" in msg:
                probe_final = decode_raw_complex(msg["raw_probe"])
                print(f"    Final probe: |P| max={np.max(np.abs(probe_final)):.4f}")

            recon_complete = True
            break

        elif mtype == "reconstruction_error":
            print(f"    RECON ERROR: {msg.get('error', '?')}")
            break
        elif mtype == "log":
            pass

    if not recon_complete:
        print("FAIL: reconstruction timed out or failed")
        await ws.close()
        return False

    # -- Step 5: Validate results --
    print("\n[6] Validation ...")
    ok = True

    # Check error convergence
    if len(error_history) >= 2:
        e_first = error_history[0]
        e_last = error_history[-1]
        improved = e_last < e_first
        ratio = e_last / max(e_first, 1e-30)
        print(f"    Error: {e_first:.6f} -> {e_last:.6f} (ratio={ratio:.4f}, improved={improved})")
        if not improved:
            print("    WARNING: Error did not improve!")
            ok = False
    else:
        print("    WARNING: No error history available")

    # Check object amplitude range
    if "final_object" in results:
        amp = np.abs(results["final_object"])
        amp_max = np.max(amp)
        # For normalized object, max amplitude should be reasonable (0.5 - 3.0)
        if amp_max < 0.1 or amp_max > 10:
            print(f"    WARNING: Object amplitude max={amp_max:.4f} seems abnormal")
            ok = False
        else:
            print(f"    Object amplitude OK (max={amp_max:.4f})")

    await ws.close()

    if ok:
        print("\n=== ALL TESTS PASSED ===")
    else:
        print("\n=== SOME WARNINGS ===")
    return ok


if __name__ == "__main__":
    asyncio.run(test_js_flow())
