"""Shared pytest fixtures for K4GSR BL10 NanoProbe tests."""
import os
import sys
import json
import tempfile
import shutil
import pytest

# Ensure server/ is importable
SERVER_DIR = os.path.join(os.path.dirname(__file__), '..', 'server')
sys.path.insert(0, os.path.abspath(SERVER_DIR))


# ── Temporary directory fixtures ──────────────────────────────────

@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a clean temporary directory."""
    return tmp_path


@pytest.fixture
def data_dir(tmp_path):
    """Provide a temp data directory mimicking server/data/scans/."""
    d = tmp_path / "scans"
    d.mkdir()
    return d


# ── PVStore fixtures ─────────────────────────────────────────────

@pytest.fixture
def pv_store():
    """Fresh PVStore instance."""
    from pv_store import PVStore
    return PVStore(scan_rate=0.1)


# ── ScanDB fixtures ──────────────────────────────────────────────

@pytest.fixture
def scan_db(tmp_path):
    """ScanDB with temp database file."""
    from data.scan_db import ScanDB
    db_path = str(tmp_path / "test_scan_history.db")
    db = ScanDB(db_path=db_path)
    yield db
    db.close()


# ── NexusWriter fixtures ─────────────────────────────────────────

@pytest.fixture
def h5_path(tmp_path):
    """Temporary HDF5 file path."""
    return str(tmp_path / "test_output.h5")


# ── NLP Agent fixtures ───────────────────────────────────────────

@pytest.fixture
def nlp_agent_no_backend():
    """NLPAgent with no backend (for JSON extraction testing)."""
    from nlp_agent import NLPAgent
    agent = NLPAgent()
    return agent


# ── Sample data fixtures ─────────────────────────────────────────

@pytest.fixture
def sample_scan_metadata():
    """Sample scan metadata dict."""
    return {
        "uid": "abcd1234-5678-90ab-cdef-1234567890ab",
        "plan_name": "energy_scan",
        "status": "success",
        "start_time": "2026-02-15T10:00:00",
        "end_time": "2026-02-15T10:05:00",
        "num_points": 50,
        "energy_keV": 10.0,
        "params": {"e_start": 9.9, "e_stop": 10.1, "n_points": 50},
        "notes": "Test scan"
    }


@pytest.fixture
def sample_nlp_response():
    """Sample NLP agent JSON response."""
    return {
        "actions": [
            {"fn": "setTargetEnergy", "args": [10.0]},
            {"fn": "runFullAlignment", "args": []}
        ],
        "explanation": "에너지를 10 keV로 설정하고 전체 정렬을 수행합니다.",
        "confirmation_required": True,
        "type": "nlp_response"
    }
