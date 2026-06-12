#!/usr/bin/env python3
"""ophyd AreaDetector device for the ADSim IOC (Phase-1 C1 detector data path).

Wraps the ADSimDetector IOC (simDetector driver + NDFileHDF5 plugin) built on
VM1 as the stand-in for the future EIGER2/Pilatus integration (manuscript
paragraph 28). The detector DATA path (driver -> NDFileHDF5 -> HDF5 file on
disk) is deliberately separate from the CONTROL path (CA PVs); Bluesky events
carry only datum references, never frames.

ROLE SEPARATION (Phase-1 roadmap section 3): this module is the CONTROL-STACK
rehearsal for real areaDetector IOCs. The browser-side `js/detector/01_eiger.js`
simulation is the virtual-experiment VISUALIZATION (XRD images / XRF spectra)
and is NOT replaced by this — the two serve different purposes.

IOC (VM1, ~/ADSim_build/iocSim/st.cmd):
    prefix BL10:SIM1: , ports cam1: / image1: / HDF1:
    CA server port 5080, LOOPBACK ONLY (production soft IOC on 5064 untouched)
    PVA on 5085 (unused here), HDF1:LazyOpen=1 set at boot
    simDetector 1024x1024 UInt8 by default

Client environment (REQUIRED — the IOC is invisible without it):
    EPICS_CA_ADDR_LIST must contain "127.0.0.1:5080"
        (host:port entries are supported by libca/pyepics, so the same process
        can still reach the production soft IOC via a plain "127.0.0.1" entry
        on the default port 5064)
    EPICS_CA_AUTO_ADDR_LIST=NO
    Alternative: EPICS_CA_ADDR_LIST=127.0.0.1 + EPICS_CA_SERVER_PORT=5080
        (process-wide port override — do NOT use inside server.py, it would
        redirect ALL CA traffic away from the production IOC)
    NOTE: libca reads these at CA-context creation (first PV connection).
    Call ensure_adsim_ca_env() BEFORE any ophyd/pyepics connection is made.

Usage (on VM1):
    from scan_engine.ad_devices import ensure_adsim_ca_env, get_adsim_detector
    ensure_adsim_ca_env()                  # before first CA connection
    det = get_adsim_detector()             # connects + primes HDF5 plugin
    from bluesky import RunEngine
    from bluesky.plans import count
    RE = RunEngine({})
    RE(count([det], num=5))                # -> one HDF5 file with 5 frames

Requires:
    - ADSim IOC running (cd ~/ADSim_build/iocSim &&
      nohup bash -c "tail -f /dev/null | $TOP/bin/linux-x86_64/simDetectorApp st.cmd" &)
    - ophyd >= 1.11 (import-safe without it: HAVE_OPHYD flag, factory raises)
"""

import os
import logging

log = logging.getLogger("bl10-ad-devices")

# ═══════════════════════════════════════════════════════════════════════
# Configuration (env-overridable)
# ═══════════════════════════════════════════════════════════════════════
ADSIM_PREFIX = os.environ.get("ADSIM_PREFIX", "BL10:SIM1:")
ADSIM_CA_PORT = os.environ.get("ADSIM_CA_PORT", "5080")
# Write path as seen by the IOC (= local path: IOC and clients share VM1)
ADSIM_DATA_DIR = os.environ.get(
    "ADSIM_DATA_DIR", os.path.expanduser("~/ADSim_build/data"))

# Import-safe when ophyd is missing (e.g. dev PC without the venv)
try:
    from ophyd.areadetector import (
        DetectorBase, SimDetectorCam, SingleTrigger, ADComponent as ADCpt)
    from ophyd.areadetector.plugins import HDF5Plugin
    from ophyd.areadetector.filestore_mixins import FileStoreHDF5IterativeWrite
    HAVE_OPHYD = True
    _OPHYD_IMPORT_ERROR = None
except ImportError as e:  # pragma: no cover
    HAVE_OPHYD = False
    _OPHYD_IMPORT_ERROR = e
    log.warning(f"ophyd.areadetector not available — ADSim device disabled: {e}")


def ensure_adsim_ca_env():
    """Make the loopback-only ADSim IOC (CA port 5080) reachable.

    Appends "127.0.0.1:<ADSIM_CA_PORT>" to EPICS_CA_ADDR_LIST (keeping any
    existing entries, e.g. the production 5064 IOC) and pins
    EPICS_CA_AUTO_ADDR_LIST=NO. Must run BEFORE the first CA connection in
    this process — libca snapshots the env when its context is created.
    """
    entry = f"127.0.0.1:{ADSIM_CA_PORT}"
    addr_list = os.environ.get("EPICS_CA_ADDR_LIST", "")
    if entry not in addr_list.split():
        os.environ["EPICS_CA_ADDR_LIST"] = (addr_list + " " + entry).strip()
    os.environ.setdefault("EPICS_CA_AUTO_ADDR_LIST", "NO")
    log.info(f"EPICS_CA_ADDR_LIST={os.environ['EPICS_CA_ADDR_LIST']}")


