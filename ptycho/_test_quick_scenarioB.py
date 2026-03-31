"""
Quick Scenario B test: 10keV, 50nm beam, asize=256, z=1m, scan 0.3x0.3um
DM 10 + ML 5 iterations for fast verification of:
  1. Progress bar total_iterations matches dm_iterations (not default 50)
  2. pipeline_stage_change fires on DM->ML transition
  3. reconstruction_complete received
"""
import asyncio
import json
import time
import sys

try:
    import websockets
except ImportError:
    print("pip install websockets")
    sys.exit(1)

WS_URL = "ws://localhost:8765"

SYNTH_PARAMS = {
    "dataset_id": 6,       # Mandrill
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

async def recv_skip_log(ws, timeout=60):
    """Receive next non-log message, skipping log/pong messages."""
    deadline = time.time() + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        msg = json.loads(raw)
        mtype = msg.get('type', '')
        if mtype in ('log', 'pong'):
            continue
        return msg

async def run_test():
    print(f"Connecting to {WS_URL}...")
    async with websockets.connect(WS_URL, max_size=50*1024*1024) as ws:
        print("Connected!")

        # 1) Preview (type field, not action)
        print("\n--- Step 1: preview_synthetic ---")
        await ws.send(json.dumps({"type": "preview_synthetic", "params": SYNTH_PARAMS}))
        msg = await recv_skip_log(ws, timeout=60)
        mtype = msg.get('type')
        info = msg.get('info', {})
        print(f"  response type={mtype}")
        if mtype == 'preview_ready':
            print(f"  num_positions={info.get('num_positions')}, asize={info.get('asize')}, "
                  f"pixel_size_nm={info.get('pixel_size_nm', '?')}")
        else:
            print(f"  ERROR: {msg.get('error', msg)}")
            return

        # 2) Generate synthetic data
        print("\n--- Step 2: generate_synthetic ---")
        await ws.send(json.dumps({"type": "generate_synthetic", "params": SYNTH_PARAMS}))
        msg = await recv_skip_log(ws, timeout=120)
        mtype = msg.get('type')
        info = msg.get('info', {})
        print(f"  response type={mtype}")
        if mtype == 'data_loaded':
            npos = info.get('num_positions', '?')
            print(f"  num_positions={npos}, asize={info.get('asize')}")
        else:
            print(f"  ERROR: {msg.get('error', msg)}")
            return

        # 3) Start DM_ML reconstruction (DM 10 + ML 5)
        print("\n--- Step 3: start_reconstruction (DM_ML, dm=10, ml=5) ---")
        recon_msg = {
            "type": "start_reconstruction",
            "params": {
                "engine": "DM_ML",
                "dm_iterations": 10,
                "number_iterations": 5,   # ML iterations
                "Nmodes": 1,
                "use_gpu": True
            }
        }
        await ws.send(json.dumps(recon_msg))

        # Listen for messages
        started_total = None
        stage_changes = []
        iterations = []
        complete = False
        t0 = time.time()

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=600)
            except asyncio.TimeoutError:
                print("  TIMEOUT waiting for message!")
                break

            msg = json.loads(raw)
            mtype = msg.get('type', '')
            elapsed = time.time() - t0

            if mtype == 'reconstruction_started':
                started_total = msg.get('total_iterations')
                engine = msg.get('engine')
                print(f"  [{elapsed:.0f}s] reconstruction_started: engine={engine}, "
                      f"total_iterations={started_total}")
                if started_total == 10:
                    print(f"  >>> PASS: total_iterations={started_total} matches dm_iterations=10")
                else:
                    print(f"  >>> FAIL: total_iterations={started_total}, expected 10")

            elif mtype == 'pipeline_stage_change':
                stage = msg.get('stage', '')
                new_total = msg.get('total_iterations')
                stage_changes.append(stage)
                print(f"  [{elapsed:.0f}s] pipeline_stage_change: stage={stage}, "
                      f"total_iterations={new_total}")

            elif mtype == 'iteration_update':
                it = msg.get('iteration', '?')
                err = msg.get('error', '?')
                iterations.append(it)
                print(f"  [{elapsed:.0f}s] iteration_update: iter={it}, error={err}")

            elif mtype == 'reconstruction_complete':
                complete = True
                total_time = msg.get('total_time', '?')
                print(f"  [{elapsed:.0f}s] reconstruction_complete: total_time={total_time}s")
                break

            elif mtype == 'reconstruction_error':
                print(f"  [{elapsed:.0f}s] reconstruction_error: {msg.get('error')}")
                break

            elif mtype == 'reconstruction_warning':
                print(f"  [{elapsed:.0f}s] warning: {msg.get('warning')}")

            elif mtype == 'reconstruction_cancelled':
                print(f"  [{elapsed:.0f}s] reconstruction_cancelled")
                break

            else:
                # Skip large data messages
                print(f"  [{elapsed:.0f}s] {mtype} ({len(raw)} bytes)")

        # Summary
        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)
        print(f"  total_iterations in started msg: {started_total} (expected: 10)")
        print(f"  stage_changes: {stage_changes}")
        print(f"  iteration count: {len(iterations)}")
        print(f"  complete received: {complete}")

        passed = True
        if started_total != 10:
            print("  FAIL: total_iterations mismatch")
            passed = False
        if 'ML' not in stage_changes:
            print("  FAIL: no ML stage change")
            passed = False
        if not complete:
            print("  FAIL: no reconstruction_complete")
            passed = False

        if passed:
            print("\n  ALL CHECKS PASSED!")
        else:
            print("\n  SOME CHECKS FAILED")

if __name__ == '__main__':
    asyncio.run(run_test())
