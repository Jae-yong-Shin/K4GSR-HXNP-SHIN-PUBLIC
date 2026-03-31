#!/usr/bin/env python3
"""Bluesky RunEngine wrapper with WebSocket event broadcasting.

Wraps the standard Bluesky RunEngine to:
  1. Run scan plans against caproto Soft IOC PVs
  2. Broadcast scan events (start, descriptor, event, stop) to WebSocket clients
  3. Provide a simple API for the NLP agent to queue/execute plans

Architecture:
    NLP Agent / WebSocket client
        |  (plan request)
        v
    BlueskyRunner.submit(plan_name, **params)
        |
        v
    RunEngine(plan_generator)
        |  (reads/moves EPICS PVs via ophyd)
        v
    caproto Soft IOC
        |
        v
    pv_store.py (simulation)

Usage:
    runner = BlueskyRunner()
    runner.start()
    uid = runner.submit('energy_scan', e_start=8.9, e_stop=9.1, n_points=100)
    runner.status()  # {'state': 'running', 'plan': 'energy_scan', ...}
    runner.stop()

WebSocket integration:
    runner = BlueskyRunner(ws_callback=my_broadcast_func)
    # my_broadcast_func receives: {'type': 'scan_event', 'doc_type': 'event', 'doc': {...}}
"""

import asyncio
import os
import threading
import time
import logging
import uuid
from typing import Optional, Callable, Any, Dict
from datetime import datetime

import numpy as np
from bluesky import RunEngine
from bluesky.callbacks.best_effort import BestEffortCallback

from .devices import create_devices, connect_devices
from . import plans

log = logging.getLogger("bl10-runner")

# Data directory for auto-saved scan files
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'scans')
os.makedirs(DATA_DIR, exist_ok=True)


