#!/usr/bin/env python3
"""Bluesky scan plans for K4GSR BL10 NanoProbe beamline.

Custom plans built on top of standard bluesky plans, specialized for:
  - Energy scans (DCM theta + IVU gap)
  - XAFS step scans (pre-edge, edge, post-edge regions)
  - 2D raster scans (sample SX/SY)
  - Alignment scans (mirror pitch, KB optimization)

Usage:
    from bluesky import RunEngine
    from plans import energy_scan, raster_scan
    from devices import create_devices

    RE = RunEngine({})
    devs = create_devices()

    RE(energy_scan(devs, 8.9, 9.1, 100))
    RE(raster_scan(devs, x_range=(-10, 10), y_range=(-10, 10), nx=21, ny=21))
"""

import math
import numpy as np
import logging

import bluesky.plans as bp
import bluesky.plan_stubs as bps
from bluesky.preprocessors import run_decorator

log = logging.getLogger("bl10-plans")

# ═══════════════════════════════════════════════════════════════════════
# Physical constants for energy ↔ theta conversion
# ═══════════════════════════════════════════════════════════════════════
HC_ANGSTROM = 12398.419843  # h*c in eV*Angstrom
SI_111_D = 3.13542          # Si(111) d-spacing in Angstrom


def energy_to_theta(energy_keV: float) -> float:
    """Convert photon energy (keV) to DCM Bragg angle (degrees).

    Uses Si(111):  theta = arcsin(hc / (2 * d * E))
    """
    energy_eV = energy_keV * 1000.0
    wavelength = HC_ANGSTROM / energy_eV
    sin_theta = wavelength / (2.0 * SI_111_D)
    if abs(sin_theta) > 1.0:
        raise ValueError(f"Energy {energy_keV} keV out of Si(111) range")
    return math.degrees(math.asin(sin_theta))


def theta_to_energy(theta_deg: float) -> float:
    """Convert DCM Bragg angle (degrees) to photon energy (keV)."""
    sin_theta = math.sin(math.radians(theta_deg))
    if sin_theta <= 0:
        raise ValueError(f"Invalid theta: {theta_deg}")
    energy_eV = HC_ANGSTROM / (2.0 * SI_111_D * sin_theta)
    return energy_eV / 1000.0


# ═══════════════════════════════════════════════════════════════════════
# Energy scan
# ═══════════════════════════════════════════════════════════════════════
def energy_scan(devices: dict, e_start: float, e_stop: float, n_points: int,
                detectors=None):
    """Scan photon energy by moving DCM theta.

    Args:
        devices: dict from create_devices()
        e_start: start energy in keV
        e_stop: stop energy in keV
        n_points: number of points
        detectors: list of detectors to read (default: ic1)

    Yields:
        bluesky messages
    """
    dcm = devices['dcm']

    if detectors is None:
        detectors = [devices.get('ic1')]
        detectors = [d for d in detectors if d is not None]

    theta_start = energy_to_theta(e_start)
    theta_stop = energy_to_theta(e_stop)

    log.info(f"Energy scan: {e_start:.3f} → {e_stop:.3f} keV "
             f"(theta: {theta_start:.4f} → {theta_stop:.4f} deg, {n_points} pts)")

    yield from bp.scan(detectors, dcm.theta, theta_start, theta_stop, n_points,
                       md={'plan_name': 'energy_scan',
                           'energy_start': e_start,
                           'energy_stop': e_stop})


# ═══════════════════════════════════════════════════════════════════════
# XAFS scan (multi-region step scan)
# ═══════════════════════════════════════════════════════════════════════

# Common absorption edges (keV)
ABSORPTION_EDGES = {
    'Ti': {'K': 4.966},
    'V':  {'K': 5.470},
    'Cr': {'K': 5.989},
    'Mn': {'K': 6.539},
    'Fe': {'K': 7.112},
    'Co': {'K': 7.709},
    'Ni': {'K': 8.333},
    'Cu': {'K': 8.979},
    'Zn': {'K': 9.659},
    'Se': {'K': 12.658},
    'Mo': {'K': 20.000},
    'Ag': {'K': 25.514},
    'Pt': {'L3': 11.564, 'L2': 13.273, 'L1': 13.880},
    'Au': {'L3': 11.919, 'L2': 13.734, 'L1': 14.353},
    'Pb': {'L3': 13.035, 'L2': 15.200, 'L1': 15.861},
}


