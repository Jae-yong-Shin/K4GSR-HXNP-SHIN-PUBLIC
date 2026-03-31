#!/usr/bin/env python3
"""Nano Scanner Service -- integrates MCS2 + PicoScale into server.py.

Provides:
    - MCS2 bridge client connection (via notebook TCP bridge)
    - PicoScale direct connection (via Ethernet)
    - NanoScanner for step/fly/spiral scans
    - Position polling for SCAN PV updates
    - Async interface for WebSocket scan commands

Architecture:
    Browser  --(ws/scan)--> server.py --> NanoScannerService
        --> MCS2Controller --(TCP:5555)--> notebook bridge --> USB --> MCS2
        --> PicoScaleController --(Ethernet)--> PicoScale V2

Usage in server.py:
    from nano_scanner_service import NanoScannerService
    nano_svc = NanoScannerService(pv_store, config)
    await nano_svc.start()
    result = await nano_svc.handle_action(msg)
    await nano_svc.stop()
"""

import asyncio
import json
import logging
import os
import time
import threading
from typing import Optional, Callable, Dict, Any

log = logging.getLogger("nano-scanner-svc")

# Import hardware controllers
from hardware.smaract_mcs2 import MCS2Controller
from hardware.picoscale import PicoScaleController
from scan_program.scanner import NanoScanner


