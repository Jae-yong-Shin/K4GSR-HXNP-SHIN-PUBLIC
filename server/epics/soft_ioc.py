#!/usr/bin/env python3
"""caproto-based EPICS Soft IOC for K4GSR BL10 NanoProbe beamline.

Uses standard EPICS motor record (via caproto FakeMotor) for all motor axes.
Full compatibility with ophyd EpicsMotor and real EPICS motor records.

PV naming follows EPICS motor record convention:
  BL10:M1:Pitch       (motor record VAL - user setpoint)
  BL10:M1:Pitch.RBV   (user readback)
  BL10:M1:Pitch.VELO  (velocity)
  BL10:M1:Pitch.DMOV  (done moving)
  BL10:M1:Pitch.STOP  (stop command)
  BL10:M1:Pitch.HLM   (high limit)
  BL10:M1:Pitch.LLM   (low limit)
  BL10:M1:Pitch.EGU   (engineering units)

Usage:
    python soft_ioc.py                        # Start IOC
    python soft_ioc.py --list-pvs             # List motor PVs
    python soft_ioc.py --interfaces 0.0.0.0   # Bind to all interfaces

Verify with:
    caproto-get BL10:M1:Pitch
    caproto-get BL10:M1:Pitch.RBV
    caproto-get BL10:M1:Pitch.VELO
    caproto-monitor BL10:M1:Pitch.RBV
"""

import sys
import math
import time
import random
import logging

try:
    from caproto.server import pvproperty, PVGroup, SubGroup, ioc_arg_parser, run
    from caproto import ChannelType
except ImportError:
    print("ERROR: caproto is not installed.")
    print("Install it with:  pip install caproto")
    sys.exit(1)

try:
    from caproto.ioc_examples.fake_motor_record import motor_record_simulator
except ImportError:
    print("ERROR: caproto.ioc_examples.fake_motor_record not found.")
    print("Update caproto:  pip install --upgrade caproto")
    sys.exit(1)

log = logging.getLogger('bl10-ioc')


