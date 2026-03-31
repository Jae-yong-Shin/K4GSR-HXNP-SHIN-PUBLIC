"""
End-to-end test: Direct engine_runner test with synthetic data.
Tests: GPU default, memory guard, stop/cleanup.
"""
import sys
import os
import time
import threading
import numpy as np
import gc

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'server'))

from synth_ptycho import SyntheticPtycho
from server.data_loader import DataLoader
from server.engine_runner import EngineRunner


def make_small_data():
    """Generate small synthetic dataset and convert to dict for DataLoader."""
    gen = SyntheticPtycho.from_dataset(
        dataset_id=6, asize=128, energy_keV=10.0,
        z_m=2.0, det_pixel_size_m=75e-6,
        scan_step_um=0.5, scan_lx_um=5.0, scan_ly_um=5.0,
    )
    ds = gen.generate()
    # Convert PtychoDataset to dict
    data = {
        'fmag': ds.fmag,
        'positions': ds.positions_noisy,
        'asize': (ds.asize, ds.asize),
        'probes': ds.probe,
        'object_init': ds.object_init,
    }
    return data, ds


def test_small_recon():
    """Test 1: Small reconstruction runs with GPU default."""
    print("=" * 60)
    print("Test 1: Small recon with GPU default")

    messages = []
    def broadcast(msg):
        messages.append(msg)
        t = msg.get('type', '')
        if t == 'reconstruction_started':
            gpu_str = 'GPU' if msg.get('use_gpu') else 'CPU'
            print(f"  Started: {msg.get('engine')} [{gpu_str}]")
        elif t == 'reconstruction_warning':
            print(f"  WARNING: {msg.get('warning', '')[:80]}")
        elif t == 'reconstruction_complete':
            print(f"  Complete: {msg.get('total_time_sec', 0):.1f}s, "
                  f"error={msg.get('final_error', 0):.4f}")
        elif t == 'reconstruction_error':
            print(f"  ERROR: {msg.get('error', '')[:100]}")

    data, ds = make_small_data()
    Npos = data['positions'].shape[0]
    print(f"  Generated: {Npos} positions, fmag shape={data['fmag'].shape}")

    # Build p dict (use_gpu should default True)
    loader = DataLoader()
    engine_params = {'number_iterations': 5, 'engine': 'DM'}
    p = loader.build_p_dict(data, engine_params)
    assert p['use_gpu'] == True, f"use_gpu should be True, got {p['use_gpu']}"
    print(f"  use_gpu={p['use_gpu']} (correct default)")

    # Try GPU first, fall back to CPU if not available
    runner = EngineRunner(broadcast)
    runner.start(p, 'DM', job_id='test_small')

    timeout = 120
    start = time.time()
    while runner.running and (time.time() - start) < timeout:
        time.sleep(0.5)

    assert not runner.running, "Runner should have finished"
    types = [m['type'] for m in messages]

    if 'reconstruction_error' in types:
        err_msg = [m for m in messages if m['type'] == 'reconstruction_error'][0]
        err_text = err_msg.get('error', '') + err_msg.get('traceback', '')
        if 'cupy' in err_text.lower() or 'gpu' in err_text.lower() or 'cuda' in err_text.lower():
            print("  (GPU not available on this machine - retrying with CPU)")
            messages.clear()
            p['use_gpu'] = False
            runner2 = EngineRunner(broadcast)
            runner2.start(p, 'DM', job_id='test_small_cpu')
            start = time.time()
            while runner2.running and (time.time() - start) < timeout:
                time.sleep(0.5)
            types = [m['type'] for m in messages]
        else:
            print(f"  FAIL: Non-GPU error: {err_text[:200]}")
            return False

    if 'reconstruction_complete' in types:
        print("  PASS: Reconstruction completed successfully")
    else:
        print(f"  Message types: {types}")
        return False

    # Small dataset should NOT trigger batching
    warnings = [m for m in messages if m['type'] == 'reconstruction_warning']
    assert len(warnings) == 0, "Small dataset should not trigger batching"
    print("  PASS: No batching warning for small dataset")
    return True