class NanoScannerService:
    """Service layer for nano scanner hardware.

    Manages MCS2 + PicoScale connections and provides an async interface
    for scan commands from the WebSocket handler.
    """

    def __init__(self, pv_store=None,
                 bridge_host: str = "", bridge_port: int = 5555,
                 ps_locator: str = ""):
        """Initialize nano scanner service.

        Args:
            pv_store: PVStore or CABridge for updating SCAN PVs
            bridge_host: MCS2 bridge server host (empty = mock)
            bridge_port: MCS2 bridge server port
            ps_locator: PicoScale locator (empty = mock)
        """
        self.pv_store = pv_store
        self._bridge_host = bridge_host
        self._bridge_port = bridge_port
        self._ps_locator = ps_locator

        self.mcs2: Optional[MCS2Controller] = None
        self.picoscale: Optional[PicoScaleController] = None
        self.scanner: Optional[NanoScanner] = None

        self._connected = False
        self._scanning = False
        self._scan_thread: Optional[threading.Thread] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._broadcast_fn: Optional[Callable] = None

        # Current scan state
        self._scan_progress = 0.0
        self._scan_status = "idle"  # idle, scanning, error, aborted
        self._scan_message = ""
        self._last_scan_result = None

        # Streaming state
        self._streaming = False
        self._stream_rate_hz = 0
        self._stream_channels: list = []
        self._stream_idx = 0
        self._stream_batch_task: Optional[asyncio.Task] = None
        self._stream_batch_buf: Dict[int, list] = {}
        self._stream_batch_lock = threading.Lock()
        self._mock_stream_task: Optional[asyncio.Task] = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def scanning(self) -> bool:
        return self._scanning

    def set_broadcast(self, fn: Callable):
        """Set broadcast function for scan events.

        Args:
            fn: async function(msg_dict) to broadcast to scan clients
        """
        self._broadcast_fn = fn

    async def start(self):
        """Initialize hardware connections and start position polling."""
        # Create controllers
        self.mcs2 = MCS2Controller(
            bridge_host=self._bridge_host,
            bridge_port=self._bridge_port,
            mock_fallback=True)
        ps_mock = not self._ps_locator
        self.picoscale = PicoScaleController(
            locator=self._ps_locator or "mock",
            mock=ps_mock)

        # Connect in thread pool (blocking I/O)
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self.mcs2.connect)
            log.info("MCS2 %s", "connected (bridge)" if not self.mcs2.mock_mode
                     else "connected (mock)")
        except Exception as e:
            log.error("MCS2 connect failed: %s", e)

        try:
            await loop.run_in_executor(None, self.picoscale.connect)
            log.info("PicoScale %s", "connected (SDK)" if not self.picoscale.mock_mode
                     else "connected (mock)")
        except Exception as e:
            log.error("PicoScale connect failed: %s", e)

        # Create scanner
        self.scanner = NanoScanner(
            self.mcs2, self.picoscale,
            progress_callback=self._on_scan_progress)

        self._connected = True

        # Start position polling loop
        self._poll_task = asyncio.create_task(self._position_poll_loop())
        log.info("Nano scanner service started (MCS2: %s, PS: %s)",
                 "bridge" if not self.mcs2.mock_mode else "mock",
                 "SDK" if not self.picoscale.mock_mode else "mock")

    async def stop(self):
        """Stop polling, streaming, and disconnect hardware."""
        # Stop streaming if active
        if self._streaming:
            await self._stop_streaming()

        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        if self.scanner and self._scanning:
            self.scanner.abort()

        loop = asyncio.get_running_loop()
        if self.mcs2:
            await loop.run_in_executor(None, self.mcs2.close)
        if self.picoscale:
            await loop.run_in_executor(None, self.picoscale.close)

        self._connected = False
        log.info("Nano scanner service stopped")

    # ── WebSocket Action Handler ──────────────────────────────

    async def handle_action(self, msg: dict) -> dict:
        """Handle a nano scanner action from WebSocket.

        Actions:
            nano_status        Get scanner status
            nano_connect       Connect to hardware
            nano_disconnect    Disconnect from hardware
            nano_get_pos       Get current positions
            nano_jog           Jog move (relative)
            nano_move          Absolute move
            nano_stop          Stop all axes
            nano_scan_start    Start a scan
            nano_scan_abort    Abort current scan
            nano_stream_start  Start position streaming
            nano_stream_stop   Stop position streaming

        Returns:
            Response dict to send back to client
        """
        action = msg.get("action", "")

        if action == "nano_status":
            return self._status_response()

        elif action == "nano_connect":
            if self._connected:
                return {"type": "nano_status", "ok": True,
                        "msg": "already connected", **self._hw_status()}
            await self.start()
            return {"type": "nano_status", "ok": True,
                    "msg": "connected", **self._hw_status()}

        elif action == "nano_disconnect":
            await self.stop()
            return {"type": "nano_status", "ok": True, "msg": "disconnected"}

        elif action == "nano_get_pos":
            return await self._get_positions()

        elif action == "nano_jog":
            ch = msg.get("ch", msg.get("channel", 0))
            delta_nm = msg.get("delta_nm", 0.0)
            return await self._jog(ch, delta_nm)

        elif action == "nano_move":
            ch = msg.get("ch", msg.get("channel", 0))
            pos_nm = msg.get("pos_nm", msg.get("position_nm", 0.0))
            return await self._move_to(ch, pos_nm)

        elif action == "nano_stop":
            return await self._stop_all()

        elif action == "nano_scan_start":
            return await self._start_scan(msg)

        elif action == "nano_scan_abort":
            return self._abort_scan()

        elif action == "nano_stream_start":
            return await self._start_streaming(msg)

        elif action == "nano_stream_stop":
            return await self._stop_streaming()

        else:
            return {"type": "nano_error", "ok": False,
                    "error": f"Unknown nano action: {action}"}

    # ── Position Polling ──────────────────────────────────────

    async def _position_poll_loop(self):
        """Poll PicoScale positions and update SCAN PVs (100ms)."""
        pv_map = {
            0: "BL10:SCAN:PX",  # PicoScale X readback
            1: "BL10:SCAN:PY",  # PicoScale Y readback
            2: "BL10:SCAN:PZ",  # PicoScale Z readback
        }
        while True:
            try:
                if self.picoscale and self.picoscale.connected:
                    loop = asyncio.get_running_loop()
                    positions = await loop.run_in_executor(
                        None, self.picoscale.get_all_positions)
                    if self.pv_store:
                        for ch, pos_nm in positions.items():
                            pv_name = pv_map.get(ch)
                            if pv_name and pv_name in self.pv_store.pvs:
                                self.pv_store.pvs[pv_name]["value"] = pos_nm

                # Also update status PVs
                if self.pv_store:
                    status_map = {"idle": 0, "scanning": 1,
                                  "error": 2, "aborted": 3}
                    status_val = status_map.get(self._scan_status, 0)
                    if "BL10:SCAN:Status" in self.pv_store.pvs:
                        self.pv_store.pvs["BL10:SCAN:Status"]["value"] = status_val
                    if "BL10:SCAN:Progress" in self.pv_store.pvs:
                        self.pv_store.pvs["BL10:SCAN:Progress"]["value"] = self._scan_progress

            except Exception as e:
                log.debug("Position poll error: %s", e)

            await asyncio.sleep(0.1)  # 100ms poll

    # ── Internal Commands ─────────────────────────────────────

    async def _get_positions(self) -> dict:
        """Get all current positions."""
        if not self._connected:
            return {"type": "nano_positions", "ok": False,
                    "error": "not connected"}

        loop = asyncio.get_running_loop()
        try:
            ps_pos = await loop.run_in_executor(
                None, self.picoscale.get_all_positions)
            mcs2_pos = await loop.run_in_executor(
                None, self.mcs2.get_all_positions)
            return {
                "type": "nano_positions", "ok": True,
                "picoscale_nm": {str(k): v for k, v in ps_pos.items()},
                "mcs2_nm": {str(k): v for k, v in mcs2_pos.items()},
            }
        except Exception as e:
            return {"type": "nano_positions", "ok": False, "error": str(e)}

    async def _jog(self, ch: int, delta_nm: float) -> dict:
        """Jog (relative move) a single channel."""
        if not self._connected:
            return {"type": "nano_move", "ok": False, "error": "not connected"}
        if self._scanning:
            return {"type": "nano_move", "ok": False, "error": "scan in progress"}

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, self.mcs2.move_relative, ch, delta_nm)
            pos = await loop.run_in_executor(
                None, self.picoscale.get_position, ch)
            return {"type": "nano_move", "ok": True,
                    "ch": ch, "pos_nm": pos, "delta_nm": delta_nm}
        except Exception as e:
            return {"type": "nano_move", "ok": False, "error": str(e)}

    async def _move_to(self, ch: int, pos_nm: float) -> dict:
        """Absolute move a single channel."""
        if not self._connected:
            return {"type": "nano_move", "ok": False, "error": "not connected"}
        if self._scanning:
            return {"type": "nano_move", "ok": False, "error": "scan in progress"}

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, self.mcs2.move_to, ch, pos_nm)
            pos = await loop.run_in_executor(
                None, self.picoscale.get_position, ch)
            return {"type": "nano_move", "ok": True,
                    "ch": ch, "pos_nm": pos, "target_nm": pos_nm}
        except Exception as e:
            return {"type": "nano_move", "ok": False, "error": str(e)}

    async def _stop_all(self) -> dict:
        """Stop all axes."""
        if not self._connected:
            return {"type": "nano_stop", "ok": False, "error": "not connected"}

        if self._scanning:
            self.scanner.abort()

        loop = asyncio.get_running_loop()
        errors = []
        for ch in range(self.mcs2.get_num_channels()):
            try:
                await loop.run_in_executor(None, self.mcs2.stop, ch)
            except Exception as e:
                errors.append(f"ch{ch}: {e}")

        return {"type": "nano_stop", "ok": not errors,
                "errors": errors if errors else None}

    async def _start_scan(self, msg: dict) -> dict:
        """Start a scan in a background thread."""
        if not self._connected:
            return {"type": "nano_scan", "ok": False, "error": "not connected"}
        if self._scanning:
            return {"type": "nano_scan", "ok": False,
                    "error": "scan already in progress"}

        scan_type = msg.get("scan_type", "step_2d")
        params = msg.get("params", {})

        self._scanning = True
        self._scan_progress = 0.0
        self._scan_status = "scanning"
        self._scan_message = ""
        self._last_scan_result = None

        # Run scan in thread pool
        loop = asyncio.get_running_loop()
        self._scan_thread = threading.Thread(
            target=self._run_scan, args=(scan_type, params, loop),
            daemon=True, name="nano-scan")
        self._scan_thread.start()

        return {"type": "nano_scan", "ok": True,
                "msg": f"Scan started: {scan_type}",
                "scan_type": scan_type, "params": params}

    def _run_scan(self, scan_type: str, params: dict,
                  loop: asyncio.AbstractEventLoop):
        """Run a scan (called in background thread)."""
        try:
            if scan_type == "step_1d":
                data = self.scanner.step_scan_1d(
                    axis=params.get("axis", 0),
                    start_nm=params.get("start_nm", -1000),
                    stop_nm=params.get("stop_nm", 1000),
                    n_points=params.get("n_points", 21),
                    dwell_s=params.get("dwell_s", 0.01))

            elif scan_type == "step_2d":
                data = self.scanner.step_scan_2d(
                    fast_axis=params.get("fast_axis", 0),
                    slow_axis=params.get("slow_axis", 1),
                    fast_start=params.get("fast_start", -1000),
                    fast_stop=params.get("fast_stop", 1000),
                    n_fast=params.get("n_fast", 21),
                    slow_start=params.get("slow_start", -1000),
                    slow_stop=params.get("slow_stop", 1000),
                    n_slow=params.get("n_slow", 21),
                    dwell_s=params.get("dwell_s", 0.01),
                    snake=params.get("snake", True))

            elif scan_type == "fly_1d":
                data = self.scanner.fly_scan_1d(
                    axis=params.get("axis", 0),
                    start_nm=params.get("start_nm", -1000),
                    stop_nm=params.get("stop_nm", 1000),
                    n_points=params.get("n_points", 100),
                    velocity_nm_s=params.get("velocity_nm_s", 1000.0),
                    stream_rate_hz=params.get("stream_rate_hz", 10000))

            elif scan_type == "spiral":
                data = self.scanner.spiral_scan(
                    x_axis=params.get("x_axis", 0),
                    y_axis=params.get("y_axis", 1),
                    x_center=params.get("x_center", 0.0),
                    y_center=params.get("y_center", 0.0),
                    radius_nm=params.get("radius_nm", 1000.0),
                    dr_nm=params.get("dr_nm", 50.0),
                    dwell_s=params.get("dwell_s", 0.01))
            else:
                raise ValueError(f"Unknown scan type: {scan_type}")

            # Scan complete
            self._scan_status = "idle"
            self._scan_progress = 100.0
            self._last_scan_result = {
                "n_points": data.n_points,
                "duration_s": data.duration_s,
                "scan_type": data.scan_type,
            }

            # Save scan data
            try:
                results_dir = os.path.join(
                    os.path.dirname(__file__), "..", "results", "nano_scans")
                os.makedirs(results_dir, exist_ok=True)
                ts_str = time.strftime("%Y%m%d_%H%M%S")
                h5_path = os.path.join(results_dir, f"scan_{ts_str}.h5")
                data.to_hdf5(h5_path)
                self._last_scan_result["h5_path"] = h5_path
            except Exception as e:
                log.warning("Failed to save scan data: %s", e)

            # Broadcast completion
            self._broadcast_event(loop, {
                "type": "nano_scan_complete",
                "ok": True,
                "result": self._last_scan_result
            })

        except Exception as e:
            log.error("Scan failed: %s", e)
            self._scan_status = "error"
            self._scan_message = str(e)
            self._broadcast_event(loop, {
                "type": "nano_scan_error",
                "ok": False,
                "error": str(e)
            })

        finally:
            self._scanning = False

    def _abort_scan(self) -> dict:
        """Abort current scan."""
        if not self._scanning:
            return {"type": "nano_scan", "ok": False,
                    "error": "no scan in progress"}
        self.scanner.abort()
        self._scan_status = "aborted"
        return {"type": "nano_scan", "ok": True, "msg": "Scan abort requested"}

    def _on_scan_progress(self, pct: float, msg: str):
        """Callback from NanoScanner for progress updates."""
        self._scan_progress = pct
        self._scan_message = msg

    def _broadcast_event(self, loop: asyncio.AbstractEventLoop, msg: dict):
        """Broadcast event to scan clients (thread-safe)."""
        if self._broadcast_fn is not None:
            asyncio.run_coroutine_threadsafe(
                self._broadcast_fn(msg), loop)

    # ── Status ────────────────────────────────────────────────

    def _status_response(self) -> dict:
        """Build status response."""
        resp = {
            "type": "nano_status",
            "ok": True,
            "connected": self._connected,
            "scanning": self._scanning,
            "scan_status": self._scan_status,
            "scan_progress": self._scan_progress,
            "scan_message": self._scan_message,
        }
        if self._connected:
            resp.update(self._hw_status())
        if self._last_scan_result:
            resp["last_scan"] = self._last_scan_result
        return resp

    def _hw_status(self) -> dict:
        """Hardware status info."""
        mcs2_conn = bool(self.mcs2 and self.mcs2.connected)
        ps_conn = bool(self.picoscale and self.picoscale.connected)
        return {
            "mcs2_connected": mcs2_conn,
            "mcs2_mode": "bridge" if (self.mcs2 and not self.mcs2.mock_mode) else "mock",
            "mcs2_host": self._bridge_host or "mock",
            "ps_connected": ps_conn,
            "picoscale_mode": "sdk" if (self.picoscale and not self.picoscale.mock_mode) else "mock",
            "picoscale_locator": self._ps_locator or "mock",
        }

    # ── Position Streaming ─────────────────────────────────────

    async def _start_streaming(self, msg: dict) -> dict:
        """Start PicoScale position streaming.

        Uses polling-based streaming (reliable) instead of SDK streaming
        API which fails with AcquireBuffer error 61449 on some firmware.

        Adaptive transfer:
          - rate <= 1000 Hz: direct (one JSON per sample)
          - rate >  1000 Hz: batch buffer, flush at ~50 Hz
        """
        if not self._connected or not self.picoscale:
            return {"type": "nano_stream_error", "ok": False,
                    "error": "PicoScale not connected"}
        if self._streaming:
            return {"type": "nano_stream_error", "ok": False,
                    "error": "Streaming already active"}

        rate_hz = int(msg.get("rate_hz", 1000))
        channels = msg.get("channels", [0, 1, 2])
        self._stream_rate_hz = rate_hz
        self._stream_channels = channels
        self._stream_idx = 0
        self._streaming = True

        loop = asyncio.get_running_loop()

        # Batch mode for high rates
        if rate_hz > 1000:
            for ch in channels:
                self._stream_batch_buf[ch] = []
            self._stream_batch_task = asyncio.create_task(
                self._stream_batch_flush_loop(loop))

        # Start streaming (polling for real HW, mock generator for mock)
        is_mock = self.picoscale.mock_mode
        if is_mock:
            self._mock_stream_task = asyncio.create_task(
                self._mock_stream_generator(loop))
        else:
            # Use polling-based streaming (reliable)
            try:
                await loop.run_in_executor(
                    None, lambda: self.picoscale.start_polling_stream(
                        rate_hz=rate_hz, channels=channels,
                        callback=lambda pos, ts: self._on_poll_data(
                            pos, ts, loop)))
            except Exception as e:
                self._streaming = False
                if self._stream_batch_task:
                    self._stream_batch_task.cancel()
                return {"type": "nano_stream_error", "ok": False,
                        "error": f"Start failed: {e}"}

        mode = "batched" if rate_hz > 1000 else "direct"
        log.info("Position streaming started: %d Hz, ch=%s, mode=%s%s",
                 rate_hz, channels, mode, " (mock)" if is_mock else "")
        return {"type": "nano_stream_started", "ok": True,
                "rate_hz": rate_hz, "channels": channels, "mode": mode}

    async def _stop_streaming(self) -> dict:
        """Stop PicoScale position streaming."""
        if not self._streaming:
            return {"type": "nano_stream_stopped", "ok": True,
                    "msg": "not streaming"}

        self._streaming = False

        # Cancel mock generator
        if self._mock_stream_task:
            self._mock_stream_task.cancel()
            try:
                await self._mock_stream_task
            except asyncio.CancelledError:
                pass
            self._mock_stream_task = None

        # Cancel batch flush
        if self._stream_batch_task:
            self._stream_batch_task.cancel()
            try:
                await self._stream_batch_task
            except asyncio.CancelledError:
                pass
            self._stream_batch_task = None

        # Stop PicoScale hardware streaming (polling or SDK)
        if self.picoscale and not self.picoscale.mock_mode:
            loop = asyncio.get_running_loop()
            if self.picoscale.poll_streaming:
                await loop.run_in_executor(
                    None, self.picoscale.stop_polling_stream)
            else:
                await loop.run_in_executor(
                    None, self.picoscale.stop_streaming)

        self._stream_batch_buf.clear()
        log.info("Position streaming stopped")
        return {"type": "nano_stream_stopped", "ok": True}

    def _on_stream_frame(self, frame, loop: asyncio.AbstractEventLoop):
        """Callback from PicoScale stream worker thread.

        frame.positions[ch] = [val1, val2, ...] in picometers.
        Convert to nm and send via direct or batch mode.
        """
        if not self._streaming:
            return

        rate = self._stream_rate_hz
        channels = self._stream_channels

        # Convert pm -> nm for each channel
        ch_data = {}
        n_samples = 0
        for ch in channels:
            vals_pm = frame.positions.get(ch, [])
            vals_nm = [v * 1e-3 for v in vals_pm]  # pm -> nm
            ch_data[ch] = vals_nm
            n_samples = max(n_samples, len(vals_nm))

        if rate <= 1000:
            # Direct mode: send one message per sample
            for i in range(n_samples):
                msg = {"type": "nano_stream_data",
                       "ts": frame.timestamp, "idx": self._stream_idx}
                for ch in channels:
                    vals = ch_data.get(ch, [])
                    msg[f"ch{ch}"] = vals[i] if i < len(vals) else 0.0
                self._stream_idx += 1
                self._broadcast_event(loop, msg)
        else:
            # Batch mode: accumulate into buffer
            with self._stream_batch_lock:
                for ch in channels:
                    if ch not in self._stream_batch_buf:
                        self._stream_batch_buf[ch] = []
                    self._stream_batch_buf[ch].extend(ch_data.get(ch, []))
                self._stream_idx += n_samples

    def _on_poll_data(self, positions: dict, timestamp: float,
                      loop: asyncio.AbstractEventLoop):
        """Callback from polling stream worker thread.

        positions: {ch_idx: position_nm, ...}
        """
        if not self._streaming:
            return

        rate = self._stream_rate_hz
        channels = self._stream_channels

        if rate <= 1000:
            # Direct mode: send one message per sample
            msg = {"type": "nano_stream_data",
                   "ts": timestamp, "idx": self._stream_idx}
            for ch in channels:
                msg[f"ch{ch}"] = positions.get(ch, 0.0)
            self._stream_idx += 1
            self._broadcast_event(loop, msg)
        else:
            # Batch mode: accumulate into buffer
            with self._stream_batch_lock:
                for ch in channels:
                    if ch not in self._stream_batch_buf:
                        self._stream_batch_buf[ch] = []
                    self._stream_batch_buf[ch].append(positions.get(ch, 0.0))
                self._stream_idx += 1

    async def _stream_batch_flush_loop(self, loop: asyncio.AbstractEventLoop):
        """Flush batch buffer at ~50 Hz (every 20ms)."""
        try:
            while self._streaming:
                await asyncio.sleep(0.02)  # 50 Hz
                with self._stream_batch_lock:
                    # Check if anything to send
                    n = 0
                    for ch in self._stream_channels:
                        buf = self._stream_batch_buf.get(ch, [])
                        n = max(n, len(buf))
                    if n == 0:
                        continue

                    msg = {"type": "nano_stream_batch",
                           "ts": time.monotonic(),
                           "rate_hz": self._stream_rate_hz,
                           "n": n, "idx": self._stream_idx - n}
                    for ch in self._stream_channels:
                        buf = self._stream_batch_buf.get(ch, [])
                        msg[f"ch{ch}"] = buf[:]
                        self._stream_batch_buf[ch] = []

                if self._broadcast_fn is not None:
                    await self._broadcast_fn(msg)
        except asyncio.CancelledError:
            pass

    async def _mock_stream_generator(self, loop: asyncio.AbstractEventLoop):
        """Generate synthetic streaming data in mock mode."""
        import math
        t0 = time.monotonic()
        rate = self._stream_rate_hz
        channels = self._stream_channels
        interval = 1.0 / min(rate, 50)  # Cap at 50 Hz for sending
        samples_per_tick = max(1, rate // 50) if rate > 50 else 1

        try:
            while self._streaming:
                await asyncio.sleep(interval)
                if not self._streaming:
                    break
                t = time.monotonic() - t0

                if rate <= 1000:
                    # Direct: send individual samples
                    for _ in range(samples_per_tick):
                        msg = {"type": "nano_stream_data",
                               "ts": time.monotonic(),
                               "idx": self._stream_idx}
                        for ch in channels:
                            # Sine wave with different freq per channel
                            freq = 0.5 * (ch + 1)
                            noise = (hash((self._stream_idx, ch)) % 100 - 50) * 0.1
                            msg[f"ch{ch}"] = round(
                                100.0 * math.sin(2 * math.pi * freq * t) + noise, 3)
                        self._stream_idx += 1
                        if self._broadcast_fn is not None:
                            await self._broadcast_fn(msg)
                else:
                    # Batch: accumulate and send
                    msg = {"type": "nano_stream_batch",
                           "ts": time.monotonic(),
                           "rate_hz": rate,
                           "n": samples_per_tick,
                           "idx": self._stream_idx}
                    for ch in channels:
                        vals = []
                        freq = 0.5 * (ch + 1)
                        for s in range(samples_per_tick):
                            dt = s / rate
                            noise = (hash((self._stream_idx + s, ch)) % 100 - 50) * 0.1
                            vals.append(round(
                                100.0 * math.sin(2 * math.pi * freq * (t + dt)) + noise, 3))
                        msg[f"ch{ch}"] = vals
                    self._stream_idx += samples_per_tick
                    if self._broadcast_fn is not None:
                        await self._broadcast_fn(msg)
        except asyncio.CancelledError:
            pass
