"""RE Manager startup profile for the K4GSR BL10 NanoProbe queueserver backend.

This module is loaded by ``start-re-manager --startup-module
scan_engine.qserver_profile`` (B1, Phase-1 roadmap). It defines, in its module
namespace:

  * ``RE``      -- a bluesky RunEngine (qserver runs plans against this object).
  * devices     -- the SAME ophyd devices as the in-process engine, so the
                   allowed-plans/devices registry matches ``BlueskyRunner``.
  * plan funcs  -- qserver-friendly wrappers around ``scan_engine.plans`` plus
                   the stock ``count``/``scan`` (used for the abort/E2E paths).

Device path toggle (env ``QSERVER_DEVICE_PATH``):

  * ``epics`` (default) -- reuse ``scan_engine.devices.create_devices`` and
    connect to the caproto soft IOC, exactly like the in-process engine. This is
    the production / VM1 path.
  * ``sim``             -- ophyd.sim simulated detector + motor (no EPICS). Used
    for local E2E on machines where live EPICS-CA is unavailable/flaky (Windows).
    Proves the QUEUE mechanics; full real-device E2E is deferred to VM1.

Why wrappers: the project plans in ``scan_engine.plans`` take a ``devices`` dict
as their first positional argument. qserver resolves plan arguments from the
namespace and cannot pass a Python dict, so we expose thin wrappers that close
over the module-level ``DEVICES`` dict and forward the user kwargs. The wrapper
names match the project plan names so a queue item added as ``energy_scan`` here
maps 1:1 to ``BlueskyRunner.submit('energy_scan', ...)``.
"""

import os
import logging

from bluesky import RunEngine

# Stock plans used directly (count is the E2E / abort vehicle; scan is generic).
# These MUST live in the module namespace so the RE Manager registers them as
# allowed plans -- __all__ documents that and keeps linters happy.
from bluesky.plans import count, scan

__all__ = ["RE", "count", "scan"]

log = logging.getLogger("bl10-qserver-profile")

# ── RunEngine (qserver executes queue items against this) ──
RE = RunEngine({})

_DEVICE_PATH = os.environ.get("QSERVER_DEVICE_PATH", "epics").strip().lower()


# ── Build the device namespace ───────────────────────────────────────────
def _build_devices():
    """Create the device dict according to QSERVER_DEVICE_PATH.

    Returns (devices_dict, individual_device_objects_to_export).
    """
    if _DEVICE_PATH == "sim":
        from ophyd.sim import det, motor
        # Minimal dict that the wrapper plans below understand.
        return {"_sim_det": det, "_sim_motor": motor}, {"det": det, "motor": motor}

    # Default: reuse the in-process engine's exact devices.
    try:
        from scan_engine.devices import create_devices, connect_devices
    except ImportError:
        from devices import create_devices, connect_devices  # type: ignore

    devices = create_devices()

    # Drop device keys whose PVs are not served by the IOC (mirrors the
    # in-process server's --exclude-groups). On a partially-served IOC (e.g.
    # VM1 excludes SAM/XBPM2/SCAN -> device keys sample/xbpm2/scanner) trying
    # to connect these stalls the worker environment for timeout x N seconds,
    # and the profile loads TWICE (list-gen + worker), so it dominates startup.
    # QSERVER_EXCLUDE_DEVICES is a space/comma list of device dict keys.
    _excl = os.environ.get("QSERVER_EXCLUDE_DEVICES", "").replace(",", " ").split()
    for _k in _excl:
        if devices.pop(_k, None) is not None:
            log.info("qserver profile: excluded unserved device '%s'", _k)

    try:
        # Default kept short so unserved devices fail fast (like the in-process
        # engine's hybrid timeout) instead of blocking environment_open.
        timeout = float(os.environ.get("QSERVER_CONNECT_TIMEOUT", "2.0"))
        connect_devices(devices, timeout=timeout)
    except Exception as e:  # never block environment_open on a flaky IOC
        log.warning(f"Device connection issue (continuing): {e}")
    return devices, {}


DEVICES, _exports = _build_devices()
# Export individual device objects into the module namespace so qserver lists
# them as allowed devices (e.g. det, motor for the sim path).
globals().update(_exports)


# ── Plan wrappers (project plans take a devices dict; qserver cannot) ──────
# Each wrapper closes over DEVICES and forwards user params. Names mirror the
# project plan names so queue items map 1:1 to BlueskyRunner.submit(...).
def _make_wrapper(plan_name):
    try:
        from scan_engine import plans as _plans
    except ImportError:
        import plans as _plans  # type: ignore
    fn = getattr(_plans, plan_name)

    def _wrapper(**params):
        yield from fn(DEVICES, **params)

    _wrapper.__name__ = plan_name
    _wrapper.__doc__ = (fn.__doc__ or f"{plan_name} (qserver wrapper)")
    return _wrapper


# Only register wrappers when running the EPICS device path (the project plans
# need the real device dict). For the sim path, count/scan over det/motor are
# sufficient to prove the queue mechanics.
if _DEVICE_PATH != "sim":
    _WRAPPED_PLANS = [
        "energy_scan", "xafs_scan", "xanes_scan", "multi_region_scan",
        "raster_scan", "alignment_scan", "beam_check", "fly_scan",
        "line_scan", "auto_tune", "adaptive_energy_scan",
        "rel_alignment_scan", "fermat_scan", "rel_raster_scan",
        "tomo_scan", "xanes_imaging", "multi_roi_raster",
        "nano_raster_scan", "nano_line_scan", "nano_spiral_scan",
    ]
    for _pn in _WRAPPED_PLANS:
        try:
            globals()[_pn] = _make_wrapper(_pn)
        except Exception as _e:  # skip a plan that fails to import; log it
            log.warning(f"Could not register plan wrapper '{_pn}': {_e}")

log.info(
    f"qserver startup profile loaded (device_path={_DEVICE_PATH}, "
    f"devices={len(DEVICES)})"
)