def xafs_scan(devices: dict, element: str, edge: str = 'K',
              pre_range: float = 150, post_range: float = 400,
              pre_step: float = 5.0, edge_step: float = 0.5,
              post_step: float = 2.0, detectors=None):
    """Multi-region XAFS step scan around an absorption edge.

    Regions:
      1. Pre-edge:  E0 - pre_range  to  E0 - 20 eV  (coarse step)
      2. Edge:      E0 - 20 eV      to  E0 + 30 eV  (fine step)
      3. Post-edge: E0 + 30 eV      to  E0 + post_range (medium step)

    Args:
        devices: dict from create_devices()
        element: element symbol (e.g. 'Cu', 'Fe')
        edge: absorption edge ('K', 'L3', etc.)
        pre_range: pre-edge range in eV
        post_range: post-edge range in eV
        pre_step: pre-edge step size in eV
        edge_step: edge region step size in eV
        post_step: post-edge step size in eV
        detectors: list of detectors to read

    Yields:
        bluesky messages
    """
    if element not in ABSORPTION_EDGES:
        raise ValueError(f"Unknown element: {element}. "
                         f"Available: {', '.join(sorted(ABSORPTION_EDGES.keys()))}")
    edges = ABSORPTION_EDGES[element]
    if edge not in edges:
        raise ValueError(f"No {edge} edge for {element}. "
                         f"Available: {', '.join(edges.keys())}")

    e0_keV = edges[edge]
    e0_eV = e0_keV * 1000.0
    dcm = devices['dcm']

    if detectors is None:
        detectors = [devices.get('ic1')]
        detectors = [d for d in detectors if d is not None]

    # Build energy points (in eV)
    pre_points = np.arange(e0_eV - pre_range, e0_eV - 20, pre_step)
    edge_points = np.arange(e0_eV - 20, e0_eV + 30, edge_step)
    post_points = np.arange(e0_eV + 30, e0_eV + post_range, post_step)
    all_eV = np.concatenate([pre_points, edge_points, post_points])
    all_keV = all_eV / 1000.0

    # Convert to theta
    theta_points = [energy_to_theta(e) for e in all_keV]

    n_total = len(theta_points)
    log.info(f"XAFS scan: {element} {edge}-edge at {e0_keV:.3f} keV, "
             f"{n_total} points ({len(pre_points)} pre + {len(edge_points)} edge "
             f"+ {len(post_points)} post)")

    yield from bp.list_scan(detectors, dcm.theta, theta_points,
                            md={'plan_name': 'xafs_scan',
                                'element': element,
                                'edge': edge,
                                'e0_keV': e0_keV,
                                'n_pre': len(pre_points),
                                'n_edge': len(edge_points),
                                'n_post': len(post_points)})


# ═══════════════════════════════════════════════════════════════════════
# 2D Raster scan (XRF/XRD mapping)
# ═══════════════════════════════════════════════════════════════════════
def raster_scan(devices: dict, x_range: tuple, y_range: tuple,
                nx: int, ny: int, use_scanner: bool = True,
                detectors=None, use_xrf: bool = True):
    """2D raster scan using sample stage piezo scanners.

    Args:
        devices: dict from create_devices()
        x_range: (x_start, x_stop) in um
        y_range: (y_start, y_stop) in um
        nx: number of x points
        ny: number of y points
        use_scanner: if True use SX/SY (fast scanner), else FX/FY (fine)
        detectors: list of detectors to read
        use_xrf: if True and vxrf available, include virtual XRF detector

    Yields:
        bluesky messages
    """
    sample = devices['sample']
    x_motor = sample.sx if use_scanner else sample.fx
    y_motor = sample.sy if use_scanner else sample.fy

    if detectors is None:
        det_list = []
        # Virtual XRF detector (position-dependent element maps)
        if use_xrf and 'vxrf' in devices:
            det_list.append(devices['vxrf'])
        # Ion chamber (total flux)
        ic1 = devices.get('ic1')
        if ic1 is not None:
            det_list.append(ic1)
        detectors = det_list if det_list else []

    x_start, x_stop = x_range
    y_start, y_stop = y_range

    log.info(f"Raster scan: X[{x_start}, {x_stop}] x Y[{y_start}, {y_stop}] um, "
             f"{nx}x{ny} = {nx*ny} points, motor={'SX/SY' if use_scanner else 'FX/FY'}")

    yield from bp.grid_scan(detectors,
                            y_motor, y_start, y_stop, ny,
                            x_motor, x_start, x_stop, nx,
                            snake_axes=True,
                            md={'plan_name': 'raster_scan',
                                'x_range': list(x_range),
                                'y_range': list(y_range),
                                'nx': nx, 'ny': ny})


# ═══════════════════════════════════════════════════════════════════════
# Alignment scans (1D peak scans)
# ═══════════════════════════════════════════════════════════════════════
def alignment_scan(devices: dict, device_name: str, axis_name: str,
                   center: float, width: float, n_points: int = 21,
                   detectors=None):
    """1D scan for alignment (find peak on detector).

    Args:
        devices: dict from create_devices()
        device_name: key in devices dict (e.g. 'm1', 'dcm', 'kbv')
        axis_name: axis attribute name (e.g. 'pitch', 'theta', 'bend_u')
        center: scan center
        width: full scan width
        n_points: number of points

    Yields:
        bluesky messages
    """
    device = devices.get(device_name)
    if device is None:
        raise ValueError(f"Unknown device: {device_name}")

    motor = getattr(device, axis_name, None)
    if motor is None:
        raise ValueError(f"Unknown axis: {device_name}.{axis_name}")

    if detectors is None:
        detectors = [devices.get('ic1')]
        detectors = [d for d in detectors if d is not None]

    start = center - width / 2
    stop = center + width / 2

    log.info(f"Alignment scan: {device_name}.{axis_name} "
             f"[{start:.4f}, {stop:.4f}], {n_points} pts")

    yield from bp.scan(detectors, motor, start, stop, n_points,
                       md={'plan_name': 'alignment_scan',
                           'device': device_name,
                           'axis': axis_name,
                           'center': center,
                           'width': width})


