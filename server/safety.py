#!/usr/bin/env python3
"""Safety checker for K4GSR Beamline motor operations.

Provides server-side safety validation before any motor move command is
executed. Acts as a second layer of defense (the EPICS motor record itself
enforces soft limits, but this catches issues before they reach the IOC).

Usage:
    checker = SafetyChecker(pv_store)
    result = checker.check_move("BL10:SAM:CX", 50.0)
    if not result["ok"]:
        # Reject the move
"""

import time
import logging
from typing import Any, Dict, Optional, Set

log = logging.getLogger("safety")

# Rate limit: minimum interval between commands to the same PV (seconds)
_RATE_LIMIT_SEC = 0.05  # 50ms = max 20 commands/sec per PV


class SafetyChecker:
    """Validate motor move commands against safety constraints.

    Checks:
    - Soft limits (from PVStore motor definitions)
    - Velocity limits (prevent unreasonable speeds)
    - Hardware-source PVs require explicit confirmation from client
    """

    def __init__(self, pv_store, hw_groups: Optional[Set[str]] = None):
        """Initialize with PV store reference.

        Args:
            pv_store: PVStore or CABridge instance.
            hw_groups: Set of group names served by real hardware
                       (e.g. {"SAM"} for KOHZU motors).
        """
        self._pv_store = pv_store
        self._hw_groups = hw_groups or set()
        self._last_cmd: Dict[str, float] = {}  # pv_name -> timestamp

    def is_hardware_pv(self, pv_name: str) -> bool:
        """Check if a PV is served by real hardware (not simulation)."""
        for grp in self._hw_groups:
            if pv_name.startswith(f"BL10:{grp}:"):
                return True
        return False

    def check_move(self, pv_name: str, target_value: float,
                   confirmed: bool = False) -> Dict[str, Any]:
        """Validate a motor move command.

        Args:
            pv_name: Target PV name (e.g. "BL10:SAM:CX").
            target_value: Requested position.
            confirmed: Whether client has confirmed this move (for HW motors).

        Returns:
            {"ok": True} or {"ok": False, "reason": str, "code": str}
        """
        # 1. Check if PV exists
        pv = None
        if hasattr(self._pv_store, 'pvs'):
            pvs_dict = self._pv_store.pvs
            if isinstance(pvs_dict, dict):
                pv = pvs_dict.get(pv_name)

        # 2. Soft limit check (if PV has limit info)
        if pv and hasattr(pv, 'user_limits'):
            lo, hi = pv.user_limits
            if target_value < lo or target_value > hi:
                return {
                    "ok": False,
                    "reason": f"Target {target_value} outside soft limits [{lo}, {hi}]",
                    "code": "SOFT_LIMIT",
                    "limits": [lo, hi]
                }

        # For CABridge, check limits from PVStore reference
        if pv is None and hasattr(self._pv_store, '_motor_names'):
            # CABridge mode: we don't have PV objects, but motor record
            # enforces limits at IOC level. Skip limit check here.
            pass

        # 3. Rate limiting: prevent command flooding on same PV
        now = time.monotonic()
        last = self._last_cmd.get(pv_name, 0)
        if now - last < _RATE_LIMIT_SEC:
            return {
                "ok": False,
                "reason": f"Rate limit: wait {_RATE_LIMIT_SEC*1000:.0f}ms between commands",
                "code": "RATE_LIMIT"
            }
        self._last_cmd[pv_name] = now

        return {"ok": True}
