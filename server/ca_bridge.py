#!/usr/bin/env python3
"""Channel Access bridge for server.py -- Digital Twin Architecture.

Uses caproto subscribe() callbacks for event-driven PV updates (no polling).
soft_ioc (caproto) serves all simulation PVs on CA port 5064.
Hardware IOCs (KOHZU etc.) serve real motor PVs on dedicated ports.

Port routing:
  EPICS_CA_ADDR_LIST = "127.0.0.1:5070 127.0.0.1:5064"  (HW ports first)

  HW groups (e.g. SAM -> port 5070):
    - CX/CY/CZ: served by KOHZU IOC (real hardware, shadows soft_ioc)
    - FX/FY/FZ/Phi etc: not in KOHZU yet -> served by soft_ioc (simulation)
    - CA ADDR_LIST priority: KOHZU wins for shared PV names

  Sim groups (DCM, M1, M2, ...):
    - READ/WRITE via soft_ioc (port 5064)

Adding new hardware IOC:
  1. Assign a new port (e.g. PIMARS -> 5071) in deploy/config.env
  2. Pass hw_groups_ports={"SAM": 5070, "PIMARS": 5071} to CABridge
  3. Set EPICS_IOC_ADDR_LIST="127.0.0.1:5071 127.0.0.1:5070 127.0.0.1:5064"
  -> No other code changes needed.

Architecture (subscribe-based, no polling):
  - Motor PVs: .RBV subscribe() callback (ophyd standard)
  - Status PVs: .VAL subscribe() callback
  - Motor limits: .LLM/.HLM/.VELO read once at startup (ophyd standard)
  - caput: ca_pv.write() for immediate writes
  - No polling thread -- purely event-driven via caproto subscribe.
"""

import os
import time
import threading
import logging
from typing import Dict, Set, Optional, Any

log = logging.getLogger("ca-bridge")

try:
    from caproto.threading.client import Context
    _CA_AVAILABLE = True
except ImportError:
    _CA_AVAILABLE = False
    log.warning("caproto.threading.client not available")


def _pv_group(pv_name: str) -> Optional[str]:
    """Extract group name from BL10:{GROUP}:{AXIS} PV name."""
    if pv_name.startswith("BL10:"):
        parts = pv_name.split(":")
        if len(parts) >= 3:
            return parts[1]
    return None


