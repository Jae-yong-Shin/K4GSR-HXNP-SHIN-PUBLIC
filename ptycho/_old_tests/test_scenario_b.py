"""
Scenario B server pipeline test: 10keV, 50nm beam, asize=256, z=1m
Verifies:
  1. preview_synthetic works
  2. generate_synthetic works
  3. reconstruction produces correct result (compare with ground truth)
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

PARAMS = {
    "dataset_id": 6,
    "material": "Au",
    "energy_keV": 10.0,
    "objheight": 1e-6,
    "asize": 256,
    "z_m": 1.0,
    "det_pixel_m": 75e-6,
    "overlap": 0.75,
    "scan_lx_um": 0.3,
    "scan_ly_um": 0.3,
    "N_photons": 1000,
    "noise_sigma": 0.0,
    "mc_probe": {
        "fwhm_h_m": 50e-9,
        "fwhm_v_m": 80e-9,
        "focal_length_m": 0.205,
        "defocus_m": 0.0,
    }
}


def decode_raw_complex(raw_b64, shape):
    data = base64.b64decode(raw_b64)
    n = shape[0] * shape[1]
    floats = struct.unpack(f'<{n*2}f', data)
    arr = np.zeros((shape[0], shape[1]), dtype=np.complex64)
    for i in range(n):
        arr.flat[i] = complex(floats[2*i], floats[2*i+1])
    return arr


async def recv_msg(ws):
    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        if msg.get("type") == "log":
            continue
        return msg


async def main():
    lam = 1239.842e-9 / (PARAMS["energy_keV"] * 1e3)
    dx_nm = lam * PARAMS["z_m"] / (PARAMS["asize"] * PARAMS["det_pixel_m"]) * 1e9
    print(f"Scenario B: 10keV, 50nm beam, asize=256, z=1m")
    print(f"  dx = {dx_nm:.2f} nm, FOV = {PARAMS['asize'] * dx_nm:.0f} nm")
    print()

    async with websockets.connect(WS_URL, max_size=100_000_000) as ws:
        # Ping
        await ws.send(json.dumps({"type": "ping"}))
        resp = await recv_msg(ws)
        gpu = resp.get("gpu_available", False)
        print(f"Server: GPU={'ON' if gpu else 'OFF'}")

        # ---- Step 1: preview_synthetic ----
        print(f"\n[1] preview_synthetic...")
        t0 = time.time()
        await ws.send(json.dumps({"type": "preview_synthetic", "params": PARAMS}))
        resp = await recv_msg(ws)
        dt = time.time() - t0
        if resp["type"] != "preview_ready":
            print(f"  FAIL: {resp['type']}: {resp.get('error','')}")
            return
        npos = resp.get("info", {}).get("num_positions", 0)
        preview = resp.get("preview", {})
        print(f"  OK: {npos} positions, {dt:.2f}s")

        # Decode preview probe
        probe_preview = None
        if "raw_probe" in preview:
            probe_preview = decode_raw_complex(preview["raw_probe"], preview["raw_probe_shape"])
            amp = np.abs(probe_preview)
            center = amp.shape[0] // 2
            h_fwhm = (amp[center, :] >= amp.max() * 0.5).sum()
            v_fwhm = (amp[:, center] >= amp.max() * 0.5).sum()
            print(f"  Probe FWHM: H={h_fwhm}px({h_fwhm*dx_nm:.1f}nm) V={v_fwhm}px({v_fwhm*dx_nm:.1f}nm)")

        # Decode preview object
        obj_preview = None
        if "raw_object" in preview:
            obj_preview = decode_raw_complex(preview["raw_object"], preview["raw_object_shape"])
            print(f"  Object: {obj_preview.shape}, |O|=[{np.abs(obj_preview).min():.3f}, {np.abs(obj_preview).max():.3f}]")

        # ---- Step 2: generate_synthetic ----
        print(f"\n[2] generate_synthetic...")
        t0 = time.time()
        await ws.send(json.dumps({"type": "generate_synthetic", "params": PARAMS}))
        resp = await recv_msg(ws)
        dt = time.time() - t0
        if resp["type"] != "data_loaded":
            print(f"  FAIL: {resp['type']}: {resp.get('error','')}")
            return
        info = resp.get("info", {})
        npos2 = info.get("num_positions", "?")
        pixel_nm = info.get("pixel_size_nm", 0)
        print(f"  OK: {npos2} positions, pixel={pixel_nm:.2f}nm, {dt:.2f}s")

        # ---- Step 3: Reconstruction (DM 200 + ML 50) ----
        dm_iter = 200
        ml_iter = 50
        print(f"\n[3] Reconstruction (DM {dm_iter} + ML {ml_iter})...")
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
        error_history = []

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
                    error_history.append(last_error)
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
                print(f"  ERROR: {msg.get('error','')}")
                return

    # ---- Quality Analysis ----
    print(f"\n{'='*60}")
    print(f"  QUALITY ANALYSIS")
    print(f"{'='*60}")

    if final_obj is None:
        print("  No final object received!")
        return

    oa = np.abs(final_obj)
    print(f"  Recon |obj|: [{oa.min():.4f}, {oa.max():.4f}]")

    # Amplitude check
    if 0.5 < oa.max() < 2.0:
        print(f"  Amplitude range: OK (max={oa.max():.3f}, expected ~1.0)")
    else:
        print(f"  Amplitude range: WARNING (max={oa.max():.3f}, expected ~1.0)")

    # Phase variation check
    phase = np.angle(final_obj)
    phase_range = phase.max() - phase.min()
    print(f"  Phase range: {phase_range:.2f} rad")

    # Compare with ground truth (from preview)
    if obj_preview is not None:
        truth = obj_preview
        oh, ow = final_obj.shape
        th, tw = truth.shape
        ch, cw = min(oh, th), min(ow, tw)
        ob_c = final_obj[oh//2-ch//2:oh//2+ch//2, ow//2-cw//2:ow//2+cw//2]
        tr_c = truth[th//2-ch//2:th//2+ch//2, tw//2-cw//2:tw//2+cw//2]

        # Phase-shift alignment
        phase_diff = np.angle(np.sum(ob_c * np.conj(tr_c)))
        ob_aligned = ob_c * np.exp(-1j * phase_diff)
        norm_error = np.sqrt(np.sum(np.abs(ob_aligned - tr_c)**2) / np.sum(np.abs(tr_c)**2))
        print(f"\n  Normalized error vs truth: {norm_error:.4f}")
        if norm_error < 0.15:
            print(f"  >> EXCELLENT (< 0.15)")
        elif norm_error < 0.30:
            print(f"  >> GOOD (< 0.30)")
        elif norm_error < 0.50:
            print(f"  ** MARGINAL (0.30 ~ 0.50)")
        else:
            print(f"  !! POOR (>= 0.50) - reconstruction failed")

    # ---- Save result image ----
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 4, figsize=(18, 9))

        # Row 1: Input
        if probe_preview is not None:
            axes[0,0].imshow(np.abs(probe_preview), cmap='hot')
            axes[0,0].set_title(f'Input Probe |P|\nFWHM H={h_fwhm}px V={v_fwhm}px')
            axes[0,1].imshow(np.angle(probe_preview), cmap='hsv', vmin=-np.pi, vmax=np.pi)
            axes[0,1].set_title('Input Probe Phase')

        if obj_preview is not None:
            axes[0,2].imshow(np.abs(obj_preview), cmap='gray')
            axes[0,2].set_title(f'Ground Truth |O|')
            axes[0,3].imshow(np.angle(obj_preview), cmap='hsv', vmin=-np.pi, vmax=np.pi)
            axes[0,3].set_title('Ground Truth Phase')

        # Row 2: Reconstruction
        axes[1,0].imshow(np.abs(final_obj), cmap='gray')
        axes[1,0].set_title(f'Recon |obj|\nmax={oa.max():.3f}')

        axes[1,1].imshow(np.angle(final_obj), cmap='hsv', vmin=-np.pi, vmax=np.pi)
        err_str = f'{norm_error:.4f}' if obj_preview is not None else '?'
        axes[1,1].set_title(f'Recon Phase\nerror={err_str}')

        if final_probe is not None:
            axes[1,2].imshow(np.abs(final_probe), cmap='hot')
            axes[1,2].set_title('Recon Probe |P|')
            axes[1,3].imshow(np.angle(final_probe), cmap='hsv', vmin=-np.pi, vmax=np.pi)
            axes[1,3].set_title('Recon Probe Phase')

        # Error convergence (if available)
        if len(error_history) > 5:
            for ax in [axes[1,2], axes[1,3]]:
                pass  # keep probe images

        for ax in axes.flat:
            ax.axis('off')

        fig.suptitle(
            f'Server Pipeline: Scenario B (10keV, 50nm, asize=256, z=1m)\n'
            f'DM{dm_iter}+ML{ml_iter}, {npos2} pos, dx={dx_nm:.1f}nm, '
            f'error={err_str}',
            fontsize=12, fontweight='bold')
        plt.tight_layout()
        out = Path(__file__).parent / 'test_scenario_b_result.png'
        plt.savefig(out, dpi=150)
        plt.close()
        print(f"\nResult image: {out}")

        # Error convergence plot
        if len(error_history) > 5:
            fig2, ax2 = plt.subplots(1, 1, figsize=(8, 4))
            ax2.semilogy(error_history)
            ax2.set_xlabel('Iteration')
            ax2.set_ylabel('Error')
            ax2.set_title('Reconstruction Error Convergence')
            ax2.grid(True, alpha=0.3)
            out2 = Path(__file__).parent / 'test_scenario_b_convergence.png'
            plt.savefig(out2, dpi=100)
            plt.close()
            print(f"Convergence: {out2}")

    except ImportError:
        print("(matplotlib not available)")


if __name__ == "__main__":
    asyncio.run(main())
