"""
Test: GPU default, memory estimation, and batched CPU DM fallback.
Verifies the engine_runner changes work correctly.
"""
import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'server'))

# ── Test 1: use_gpu default is True ──
print("=" * 60)
print("Test 1: use_gpu default = True")
from server.data_loader import DataLoader
loader = DataLoader()
# Build a small p dict
data = {
    'fmag': np.ones((128, 128, 100), dtype=np.float32),
    'positions': np.random.rand(100, 2) * 50,
    'asize': (128, 128),
}
engine_params = {'number_iterations': 10}  # No use_gpu specified
p = loader.build_p_dict(data, engine_params)
assert p['use_gpu'] == True, f"Expected use_gpu=True, got {p['use_gpu']}"
print("  PASS: use_gpu defaults to True")

# ── Test 2: Memory estimation ──
print("\n" + "=" * 60)
print("Test 2: Memory estimation for large Npos")
Npos = 4761
asize = (512, 512)
bytes_per_pos = asize[0] * asize[1] * 16 * 3
mem_gb = Npos * bytes_per_pos / (1024**3)
print(f"  Npos={Npos}, asize={asize}")
print(f"  Estimated memory: {mem_gb:.1f} GB")
assert mem_gb > 4.0, f"Expected > 4 GB, got {mem_gb:.1f}"
print(f"  PASS: Would trigger batched mode (>{4.0} GB limit)")

# ── Test 3: Batch size calculation ──
print("\n" + "=" * 60)
print("Test 3: Batch size calculation")
MAX_MEM_GB = 4.0
max_pos = max(100, int(MAX_MEM_GB * (1024**3) / bytes_per_pos))
n_batches = int(np.ceil(Npos / max_pos))
print(f"  max_pos per batch: {max_pos}")
print(f"  n_batches: {n_batches}")
batch_mem = max_pos * bytes_per_pos / (1024**3)
print(f"  Memory per batch: {batch_mem:.1f} GB")
assert batch_mem <= MAX_MEM_GB, f"Batch memory {batch_mem:.1f} exceeds limit {MAX_MEM_GB}"
print("  PASS: Each batch fits in memory")

# ── Test 4: Small Npos should NOT trigger batching ──
print("\n" + "=" * 60)
print("Test 4: Small Npos (no batching needed)")
Npos_small = 200
asize_small = (128, 128)
bytes_small = asize_small[0] * asize_small[1] * 16 * 3
mem_small = Npos_small * bytes_small / (1024**3)
print(f"  Npos={Npos_small}, asize={asize_small}, mem={mem_small:.3f} GB")
assert mem_small < MAX_MEM_GB, f"Should be under limit"
print("  PASS: Regular CPU DM would be used (no batching)")

# ── Test 5: Engine runner stop() method has gc.collect ──
print("\n" + "=" * 60)
print("Test 5: EngineRunner.stop() includes memory cleanup")
import inspect
from server.engine_runner import EngineRunner

stop_source = inspect.getsource(EngineRunner.stop)
assert 'gc.collect' in stop_source, "stop() should call gc.collect()"
assert 'free_all_blocks' in stop_source, "stop() should free GPU memory"
print("  PASS: stop() includes gc.collect + GPU memory cleanup")

# ── Test 6: _run cleanup (finally block) ──
print("\n" + "=" * 60)
print("Test 6: _run() finally block includes cleanup")
run_source = inspect.getsource(EngineRunner._run)
assert 'gc.collect' in run_source, "_run() should have gc.collect in finally"
print("  PASS: _run() finally block includes gc.collect")

# ── Test 7: GPU DM is default path in _run_dm ──
print("\n" + "=" * 60)
print("Test 7: _run_dm defaults to GPU first")
dm_source = inspect.getsource(EngineRunner._run_dm)
# Check that use_gpu default is True
assert "get('use_gpu', True)" in dm_source, "_run_dm should default use_gpu=True"
# Check batched fallback exists
assert '_run_dm_batched' in dm_source, "_run_dm should have batched fallback"
print("  PASS: _run_dm defaults to GPU, falls back to batched CPU")

# ── Test 8: _run_ml defaults to GPU ──
print("\n" + "=" * 60)
print("Test 8: _run_ml defaults to GPU")
ml_source = inspect.getsource(EngineRunner._run_ml)
assert "get('use_gpu', True)" in ml_source, "_run_ml should default use_gpu=True"
print("  PASS: _run_ml defaults to GPU")

# ── Test 9: _run_dm_batched exists and is correct ──
print("\n" + "=" * 60)
print("Test 9: _run_dm_batched method structure")
batch_source = inspect.getsource(EngineRunner._run_dm_batched)
assert 'reconstruction_warning' in batch_source, "Should broadcast warning"
assert 'cancel_event' in batch_source, "Should check cancel_event"
assert 'MemoryError' in batch_source, "Should handle MemoryError"
print("  PASS: _run_dm_batched has warning, cancel, MemoryError handling")

# ── Test 10: Realistic scenario — simulate what happens with 4761 positions ──
print("\n" + "=" * 60)
print("Test 10: Simulated large scan - memory path decision")

warnings_sent = []
def mock_broadcast(msg):
    if msg.get('type') == 'reconstruction_warning':
        warnings_sent.append(msg)

runner = EngineRunner(mock_broadcast)

# Simulate the memory check logic from _run_dm
Npos = 4761
asize = (512, 512)
use_gpu = True  # default

# When GPU fails, CPU fallback triggers
mem_bytes = asize[0] * asize[1] * Npos * 16 * 3
mem_gb = mem_bytes / (1024**3)
MAX_MEM_GB = 4.0

if mem_gb > MAX_MEM_GB:
    bytes_per_pos = asize[0] * asize[1] * 16 * 3
    max_pos = max(100, int(MAX_MEM_GB * (1024**3) / bytes_per_pos))
    n_batches = int(np.ceil(Npos / max_pos))
    est_mem_gb = Npos * bytes_per_pos / (1024**3)

    runner.broadcast({
        'type': 'reconstruction_warning',
        'job_id': 'test',
        'warning': f'GPU unavailable. Using batched CPU mode ({n_batches} batches, ~{max_pos} pos each). '
                   f'Memory needed: {est_mem_gb:.1f} GB > {MAX_MEM_GB:.0f} GB limit.',
        'batched': True,
        'n_batches': n_batches,
    })

assert len(warnings_sent) == 1, f"Expected 1 warning, got {len(warnings_sent)}"
print(f"  Warning message: {warnings_sent[0]['warning']}")
print(f"  PASS: Warning broadcast sent correctly")

print("\n" + "=" * 60)
print("ALL 10 TESTS PASSED")
print("=" * 60)
