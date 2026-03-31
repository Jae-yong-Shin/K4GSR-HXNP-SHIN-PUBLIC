"""PV Store — Python equivalent of the JS SimIOC class.

Manages all simulated Process Variables (PVs) for the K4GSR beamline.
Provides motor movement simulation, BPM noise, ring status, and alarm checking.
"""

import time
import math
import random
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, Set, Optional, Any

log = logging.getLogger(__name__)


@dataclass
class PV:
    value: float = 0.0
    setpoint: float = 0.0
    moving: bool = False
    speed: float = 1.0
    severity: int = 0  # 0=NO_ALARM, 1=MINOR, 2=MAJOR, 3=INVALID
    lo_limit: float = -1e6
    hi_limit: float = 1e6
    unit: str = ""


class PVStore:
    """In-memory PV store with motor simulation, matching JS SimIOC behavior."""

    def __init__(self, scan_rate: float = 0.1):
        self.pvs: Dict[str, PV] = {}
        self.scan_rate = scan_rate  # seconds
        self._changed: Set[str] = set()
        self._lock = threading.RLock()
        self._init_pvs()

    def _init_pvs(self):
        """Initialize all PVs matching JS DEVICE_CONFIGS with real hardware specs."""

        # ── Source (IVU24 Undulator, 24mm period, 123 periods) ──
        self._add_motor("BL10:IVU:Gap",         7.0,   5,    25,   0.5,  "mm")
        self._add_motor("BL10:IVU:TaperGap",    0.0,  -2,     2,   0.5,  "mm")
        self._add_motor("BL10:IVU:Harmonic",    5,     1,    13,   1,    "")
        self._add_motor("BL10:IVU:GirderX",     0.0,  -5,     5,   1,    "mm")
        self._add_motor("BL10:IVU:GirderY",     0.0,  -5,     5,   1,    "mm")
        self._add_motor("BL10:IVU:GirderPitch", 0.0, -200,  200,  50,    "urad")
        self._add_motor("BL10:IVU:GirderYaw",   0.0, -200,  200,  50,    "urad")
        self._add_motor("BL10:IVU:EncUS",       7.0,   5,    25,   0.5,  "mm")
        self._add_motor("BL10:IVU:EncDS",       7.0,   5,    25,   0.5,  "mm")

        # ── Front-End Masks ──
        for prefix in ["BL10:FMASK", "BL10:MMASK"]:
            self._add_motor(f"{prefix}:X", 0, -20, 20, 2, "mm")
            self._add_motor(f"{prefix}:Y", 0, -20, 20, 2, "mm")
            self._add_motor(f"{prefix}:Hgap", 4.0, 0.1, 20, 1, "mm")
            self._add_motor(f"{prefix}:Vgap", 4.0, 0.1, 20, 1, "mm")

        # ── White Beam Slit (JJ X-Ray 24053, 50mm stroke, self-locking worm) ──
        self._add_motor("BL10:WBS:Top", 0.5, -25, 25, 1, "mm")
        self._add_motor("BL10:WBS:Bot", -0.5, -25, 25, 1, "mm")
        self._add_motor("BL10:WBS:Inb", -1, -25, 25, 1, "mm")
        self._add_motor("BL10:WBS:Outb", 1, -25, 25, 1, "mm")
        self._add_motor("BL10:WBS:Hgap", 2.0, 0.01, 48, 1, "mm")
        self._add_motor("BL10:WBS:Vgap", 1.0, 0.01, 48, 1, "mm")

        # ── Attenuator (between WB Slit 27.8m and XBPM-WB 28.5m) ──
        self._add_motor("BL10:ATT:X", 0, -25, 25, 0.01, "mm")
        self._add_motor("BL10:ATT:Y", 0, -25, 25, 0.01, "mm")

        # ── M1 Mirror (FMB Oxford HHLMS, 6 motorized + 2 manual) ──
        self._add_motor("BL10:M1:Z", 0, -5, 5, 0.5, "mm")           # vertical (wedge)
        self._add_motor("BL10:M1:Pitch", 2.5, -2, 5, 0.5, "mrad")   # fixed curvature, 2.5 mrad nominal
        self._add_motor("BL10:M1:PitchF", 0, -50, 50, 100, "urad")  # PI P-843 piezo
        self._add_motor("BL10:M1:Tx", 0, -10, 10, 1, "mm")          # lateral (in-vacuum)
        self._add_motor("BL10:M1:Roll", 0, -2, 2, 1, "mrad")        # manual
        self._add_motor("BL10:M1:Yaw", 0, -2, 2, 1, "mrad")        # manual
        # M1 has no bender (fixed curvature mirror)

        # ── DCM (XDS Oxford HDCM-HCCM Q11055, 8 axes, ACS SPiiEC) ──
        self._add_motor("BL10:DCM:Theta", 11.402, -1, 20, 0.05, "deg")
        self._add_motor("BL10:DCM:Y1", 0, -2.5, 2.5, 0.5, "mm")       # 1st crystal y-translation
        self._add_motor("BL10:DCM:Chi1", 0, -300, 300, 1, "arcsec")
        self._add_motor("BL10:DCM:TX", 0, -12.5, 12.5, 0.5, "mm")   # stripe selection
        self._add_motor("BL10:DCM:Y2", 0, -25, 25, 0.5, "mm")        # beam offset
        self._add_motor("BL10:DCM:Z2", 6.12, 0, 25, 0.5, "mm")      # crystal gap (perp to C1)
        self._add_motor("BL10:DCM:DTheta2", 0, -2520, 2520, 10, "arcsec")  # 2nd crystal pitch
        self._add_motor("BL10:DCM:Roll2", 0, -2520, 2520, 10, "arcsec")    # 2nd crystal roll
        self._add_motor("BL10:DCM:DTheta2F", 0, -10.3, 10.3, 100, "arcsec")  # piezo fine

        # ── M2 Mirror (FMB Oxford HHLMS, same as M1) ──
        self._add_motor("BL10:M2:Z", 0, -5, 5, 0.5, "mm")
        self._add_motor("BL10:M2:Pitch", 2.5, -2, 5, 0.5, "mrad")   # bendable, 2.5 mrad nominal
        self._add_motor("BL10:M2:PitchF", 0, -50, 50, 100, "urad")
        self._add_motor("BL10:M2:Tx", 0, -10, 10, 1, "mm")
        self._add_motor("BL10:M2:Roll", 0, -2, 2, 1, "mrad")
        self._add_motor("BL10:M2:Yaw", 0, -2, 2, 1, "mrad")
        self._add_motor("BL10:M2:BendU", 0, -50, 50, 1, "Nm")
        self._add_motor("BL10:M2:BendD", 0, -50, 50, 1, "Nm")

        # ── SSA ──
        self._add_motor("BL10:SSA:Hgap", 50, 1, 500, 1, "um")
        self._add_motor("BL10:SSA:Vgap", 50, 1, 500, 1, "um")
        self._add_motor("BL10:SSA:Hcen", 0, -500, 500, 1, "um")
        self._add_motor("BL10:SSA:Vcen", 0, -500, 500, 1, "um")

        # ── KB Upstream Slit (500mm upstream KB-V) ──
        self._add_motor("BL10:KBS:Hgap", 5000, 1, 10000, 50, "um")
        self._add_motor("BL10:KBS:Vgap", 5000, 1, 10000, 50, "um")
        self._add_motor("BL10:KBS:Hcen", 0, -5000, 5000, 1, "um")
        self._add_motor("BL10:KBS:Vcen", 0, -5000, 5000, 1, "um")

        # ── KB-V Mirror (JTEC JM2000-200 VFM) ──
        self._add_motor("BL10:KBV:X", 0, -2, 2, 0.5, "mm")
        self._add_motor("BL10:KBV:Y", 0, -15, 15, 0.5, "mm")       # height (deflection axis)
        self._add_motor("BL10:KBV:Z", 0, -100, 100, 0.5, "mm")     # along-beam
        self._add_motor("BL10:KBV:Pitch", 3.0, -2, 5, 0.2, "mrad")
        self._add_motor("BL10:KBV:BendU", 0, -20, 20, 1, "Nm")
        self._add_motor("BL10:KBV:BendD", 0, -20, 20, 1, "Nm")

        # ── KB-H Mirror (JTEC JM2000-200 HFM) ──
        self._add_motor("BL10:KBH:X", 0, -15, 15, 0.5, "mm")
        self._add_motor("BL10:KBH:Y", 0, -2, 2, 0.5, "mm")         # height (sagittal)
        self._add_motor("BL10:KBH:Z", 0, -100, 100, 0.5, "mm")     # along-beam
        self._add_motor("BL10:KBH:Pitch", 3.0, -2, 5, 0.2, "mrad")
        self._add_motor("BL10:KBH:BendU", 0, -20, 20, 1, "Nm")
        self._add_motor("BL10:KBH:BendD", 0, -20, 20, 1, "Nm")

        # ── Zone Plate ──
        self._add_motor("BL10:ZP:X", 0, -2000, 2000, 1, "um")
        self._add_motor("BL10:ZP:Y", 0, -2000, 2000, 1, "um")
        self._add_motor("BL10:ZP:Z", 0, -5000, 5000, 1, "um")

        # ── Sample Stage (KOHZU coarse + PI PIMars nano + PI scanner + PI rotation) ──
        self._add_motor("BL10:SAM:CX", 0, -34, 34, 2, "mm")        # KOHZU XA07A-L202 (±35mm, Lead 1.0mm)
        self._add_motor("BL10:SAM:CY", 0, -34, 34, 2, "mm")        # KOHZU XA07A-L202 (±35mm, Lead 1.0mm)
        self._add_motor("BL10:SAM:CZ", 0, -9.5, 9.5, 1, "mm")     # KOHZU ZA07A-V1F01 (±10mm, Lead 0.5mm)
        self._add_motor("BL10:SAM:Theta", 0, -180, 180, 200, "deg") # PI L-611.90AD
        self._add_motor("BL10:SAM:Phi", 0, -5, 5, 2, "deg")        # SmarAct tilt
        self._add_motor("BL10:SAM:FX", 0, -150, 150, 50, "um")     # PI P-563.3CD PIMars
        self._add_motor("BL10:SAM:FY", 0, -150, 150, 50, "um")     # PI P-563.3CD PIMars
        self._add_motor("BL10:SAM:FZ", 0, -150, 150, 50, "um")     # PI P-563.3CD PIMars
        self._add_motor("BL10:SAM:SX", 0, -50, 50, 100, "um")      # PI P-733.2CD scanner
        self._add_motor("BL10:SAM:SY", 0, -50, 50, 100, "um")      # PI P-733.2CD scanner

        # ── Fast Nano Scanner (SmarAct MCS2 + PicoScale interferometer) ──
        self._add_motor("BL10:SCAN:X", 0, -5000, 5000, 100, "nm")   # MCS2 ch0 (X axis)
        self._add_motor("BL10:SCAN:Y", 0, -5000, 5000, 100, "nm")   # MCS2 ch1 (Y axis)
        self._add_motor("BL10:SCAN:Z", 0, -5000, 5000, 100, "nm")   # MCS2 ch2 (Z axis)

        # ── Detector ──
        self._add_motor("BL10:DET:X", 0, -50, 50, 1, "mm")
        self._add_motor("BL10:DET:Y", 0, -50, 50, 1, "mm")
        self._add_motor("BL10:DET:Z", 0, 0, 5000, 5, "mm")

        # ── Virtual Readback PVs (no motor movement) ──
        self._add_readback("BL10:RING:Current", 400.0)
        self._add_readback("BL10:RING:Energy", 4.0)
        self._add_readback("BL10:RING:Lifetime", 12.5)
        self._add_readback("BL10:FE:Shutter", 1)
        self._add_readback("BL10:XBPM1:X", 0)   # Sydor SIDBPM403
        self._add_readback("BL10:XBPM1:Y", 0)
        # ── XBPM2 (Sydor SI-DBPM-M403V + T4U Electrometer, quadEM IOC PVs) ──
        # PV names match actual T4UDirect_EM IOC (PREFIX=BL10:, RECORD=XBPM2:)
        self._add_readback("BL10:XBPM2:Current1:MeanValue_RBV", 0)  # Ch A (nA)
        self._add_readback("BL10:XBPM2:Current2:MeanValue_RBV", 0)  # Ch B (nA)
        self._add_readback("BL10:XBPM2:Current3:MeanValue_RBV", 0)  # Ch C (nA)
        self._add_readback("BL10:XBPM2:Current4:MeanValue_RBV", 0)  # Ch D (nA)
        self._add_readback("BL10:XBPM2:SumAll:MeanValue_RBV", 0)    # A+B+C+D total
        self._add_readback("BL10:XBPM2:PosX:MeanValue_RBV", 0)      # Normalized X
        self._add_readback("BL10:XBPM2:PosY:MeanValue_RBV", 0)      # Normalized Y
        self._add_readback("BL10:XBPM2:Range", 2)       # Gain range (0=Low,1=Med,2=Hi)
        self._add_readback("BL10:XBPM2:BiasPEn", 0)     # Bias enable
        self._add_readback("BL10:XBPM2:SampleFreq", 10000)  # Sampling Hz
        self._add_readback("BL10:XBPM2:Acquire", 0)     # Acquisition status
        # ── Fast Nano Scanner readback (PicoScale encoder, scan status) ──
        self._add_readback("BL10:SCAN:PX", 0.0)       # PicoScale ch0 X position (nm)
        self._add_readback("BL10:SCAN:PY", 0.0)       # PicoScale ch1 Y position (nm)
        self._add_readback("BL10:SCAN:PZ", 0.0)       # PicoScale ch2 Z position (nm)
        self._add_readback("BL10:SCAN:Status", 0)     # 0=idle, 1=scanning, 2=error
        self._add_readback("BL10:SCAN:Progress", 0.0) # Scan progress 0-100%
        self._add_readback("BL10:IC1:Current", 1e-9)

    def _add_motor(self, name: str, value: float, lo: float, hi: float,
                   speed: float, unit: str = ""):
        self.pvs[name] = PV(
            value=value, setpoint=value, moving=False,
            speed=speed, severity=0, lo_limit=lo, hi_limit=hi, unit=unit
        )

    def _add_readback(self, name: str, value: float):
        self.pvs[name] = PV(
            value=value, setpoint=value, moving=False,
            speed=0, severity=0
        )

    def _auto_create(self, pv_name: str, value: float = 0.0) -> 'PV':
        """Auto-create a PV when JS sends an unknown name (motor by default)."""
        log.info(f"Auto-creating PV '{pv_name}' (value={value})")
        self._add_motor(pv_name, value, -1e6, 1e6, 1.0, "")
        return self.pvs[pv_name]

    def caput(self, pv_name: str, value: float) -> bool:
        """Write a value to a PV (start motor movement or set immediately)."""
        with self._lock:
            pv = self.pvs.get(pv_name)
            if pv is None:
                pv = self._auto_create(pv_name, value)
            # Soft limit check for motor PVs
            if pv.speed > 0 and (value < pv.lo_limit or value > pv.hi_limit):
                pv.severity = 2  # MAJOR alarm
                log.warning(f"caput {pv_name}={value:.4f} outside limits "
                            f"[{pv.lo_limit}, {pv.hi_limit}], clamped")
                value = max(pv.lo_limit, min(pv.hi_limit, value))
            pv.setpoint = value
            if pv.speed > 0:
                pv.moving = True
            else:
                pv.value = value
                self._changed.add(pv_name)
            return True

    def caget(self, pv_name: str) -> Optional[Dict[str, Any]]:
        """Read current value of a PV. Supports .RBV suffix for motor readback."""
        pv = self.pvs.get(pv_name)
        if pv is None and pv_name.endswith('.RBV'):
            base = pv_name[:-4]
            pv = self.pvs.get(base)
            if pv and pv.speed > 0:
                return {
                    "pv": pv_name,
                    "value": pv.value,
                    "severity": pv.severity,
                    "timestamp": time.time()
                }
        if pv is None:
            pv = self._auto_create(pv_name)
        return {
            "pv": pv_name,
            "value": pv.value,
            "severity": pv.severity,
            "timestamp": time.time()
        }

    def scan(self):
        """One scan cycle: advance motors, add noise, check alarms.
        Thread-safe: acquires _lock for the entire cycle.
        """
        self._lock.acquire()
        try:
            self._scan_inner()
        finally:
            self._lock.release()

    def _scan_inner(self):
        now = time.time()

        for pv_name, pv in self.pvs.items():
            changed = False

            # Motor movement simulation
            if pv.moving and pv.speed > 0:
                diff = pv.setpoint - pv.value
                step = pv.speed * self.scan_rate
                if abs(diff) < step:
                    pv.value = pv.setpoint
                    pv.moving = False
                else:
                    pv.value += (1 if diff > 0 else -1) * step
                changed = True

            # BPM noise (XBPM1 legacy + IC1)
            if ("XBPM1" in pv_name or "IC1" in pv_name):
                pv.value = pv.setpoint + (random.random() - 0.5) * 0.01
                changed = True

            # XBPM2 quadEM simulation (4-channel currents + position)
            if "XBPM2:Current" in pv_name and ":MeanValue_RBV" in pv_name:
                pv.value = 1.0 + (random.random() - 0.5) * 0.02  # ~1nA + noise
                changed = True
            elif pv_name == "BL10:XBPM2:SumAll:MeanValue_RBV":
                c = [self.pvs.get(f"BL10:XBPM2:Current{i}:MeanValue_RBV")
                     for i in range(1, 5)]
                pv.value = sum(p.value for p in c if p)
                changed = True
            elif pv_name == "BL10:XBPM2:PosX:MeanValue_RBV":
                c = [self.pvs.get(f"BL10:XBPM2:Current{i}:MeanValue_RBV")
                     for i in range(1, 5)]
                vals = [p.value if p else 0 for p in c]
                s = sum(vals)
                if s > 0:
                    pv.value = ((vals[0]+vals[3]) - (vals[1]+vals[2])) / s
                changed = True
            elif pv_name == "BL10:XBPM2:PosY:MeanValue_RBV":
                c = [self.pvs.get(f"BL10:XBPM2:Current{i}:MeanValue_RBV")
                     for i in range(1, 5)]
                vals = [p.value if p else 0 for p in c]
                s = sum(vals)
                if s > 0:
                    pv.value = ((vals[0]+vals[1]) - (vals[2]+vals[3])) / s
                changed = True

            # Ring current noise
            if pv_name == "BL10:RING:Current":
                pv.value = 400.0 + (random.random() - 0.5) * 0.1
                changed = True

            # Lifetime oscillation
            if pv_name == "BL10:RING:Lifetime":
                pv.value = 12.5 + math.sin(now * 0.01) * 0.3
                changed = True

            # Alarm checking for motor PVs
            if pv.speed > 0:
                if pv.value < pv.lo_limit or pv.value > pv.hi_limit:
                    pv.severity = 2  # MAJOR
                elif (pv.value < pv.lo_limit * 1.05 or
                      pv.value > pv.hi_limit * 0.95):
                    pv.severity = 1  # MINOR
                else:
                    pv.severity = 0  # NO_ALARM

            if changed:
                self._changed.add(pv_name)

    def get_changed(self) -> Dict[str, Dict[str, Any]]:
        """Return PVs that changed since last call, then clear the set.

        Motor PVs also emit a .RBV alias so that browser subscribers
        listening on 'BL10:M1:Pitch.RBV' receive updates.
        Thread-safe: acquires _lock to snapshot and clear _changed.
        """
        with self._lock:
            return self._get_changed_inner()

    def _get_changed_inner(self) -> Dict[str, Dict[str, Any]]:
        result = {}
        now = time.time()
        for pv_name in self._changed:
            pv = self.pvs.get(pv_name)
            if pv:
                result[pv_name] = {
                    "pv": pv_name,
                    "value": pv.value,
                    "severity": pv.severity,
                    "timestamp": now
                }
                # Motor PVs: also emit .RBV alias
                if pv.speed > 0:
                    rbv_name = pv_name + '.RBV'
                    result[rbv_name] = {
                        "pv": rbv_name,
                        "value": pv.value,
                        "severity": pv.severity,
                        "timestamp": now
                    }
        self._changed.clear()
        return result

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """Return all PV values (for initial snapshot on subscribe)."""
        now = time.time()
        return {
            name: {
                "pv": name,
                "value": pv.value,
                "severity": pv.severity,
                "timestamp": now
            }
            for name, pv in self.pvs.items()
        }