# ═══════════════════════════════════════════════════════════════════════
# Simple count (read all detectors)
# ═══════════════════════════════════════════════════════════════════════
def beam_check(devices: dict, n_readings: int = 5, delay: float = 0.5):
    """Take multiple readings to check beam stability.

    Args:
        devices: dict from create_devices()
        n_readings: number of readings
        delay: seconds between readings

    Yields:
        bluesky messages
    """
    detectors = []
    for key in ['ic1', 'xbpm1', 'xbpm2']:
        d = devices.get(key)
        if d is not None:
            detectors.append(d)

    log.info(f"Beam check: {n_readings} readings, {delay}s interval")

    yield from bp.count(detectors, num=n_readings, delay=delay,
                        md={'plan_name': 'beam_check'})


# ═══════════════════════════════════════════════════════════════════════
# XANES scan (fine near-edge structure)
# ═══════════════════════════════════════════════════════════════════════
def xanes_scan(devices: dict, element: str, edge: str = 'K',
               pre_range: float = 50, post_range: float = 100,
               pre_step: float = 2.0, edge_step: float = 0.25,
               post_step: float = 1.0, detectors=None):
    """XANES scan with very fine step at the absorption edge.

    Optimized for near-edge structure (XANES/NEXAFS) with higher
    resolution at the edge compared to full XAFS.

    Regions:
      1. Pre-edge:  E0 - pre_range  to  E0 - 10 eV  (medium step)
      2. Edge:      E0 - 10 eV      to  E0 + 20 eV  (very fine step)
      3. Post-edge: E0 + 20 eV      to  E0 + post_range (medium step)

    Args:
        devices: dict from create_devices()
        element: element symbol (e.g. 'Cu', 'Fe')
        edge: absorption edge ('K', 'L3', etc.)
        pre_range: pre-edge range in eV (default: 50)
        post_range: post-edge range in eV (default: 100)
        pre_step: pre-edge step size in eV
        edge_step: edge region step size in eV (default: 0.25 eV)
        post_step: post-edge step size in eV
        detectors: list of detectors to read
    """
    if element not in ABSORPTION_EDGES:
        raise ValueError(f"Unknown element: {element}")
    edges = ABSORPTION_EDGES[element]
    if edge not in edges:
        raise ValueError(f"No {edge} edge for {element}")

    e0_keV = edges[edge]
    e0_eV = e0_keV * 1000.0
    dcm = devices['dcm']

    if detectors is None:
        detectors = [devices.get('ic1')]
        detectors = [d for d in detectors if d is not None]

    pre_pts = np.arange(e0_eV - pre_range, e0_eV - 10, pre_step)
    edge_pts = np.arange(e0_eV - 10, e0_eV + 20, edge_step)
    post_pts = np.arange(e0_eV + 20, e0_eV + post_range, post_step)
    all_eV = np.concatenate([pre_pts, edge_pts, post_pts])
    all_keV = all_eV / 1000.0
    theta_points = [energy_to_theta(e) for e in all_keV]

    n_total = len(theta_points)
    log.info(f"XANES scan: {element} {edge}-edge at {e0_keV:.3f} keV, "
             f"{n_total} pts ({len(pre_pts)}+{len(edge_pts)}+{len(post_pts)})")

    yield from bp.list_scan(detectors, dcm.theta, theta_points,
                            md={'plan_name': 'xanes_scan',
                                'element': element, 'edge': edge,
                                'e0_keV': e0_keV,
                                'n_pre': len(pre_pts),
                                'n_edge': len(edge_pts),
                                'n_post': len(post_pts)})


# ═══════════════════════════════════════════════════════════════════════
# Multi-region energy scan
# ═══════════════════════════════════════════════════════════════════════
def multi_region_scan(devices: dict, regions: list, detectors=None):
    """Multi-region energy scan with different step sizes per region.

    Each region is a dict: {'start': keV, 'stop': keV, 'step': eV}

    Example:
        regions = [
            {'start': 6.9, 'stop': 7.05, 'step': 5.0},   # pre-edge
            {'start': 7.05, 'stop': 7.18, 'step': 0.3},   # Fe K-edge
            {'start': 7.18, 'stop': 7.5, 'step': 2.0},    # post-edge
        ]

    Args:
        devices: dict from create_devices()
        regions: list of region dicts with start/stop (keV) and step (eV)
        detectors: list of detectors to read
    """
    if not regions:
        raise ValueError("At least one region is required")

    dcm = devices['dcm']

    if detectors is None:
        detectors = [devices.get('ic1')]
        detectors = [d for d in detectors if d is not None]

    all_keV = []
    region_info = []
    for reg in regions:
        start_eV = reg['start'] * 1000.0
        stop_eV = reg['stop'] * 1000.0
        step_eV = reg.get('step', 1.0)
        pts = np.arange(start_eV, stop_eV, step_eV)
        region_info.append({'n_pts': len(pts), 'start': reg['start'],
                            'stop': reg['stop'], 'step': step_eV})
        all_keV.extend((pts / 1000.0).tolist())

    # Remove duplicates at region boundaries, keep order
    unique_keV = []
    for e in all_keV:
        if not unique_keV or abs(e - unique_keV[-1]) > 1e-7:
            unique_keV.append(e)

    theta_points = [energy_to_theta(e) for e in unique_keV]
    n_total = len(theta_points)

    log.info(f"Multi-region scan: {len(regions)} regions, {n_total} total points")

    yield from bp.list_scan(detectors, dcm.theta, theta_points,
                            md={'plan_name': 'multi_region_scan',
                                'regions': region_info,
                                'n_total': n_total})