if HAVE_OPHYD:

    # ═══════════════════════════════════════════════════════════════════
    # HDF5 file-writer plugin (NDFileHDF5) with Bluesky filestore staging
    # ═══════════════════════════════════════════════════════════════════
    class ADSimHDF5Plugin(HDF5Plugin, FileStoreHDF5IterativeWrite):
        """NDFileHDF5 staged for Stream capture, one file per Bluesky run.

        FileStoreHDF5IterativeWrite handles: file path/name/number staging,
        file_write_mode=Stream + capture=1 on stage (capture reverts to 0 on
        unstage, closing the file), one datum document per trigger
        (point_number-indexed frames in '/entry/data/data').
        IOC-side HDF1:LazyOpen=1 (st.cmd) lets capture arm before the first
        frame; ophyd-side the plugin must still be primed once after IOC boot
        (see prime_hdf5_plugin) so HDF5Plugin.stage() knows the array dims.
        """

        def get_frames_per_point(self):
            return self.parent.cam.num_images.get()

    # ═══════════════════════════════════════════════════════════════════
    # ADSim detector (SimDetectorCam + HDF5 writer)
    # ═══════════════════════════════════════════════════════════════════
    class ADSimDetector(SingleTrigger, DetectorBase):
        """simDetector with HDF5 data path, Bluesky-ready (SingleTrigger).

        Each trigger acquires one frame (cam staged to image_mode='Multiple',
        num_images=1 — TriggerBase convention) which NDFileHDF5 appends to the
        per-run HDF5 file. read() returns a datum reference, not pixels.
        """
        cam = ADCpt(SimDetectorCam, "cam1:")
        hdf5 = ADCpt(ADSimHDF5Plugin, "HDF1:",
                     write_path_template=ADSIM_DATA_DIR.rstrip("/") + "/",
                     read_path_template=ADSIM_DATA_DIR.rstrip("/") + "/",
                     root="/")

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.cam.stage_sigs["num_images"] = 1
            self.cam.stage_sigs["array_callbacks"] = 1
            # Stream until unstage closes the file (frames = #triggers)
            self.hdf5.stage_sigs["num_capture"] = 0
            # Event payload = the image datum only; cam scalars stay config
            self.hdf5.read_attrs = []
            self.read_attrs = ["hdf5"]
            self.configuration_attrs = [
                "cam.acquire_time", "cam.acquire_period", "cam.image_mode",
                "cam.data_type", "cam.size.size_x", "cam.size.size_y"]


def prime_hdf5_plugin(det, timeout: float = 15.0):
    """Push one frame through the plugin chain after IOC boot.

    HDF5Plugin.stage() raises UnprimedPlugin until the plugin has seen one
    NDArray (array dims unknown); IOC-side the symptom is "must collect an
    array to get dimensions first". LazyOpen=1 (st.cmd) covers the IOC side;
    this covers the ophyd side via the stock HDF5Plugin.warmup() (acquires a
    single throwaway frame, ~3 s). No-op if the plugin already saw a frame.
    """
    try:
        if sum(det.hdf5.array_size.get()) > 0:
            return False
    except Exception as e:
        log.warning(f"array_size read failed (priming anyway): {e}")
    log.info("Priming HDF5 plugin (one throwaway frame)...")
    det.hdf5.warmup()
    return True


def get_adsim_detector(prefix: str = None, name: str = "adsim",
                       connect: bool = True, timeout: float = 10.0):
    """Create the ADSim detector device (and connect + prime it).

    Args:
        prefix: PV prefix (default env ADSIM_PREFIX -> 'BL10:SIM1:').
        name: ophyd device name (event keys become '<name>_image').
        connect: wait for CA connection and prime the HDF5 plugin.
        timeout: CA connection timeout in seconds.

    Raises:
        RuntimeError: ophyd missing, or the IOC is unreachable (check that
            the ADSim IOC is running and ensure_adsim_ca_env() was called
            before any CA connection).
    """
    if not HAVE_OPHYD:
        raise RuntimeError(
            f"ophyd.areadetector unavailable: {_OPHYD_IMPORT_ERROR}")
    det = ADSimDetector(prefix or ADSIM_PREFIX, name=name)
    if connect:
        try:
            det.wait_for_connection(timeout=timeout)
        except Exception as e:
            raise RuntimeError(
                f"ADSim IOC ({prefix or ADSIM_PREFIX}, CA :{ADSIM_CA_PORT}) "
                f"unreachable — is the IOC running and was "
                f"ensure_adsim_ca_env() called before any CA use? {e}") from e
        prime_hdf5_plugin(det)
    return det