class CABridge:
    """PVStore-compatible CA bridge with subscribe-based updates.

    Connects to multiple IOCs (soft_ioc + hardware IOCs) using port-based
    routing. Uses caproto subscribe() callbacks for RBV/status updates.

    Args:
        pv_definitions: {pv_name: PV} from PVStore -- defines all known PVs.
        hw_groups_ports: {group_name: ca_port} for hardware IOCs.
                         e.g. {"SAM": 5070}
        soft_port: CA port for soft_ioc (default 5064).
        timeout: initial CA connection timeout in seconds.
    """

    def __init__(self,
                 pv_definitions: dict,
                 hw_groups_ports: Optional[Dict[str, int]] = None,
                 soft_port: int = 5064,
                 timeout: float = 10.0):
        if not _CA_AVAILABLE:
            raise RuntimeError("caproto is not installed")

        self._timeout = timeout
        self._soft_port = soft_port
        self._hw_groups_ports: Dict[str, int] = hw_groups_ports or {}
        self._lock = threading.Lock()
        self._changed: Dict[str, Dict[str, Any]] = {}
        self._values: Dict[str, float] = {}
        self._severities: Dict[str, int] = {}
        self._motor_names: Set[str] = set()
        self._status_names: Set[str] = set()
        self._ca_pvs: Dict[str, Any] = {}      # ca_name -> caproto PV object
        self._hw_pvs: Set[str] = set()
        self._subscriptions = []                # keep refs to prevent GC
        self._running = True

        # Classify PVs and identify hw_pvs
        all_ca_names = []
        poll_targets = {}  # base_name -> ca_name (for initial read)
        for name, pv in pv_definitions.items():
            grp = _pv_group(name)
            if grp and grp in self._hw_groups_ports:
                self._hw_pvs.add(name)

            if pv.speed > 0:
                self._motor_names.add(name)
                all_ca_names.append(name)
                all_ca_names.append(name + '.RBV')
                all_ca_names.append(name + '.LLM')
                all_ca_names.append(name + '.HLM')
                all_ca_names.append(name + '.VELO')
                poll_targets[name] = name + '.RBV'
            else:
                self._status_names.add(name)
                all_ca_names.append(name)
                poll_targets[name] = name

        n_motor = len(self._motor_names)
        n_status = len(self._status_names)
        n_hw = len(self._hw_pvs)
        log.info(f"CA Bridge: {len(all_ca_names)} channels "
                 f"({n_motor} motors + {n_status} status, {n_hw} hw_pvs)")
        if self._hw_groups_ports:
            for grp, port in self._hw_groups_ports.items():
                log.info(f"  {grp} -> port {port} (real hardware)")
            log.info(f"  sim  -> port {soft_port} (soft_ioc)")

        # Build ADDR_LIST: HW ports first so caproto prefers real hardware.
        # Also include EPICS_IOC_ADDR_LIST from config.env if available
        # (needed for multi-homed VM1 where IOCs bind to 192.168.101.212).
        hw_addrs = [f"127.0.0.1:{p}"
                    for p in sorted(set(self._hw_groups_ports.values()))]
        soft_addr = f"127.0.0.1:{soft_port}"
        base_addrs = hw_addrs + [soft_addr]

        # Merge extra IOC addresses from environment (e.g. "192.168.101.212")
        extra = os.environ.get("EPICS_IOC_ADDR_LIST", "")
        if extra:
            for addr in extra.split():
                if addr not in base_addrs:
                    base_addrs.append(addr)
        addr_list = " ".join(base_addrs)

        os.environ["EPICS_CA_ADDR_LIST"] = addr_list
        os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
        log.info(f"CA Bridge: EPICS_CA_ADDR_LIST={addr_list}")

        # Connect to all PVs (batch)
        self._ctx = Context()
        try:
            raw_pvs = self._ctx.get_pvs(*all_ca_names, timeout=timeout)
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to CA PVs (are IOCs running?): {e}"
            )

        for ca_name, ca_pv in zip(all_ca_names, raw_pvs):
            self._ca_pvs[ca_name] = ca_pv

        # --- Read initial values (blocking, one-time) ---
        connected = 0
        for base_name, ca_name in sorted(poll_targets.items()):
            ca_pv = self._ca_pvs.get(ca_name)
            if ca_pv is None:
                self._values[base_name] = 0.0
                self._severities[base_name] = 3
                continue
            try:
                resp = ca_pv.read(timeout=min(timeout, 2.0))
                val = float(resp.data[0])
                self._values[base_name] = val
                self._severities[base_name] = 0
                connected += 1
            except Exception as e:
                log.warning(f"CA initial read failed for {ca_name}: {e}")
                self._values[base_name] = 0.0
                self._severities[base_name] = 3

        log.info(f"CA Bridge: {connected}/{n_motor + n_status} PVs connected")

        # --- Read motor limit/speed fields (one-time, ophyd standard) ---
        limit_read = 0
        for name in sorted(self._motor_names):
            for suffix in ['.LLM', '.HLM', '.VELO']:
                full_name = name + suffix
                ca_pv = self._ca_pvs.get(full_name)
                if ca_pv is None:
                    continue
                try:
                    resp = ca_pv.read(timeout=min(timeout, 2.0))
                    self._values[full_name] = float(resp.data[0])
                    limit_read += 1
                except Exception:
                    pass
        if limit_read > 0:
            log.info(f"CA Bridge: {limit_read} motor limit/speed fields read "
                     f"(LLM/HLM/VELO)")

        # --- Set up subscribe callbacks (event-driven, no polling) ---
        n_subs = 0

        # Motor .RBV subscribes
        for name in sorted(self._motor_names):
            rbv_name = name + '.RBV'
            ca_pv = self._ca_pvs.get(rbv_name)
            if ca_pv is None:
                continue
            try:
                motor_name = name  # capture for closure
                def _make_rbv_cb(mn):
                    def _cb(sub, response):
                        self._on_rbv_change(mn, response)
                    return _cb
                sub = ca_pv.subscribe(data_type='time')
                sub.add_callback(_make_rbv_cb(motor_name))
                self._subscriptions.append(sub)
                n_subs += 1
            except Exception as e:
                log.warning(f"CA subscribe failed for {rbv_name}: {e}")

        # Status PV subscribes
        for name in sorted(self._status_names):
            ca_pv = self._ca_pvs.get(name)
            if ca_pv is None:
                continue
            try:
                pv_name = name
                def _make_status_cb(pn):
                    def _cb(sub, response):
                        self._on_status_change(pn, response)
                    return _cb
                sub = ca_pv.subscribe(data_type='time')
                sub.add_callback(_make_status_cb(pv_name))
                self._subscriptions.append(sub)
                n_subs += 1
            except Exception as e:
                log.warning(f"CA subscribe failed for {name}: {e}")

        log.info(f"CA Bridge: {n_subs} subscriptions active (event-driven)")

    # ------------------------------------------------------------------
    # Subscribe callbacks
    # ------------------------------------------------------------------

    def _on_rbv_change(self, motor_name: str, response):
        """Subscribe callback for motor .RBV."""
        try:
            val = float(response.data[0])
        except Exception:
            return
        now = time.time()
        with self._lock:
            self._values[motor_name] = val
            self._severities[motor_name] = 0
            entry = {
                "pv": motor_name,
                "value": val,
                "severity": 0,
                "timestamp": now,
            }
            self._changed[motor_name] = entry
            self._changed[motor_name + '.RBV'] = {
                "pv": motor_name + '.RBV',
                "value": val,
                "severity": 0,
                "timestamp": now,
            }

    def _on_status_change(self, pv_name: str, response):
        """Subscribe callback for status PVs."""
        try:
            val = float(response.data[0])
        except Exception:
            return
        now = time.time()
        with self._lock:
            self._values[pv_name] = val
            self._severities[pv_name] = 0
            self._changed[pv_name] = {
                "pv": pv_name,
                "value": val,
                "severity": 0,
                "timestamp": now,
            }

    # ------------------------------------------------------------------
    # PVStore-compatible interface
    # ------------------------------------------------------------------

    @property
    def pvs(self):
        return self._values

    def caput(self, pv_name: str, value: float) -> bool:
        """Write a value via CA. For motors, writes to setpoint channel."""
        ca_pv = self._ca_pvs.get(pv_name)
        if ca_pv is None:
            log.warning(f"CA put: unknown PV {pv_name}")
            return False
        try:
            ca_pv.write([value], timeout=self._timeout)
            return True
        except Exception as e:
            log.error(f"CA put {pv_name}={value} failed: {e}")
            return False

    def caget(self, pv_name: str) -> Optional[Dict[str, Any]]:
        """Return cached PV value. Subscriptions keep _values up-to-date.
        Note: do NOT perform blocking CA reads here -- called from asyncio."""
        now = time.time()

        if pv_name in self._values:
            return {
                "pv": pv_name,
                "value": self._values[pv_name],
                "severity": self._severities.get(pv_name, 0),
                "timestamp": now,
            }
        if pv_name.endswith('.RBV'):
            base = pv_name[:-4]
            if base in self._values and base in self._motor_names:
                return {
                    "pv": pv_name,
                    "value": self._values[base],
                    "severity": self._severities.get(base, 0),
                    "timestamp": now,
                }
        return None

    def scan(self):
        """No-op. Subscribe-based -- no polling needed."""
        pass

    def get_changed(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            result = dict(self._changed)
            self._changed.clear()
        return result

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        now = time.time()
        return {
            name: {
                "pv": name,
                "value": val,
                "severity": self._severities.get(name, 0),
                "timestamp": now,
            }
            for name, val in self._values.items()
        }

    def get_connected_pvs(self) -> set:
        return set(self._values.keys())

    def close(self):
        """Close all subscriptions."""
        log.info("CA Bridge: closing")
        self._running = False
        self._subscriptions.clear()
        self._ca_pvs.clear()