# ═══════════════════════════════════════════════════════════════════════
# Fly scan (continuous motion with readout)
# ═══════════════════════════════════════════════════════════════════════
def fly_scan(devices: dict, motor_name: str, axis_name: str,
             start: float, stop: float, n_points: int,
             dwell: float = 0.1, detectors=None):
    """Simulated fly scan — fast step scan with minimal overhead.

    In a real fly scan the motor moves continuously while detectors
    read at fixed time intervals. This plan emulates that behavior
    using a step scan with short dwell time between points.

    When real fly-scan hardware is available (e.g., Delta Tau encoder,
    Struck MCS, Zebra), replace this with bp.fly() and proper
    flyer devices.

    Args:
        devices: dict from create_devices()
        motor_name: device key (e.g. 'sample', 'dcm')
        axis_name: motor axis (e.g. 'sx', 'theta')
        start: start position
        stop: stop position
        n_points: number of readout points
        dwell: dwell time per point in seconds
        detectors: list of detectors to read
    """
    device = devices.get(motor_name)
    if device is None:
        raise ValueError(f"Unknown device: {motor_name}")
    motor = getattr(device, axis_name, None)
    if motor is None:
        raise ValueError(f"Unknown axis: {motor_name}.{axis_name}")

    if detectors is None:
        detectors = [devices.get('ic1')]
        detectors = [d for d in detectors if d is not None]

    log.info(f"Fly scan: {motor_name}.{axis_name} [{start}, {stop}], "
             f"{n_points} pts, dwell={dwell}s")

    yield from bp.scan(detectors, motor, start, stop, n_points,
                       md={'plan_name': 'fly_scan',
                           'device': motor_name,
                           'axis': axis_name,
                           'dwell': dwell,
                           'fly_mode': 'step_emulated'})


# ═══════════════════════════════════════════════════════════════════════
# Line scan (1D scan along arbitrary direction)
# ═══════════════════════════════════════════════════════════════════════
def line_scan(devices: dict, x_start: float, y_start: float,
              x_stop: float, y_stop: float, n_points: int,
              use_scanner: bool = True, detectors=None):
    """1D line scan along an arbitrary direction in 2D sample space.

    Simultaneously moves X and Y motors to trace a line.
    Useful for cross-section profiles through features.

    Args:
        devices: dict from create_devices()
        x_start, y_start: start position (um)
        x_stop, y_stop: end position (um)
        n_points: number of points along the line
        use_scanner: if True use SX/SY, else FX/FY
        detectors: list of detectors
    """
    sample = devices['sample']
    x_motor = sample.sx if use_scanner else sample.fx
    y_motor = sample.sy if use_scanner else sample.fy

    if detectors is None:
        det_list = []
        if 'vxrf' in devices:
            det_list.append(devices['vxrf'])
        ic1 = devices.get('ic1')
        if ic1 is not None:
            det_list.append(ic1)
        detectors = det_list if det_list else []

    log.info(f"Line scan: ({x_start},{y_start}) → ({x_stop},{y_stop}), "
             f"{n_points} pts")

    x_positions = np.linspace(x_start, x_stop, n_points).tolist()
    y_positions = np.linspace(y_start, y_stop, n_points).tolist()

    yield from bp.list_scan(detectors,
                            x_motor, x_positions,
                            y_motor, y_positions,
                            md={'plan_name': 'line_scan',
                                'x_start': x_start, 'y_start': y_start,
                                'x_stop': x_stop, 'y_stop': y_stop})


# ═══════════════════════════════════════════════════════════════════════
# Auto-tune (iterative centroid alignment)
# ═══════════════════════════════════════════════════════════════════════
def auto_tune(devices: dict, device_name: str, axis_name: str,
              target_field: str = 'ic1_current',
              start: float = None, stop: float = None,
              min_step: float = 0.001, n_points: int = 21,
              step_factor: float = 3.0, detectors=None):
    """Iteratively scan a motor and move to the centroid, narrowing range.

    Wraps bp.tune_centroid. Each iteration scans the motor, computes
    the intensity-weighted centroid, moves to it, then narrows the range
    by step_factor. Repeats until range < min_step.

    Args:
        devices: dict from create_devices()
        device_name: key in devices dict (e.g. 'm1', 'dcm', 'kbv')
        axis_name: axis attribute name (e.g. 'pitch', 'theta', 'bend_u')
        target_field: detector signal field for centroid calc
                      (default: 'ic1_current')
        start: scan start position (absolute)
        stop: scan stop position (absolute)
        min_step: minimum step size — iteration stops when range < this
        n_points: points per iteration (default: 21)
        step_factor: range narrowing factor per iteration (default: 3.0)
        detectors: list of detectors to read
    """
    device = devices.get(device_name)
    if device is None:
        raise ValueError(f"Unknown device: {device_name}")
    motor = getattr(device, axis_name, None)
    if motor is None:
        raise ValueError(f"Unknown axis: {device_name}.{axis_name}")

    if detectors is None:
        detectors = [devices.get('ic1')]
        detectors = [d for d in detectors if d is not None]

    if start is None or stop is None:
        raise ValueError("start and stop positions are required for auto_tune")

    log.info(f"Auto-tune: {device_name}.{axis_name} [{start:.4f}, {stop:.4f}], "
             f"signal={target_field}, min_step={min_step}, "
             f"step_factor={step_factor}")

    yield from bp.tune_centroid(
        detectors, target_field, motor, start, stop,
        min_step, num=n_points, step_factor=step_factor, snake=False,
        md={'plan_name': 'auto_tune',
            'device': device_name,
            'axis': axis_name,
            'target_field': target_field})


