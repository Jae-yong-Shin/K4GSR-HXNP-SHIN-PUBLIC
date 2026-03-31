#!/usr/bin/env python3
"""ophyd device definitions for K4GSR BL10 NanoProbe beamline.

Each device wraps EPICS PVs served by the caproto Soft IOC (soft_ioc.py).

The Soft IOC uses caproto FakeMotor (record='motor'), providing standard EPICS
motor record fields (.RBV, .VELO, .DMOV, .HLM, .LLM, .EGU, .STOP, etc.).
We use ophyd EpicsMotor directly — no custom wrapper needed.

When transitioning to real hardware (Kohzu, XDS Oxford DCM, JTEC KB, etc.),
this file requires ZERO changes — just point to the real IOC prefix.

Usage:
    from devices import create_devices, connect_devices
    devs = create_devices()
    connect_devices(devs, timeout=10.0)
    devs['dcm'].theta.move(11.0)
    devs['dcm'].theta.position  # readback value (.RBV)
    devs['dcm'].theta.velocity.get()  # .VELO

Requires:
    - caproto Soft IOC running (python server/epics/soft_ioc.py)
    - EPICS_CA_ADDR_LIST=localhost (or appropriate broadcast address)
"""

import os
import logging

from ophyd import Device, EpicsMotor, EpicsSignal, EpicsSignalRO, Component as Cpt

log = logging.getLogger("bl10-devices")

