#!/usr/bin/env python3
"""p4p CA failure diagnosis - 3 tests in order."""
import os
import sys

# ============================================================
# Test 1: PVXS debug log (where exactly does it fail?)
# ============================================================
print("=" * 60)
print("TEST 1: PVXS debug log")
print("=" * 60)

os.environ["EPICS_CA_ADDR_LIST"] = "127.0.0.1:5064"
os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
os.environ["PVXS_LOG"] = "pvxs.*:5"

from p4p.client.thread import Context

ctx1 = Context("ca")
try:
    val = ctx1.get("BL10:DCM:Theta", timeout=5.0)
    print(f"\n  RESULT: OK = {val}")
except Exception as e:
    print(f"\n  RESULT: FAIL {type(e).__name__}")
ctx1.close()

# ============================================================
# Test 2: Force loopback interface binding
# ============================================================
print("\n" + "=" * 60)
print("TEST 2: EPICS_CA_INTF_ADDR_LIST=127.0.0.1 (force loopback)")
print("=" * 60)

os.environ.pop("PVXS_LOG", None)
os.environ["EPICS_CA_ADDR_LIST"] = "127.0.0.1:5064"
os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
os.environ["EPICS_CAS_INTF_ADDR_LIST"] = "127.0.0.1"

# NOTE: EPICS base reads env only on first ca_context_create per process.
# So we test this in a subprocess.
import subprocess
code = '''
import os
os.environ["EPICS_CA_ADDR_LIST"] = "127.0.0.1:5064"
os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
os.environ["EPICS_CAS_INTF_ADDR_LIST"] = "127.0.0.1"
from p4p.client.thread import Context
ctx = Context("ca")
try:
    val = ctx.get("BL10:DCM:Theta", timeout=5.0)
    print(f"OK = {val}")
except Exception as e:
    print(f"FAIL {type(e).__name__}")
ctx.close()
'''
r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=15)
print(f"  stdout: {r.stdout.strip()}")
if r.stderr.strip():
    # Only last 5 lines of stderr
    lines = r.stderr.strip().split('\n')
    for line in lines[-5:]:
        print(f"  stderr: {line}")

# ============================================================
# Test 3: pyepics (direct libca, not PVXS)
# ============================================================
print("\n" + "=" * 60)
print("TEST 3: pyepics (direct libca wrapper)")
print("=" * 60)

# Install pyepics in subprocess if needed, then test
code2 = '''
import os, sys
os.environ["EPICS_CA_ADDR_LIST"] = "127.0.0.1:5064"
os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
try:
    from epics import caget
    val = caget("BL10:DCM:Theta", timeout=5.0)
    if val is not None:
        print(f"OK = {val}")
    else:
        print("FAIL: caget returned None")
except ImportError:
    # Try to install
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyepics", "-q"])
    from epics import caget
    val = caget("BL10:DCM:Theta", timeout=5.0)
    if val is not None:
        print(f"OK = {val}")
    else:
        print("FAIL: caget returned None")
except Exception as e:
    print(f"FAIL {type(e).__name__}: {e}")
'''
r2 = subprocess.run([sys.executable, "-c", code2], capture_output=True, text=True, timeout=30)
print(f"  stdout: {r2.stdout.strip()}")
if r2.stderr.strip():
    lines = r2.stderr.strip().split('\n')
    for line in lines[-5:]:
        print(f"  stderr: {line}")

print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