# ═══════════════════════════════════════════════════════════════════════
# Adaptive energy scan (auto-densify at absorption edges)
# ═══════════════════════════════════════════════════════════════════════
def adaptive_energy_scan(devices: dict, e_start: float, e_stop: float,
                         min_step_eV: float = 0.1, max_step_eV: float = 5.0,
                         target_delta: float = 0.2, backstep: bool = True,
                         target_field: str = 'ic1_current', detectors=None):
    """Adaptive energy scan that auto-densifies around absorption edges.

    Step size adapts based on signal change rate: small steps where the
    signal changes rapidly (at edges), large steps in flat regions.

    Args:
        devices: dict from create_devices()
        e_start: start energy in keV
        e_stop: stop energy in keV
        min_step_eV: minimum step size in eV (default: 0.1)
        max_step_eV: maximum step size in eV (default: 5.0)
        target_delta: desired fractional change per step (default: 0.2)
        backstep: go back and re-measure if change too large (default: True)
        target_field: signal field for adaptation (default: 'ic1_current')
        detectors: list of detectors to read
    """
    dcm = devices['dcm']

    if detectors is None:
        detectors = [devices.get('ic1')]
        detectors = [d for d in detectors if d is not None]

    theta_start = energy_to_theta(e_start)
    theta_stop = energy_to_theta(e_stop)

    # Convert eV step sizes to theta at mid-energy
    e_mid = (e_start + e_stop) / 2.0
    theta_mid = energy_to_theta(e_mid)
    theta_mid_lo = energy_to_theta(e_mid + min_step_eV / 1000.0)
    theta_mid_hi = energy_to_theta(e_mid + max_step_eV / 1000.0)
    min_step_theta = abs(theta_mid - theta_mid_lo)
    max_step_theta = abs(theta_mid - theta_mid_hi)

    # theta decreases as energy increases — ensure start < stop
    t_lo = min(theta_start, theta_stop)
    t_hi = max(theta_start, theta_stop)

    log.info(f"Adaptive energy scan: {e_start:.3f} → {e_stop:.3f} keV, "
             f"step: {min_step_eV}~{max_step_eV} eV, "
             f"target_delta={target_delta}")

    yield from bp.adaptive_scan(
        detectors, target_field, dcm.theta,
        t_lo, t_hi,
        min_step_theta, max_step_theta,
        target_delta, backstep,
        md={'plan_name': 'adaptive_energy_scan',
            'energy_start': e_start,
            'energy_stop': e_stop,
            'min_step_eV': min_step_eV,
            'max_step_eV': max_step_eV,
            'target_delta': target_delta})


# ═══════════════════════════════════════════════════════════════════════
# Relative alignment scan (+/- width around current position)
# ═══════════════════════════════════════════════════════════════════════
def rel_alignment_scan(devices: dict, device_name: str, axis_name: str,
                       width: float, n_points: int = 21, detectors=None):
    """Relative 1D scan for alignment: +/- width/2 around current position.

    Uses bp.rel_scan — no need to compute absolute positions.

    Args:
        devices: dict from create_devices()
        device_name: key in devices dict (e.g. 'm1', 'dcm', 'kbv')
        axis_name: axis attribute name (e.g. 'pitch', 'theta', 'bend_u')
        width: full scan width (scans from -width/2 to +width/2)
        n_points: number of points (default: 21)
        detectors: list of detectors to read
    """
    device = devices.get(device_name)
    if device is None:
        raise ValueError(f"Unknown device: {device_name}")
    motor = getattr(device, axis_name, None)
    if motor is None:
        raise ValueError(f"Unknown axis: {device_name}.{axis_name}")

    if detectors is None:
        detectors = [devices.get('ic1')]
        detectors = [d for d in detectors if d is not None]

    half = width / 2.0
    log.info(f"Relative alignment scan: {device_name}.{axis_name} "
             f"+/- {half:.4f} ({n_points} pts)")

    yield from bp.rel_scan(detectors, motor, -half, half, num=n_points,
                           md={'plan_name': 'rel_alignment_scan',
                               'device': device_name,
                               'axis': axis_name,
                               'width': width})