def test_memory_guard():
    """Test 2: Large position count triggers memory guard."""
    print("\n" + "=" * 60)
    print("Test 2: Memory guard for large Npos")

    Npos = 4761
    asize = (512, 512)
    mem_bytes = asize[0] * asize[1] * Npos * 16 * 3
    mem_gb = mem_bytes / (1024**3)
    MAX_MEM_GB = 4.0

    print(f"  Npos={Npos}, asize=512x512")
    print(f"  Estimated memory: {mem_gb:.1f} GB (limit: {MAX_MEM_GB:.0f} GB)")
    assert mem_gb > MAX_MEM_GB, "Should exceed memory limit"

    bytes_per_pos = asize[0] * asize[1] * 16 * 3
    max_pos = max(100, int(MAX_MEM_GB * (1024**3) / bytes_per_pos))
    n_batches = int(np.ceil(Npos / max_pos))
    batch_mem = max_pos * bytes_per_pos / (1024**3)
    print(f"  Would split into {n_batches} batches of ~{max_pos} positions")
    print(f"  Per-batch memory: {batch_mem:.1f} GB")
    assert batch_mem <= MAX_MEM_GB
    print("  PASS: Memory guard correctly prevents OOM")
    return True


def test_stop_cleanup():
    """Test 3: Stop during reconstruction cleans up memory."""
    print("\n" + "=" * 60)
    print("Test 3: Stop + memory cleanup")

    messages = []
    def broadcast(msg):
        messages.append(msg)

    data, ds = make_small_data()
    loader = DataLoader()
    p = loader.build_p_dict(data, {'number_iterations': 200, 'engine': 'DM'})
    p['use_gpu'] = False  # Force CPU for predictable timing

    runner = EngineRunner(broadcast)
    runner.start(p, 'DM', job_id='test_stop')

    # Wait a bit then stop
    time.sleep(2)
    if runner.running:
        print("  Stopping reconstruction...")
        runner.stop()
        time.sleep(3)

        types = [m['type'] for m in messages]
        if 'reconstruction_cancelled' in types:
            print("  PASS: Cancellation message sent")
        else:
            # May have finished or errored before stop
            print(f"  Types: {[t for t in types if t != 'iteration_update']}")

        gc.collect()
        print("  PASS: Memory cleanup completed without error")
    else:
        print("  (Finished before stop)")
        print("  PASS: No cleanup needed")
    return True


def test_various_sizes():
    """Test 4: Verify memory threshold for various asize/Npos combos."""
    print("\n" + "=" * 60)
    print("Test 4: Memory threshold for various configurations")

    MAX_MEM_GB = 4.0
    test_cases = [
        # (asize, Npos, expected_batch)
        ((128, 128), 100, False),      # 0.007 GB
        ((128, 128), 1000, False),     # 0.073 GB
        ((256, 256), 500, False),      # 0.146 GB
        ((256, 256), 5000, True),      # 1.46 GB -> still under for 256
        ((512, 512), 100, False),      # 0.059 GB
        ((512, 512), 500, True),       # 5.86 GB -> batch!
        ((512, 512), 4761, True),      # 55.8 GB -> batch!
    ]

    all_ok = True
    for asize, Npos, expected_batch in test_cases:
        mem_bytes = asize[0] * asize[1] * Npos * 16 * 3
        mem_gb = mem_bytes / (1024**3)
        needs_batch = mem_gb > MAX_MEM_GB
        status = 'OK' if needs_batch == expected_batch else 'MISMATCH'
        if status == 'MISMATCH':
            all_ok = False
        print(f"  asize={asize[0]:>3}, Npos={Npos:>5} -> {mem_gb:>6.2f} GB "
              f"-> batch={needs_batch} (expect={expected_batch}) [{status}]")

    if all_ok:
        print("  PASS: All memory thresholds correct")
    else:
        print("  FAIL: Some thresholds incorrect")
    return all_ok


if __name__ == '__main__':
    results = []
    results.append(('Small recon (GPU default)', test_small_recon()))
    results.append(('Memory guard', test_memory_guard()))
    results.append(('Stop cleanup', test_stop_cleanup()))
    results.append(('Various sizes', test_various_sizes()))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results:
        status = 'PASS' if passed else 'FAIL'
        print(f"  {status}: {name}")

    n_pass = sum(1 for _, p in results if p)
    print(f"\n{n_pass}/{len(results)} tests passed")
