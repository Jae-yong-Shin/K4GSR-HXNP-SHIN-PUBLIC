"""Abstract base class for simulation engines.

Every engine implements:
  - available()   -> bool   : True if required libraries are installed
  - name()        -> str    : mode name matching WS protocol (e.g. 'xrf2d')
  - run(ws, params, beamline) : async, streams results via websocket

The run() method sends JSON messages following the existing /ws/expt protocol:
  {type: 'expt_progress', fraction: 0.0-1.0, msg: '...'}
  {type: 'expt_data',     mode: '...', batch: [...]}
  {type: 'expt_result',   mode: '...', ...mode-specific data...}
  {type: 'expt_done',     elapsed_sec: 1.23}
  {type: 'expt_error',    message: '...'}
"""

import json
import logging
import time

log = logging.getLogger("sim-engine")


class SimEngine:
    """Abstract base for all simulation engines."""

    def __init__(self):
        self._cancelled = False

    @staticmethod
    def available():
        """Return True if required libraries are installed."""
        raise NotImplementedError

    @staticmethod
    def name():
        """Return mode name (e.g. 'xrf2d', 'xrd2d', 'xafs', 'xrdmap')."""
        raise NotImplementedError

    async def run(self, ws, params, beamline):
        """Execute simulation, streaming results to websocket.

        Args:
            ws: websocket connection
            params: mode-specific parameter dict
            beamline: {energy_keV, spot_h_nm, spot_v_nm, flux, ssaH, ssaV}
        """
        raise NotImplementedError

    def cancel(self):
        """Request cancellation of the running simulation."""
        self._cancelled = True

    def reset(self):
        """Reset cancellation flag before a new run."""
        self._cancelled = False

    # ── Helpers for streaming messages ──

    async def send_progress(self, ws, fraction, msg=""):
        """Send progress update (0.0 to 1.0)."""
        await ws.send(json.dumps({
            "type": "expt_progress",
            "fraction": min(max(fraction, 0.0), 1.0),
            "msg": msg,
        }))

    async def send_data(self, ws, mode, batch, progress=None):
        """Send streaming data batch (e.g. XAFS points)."""
        msg = {"type": "expt_data", "mode": mode, "batch": batch}
        if progress is not None:
            msg["progress"] = progress
        await ws.send(json.dumps(msg))

    async def send_result(self, ws, mode, **kwargs):
        """Send final result. kwargs are mode-specific fields."""
        msg = {"type": "expt_result", "mode": mode}
        msg.update(kwargs)
        await ws.send(json.dumps(msg, default=_json_default))

    async def send_done(self, ws, elapsed_sec):
        """Send completion marker."""
        await ws.send(json.dumps({
            "type": "expt_done",
            "elapsed_sec": round(elapsed_sec, 3),
        }))

    async def send_error(self, ws, message):
        """Send error message."""
        await ws.send(json.dumps({
            "type": "expt_error",
            "message": str(message),
        }))


def _json_default(obj):
    """JSON serializer for numpy types."""
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