# ═══════════════════════════════════════════════════════════════════════
# Fermat spiral scan (efficient 2D area coverage)
# ═══════════════════════════════════════════════════════════════════════
def fermat_scan(devices: dict, x_range: float, y_range: float,
                dr: float = 0.5, factor: float = 1.0,
                x_center: float = None, y_center: float = None,
                use_scanner: bool = True, detectors=None):
    """Fermat spiral scan for efficient 2D area coverage.

    Better area coverage than raster for the same number of points.
    Useful for ptychography and XRF mapping.

    If x_center/y_center are not given, uses current motor position.

    Args:
        devices: dict from create_devices()
        x_range: full X range in um
        y_range: full Y range in um
        dr: delta radius step in um (default: 0.5)
        factor: scaling factor for spiral density (default: 1.0)
        x_center: X center in um (default: current position)
        y_center: Y center in um (default: current position)
        use_scanner: if True use SX/SY, else FX/FY
        detectors: list of detectors to read
    """
    sample = devices['sample']
    x_motor = sample.sx if use_scanner else sample.fx
    y_motor = sample.sy if use_scanner else sample.fy

    if detectors is None:
        det_list = []
        if 'vxrf' in devices:
            det_list.append(devices['vxrf'])
        ic1 = devices.get('ic1')
        if ic1 is not None:
            det_list.append(ic1)
        detectors = det_list if det_list else []

    if x_center is None:
        x_center = x_motor.position
    if y_center is None:
        y_center = y_motor.position

    log.info(f"Fermat spiral: center=({x_center:.2f}, {y_center:.2f}), "
             f"range={x_range:.1f}x{y_range:.1f} um, dr={dr}, "
             f"motor={'SX/SY' if use_scanner else 'FX/FY'}")

    yield from bp.spiral_fermat(
        detectors, x_motor, y_motor,
        x_center, y_center,
        x_range, y_range,
        dr, factor,
        md={'plan_name': 'fermat_scan',
            'x_center': x_center,
            'y_center': y_center,
            'x_range': x_range,
            'y_range': y_range,
            'dr': dr})


# ═══════════════════════════════════════════════════════════════════════
# Relative raster scan (centered on current position)
# ═══════════════════════════════════════════════════════════════════════
def rel_raster_scan(devices: dict, dx: float, dy: float,
                    nx: int, ny: int, use_scanner: bool = True,
                    detectors=None, use_xrf: bool = True):
    """Relative 2D raster scan centered on current position.

    Scans +/- dx/2, +/- dy/2 around current motor position.
    Convenient for quick area scans without computing absolute positions.

    Args:
        devices: dict from create_devices()
        dx: full X range in um
        dy: full Y range in um
        nx: number of X points
        ny: number of Y points
        use_scanner: if True use SX/SY, else FX/FY
        detectors: list of detectors to read
        use_xrf: if True and vxrf available, include virtual XRF
    """
    sample = devices['sample']
    x_motor = sample.sx if use_scanner else sample.fx
    y_motor = sample.sy if use_scanner else sample.fy

    if detectors is None:
        det_list = []
        if use_xrf and 'vxrf' in devices:
            det_list.append(devices['vxrf'])
        ic1 = devices.get('ic1')
        if ic1 is not None:
            det_list.append(ic1)
        detectors = det_list if det_list else []

    hx, hy = dx / 2.0, dy / 2.0

    log.info(f"Relative raster: +/-{hx:.1f} x +/-{hy:.1f} um, {nx}x{ny} pts, "
             f"motor={'SX/SY' if use_scanner else 'FX/FY'}")

    yield from bp.rel_grid_scan(
        detectors,
        y_motor, -hy, hy, ny,
        x_motor, -hx, hx, nx,
        snake_axes=True,
        md={'plan_name': 'rel_raster_scan',
            'dx': dx, 'dy': dy,
            'nx': nx, 'ny': ny})


# ═══════════════════════════════════════════════════════════════════════
# Tomography scan (theta rotation + 2D raster or 1D projection)
# ═══════════════════════════════════════════════════════════════════════
def tomo_scan(devices: dict, theta_start: float, theta_stop: float,
              n_projections: int, x_range: tuple,
              y_range: tuple = None, nx: int = 21, ny: int = None,
              use_scanner: bool = True, detectors=None,
              use_xrf: bool = True):
    """Tomography scan: rotate sample theta, acquire projection at each angle.

    For 2D XRF tomography: at each theta, do a full 2D raster scan.
    For 1D projection: set y_range=None (or ny=None) for line scans only.

    Args:
        devices: dict from create_devices()
        theta_start: start rotation angle (degrees)
        theta_stop: stop rotation angle (degrees)
        n_projections: number of angular projections
        x_range: (x_start, x_stop) for each projection (um)
        y_range: (y_start, y_stop) for 2D raster (um). None for 1D.
        nx: number of x points per projection
        ny: number of y points per projection (None for 1D)
        use_scanner: if True use SX/SY, else FX/FY
        detectors: list of detectors
        use_xrf: include virtual XRF detector
    """
    sample = devices['sample']
    theta_motor = sample.theta
    theta_positions = np.linspace(theta_start, theta_stop, n_projections)

    is_2d = y_range is not None and ny is not None and ny > 1
    n_pts_per_proj = nx * ny if is_2d else nx
    total_pts = n_projections * n_pts_per_proj

    log.info(f"Tomo scan: theta [{theta_start:.1f}, {theta_stop:.1f}] deg, "
             f"{n_projections} projections, "
             f"{'2D ' + str(nx) + 'x' + str(ny) if is_2d else '1D ' + str(nx)} pts/proj, "
             f"total={total_pts}")

    @run_decorator(md={'plan_name': 'tomo_scan',
                       'theta_start': theta_start,
                       'theta_stop': theta_stop,
                       'n_projections': n_projections,
                       'x_range': list(x_range),
                       'y_range': list(y_range) if y_range else None,
                       'nx': nx, 'ny': ny,
                       'num_points': total_pts})
    def _inner():
        for i, theta in enumerate(theta_positions):
            yield from bps.mv(theta_motor, theta)
            log.info(f"Tomo projection {i+1}/{n_projections}: theta={theta:.2f} deg")

            if is_2d:
                yield from raster_scan(devices, x_range, y_range, nx, ny,
                                       use_scanner=use_scanner,
                                       detectors=detectors, use_xrf=use_xrf)
            else:
                x_start, x_stop = x_range
                yield from line_scan(devices, x_start, 0, x_stop, 0,
                                     nx, use_scanner=use_scanner,
                                     detectors=detectors)

    return (yield from _inner())


