#!/usr/bin/env python3
"""PV Auto-Discovery for K4GSR Beamline.

Periodically probes for new PVs on the CA network that are not in the
server's known PV set. When found, reports them to connected WebSocket
clients so the browser UI can offer placement options.

Usage:
    Used internally by server.py when --ca-bridge is active.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Set

log = logging.getLogger("pv-discovery")

try:
    from caproto.threading.client import Context
    _CA_AVAILABLE = True
except ImportError:
    _CA_AVAILABLE = False


class PVDiscovery:
    """Probe candidate PV names and detect newly-available ones.

    Args:
        known_pvs: Set of PV names already managed by the server.
        probe_interval: Seconds between discovery scans.
    """

    def __init__(self, known_pvs: Set[str], probe_interval: float = 30.0):
        self.known_pvs = set(known_pvs)
        self.probe_interval = probe_interval
        self._discovered: Set[str] = set()
        self._candidates: List[str] = []
        self._ctx: Optional[object] = None

    def set_candidates(self, candidates: List[str]):
        """Set PV names to probe. Only names not in known_pvs are kept."""
        self._candidates = [c for c in candidates if c not in self.known_pvs
                            and c not in self._discovered]
        if self._candidates:
            log.info(f"PV Discovery: {len(self._candidates)} candidate PVs to probe")

    def add_to_known(self, pv_name: str):
        """Mark a PV as known (e.g. after user places it in a device group)."""
        self.known_pvs.add(pv_name)
        self._discovered.discard(pv_name)

    def scan(self) -> List[Dict]:
        """Try to connect to candidate PVs. Returns list of newly found PVs.

        Each entry: {"name": str, "value": float, "type": "motor"|"status"}
        Blocking call — run in executor from async context.
        """
        if not self._candidates or not _CA_AVAILABLE:
            return []

        # Lazy-init CA context
        if self._ctx is None:
            try:
                self._ctx = Context()
            except Exception as e:
                log.warning(f"PV Discovery: cannot create CA context: {e}")
                return []

        new_pvs = []
        remaining = []

        for pv_name in self._candidates:
            if pv_name in self._discovered or pv_name in self.known_pvs:
                continue
            try:
                pvs = self._ctx.get_pvs(pv_name, timeout=1.0)
                val = float(pvs[0].read(timeout=1.0).data[0])
                self._discovered.add(pv_name)
                new_pvs.append({
                    "name": pv_name,
                    "value": val,
                    "type": "motor"  # assume motor; server can refine
                })
                log.info(f"PV Discovery: found new PV {pv_name} = {val}")
            except Exception:
                remaining.append(pv_name)

        self._candidates = remaining
        return new_pvs

    def generate_candidates(self, hw_groups: Set[str],
                            axis_names: Optional[List[str]] = None,
                            skip_groups: Optional[Set[str]] = None,
                            ) -> List[str]:
        """Generate candidate PV names from naming convention.

        For each hardware group, generates BL10:{group}:{axis} for common axes.

        Args:
            hw_groups: Set of group names to probe.
            axis_names: List of axis suffixes to probe.
            skip_groups: Groups to skip (e.g. DBPM groups that have no motor
                         axes). Their PVs use non-standard names (quadEM etc.)
                         and should not be probed with standard motor axes.
        """
        if axis_names is None:
            # Common motor axis names for beamline stages
            axis_names = [
                "CX", "CY", "CZ", "FX", "FY", "FZ",
                "SX", "SY", "SZ",
                "Theta", "Phi", "Chi",
                "RX", "RY", "RZ",
                "Pitch", "Roll", "Yaw",
                "TX", "TY", "TZ",
                "X", "Y", "Z",
            ]
        skip = skip_groups or set()

        candidates = []
        for grp in hw_groups:
            if grp in skip:
                log.info(f"PV Discovery: skipping group {grp} "
                         f"(non-motor device, e.g. DBPM)")
                continue
            prefix = f"BL10:{grp}"
            for ax in axis_names:
                pv = f"{prefix}:{ax}"
                if pv not in self.known_pvs and pv not in self._discovered:
                    candidates.append(pv)
        return candidates