# ═══════════════════════════════════════════════════════════════════════
# BL10Motor — Standard motor record with initial position + EGU
# ═══════════════════════════════════════════════════════════════════════
class BL10Motor(PVGroup):
    """Standard EPICS motor record with initial position and EGU support.

    Unlike FakeMotor subclassing (which has startup hook override issues),
    this is a standalone PVGroup with its own motor pvproperty and startup.
    """
    motor = pvproperty(value=0.0, name='', record='motor', precision=3)

    def __init__(self, *args,
                 velocity=0.1, precision=3, acceleration=1.0,
                 resolution=1e-6, user_limits=(0.0, 100.0),
                 tick_rate_hz=10.,
                 initial_position=0.0, egu='',
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.tick_rate_hz = tick_rate_hz
        self._initial_position = initial_position
        self._egu = egu
        self.defaults = {
            'velocity': velocity,
            'precision': precision,
            'acceleration': acceleration,
            'resolution': resolution,
            'user_limits': user_limits,
        }

    @motor.startup
    async def motor(self, instance, async_lib):
        fields = instance.field_inst
        # Set engineering units before simulator applies defaults
        if self._egu:
            await fields.engineering_units.write(self._egu)
        # Set initial position (VAL + RBV + DRBV) so simulator sees no diff
        if self._initial_position != 0.0:
            await instance.write(self._initial_position)
            await fields.user_readback_value.write(self._initial_position)
            await fields.dial_readback_value.write(self._initial_position)
        # Start the motor simulator (applies velocity/limits, then runs loop)
        await motor_record_simulator(
            self.motor, async_lib, self.defaults,
            tick_rate_hz=self.tick_rate_hz,
        )


# ═══════════════════════════════════════════════════════════════════════
# Device Groups — match pv_store.py motor definitions exactly
# ═══════════════════════════════════════════════════════════════════════

class BL10IVUGroup(PVGroup):
    """IVU24 in-vacuum undulator (24mm period, 123 periods)."""
    gap          = SubGroup(BL10Motor, prefix='Gap',
                            velocity=0.5, user_limits=(5, 25), precision=3,
                            initial_position=7.0, egu='mm')
    taper_gap    = SubGroup(BL10Motor, prefix='TaperGap',
                            velocity=0.5, user_limits=(-2, 2), precision=3,
                            egu='mm')
    harmonic     = SubGroup(BL10Motor, prefix='Harmonic',
                            velocity=1, user_limits=(1, 13), precision=0,
                            initial_position=5, egu='')
    girder_x     = SubGroup(BL10Motor, prefix='GirderX',
                            velocity=1, user_limits=(-5, 5), precision=3, egu='mm')
    girder_y     = SubGroup(BL10Motor, prefix='GirderY',
                            velocity=1, user_limits=(-5, 5), precision=3, egu='mm')
    girder_pitch = SubGroup(BL10Motor, prefix='GirderPitch',
                            velocity=50, user_limits=(-200, 200), precision=2,
                            egu='urad')
    girder_yaw   = SubGroup(BL10Motor, prefix='GirderYaw',
                            velocity=50, user_limits=(-200, 200), precision=2,
                            egu='urad')
    enc_us       = SubGroup(BL10Motor, prefix='EncUS',
                            velocity=0.5, user_limits=(5, 25), precision=4,
                            initial_position=7.0, egu='mm')
    enc_ds       = SubGroup(BL10Motor, prefix='EncDS',
                            velocity=0.5, user_limits=(5, 25), precision=4,
                            initial_position=7.0, egu='mm')


class BL10MaskGroup(PVGroup):
    """Front-end or movable mask."""
    x    = SubGroup(BL10Motor, prefix='X',
                    velocity=2, user_limits=(-20, 20), precision=3, egu='mm')
    y    = SubGroup(BL10Motor, prefix='Y',
                    velocity=2, user_limits=(-20, 20), precision=3, egu='mm')
    hgap = SubGroup(BL10Motor, prefix='Hgap',
                    velocity=1, user_limits=(0.1, 20), precision=3,
                    initial_position=4.0, egu='mm')
    vgap = SubGroup(BL10Motor, prefix='Vgap',
                    velocity=1, user_limits=(0.1, 20), precision=3,
                    initial_position=4.0, egu='mm')


class BL10WBSlitGroup(PVGroup):
    """JJ X-Ray white beam slit (Model 24053)."""
    top  = SubGroup(BL10Motor, prefix='Top',
                    velocity=1, user_limits=(-25, 25), precision=4,
                    initial_position=0.5, egu='mm')
    bot  = SubGroup(BL10Motor, prefix='Bot',
                    velocity=1, user_limits=(-25, 25), precision=4,
                    initial_position=-0.5, egu='mm')
    inb  = SubGroup(BL10Motor, prefix='Inb',
                    velocity=1, user_limits=(-25, 25), precision=4,
                    initial_position=-1.0, egu='mm')
    outb = SubGroup(BL10Motor, prefix='Outb',
                    velocity=1, user_limits=(-25, 25), precision=4,
                    initial_position=1.0, egu='mm')
    hgap = SubGroup(BL10Motor, prefix='Hgap',
                    velocity=1, user_limits=(0.01, 48), precision=4,
                    initial_position=2.0, egu='mm')
    vgap = SubGroup(BL10Motor, prefix='Vgap',
                    velocity=1, user_limits=(0.01, 48), precision=4,
                    initial_position=1.0, egu='mm')


class BL10AttGroup(PVGroup):
    """Attenuator stage."""
    x = SubGroup(BL10Motor, prefix='X',
                 velocity=0.01, user_limits=(-25, 25), precision=3, egu='mm')
    y = SubGroup(BL10Motor, prefix='Y',
                 velocity=0.01, user_limits=(-25, 25), precision=3, egu='mm')


class BL10MirrorGroup(PVGroup):
    """FMB Oxford HHLMS mirror (M1 or M2)."""
    z       = SubGroup(BL10Motor, prefix='Z',
                       velocity=0.5, user_limits=(-5, 5), precision=4,
                       egu='mm')
    pitch   = SubGroup(BL10Motor, prefix='Pitch',
                       velocity=0.5, user_limits=(-2, 5), precision=4,
                       initial_position=3.0, egu='mrad')
    pitch_f = SubGroup(BL10Motor, prefix='PitchF',
                       velocity=100, user_limits=(-50, 50), precision=3,
                       egu='urad')
    tx      = SubGroup(BL10Motor, prefix='Tx',
                       velocity=1, user_limits=(-10, 10), precision=3,
                       egu='mm')
    roll    = SubGroup(BL10Motor, prefix='Roll',
                       velocity=1, user_limits=(-2, 2), precision=4,
                       egu='mrad')
    yaw     = SubGroup(BL10Motor, prefix='Yaw',
                       velocity=1, user_limits=(-2, 2), precision=4,
                       egu='mrad')
    bend_u  = SubGroup(BL10Motor, prefix='BendU',
                       velocity=1, user_limits=(-50, 50), precision=2,
                       egu='Nm')
    bend_d  = SubGroup(BL10Motor, prefix='BendD',
                       velocity=1, user_limits=(-50, 50), precision=2,
                       egu='Nm')


class BL10DCMGroup(PVGroup):
    """XDS Oxford HDCM-HCCM Q11055 double-crystal monochromator."""
    theta    = SubGroup(BL10Motor, prefix='Theta',
                        velocity=0.05, user_limits=(-1, 20), precision=5,
                        initial_position=11.402, egu='deg')
    y1       = SubGroup(BL10Motor, prefix='Y1',
                        velocity=0.5, user_limits=(-2.5, 2.5), precision=3,
                        egu='mm')
    chi1     = SubGroup(BL10Motor, prefix='Chi1',
                        velocity=1, user_limits=(-300, 300), precision=2,
                        egu='arcsec')
    tx       = SubGroup(BL10Motor, prefix='TX',
                        velocity=0.5, user_limits=(-12.5, 12.5), precision=3,
                        egu='mm')
    y2       = SubGroup(BL10Motor, prefix='Y2',
                        velocity=0.5, user_limits=(-25, 25), precision=3,
                        egu='mm')
    z2       = SubGroup(BL10Motor, prefix='Z2',
                        velocity=0.5, user_limits=(0, 25), precision=4,
                        initial_position=6.12, egu='mm')
    dtheta2  = SubGroup(BL10Motor, prefix='DTheta2',
                        velocity=10, user_limits=(-2520, 2520), precision=2,
                        egu='arcsec')
    roll2    = SubGroup(BL10Motor, prefix='Roll2',
                        velocity=10, user_limits=(-2520, 2520), precision=2,
                        egu='arcsec')
    dtheta2f = SubGroup(BL10Motor, prefix='DTheta2F',
                        velocity=100, user_limits=(-10.3, 10.3), precision=3,
                        egu='arcsec')


class BL10SSAGroup(PVGroup):
    """Secondary source aperture."""
    hgap = SubGroup(BL10Motor, prefix='Hgap',
                    velocity=1, user_limits=(1, 500), precision=1,
                    initial_position=50, egu='um')
    vgap = SubGroup(BL10Motor, prefix='Vgap',
                    velocity=1, user_limits=(1, 500), precision=1,
                    initial_position=50, egu='um')
    hcen = SubGroup(BL10Motor, prefix='Hcen',
                    velocity=1, user_limits=(-500, 500), precision=1,
                    egu='um')
    vcen = SubGroup(BL10Motor, prefix='Vcen',
                    velocity=1, user_limits=(-500, 500), precision=1,
                    egu='um')


class BL10KBSlitGroup(PVGroup):
    """KB upstream slit (500mm upstream KB-V)."""
    hgap = SubGroup(BL10Motor, prefix='Hgap',
                    velocity=50, user_limits=(1, 10000), precision=0,
                    initial_position=5000, egu='um')
    vgap = SubGroup(BL10Motor, prefix='Vgap',
                    velocity=50, user_limits=(1, 10000), precision=0,
                    initial_position=5000, egu='um')
    hcen = SubGroup(BL10Motor, prefix='Hcen',
                    velocity=1, user_limits=(-5000, 5000), precision=1,
                    egu='um')
    vcen = SubGroup(BL10Motor, prefix='Vcen',
                    velocity=1, user_limits=(-5000, 5000), precision=1,
                    egu='um')


class BL10KBVGroup(PVGroup):
    """JTEC JM2000-200 KB vertical focusing mirror."""
    x      = SubGroup(BL10Motor, prefix='X',
                      velocity=0.5, user_limits=(-2, 2), precision=4,
                      egu='mm')
    y      = SubGroup(BL10Motor, prefix='Y',
                      velocity=0.5, user_limits=(-15, 15), precision=4,
                      egu='mm')
    z      = SubGroup(BL10Motor, prefix='Z',
                      velocity=0.5, user_limits=(-100, 100), precision=3,
                      egu='mm')
    pitch  = SubGroup(BL10Motor, prefix='Pitch',
                      velocity=0.2, user_limits=(-2, 5), precision=4,
                      initial_position=3.0, egu='mrad')
    bend_u = SubGroup(BL10Motor, prefix='BendU',
                      velocity=1, user_limits=(-20, 20), precision=2,
                      egu='Nm')
    bend_d = SubGroup(BL10Motor, prefix='BendD',
                      velocity=1, user_limits=(-20, 20), precision=2,
                      egu='Nm')


class BL10KBHGroup(PVGroup):
    """JTEC JM2000-200 KB horizontal focusing mirror."""
    x      = SubGroup(BL10Motor, prefix='X',
                      velocity=0.5, user_limits=(-15, 15), precision=4,
                      egu='mm')
    y      = SubGroup(BL10Motor, prefix='Y',
                      velocity=0.5, user_limits=(-2, 2), precision=4,
                      egu='mm')
    z      = SubGroup(BL10Motor, prefix='Z',
                      velocity=0.5, user_limits=(-100, 100), precision=3,
                      egu='mm')
    pitch  = SubGroup(BL10Motor, prefix='Pitch',
                      velocity=0.2, user_limits=(-2, 5), precision=4,
                      initial_position=3.0, egu='mrad')
    bend_u = SubGroup(BL10Motor, prefix='BendU',
                      velocity=1, user_limits=(-20, 20), precision=2,
                      egu='Nm')
    bend_d = SubGroup(BL10Motor, prefix='BendD',
                      velocity=1, user_limits=(-20, 20), precision=2,
                      egu='Nm')


class BL10ZPGroup(PVGroup):
    """Zone plate positioner."""
    x = SubGroup(BL10Motor, prefix='X',
                 velocity=1, user_limits=(-2000, 2000), precision=2,
                 egu='um')
    y = SubGroup(BL10Motor, prefix='Y',
                 velocity=1, user_limits=(-2000, 2000), precision=2,
                 egu='um')
    z = SubGroup(BL10Motor, prefix='Z',
                 velocity=1, user_limits=(-5000, 5000), precision=2,
                 egu='um')


class BL10SampleGroup(PVGroup):
    """Multi-stage sample positioner (PI PIMars + PI Scanner + rotation).

    Note: CX/CY/CZ (KOHZU XA07A/ZA07A) are served by the KOHZU IOC (port 5070),
    not this soft_ioc, to avoid CA naming conflict in the digital twin architecture.
    Add cx/cy/cz here when KOHZU is replaced or mirroring is needed.
    """
    theta = SubGroup(BL10Motor, prefix='Theta',
                     velocity=200, user_limits=(-180, 180), precision=3,
                     egu='deg')
    phi   = SubGroup(BL10Motor, prefix='Phi',
                     velocity=2, user_limits=(-5, 5), precision=4,
                     egu='deg')
    fx    = SubGroup(BL10Motor, prefix='FX',
                     velocity=50, user_limits=(-150, 150), precision=4,
                     egu='um')
    fy    = SubGroup(BL10Motor, prefix='FY',
                     velocity=50, user_limits=(-150, 150), precision=4,
                     egu='um')
    fz    = SubGroup(BL10Motor, prefix='FZ',
                     velocity=50, user_limits=(-150, 150), precision=4,
                     egu='um')
    sx    = SubGroup(BL10Motor, prefix='SX',
                     velocity=100, user_limits=(-50, 50), precision=4,
                     egu='um')
    sy    = SubGroup(BL10Motor, prefix='SY',
                     velocity=100, user_limits=(-50, 50), precision=4,
                     egu='um')


class BL10DetGroup(PVGroup):
    """Detector positioning stage."""
    x = SubGroup(BL10Motor, prefix='X',
                 velocity=1, user_limits=(-50, 50), precision=3, egu='mm')
    y = SubGroup(BL10Motor, prefix='Y',
                 velocity=1, user_limits=(-50, 50), precision=3, egu='mm')
    z = SubGroup(BL10Motor, prefix='Z',
                 velocity=5, user_limits=(0, 5000), precision=2, egu='mm')


# ═══════════════════════════════════════════════════════════════════════
# Main IOC
# ═══════════════════════════════════════════════════════════════════════
class BL10BeamlineIOC(PVGroup):
    """K4GSR BL10 NanoProbe Beamline — Full EPICS motor record IOC.

    66 motor axes (standard motor records) + 9 status PVs + 1 heartbeat.
    """

    # ── Device groups (motor records) ──
    ivu   = SubGroup(BL10IVUGroup,     prefix='IVU:')
    fmask = SubGroup(BL10MaskGroup,    prefix='FMASK:')
    mmask = SubGroup(BL10MaskGroup,    prefix='MMASK:')
    wbs   = SubGroup(BL10WBSlitGroup,  prefix='WBS:')
    att   = SubGroup(BL10AttGroup,     prefix='ATT:')
    m1    = SubGroup(BL10MirrorGroup,  prefix='M1:')
    dcm   = SubGroup(BL10DCMGroup,     prefix='DCM:')
    m2    = SubGroup(BL10MirrorGroup,  prefix='M2:')
    ssa   = SubGroup(BL10SSAGroup,     prefix='SSA:')
    kbs   = SubGroup(BL10KBSlitGroup,  prefix='KBS:')
    kbv   = SubGroup(BL10KBVGroup,     prefix='KBV:')
    kbh   = SubGroup(BL10KBHGroup,     prefix='KBH:')
    zp    = SubGroup(BL10ZPGroup,      prefix='ZP:')
    sam   = SubGroup(BL10SampleGroup,  prefix='SAM:')
    det   = SubGroup(BL10DetGroup,     prefix='DET:')

    # ── Status PVs (non-motor, read-only with simulated noise) ──
    ring_current  = pvproperty(value=400.0, name='RING:Current',
                               read_only=True, precision=2)
    ring_energy   = pvproperty(value=4.0, name='RING:Energy',
                               read_only=True, precision=3)
    ring_lifetime = pvproperty(value=12.5, name='RING:Lifetime',
                               read_only=True, precision=1)
    fe_shutter    = pvproperty(value=1.0, name='FE:Shutter',
                               read_only=True, precision=0)
    xbpm1_x = pvproperty(value=0.0, name='XBPM1:X',
                          read_only=True, precision=4)
    xbpm1_y = pvproperty(value=0.0, name='XBPM1:Y',
                          read_only=True, precision=4)
    # XBPM2:X/Y removed -- XBPM2 is now a DBPM (T4U quadEM hardware).
    # Real PVs: BL10:XBPM2:PosX:MeanValue_RBV / PosY:MeanValue_RBV
    ic1_current = pvproperty(value=1e-9, name='IC1:Current',
                             read_only=True, precision=12)

    # ── Heartbeat (drives status PV noise simulation at 10 Hz) ──
    heartbeat = pvproperty(value=0, name='IOC:Heartbeat',
                           dtype=ChannelType.INT, read_only=True)

    @heartbeat.scan(period=0.1, use_scan_field=False)
    async def heartbeat(self, instance, async_lib):
        """100ms status PV noise generator."""
        now = time.time()

        # Ring current: 400 +/- 0.05
        await self.ring_current.write(
            400.0 + (random.random() - 0.5) * 0.1)

        # Lifetime: slow sine oscillation
        await self.ring_lifetime.write(
            12.5 + math.sin(now * 0.01) * 0.3)

        # BPM noise: +/- 0.005
        for pv in (self.xbpm1_x, self.xbpm1_y,
                   self.xbpm2_x, self.xbpm2_y):
            await pv.write((random.random() - 0.5) * 0.01)

        # IC1: small noise around 1e-9
        await self.ic1_current.write(
            1e-9 + (random.random() - 0.5) * 1e-11)

        # Heartbeat counter
        await instance.write(instance.value + 1)


# ═══════════════════════════════════════════════════════════════════════
# Motor inventory (for --list-pvs)
# ═══════════════════════════════════════════════════════════════════════
MOTOR_LIST = [
    # (PV suffix under BL10:, initial, lo, hi, velocity, unit)
    ('IVU:Gap',       7.0,    5,    25,   0.5,  'mm'),
    ('FMASK:X',       0,    -20,    20,   2,    'mm'),
    ('FMASK:Y',       0,    -20,    20,   2,    'mm'),
    ('FMASK:Hgap',    4.0,  0.1,    20,   1,    'mm'),
    ('FMASK:Vgap',    4.0,  0.1,    20,   1,    'mm'),
    ('MMASK:X',       0,    -20,    20,   2,    'mm'),
    ('MMASK:Y',       0,    -20,    20,   2,    'mm'),
    ('MMASK:Hgap',    4.0,  0.1,    20,   1,    'mm'),
    ('MMASK:Vgap',    4.0,  0.1,    20,   1,    'mm'),
    ('WBS:Top',       0.5,  -25,    25,   1,    'mm'),
    ('WBS:Bot',      -0.5,  -25,    25,   1,    'mm'),
    ('WBS:Inb',      -1.0,  -25,    25,   1,    'mm'),
    ('WBS:Outb',      1.0,  -25,    25,   1,    'mm'),
    ('WBS:Hgap',      2.0, 0.01,    48,   1,    'mm'),
    ('WBS:Vgap',      1.0, 0.01,    48,   1,    'mm'),
    ('ATT:X',         0,    -25,    25,   0.01, 'mm'),
    ('ATT:Y',         0,    -25,    25,   0.01, 'mm'),
    ('M1:Z',          0,     -5,     5,   0.5,  'mm'),
    ('M1:Pitch',      3.0,   -2,     5,   0.5,  'mrad'),
    ('M1:PitchF',     0,    -50,    50,   100,  'urad'),
    ('M1:Tx',         0,    -10,    10,   1,    'mm'),
    ('M1:Roll',       0,     -2,     2,   1,    'mrad'),
    ('M1:Yaw',        0,     -2,     2,   1,    'mrad'),
    ('M1:BendU',      0,    -50,    50,   1,    'Nm'),
    ('M1:BendD',      0,    -50,    50,   1,    'Nm'),
    ('DCM:Theta',    11.402, -1,    20,   0.05, 'deg'),
    ('DCM:Y1',        0,   -2.5,   2.5,  0.5,  'mm'),
    ('DCM:Chi1',      0,   -300,   300,   1,    'arcsec'),
    ('DCM:TX',        0,  -12.5,  12.5,  0.5,  'mm'),
    ('DCM:Y2',        0,    -25,    25,   0.5,  'mm'),
    ('DCM:Z2',        6.12,   0,    25,   0.5,  'mm'),
    ('DCM:DTheta2',   0,  -2520,  2520,   10,   'arcsec'),
    ('DCM:Roll2',     0,  -2520,  2520,   10,   'arcsec'),
    ('DCM:DTheta2F',  0,  -10.3,  10.3,  100,  'arcsec'),
    ('M2:Z',          0,     -5,     5,   0.5,  'mm'),
    ('M2:Pitch',      3.0,   -2,     5,   0.5,  'mrad'),
    ('M2:PitchF',     0,    -50,    50,   100,  'urad'),
    ('M2:Tx',         0,    -10,    10,   1,    'mm'),
    ('M2:Roll',       0,     -2,     2,   1,    'mrad'),
    ('M2:Yaw',        0,     -2,     2,   1,    'mrad'),
    ('M2:BendU',      0,    -50,    50,   1,    'Nm'),
    ('M2:BendD',      0,    -50,    50,   1,    'Nm'),
    ('SSA:Hgap',     50,      1,   500,   1,    'um'),
    ('SSA:Vgap',     50,      1,   500,   1,    'um'),
    ('SSA:Hcen',      0,   -500,   500,   1,    'um'),
    ('SSA:Vcen',      0,   -500,   500,   1,    'um'),
    ('KBV:X',         0,     -2,     2,   0.5,  'mm'),
    ('KBV:Y',         0,    -15,    15,   0.5,  'mm'),
    ('KBV:Z',         0,   -100,   100,   0.5,  'mm'),
    ('KBV:Pitch',     3.0,   -2,     5,   0.2,  'mrad'),
    ('KBV:BendU',     0,    -20,    20,   1,    'Nm'),
    ('KBV:BendD',     0,    -20,    20,   1,    'Nm'),
    ('KBH:X',         0,    -15,    15,   0.5,  'mm'),
    ('KBH:Y',         0,     -2,     2,   0.5,  'mm'),
    ('KBH:Z',         0,   -100,   100,   0.5,  'mm'),
    ('KBH:Pitch',     3.0,   -2,     5,   0.2,  'mrad'),
    ('KBH:BendU',     0,    -20,    20,   1,    'Nm'),
    ('KBH:BendD',     0,    -20,    20,   1,    'Nm'),
    ('ZP:X',          0,  -2000,  2000,   1,    'um'),
    ('ZP:Y',          0,  -2000,  2000,   1,    'um'),
    ('ZP:Z',          0,  -5000,  5000,   1,    'um'),
    # SAM:CX/CY/CZ are served by KOHZU IOC (port 5070) — not soft_ioc
    ('SAM:Theta',     0,   -180,   180,   200,  'deg'),
    ('SAM:Phi',       0,     -5,     5,   2,    'deg'),
    ('SAM:FX',        0,   -150,   150,   50,   'um'),
    ('SAM:FY',        0,   -150,   150,   50,   'um'),
    ('SAM:FZ',        0,   -150,   150,   50,   'um'),
    ('SAM:SX',        0,    -50,    50,   100,  'um'),
    ('SAM:SY',        0,    -50,    50,   100,  'um'),
    ('DET:X',         0,    -50,    50,   1,    'mm'),
    ('DET:Y',         0,    -50,    50,   1,    'mm'),
    ('DET:Z',         0,      0,  5000,   5,    'mm'),
]

STATUS_LIST = [
    ('RING:Current',  400.0),
    ('RING:Energy',   4.0),
    ('RING:Lifetime', 12.5),
    ('FE:Shutter',    1),
    ('XBPM1:X',       0),
    ('XBPM1:Y',       0),
    ('IC1:Current',   1e-9),
]


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════
def list_pvs():
    """Print all PV names with metadata."""
    print('=' * 72)
    print('K4GSR BL10 NanoProbe - EPICS Soft IOC (Motor Record)')
    print('=' * 72)
    print(f'  {"PV Name":<35} {"Type":<4} {"Value":>10}  '
          f'{"Unit":<8} {"Limits"}')
    print('-' * 72)
    for suffix, val, lo, hi, vel, unit in MOTOR_LIST:
        pv = f'BL10:{suffix}'
        lim = f'[{lo}, {hi}]'
        print(f'  {pv:<35} MTR  {val:>10.4f}  {unit:<8} {lim}')
    print('-' * 72)
    for suffix, val in STATUS_LIST:
        pv = f'BL10:{suffix}'
        print(f'  {pv:<35} RO   {val:>10.4f}')
    print('-' * 72)
    n_motor = len(MOTOR_LIST)
    n_status = len(STATUS_LIST)
    print(f'Motor axes:  {n_motor} (each = standard motor record, '
          f'~153 fields)')
    print(f'Status PVs:  {n_status}')
    print('Heartbeat:   1')
    print(f'Total:       {n_motor + n_status + 1} logical PVs')
    print('=' * 72)


def main():
    if '--list-pvs' in sys.argv:
        list_pvs()
        return

    # Parse --exclude-groups before ioc_arg_parser (which doesn't know it)
    exclude_groups = []
    filtered_argv = []
    skip_next = False
    for i, arg in enumerate(sys.argv):
        if skip_next:
            skip_next = False
            continue
        if arg == '--exclude-groups':
            # Collect all following non-flag args as group names
            for j in range(i + 1, len(sys.argv)):
                if sys.argv[j].startswith('-'):
                    break
                exclude_groups.append(sys.argv[j].upper())
            skip_next = False
            continue
        if arg.upper() in exclude_groups:
            continue  # skip group name args
        filtered_argv.append(arg)
    sys.argv = filtered_argv

    ioc_options, run_options = ioc_arg_parser(
        default_prefix='BL10:',
        desc='K4GSR BL10 NanoProbe Beamline Soft IOC '
             '(standard motor records)',
    )

    ioc = BL10BeamlineIOC(**ioc_options)
    prefix = ioc_options.get('prefix', 'BL10:')

    # Exclude groups: remove PVs matching excluded prefixes from pvdb
    pvdb = dict(ioc.pvdb)
    if exclude_groups:
        excluded_count = 0
        for group in exclude_groups:
            group_prefix = f'{prefix}{group}:'
            to_remove = [k for k in pvdb if k.startswith(group_prefix)]
            for k in to_remove:
                del pvdb[k]
                excluded_count += 1
        print(f'Excluded groups: {", ".join(exclude_groups)} '
              f'({excluded_count} PV fields removed)')

    n_pvs = len(pvdb)
    n_motor = len(MOTOR_LIST)
    n_status = len(STATUS_LIST)
    print(f'Starting BL10 Soft IOC with {n_pvs} PV fields...')
    print(f'Motor axes:    {n_motor} (standard motor records)')
    print(f'Status PVs:    {n_status}')
    if exclude_groups:
        print(f'Hybrid mode:   {", ".join(exclude_groups)} served by real IOC')
    print('Scan rate:     100 ms (status noise)')
    print()
    print('Verify with:')
    print('  caproto-get BL10:M1:Pitch')
    print('  caproto-get BL10:M1:Pitch.RBV')
    print('  caproto-get BL10:M1:Pitch.VELO')
    print('  caproto-monitor BL10:M1:Pitch.RBV')
    print()

    run(pvdb, **run_options)


if __name__ == '__main__':
    main()