# ═══════════════════════════════════════════════════════════════════════
# XANES Imaging (energy stack x 2D raster)
# ═══════════════════════════════════════════════════════════════════════
def xanes_imaging(devices: dict, element: str, edge: str = 'K',
                  x_range: tuple = (-5, 5), y_range: tuple = (-5, 5),
                  nx: int = 21, ny: int = 21,
                  n_energies: int = 50, e_range_eV: float = 100,
                  use_scanner: bool = True, detectors=None,
                  use_xrf: bool = True):
    """XANES imaging: 2D raster at each energy point around absorption edge.

    Produces a spectroscopic image dataset: (n_energies, ny, nx) per element.

    Args:
        devices: dict from create_devices()
        element: element symbol (e.g. 'Fe', 'Cu')
        edge: absorption edge ('K', 'L3', etc.)
        x_range: (x_start, x_stop) for raster (um)
        y_range: (y_start, y_stop) for raster (um)
        nx: number of x points
        ny: number of y points
        n_energies: number of energy points
        e_range_eV: total energy range in eV (centered on edge)
        use_scanner: if True use SX/SY, else FX/FY
        detectors: list of detectors
        use_xrf: include virtual XRF detector
    """
    if element not in ABSORPTION_EDGES:
        raise ValueError(f"Unknown element: {element}")
    edges = ABSORPTION_EDGES[element]
    if edge not in edges:
        raise ValueError(f"No {edge} edge for {element}")

    e0_keV = edges[edge]
    half_range_keV = e_range_eV / 2000.0
    energies_keV = np.linspace(e0_keV - half_range_keV,
                                e0_keV + half_range_keV, n_energies)
    dcm = devices['dcm']
    total_pts = n_energies * nx * ny

    log.info(f"XANES imaging: {element} {edge}-edge at {e0_keV:.3f} keV, "
             f"{n_energies} energies x {nx}x{ny} = {total_pts} total pts")

    @run_decorator(md={'plan_name': 'xanes_imaging',
                       'element': element, 'edge': edge,
                       'e0_keV': e0_keV,
                       'n_energies': n_energies,
                       'e_range_eV': e_range_eV,
                       'x_range': list(x_range),
                       'y_range': list(y_range),
                       'nx': nx, 'ny': ny,
                       'num_points': total_pts})
    def _inner():
        for i, e_keV in enumerate(energies_keV):
            theta = energy_to_theta(e_keV)
            yield from bps.mv(dcm.theta, theta)
            log.info(f"XANES energy {i+1}/{n_energies}: "
                     f"{e_keV:.4f} keV (theta={theta:.4f} deg)")

            # Update virtual XRF detector energy
            vxrf = devices.get('vxrf')
            if vxrf is not None and hasattr(vxrf, 'energy_keV'):
                vxrf.energy_keV = e_keV

            yield from raster_scan(devices, x_range, y_range, nx, ny,
                                   use_scanner=use_scanner,
                                   detectors=detectors, use_xrf=use_xrf)

    return (yield from _inner())


# ═══════════════════════════════════════════════════════════════════════
# Multi-ROI raster (survey + high-res ROIs)
# ═══════════════════════════════════════════════════════════════════════
def multi_roi_raster(devices: dict, survey_x_range: tuple, survey_y_range: tuple,
                     survey_nx: int, survey_ny: int,
                     rois: list, roi_nx: int = 51, roi_ny: int = 51,
                     use_scanner: bool = True, detectors=None,
                     use_xrf: bool = True):
    """Survey scan at coarse resolution, then zoom into ROIs at fine resolution.

    Args:
        devices: dict from create_devices()
        survey_x_range: (x_start, x_stop) for survey (um)
        survey_y_range: (y_start, y_stop) for survey (um)
        survey_nx: survey x points (coarse)
        survey_ny: survey y points (coarse)
        rois: list of (x_center, y_center, width, height) tuples
        roi_nx: x points per ROI (fine)
        roi_ny: y points per ROI (fine)
        use_scanner: if True use SX/SY, else FX/FY
        detectors: list of detectors
        use_xrf: include virtual XRF detector
    """
    total_pts = survey_nx * survey_ny + len(rois) * roi_nx * roi_ny

    log.info(f"Multi-ROI raster: survey {survey_nx}x{survey_ny} + "
             f"{len(rois)} ROIs @ {roi_nx}x{roi_ny}, total={total_pts}")

    @run_decorator(md={'plan_name': 'multi_roi_raster',
                       'survey_nx': survey_nx, 'survey_ny': survey_ny,
                       'n_rois': len(rois),
                       'roi_nx': roi_nx, 'roi_ny': roi_ny,
                       'num_points': total_pts})
    def _inner():
        # Phase 1: Survey scan
        log.info("Multi-ROI: survey scan")
        yield from raster_scan(devices, survey_x_range, survey_y_range,
                               survey_nx, survey_ny,
                               use_scanner=use_scanner,
                               detectors=detectors, use_xrf=use_xrf)

        # Phase 2: ROI scans
        for j, roi in enumerate(rois):
            xc, yc, w, h = roi
            roi_x_range = (xc - w / 2.0, xc + w / 2.0)
            roi_y_range = (yc - h / 2.0, yc + h / 2.0)
            log.info(f"Multi-ROI: ROI {j+1}/{len(rois)} at ({xc:.1f}, {yc:.1f})")
            yield from raster_scan(devices, roi_x_range, roi_y_range,
                                   roi_nx, roi_ny,
                                   use_scanner=use_scanner,
                                   detectors=detectors, use_xrf=use_xrf)

    return (yield from _inner())