class BlueskyRunner:
    """Manages RunEngine lifecycle and plan execution in a background thread."""

    def __init__(self, ws_callback: Optional[Callable] = None,
                 connect_timeout: float = 10.0):
        """Initialize BlueskyRunner.

        Args:
            ws_callback: async function(event_dict) called for each scan event.
                         Event dict: {'type': 'scan_event', 'doc_type': str, 'doc': dict}
            connect_timeout: timeout for EPICS device connections.
        """
        self._ws_callback = ws_callback
        self._connect_timeout = connect_timeout
        self._re: Optional[RunEngine] = None
        self._devices: Optional[dict] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._current_plan: Optional[str] = None
        self._current_uid: Optional[str] = None
        self._state = 'idle'  # idle, connecting, running, paused, error
        self._last_error: Optional[str] = None
        self._event_count = 0
        # Auto-save: accumulate documents during scan
        self._scan_docs: list = []      # collected event data dicts
        self._scan_metadata: dict = {}  # start document metadata
        self._auto_save = True          # enable auto-save to HDF5
        self._live_write = True         # enable incremental HDF5 writing
        self._active_writer = None      # NexusWriter during live scan
        self._active_filepath = None    # path to current H5 file
        self._active_columns = None     # column names for extensible dataset
        self._scan_db = None            # ScanDB instance (lazy init)
        self._init_scan_db()

    def _init_scan_db(self):
        """Initialize SQLite scan history database."""
        try:
            import sys as _sys
            import os as _os
            _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..'))
            from data.scan_db import ScanDB
            self._scan_db = ScanDB()
        except Exception as e:
            log.warning(f"ScanDB init failed (history disabled): {e}")

    @property
    def state(self):
        return self._state

    def status(self) -> dict:
        """Return current runner status."""
        return {
            'state': self._state,
            'plan': self._current_plan,
            'uid': self._current_uid,
            'event_count': self._event_count,
            'last_error': self._last_error,
            'devices_connected': self._devices is not None,
            'auto_save': self._auto_save,
            'data_dir': DATA_DIR,
        }

    def start(self):
        """Initialize RunEngine and connect to EPICS devices."""
        if self._state == 'running':
            log.warning("Runner already running")
            return

        self._state = 'connecting'
        log.info("Initializing Bluesky RunEngine...")

        try:
            # Create RunEngine (disable signal handlers for thread-safe operation)
            self._re = RunEngine({}, context_managers=[])
            self._re.subscribe(self._document_callback)

            # Add best effort callback for logging
            bec = BestEffortCallback()
            self._re.subscribe(bec)

            # Create and connect devices
            self._devices = create_devices()
            n_ok, n_fail = connect_devices(self._devices, self._connect_timeout)

            if n_ok == 0:
                raise RuntimeError("No devices connected. Is soft_ioc.py running?")

            # Add SupplementalData preprocessor for baseline readings
            try:
                from bluesky.preprocessors import SupplementalData
                sd = SupplementalData()
                baseline_devs = []
                for key in ['ring', 'xbpm1', 'xbpm2']:
                    dev = self._devices.get(key)
                    if dev is not None:
                        baseline_devs.append(dev)
                sd.baseline = baseline_devs
                self._re.preprocessors.append(sd)
                log.info(f"SupplementalData: {len(baseline_devs)} baseline devices")
            except Exception as e:
                log.warning(f"SupplementalData setup failed: {e}")

            self._state = 'idle'
            log.info(f"BlueskyRunner ready: {n_ok} devices, RunEngine idle")

        except Exception as e:
            self._state = 'error'
            self._last_error = str(e)
            log.error(f"Runner start failed: {e}")
            raise

    def _document_callback(self, name: str, doc: dict):
        """Called by RunEngine for each document (start, descriptor, event, stop)."""
        _ts_callback = time.time()

        if name == 'start':
            self._scan_docs = []
            self._scan_metadata = dict(doc)
            # Open live HDF5 writer for incremental saves
            if self._live_write and self._auto_save:
                self._open_live_writer(doc)

        if name == 'event':
            self._event_count += 1
            data = dict(doc.get('data', {}))
            # D13: only accumulate in RAM when live writer is inactive
            # (live writer streams directly to disk, avoiding OOM on large scans)
            if self._active_writer:
                self._write_live_event(data)
            else:
                self._scan_docs.append(data)

        if name == 'stop':
            self._state = 'idle'
            exit_status = doc.get('exit_status', 'unknown')
            log.info(f"Plan completed: {exit_status}")
            # Finalize live HDF5 file
            if self._active_writer:
                self._close_live_writer(doc)
            elif self._auto_save and exit_status == 'success' and self._scan_docs:
                # Fallback: batch save if live write was not active
                self._save_scan_data(doc)
            self._current_plan = None

        # Broadcast to WebSocket if callback provided
        if self._ws_callback:
            event = {
                'type': 'scan_event',
                'doc_type': name,
                'doc': _serialize_doc(doc),
                'plan': self._current_plan,
                'event_count': self._event_count,
                '_ts_callback': _ts_callback,
                '_ts_send': time.time(),
            }
            try:
                # ws_callback might be async — schedule if we have a loop
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._ws_callback(event), self._loop
                    )
                else:
                    # Synchronous fallback
                    self._ws_callback(event)
            except Exception as e:
                log.warning(f"WS broadcast error: {e}")

    @staticmethod
    def _estimate_num_points(plan_name: str, kwargs: dict) -> int:
        """Estimate total number of points for a plan (for progress display).

        Standard bp.scan/grid_scan/list_scan set num_points automatically.
        This provides a fallback for composite or custom plans.
        """
        if plan_name == 'raster_scan' or plan_name == 'rel_raster_scan':
            return kwargs.get('nx', 1) * kwargs.get('ny', 1)
        elif plan_name in ('energy_scan', 'alignment_scan', 'fly_scan',
                           'rel_alignment_scan', 'line_scan'):
            return kwargs.get('n_points', 0)
        elif plan_name == 'beam_check':
            return kwargs.get('n_readings', 5)
        elif plan_name == 'tomo_scan':
            n_proj = kwargs.get('n_projections', 1)
            nx = kwargs.get('nx', 1)
            ny = kwargs.get('ny', 1) if kwargs.get('y_range') else 1
            return n_proj * nx * ny
        elif plan_name == 'xanes_imaging':
            return kwargs.get('n_energies', 1) * kwargs.get('nx', 1) * kwargs.get('ny', 1)
        elif plan_name == 'multi_roi_raster':
            survey = kwargs.get('survey_nx', 1) * kwargs.get('survey_ny', 1)
            rois = kwargs.get('rois', [])
            roi_pts = len(rois) * kwargs.get('roi_nx', 1) * kwargs.get('roi_ny', 1)
            return survey + roi_pts
        return 0

    def submit(self, plan_name: str, **kwargs) -> Optional[str]:
        """Submit a plan for execution.

        Args:
            plan_name: one of 'energy_scan', 'xafs_scan', 'raster_scan',
                       'alignment_scan', 'beam_check', etc.
            **kwargs: plan-specific parameters

        Returns:
            Run UID or None if failed.
        """
        if self._re is None or self._devices is None:
            log.error("Runner not started. Call start() first.")
            return None

        if self._state == 'running':
            log.warning("A plan is already running")
            return None

        plan_func = getattr(plans, plan_name, None)
        if plan_func is None:
            log.error(f"Unknown plan: {plan_name}")
            return None

        self._current_plan = plan_name
        self._state = 'running'
        self._event_count = 0

        log.info(f"Executing plan: {plan_name}({kwargs})")

        # Estimate num_points for progress display (safety net)
        md_extra = {}
        est = self._estimate_num_points(plan_name, kwargs)
        if est > 0:
            md_extra['num_points'] = est
            md_extra['plan_args'] = {k: v for k, v in kwargs.items()
                                     if isinstance(v, (int, float, str, bool, list, tuple))}

        try:
            plan_gen = plan_func(self._devices, **kwargs)
            uids = self._re(plan_gen, **md_extra)
            self._current_uid = uids[0] if uids else None
            return self._current_uid
        except Exception as e:
            self._state = 'error'
            self._last_error = str(e)
            self._current_plan = None
            log.error(f"Plan execution failed: {e}")
            return None

    def submit_async(self, plan_name: str, loop: asyncio.AbstractEventLoop,
                     **kwargs):
        """Submit a plan for execution in a background thread.

        Args:
            plan_name: plan name
            loop: asyncio event loop for WS callbacks
            **kwargs: plan parameters
        """
        self._loop = loop

        def _run():
            self.submit(plan_name, **kwargs)

        self._thread = threading.Thread(target=_run, daemon=True,
                                        name=f"bluesky-{plan_name}")
        self._thread.start()

    def abort(self, reason: str = "User abort"):
        """Abort the currently running plan."""
        if self._re and self._state == 'running':
            log.info(f"Aborting plan: {reason}")
            self._re.abort(reason=reason)
            self._state = 'idle'
            self._current_plan = None

    def pause(self):
        """Pause the currently running plan."""
        if self._re and self._state == 'running':
            self._re.request_pause(defer=True)
            self._state = 'paused'

    def resume(self):
        """Resume a paused plan."""
        if self._re and self._state == 'paused':
            self._re.resume()
            self._state = 'running'

    def list_plans(self) -> list:
        """Return available plan names and descriptions."""
        return [
            {'name': 'energy_scan',
             'desc': 'Scan photon energy (DCM theta)',
             'params': ['e_start', 'e_stop', 'n_points']},
            {'name': 'xafs_scan',
             'desc': 'Multi-region XAFS step scan',
             'params': ['element', 'edge']},
            {'name': 'xanes_scan',
             'desc': 'Fine near-edge XANES scan (0.25 eV resolution)',
             'params': ['element', 'edge']},
            {'name': 'multi_region_scan',
             'desc': 'Arbitrary multi-region energy scan',
             'params': ['regions']},
            {'name': 'raster_scan',
             'desc': '2D XRF/XRD mapping scan',
             'params': ['x_range', 'y_range', 'nx', 'ny']},
            {'name': 'fly_scan',
             'desc': 'Fast continuous-motion scan (step-emulated)',
             'params': ['motor_name', 'axis_name', 'start', 'stop', 'n_points']},
            {'name': 'line_scan',
             'desc': '1D line scan along arbitrary direction',
             'params': ['x_start', 'y_start', 'x_stop', 'y_stop', 'n_points']},
            {'name': 'alignment_scan',
             'desc': '1D alignment peak scan',
             'params': ['device_name', 'axis_name', 'center', 'width']},
            {'name': 'beam_check',
             'desc': 'Check beam stability',
             'params': ['n_readings', 'delay']},
            {'name': 'auto_tune',
             'desc': 'Iterative centroid alignment (auto-tune)',
             'params': ['device_name', 'axis_name', 'start', 'stop']},
            {'name': 'adaptive_energy_scan',
             'desc': 'Adaptive energy scan (auto-densify at edges)',
             'params': ['e_start', 'e_stop']},
            {'name': 'rel_alignment_scan',
             'desc': 'Relative alignment scan (+/- width)',
             'params': ['device_name', 'axis_name', 'width']},
            {'name': 'fermat_scan',
             'desc': 'Fermat spiral scan (efficient 2D coverage)',
             'params': ['x_range', 'y_range', 'dr']},
            {'name': 'rel_raster_scan',
             'desc': 'Relative raster scan (centered on current pos)',
             'params': ['dx', 'dy', 'nx', 'ny']},
            {'name': 'tomo_scan',
             'desc': 'Tomography scan (theta rotation + projection)',
             'params': ['theta_start', 'theta_stop', 'n_projections',
                        'x_range', 'y_range', 'nx', 'ny']},
            {'name': 'xanes_imaging',
             'desc': 'XANES imaging (energy stack x 2D raster)',
             'params': ['element', 'edge', 'x_range', 'y_range',
                        'nx', 'ny', 'n_energies', 'e_range_eV']},
            {'name': 'multi_roi_raster',
             'desc': 'Multi-ROI raster (survey + high-res ROIs)',
             'params': ['survey_x_range', 'survey_y_range',
                        'survey_nx', 'survey_ny', 'rois',
                        'roi_nx', 'roi_ny']},
        ]

    def _open_live_writer(self, start_doc: dict):
        """Open HDF5 file at scan start for incremental writing."""
        try:
            from ..data.writer import NexusWriter
        except ImportError:
            log.warning("NexusWriter not available — live write disabled")
            return

        plan = start_doc.get('plan_name',
               start_doc.get('plan_type', self._current_plan or 'unknown'))
        uid = start_doc.get('uid', 'no-uid')[:8]
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{ts}_{plan}_{uid}.h5"
        filepath = os.path.join(DATA_DIR, filename)

        try:
            writer = NexusWriter(filepath)
            writer.open()

            energy = start_doc.get('energy_start',
                     start_doc.get('energy', 10.0))
            writer.write_metadata(
                energy_keV=float(energy) if energy else 10.0,
                scan_type=plan,
                uid=uid,
                num_points=start_doc.get('num_points', 0),
            )

            self._active_writer = writer
            self._active_filepath = filepath
            self._active_columns = None
            log.info(f"Live HDF5 opened: {filepath}")
        except Exception as e:
            log.error(f"Failed to open live HDF5: {e}")
            self._active_writer = None

    def _write_live_event(self, data: dict):
        """Write a single event to the live HDF5 file incrementally."""
        writer = self._active_writer
        if not writer:
            return

        try:
            # First event: create extensible datasets for each column
            if self._active_columns is None:
                self._active_columns = []
                for key in sorted(data.keys()):
                    val = data[key]
                    if isinstance(val, (int, float)):
                        writer.create_extensible_1d(key)
                        self._active_columns.append(key)

                # Create XRF spectrum dataset if virtual detector is available
                vxrf = self._devices.get('vxrf') if self._devices else None
                if vxrf is not None and hasattr(vxrf, '_last_spectrum'):
                    n_ch = getattr(vxrf, '_n_channels', 4096)
                    writer.create_extensible_dataset('xrf_spectra', n_ch,
                                                     dtype=np.int32)
                    self._active_columns.append('__xrf_spectra__')

                log.debug(f"Live HDF5 columns: {self._active_columns}")

            # Append values for each column
            for key in self._active_columns:
                if key == '__xrf_spectra__':
                    continue  # handled separately below
                val = data.get(key)
                if val is not None:
                    try:
                        writer.append_value(key, float(val))
                    except (ValueError, TypeError):
                        pass

            # Write full XRF spectrum if available
            if '__xrf_spectra__' in self._active_columns:
                vxrf = self._devices.get('vxrf') if self._devices else None
                if vxrf is not None and vxrf._last_spectrum is not None:
                    writer.append_row('xrf_spectra', vxrf._last_spectrum)

            # Periodic flush (every 50 events) to preserve data on crash
            if self._event_count % 50 == 0:
                writer.flush()

        except Exception as e:
            log.warning(f"Live HDF5 write error: {e}")

    def _close_live_writer(self, stop_doc: dict):
        """Finalize and close the live HDF5 file."""
        writer = self._active_writer
        filepath = self._active_filepath
        if not writer:
            return

        try:
            exit_status = stop_doc.get('exit_status', 'unknown')
            writer.h5['entry'].attrs['exit_status'] = exit_status
            writer.finalize()
            writer.close()
            log.info(f"Live HDF5 finalized: {filepath} "
                     f"({self._event_count} events, {exit_status})")

            # Record in SQLite history
            if self._scan_db and filepath:
                filename = os.path.basename(filepath)
                plan = self._scan_metadata.get('plan_name',
                       self._scan_metadata.get('plan_type', 'unknown'))
                full_uid = self._scan_metadata.get('uid', 'no-uid')
                energy = self._scan_metadata.get('energy_start',
                         self._scan_metadata.get('energy', None))
                start_time = self._scan_metadata.get('time', '')
                if isinstance(start_time, (int, float)):
                    start_time = datetime.fromtimestamp(start_time).isoformat()
                elif not start_time:
                    start_time = datetime.now().isoformat()

                self._scan_db.record_scan(
                    uid=full_uid,
                    plan_name=plan,
                    status=exit_status,
                    start_time=start_time,
                    end_time=datetime.now().isoformat(),
                    num_points=self._event_count,
                    energy_keV=float(energy) if energy else None,
                    params=dict(self._scan_metadata.get('plan_args', {}))
                           if self._scan_metadata.get('plan_args') else None,
                    h5_file=filename,
                )

        except Exception as e:
            log.error(f"Live HDF5 close error: {e}")
            try:
                writer.close()
            except Exception:
                pass

        self._active_writer = None
        self._active_filepath = None
        self._active_columns = None

    def _save_scan_data(self, stop_doc: dict):
        """Auto-save scan data to HDF5/NeXus file (batch mode fallback)."""
        try:
            from ..data.writer import NexusWriter
        except ImportError:
            log.warning("NexusWriter not available — skipping auto-save")
            return

        plan = self._scan_metadata.get('plan_name',
               self._scan_metadata.get('plan_type', 'unknown'))
        uid = self._scan_metadata.get('uid', 'no-uid')[:8]
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{ts}_{plan}_{uid}.h5"
        filepath = os.path.join(DATA_DIR, filename)

        try:
            with NexusWriter(filepath) as w:
                # Metadata
                energy = self._scan_metadata.get('energy_start',
                         self._scan_metadata.get('energy', 10.0))
                w.write_metadata(
                    energy_keV=float(energy) if energy else 10.0,
                    scan_type=plan,
                    uid=uid,
                    num_points=len(self._scan_docs),
                    exit_status=stop_doc.get('exit_status', 'unknown'),
                )

                # Extract column data from events
                if self._scan_docs:
                    keys = list(self._scan_docs[0].keys())
                    for key in keys:
                        values = []
                        for evt in self._scan_docs:
                            v = evt.get(key)
                            if isinstance(v, (int, float)):
                                values.append(v)
                            elif v is not None:
                                try:
                                    values.append(float(v))
                                except (ValueError, TypeError):
                                    pass
                        if values:
                            w.write_1d_data(key, np.array(values),
                                            description=f'{plan} scan data')

                w.finalize()

            log.info(f"Scan auto-saved: {filepath} ({len(self._scan_docs)} events)")

            # Record in SQLite history database
            if self._scan_db:
                full_uid = self._scan_metadata.get('uid', 'no-uid')
                start_time = self._scan_metadata.get('time', '')
                if isinstance(start_time, (int, float)):
                    start_time = datetime.fromtimestamp(start_time).isoformat()
                elif not start_time:
                    start_time = datetime.now().isoformat()

                self._scan_db.record_scan(
                    uid=full_uid,
                    plan_name=plan,
                    status=stop_doc.get('exit_status', 'unknown'),
                    start_time=start_time,
                    end_time=datetime.now().isoformat(),
                    num_points=self._event_count,
                    energy_keV=float(energy) if energy else None,
                    params=dict(self._scan_metadata.get('plan_args', {}))
                           if self._scan_metadata.get('plan_args') else None,
                    h5_file=filename,
                )

        except Exception as e:
            log.error(f"Auto-save failed: {e}")
            # Still try to record in DB even if HDF5 write fails
            if self._scan_db:
                try:
                    full_uid = self._scan_metadata.get('uid', 'no-uid')
                    self._scan_db.record_scan(
                        uid=full_uid,
                        plan_name=self._scan_metadata.get('plan_name', 'unknown'),
                        status='save_error',
                        start_time=datetime.now().isoformat(),
                        num_points=len(self._scan_docs),
                        notes=f"HDF5 save error: {e}",
                    )
                except Exception:
                    pass

    def shutdown(self):
        """Clean up RunEngine."""
        if self._re:
            if self._state == 'running':
                self.abort("Shutdown")
            self._re = None
            self._devices = None
            self._state = 'idle'
            log.info("BlueskyRunner shut down")


def _serialize_doc(doc: dict) -> dict:
    """Make a Bluesky document JSON-serializable."""
    result = {}
    for k, v in doc.items():
        if isinstance(v, (str, int, float, bool, type(None))):
            result[k] = v
        elif isinstance(v, (list, tuple)):
            result[k] = [_serialize_val(x) for x in v]
        elif isinstance(v, dict):
            result[k] = _serialize_doc(v)
        else:
            result[k] = str(v)
    return result


def _serialize_val(v):
    """Serialize a single value for JSON."""
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    return str(v)