# Ensure CA can find the local IOC
if "EPICS_CA_ADDR_LIST" not in os.environ:
    os.environ["EPICS_CA_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"


# ═══════════════════════════════════════════════════════════════════════
# Mirror Device (M1, M2)
# ═══════════════════════════════════════════════════════════════════════
class BL10Mirror(Device):
    """FMB Oxford HHLMS mirror (M1 or M2)."""
    z       = Cpt(EpicsMotor, ':Z',      name='z')
    pitch   = Cpt(EpicsMotor, ':Pitch',   name='pitch')
    pitch_f = Cpt(EpicsMotor, ':PitchF',  name='pitch_f')
    tx      = Cpt(EpicsMotor, ':Tx',      name='tx')
    roll    = Cpt(EpicsMotor, ':Roll',     name='roll')
    yaw     = Cpt(EpicsMotor, ':Yaw',      name='yaw')
    bend_u  = Cpt(EpicsMotor, ':BendU',   name='bend_u')
    bend_d  = Cpt(EpicsMotor, ':BendD',   name='bend_d')


# ═══════════════════════════════════════════════════════════════════════
# DCM Device
# ═══════════════════════════════════════════════════════════════════════
class BL10DCM(Device):
    """XDS Oxford HDCM-HCCM Q11055 double-crystal monochromator."""
    theta     = Cpt(EpicsMotor, ':Theta',    name='theta')
    chi1      = Cpt(EpicsMotor, ':Chi1',     name='chi1')
    tx        = Cpt(EpicsMotor, ':TX',       name='tx')
    y1        = Cpt(EpicsMotor, ':Y1',       name='y1')
    y2        = Cpt(EpicsMotor, ':Y2',       name='y2')
    z2        = Cpt(EpicsMotor, ':Z2',       name='z2')
    dtheta2   = Cpt(EpicsMotor, ':DTheta2',  name='dtheta2')
    roll2     = Cpt(EpicsMotor, ':Roll2',    name='roll2')
    dtheta2f  = Cpt(EpicsMotor, ':DTheta2F', name='dtheta2f')


# ═══════════════════════════════════════════════════════════════════════
# KB Mirror Device
# ═══════════════════════════════════════════════════════════════════════
class BL10KBV(Device):
    """JTEC JM2000-200 KB vertical focusing mirror."""
    x      = Cpt(EpicsMotor, ':X',     name='x')
    y      = Cpt(EpicsMotor, ':Y',     name='y')
    z      = Cpt(EpicsMotor, ':Z',     name='z')
    pitch  = Cpt(EpicsMotor, ':Pitch', name='pitch')
    bend_u = Cpt(EpicsMotor, ':BendU', name='bend_u')
    bend_d = Cpt(EpicsMotor, ':BendD', name='bend_d')


class BL10KBH(Device):
    """JTEC JM2000-200 KB horizontal focusing mirror."""
    x      = Cpt(EpicsMotor, ':X',     name='x')
    z      = Cpt(EpicsMotor, ':Z',     name='z')
    pitch  = Cpt(EpicsMotor, ':Pitch', name='pitch')
    y      = Cpt(EpicsMotor, ':Y',     name='y')
    bend_u = Cpt(EpicsMotor, ':BendU', name='bend_u')
    bend_d = Cpt(EpicsMotor, ':BendD', name='bend_d')


# ═══════════════════════════════════════════════════════════════════════
# Slit Devices
# ═══════════════════════════════════════════════════════════════════════
class BL10WBSlit(Device):
    """JJ X-Ray white beam slit with individual blade + virtual gap/center."""
    top   = Cpt(EpicsMotor, ':Top',  name='top')
    bot   = Cpt(EpicsMotor, ':Bot',  name='bot')
    inb   = Cpt(EpicsMotor, ':Inb',  name='inb')
    outb  = Cpt(EpicsMotor, ':Outb', name='outb')
    hgap  = Cpt(EpicsMotor, ':Hgap', name='hgap')
    vgap  = Cpt(EpicsMotor, ':Vgap', name='vgap')


class BL10SSA(Device):
    """Secondary source aperture."""
    hgap = Cpt(EpicsMotor, ':Hgap', name='hgap')
    vgap = Cpt(EpicsMotor, ':Vgap', name='vgap')
    hcen = Cpt(EpicsMotor, ':Hcen', name='hcen')
    vcen = Cpt(EpicsMotor, ':Vcen', name='vcen')


# ═══════════════════════════════════════════════════════════════════════
# Sample Stage
# ═══════════════════════════════════════════════════════════════════════
class BL10Sample(Device):
    """Multi-stage sample positioner (KOHZU + PI PIMars + PI Scanner)."""
    cx    = Cpt(EpicsMotor, ':CX',    name='cx')
    cy    = Cpt(EpicsMotor, ':CY',    name='cy')
    cz    = Cpt(EpicsMotor, ':CZ',    name='cz')
    theta = Cpt(EpicsMotor, ':Theta', name='theta')
    phi   = Cpt(EpicsMotor, ':Phi',   name='phi')
    fx    = Cpt(EpicsMotor, ':FX',    name='fx')
    fy    = Cpt(EpicsMotor, ':FY',    name='fy')
    fz    = Cpt(EpicsMotor, ':FZ',    name='fz')
    sx    = Cpt(EpicsMotor, ':SX',    name='sx')
    sy    = Cpt(EpicsMotor, ':SY',    name='sy')


# ═══════════════════════════════════════════════════════════════════════
# Fast Nano Scanner (SmarAct MCS2 + PicoScale interferometer)
# ═══════════════════════════════════════════════════════════════════════
class BL10Scanner(Device):
    """Fast Nano Scanner: SmarAct MCS2 piezo stages + PicoScale encoder.

    MCS2 provides closed-loop piezo motion (X/Y/Z).
    PicoScale provides sub-nm position readback via laser interferometry.
    Units: nanometers (nm).
    """
    x  = Cpt(EpicsMotor,    ':X',  name='x')     # MCS2 ch0
    y  = Cpt(EpicsMotor,    ':Y',  name='y')     # MCS2 ch1
    z  = Cpt(EpicsMotor,    ':Z',  name='z')     # MCS2 ch2
    px = Cpt(EpicsSignalRO, ':PX', name='px')    # PicoScale X encoder (nm)
    py = Cpt(EpicsSignalRO, ':PY', name='py')    # PicoScale Y encoder (nm)
    pz = Cpt(EpicsSignalRO, ':PZ', name='pz')    # PicoScale Z encoder (nm)
    status   = Cpt(EpicsSignalRO, ':Status',   name='status')    # 0=idle
    progress = Cpt(EpicsSignalRO, ':Progress', name='progress')  # 0-100%


# ═══════════════════════════════════════════════════════════════════════
# Detector
# ═══════════════════════════════════════════════════════════════════════
class BL10Detector(Device):
    """Detector positioning stage."""
    x = Cpt(EpicsMotor, ':X', name='x')
    y = Cpt(EpicsMotor, ':Y', name='y')
    z = Cpt(EpicsMotor, ':Z', name='z')


# ═══════════════════════════════════════════════════════════════════════
# Ring / BPM / IC (read-only signals)
# ═══════════════════════════════════════════════════════════════════════
class BL10Ring(Device):
    """Storage ring status signals."""
    current  = Cpt(EpicsSignalRO, ':Current',  name='current')
    energy   = Cpt(EpicsSignalRO, ':Energy',   name='energy')
    lifetime = Cpt(EpicsSignalRO, ':Lifetime', name='lifetime')


class BL10Shutter(Device):
    """Front-end shutter."""
    status = Cpt(EpicsSignalRO, ':Shutter', name='status')


class BL10XBPM(Device):
    """X-ray beam position monitor (simple X/Y readback)."""
    x = Cpt(EpicsSignalRO, ':X', name='x')
    y = Cpt(EpicsSignalRO, ':Y', name='y')


class BL10XBPM2QuadEM(Device):
    """Sydor SI-DBPM-M403V diamond BPM with T4U electrometer (quadEM IOC).

    Provides 4-channel current readback, computed X/Y position, and control PVs.
    Position formula: X = [(A+D)-(B+C)]/Sum, Y = [(A+B)-(C+D)]/Sum
    """
    current1   = Cpt(EpicsSignalRO, ':Current1:MeanValue_RBV', name='current1')   # Ch A
    current2   = Cpt(EpicsSignalRO, ':Current2:MeanValue_RBV', name='current2')   # Ch B
    current3   = Cpt(EpicsSignalRO, ':Current3:MeanValue_RBV', name='current3')   # Ch C
    current4   = Cpt(EpicsSignalRO, ':Current4:MeanValue_RBV', name='current4')   # Ch D
    sum_all    = Cpt(EpicsSignalRO, ':SumAll:MeanValue_RBV',    name='sum_all')
    position_x = Cpt(EpicsSignalRO, ':PosX:MeanValue_RBV',     name='position_x')
    position_y = Cpt(EpicsSignalRO, ':PosY:MeanValue_RBV',     name='position_y')
    gain_range = Cpt(EpicsSignal,   ':Range',       name='gain_range')  # 0=Low,1=Med,2=Hi
    bias_en    = Cpt(EpicsSignal,   ':BiasPEn',     name='bias_en')


class BL10IC(Device):
    """Ion chamber."""
    current = Cpt(EpicsSignalRO, ':Current', name='current')


# ═══════════════════════════════════════════════════════════════════════
# Undulator
# ═══════════════════════════════════════════════════════════════════════
class BL10IVU(Device):
    """IVU24 in-vacuum undulator."""
    gap = Cpt(EpicsMotor, ':Gap', name='gap')


# ═══════════════════════════════════════════════════════════════════════
# Mask devices
# ═══════════════════════════════════════════════════════════════════════
class BL10Mask(Device):
    """Front-end or mono mask."""
    x    = Cpt(EpicsMotor, ':X',    name='x')
    y    = Cpt(EpicsMotor, ':Y',    name='y')
    hgap = Cpt(EpicsMotor, ':Hgap', name='hgap')
    vgap = Cpt(EpicsMotor, ':Vgap', name='vgap')


# ═══════════════════════════════════════════════════════════════════════
# Zone Plate
# ═══════════════════════════════════════════════════════════════════════
class BL10ZP(Device):
    """Zone plate positioner."""
    x = Cpt(EpicsMotor, ':X', name='x')
    y = Cpt(EpicsMotor, ':Y', name='y')
    z = Cpt(EpicsMotor, ':Z', name='z')


# ═══════════════════════════════════════════════════════════════════════
# Attenuator
# ═══════════════════════════════════════════════════════════════════════
class BL10Attenuator(Device):
    """Attenuator stage."""
    x = Cpt(EpicsMotor, ':X', name='x')
    y = Cpt(EpicsMotor, ':Y', name='y')


# ═══════════════════════════════════════════════════════════════════════
# Instantiate all devices
# ═══════════════════════════════════════════════════════════════════════
def create_devices():
    """Create all BL10 ophyd devices. Call after IOC is running."""
    devices = {}

    devices['ivu']   = BL10IVU('BL10:IVU', name='ivu')
    devices['fmask'] = BL10Mask('BL10:FMASK', name='fmask')
    devices['mmask'] = BL10Mask('BL10:MMASK', name='mmask')
    devices['wbs']   = BL10WBSlit('BL10:WBS', name='wbs')
    devices['m1']    = BL10Mirror('BL10:M1', name='m1')
    devices['dcm']   = BL10DCM('BL10:DCM', name='dcm')
    devices['m2']    = BL10Mirror('BL10:M2', name='m2')
    devices['ssa']   = BL10SSA('BL10:SSA', name='ssa')
    devices['kbv']   = BL10KBV('BL10:KBV', name='kbv')
    devices['kbh']   = BL10KBH('BL10:KBH', name='kbh')
    devices['zp']    = BL10ZP('BL10:ZP', name='zp')
    devices['att']   = BL10Attenuator('BL10:ATT', name='att')
    devices['sample'] = BL10Sample('BL10:SAM', name='sample')
    devices['det']   = BL10Detector('BL10:DET', name='det')
    devices['ring']  = BL10Ring('BL10:RING', name='ring')
    devices['fe_shutter'] = BL10Shutter('BL10:FE', name='fe_shutter')
    devices['xbpm1'] = BL10XBPM('BL10:XBPM1', name='xbpm1')
    devices['xbpm2'] = BL10XBPM2QuadEM('BL10:XBPM2', name='xbpm2')
    devices['ic1']   = BL10IC('BL10:IC1', name='ic1')
    devices['scanner'] = BL10Scanner('BL10:SCAN', name='scanner')

    # Virtual XRF detector (no EPICS needed — pure simulation)
    try:
        from .virtual_detector import VirtualXRFDetector
        sample = devices['sample']
        devices['vxrf'] = VirtualXRFDetector(
            'vxrf', name='vxrf',
            sample_motors=(sample.sx, sample.sy),
            energy_keV=10.0,
        )
    except ImportError as e:
        log.warning(f"VirtualXRFDetector not available: {e}")

    return devices


def connect_devices(devices: dict, timeout: float = 10.0):
    """Wait for all devices to connect to EPICS."""
    connected = 0
    failed = 0
    for name, dev in devices.items():
        try:
            dev.wait_for_connection(timeout=timeout)
            connected += 1
        except Exception as e:
            log.warning(f"Device {name} connection failed: {e}")
            failed += 1
    log.info(f"Devices connected: {connected}/{connected + failed}")
    return connected, failed