# ═══════════════════════════════════════════════════════════════════════
# Nano Scanner scans (SmarAct MCS2 + PicoScale)
# ═══════════════════════════════════════════════════════════════════════
def nano_raster_scan(devices: dict, x_range: tuple, y_range: tuple,
                     nx: int, ny: int, detectors=None):
    """2D raster scan using Fast Nano Scanner (SmarAct MCS2).

    Uses BL10:SCAN:X/Y motors with PicoScale encoder readback.
    Positions in nanometers (nm).

    Args:
        devices: dict from create_devices()
        x_range: (x_start, x_stop) in nm
        y_range: (y_start, y_stop) in nm
        nx: number of x points
        ny: number of y points
        detectors: list of detectors to read

    Yields:
        bluesky messages
    """
    scanner = devices['scanner']

    if detectors is None:
        det_list = []
        ic1 = devices.get('ic1')
        if ic1 is not None:
            det_list.append(ic1)
        detectors = det_list

    x_start, x_stop = x_range
    y_start, y_stop = y_range

    log.info(f"Nano raster: X[{x_start}, {x_stop}] x Y[{y_start}, {y_stop}] nm, "
             f"{nx}x{ny} = {nx*ny} points")

    yield from bp.grid_scan(detectors,
                            scanner.y, y_start, y_stop, ny,
                            scanner.x, x_start, x_stop, nx,
                            snake_axes=True,
                            md={'plan_name': 'nano_raster_scan',
                                'x_range': list(x_range),
                                'y_range': list(y_range),
                                'nx': nx, 'ny': ny,
                                'unit': 'nm'})


def nano_line_scan(devices: dict, axis: str, start: float, stop: float,
                   n_points: int, detectors=None):
    """1D line scan using Fast Nano Scanner.

    Args:
        devices: dict from create_devices()
        axis: 'x', 'y', or 'z'
        start: start position (nm)
        stop: stop position (nm)
        n_points: number of points
        detectors: list of detectors to read

    Yields:
        bluesky messages
    """
    scanner = devices['scanner']
    motor = getattr(scanner, axis, None)
    if motor is None:
        raise ValueError(f"Unknown scanner axis: {axis}")

    if detectors is None:
        det_list = []
        ic1 = devices.get('ic1')
        if ic1 is not None:
            det_list.append(ic1)
        detectors = det_list

    log.info(f"Nano line scan: {axis} [{start}, {stop}] nm, {n_points} pts")

    yield from bp.scan(detectors, motor, start, stop, n_points,
                       md={'plan_name': 'nano_line_scan',
                           'axis': axis,
                           'start': start, 'stop': stop,
                           'unit': 'nm'})


def nano_spiral_scan(devices: dict, x_center: float, y_center: float,
                     radius_nm: float, dr_nm: float = 50.0,
                     detectors=None):
    """Fermat spiral scan using Fast Nano Scanner.

    Efficient area coverage for ptychography.

    Args:
        devices: dict from create_devices()
        x_center: spiral center X (nm)
        y_center: spiral center Y (nm)
        radius_nm: maximum radius (nm)
        dr_nm: radial step (nm)
        detectors: list of detectors

    Yields:
        bluesky messages
    """
    scanner = devices['scanner']

    if detectors is None:
        det_list = []
        ic1 = devices.get('ic1')
        if ic1 is not None:
            det_list.append(ic1)
        detectors = det_list

    log.info(f"Nano spiral: center=({x_center}, {y_center}) nm, "
             f"R={radius_nm} nm, dr={dr_nm} nm")

    yield from bp.spiral_fermat(
        detectors, scanner.x, scanner.y,
        x_center, y_center,
        radius_nm * 2, radius_nm * 2,  # x_range, y_range (diameter)
        dr_nm, 1.0,
        md={'plan_name': 'nano_spiral_scan',
            'x_center': x_center, 'y_center': y_center,
            'radius_nm': radius_nm, 'dr_nm': dr_nm,
            'unit': 'nm'})
