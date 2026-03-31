#!/usr/bin/env python3
"""Fast nano scanner engine for K4GSR BL10 NanoProbe beamline.

Implements scan patterns using SmarAct MCS2 controller (motion) and
PicoScale interferometer (position readback). Based on the PTC Scan
Function algorithm (PTC Manual Ch.4) extended with fly-scan support.

Scan types:
    step_scan_1d:  1D step scan (move -> settle -> read)
    step_scan_2d:  2D raster scan (snake/boustrophedon pattern)
    fly_scan_1d:   Continuous motion with streaming position readback
    fly_scan_2d:   2D fly scan (fast axis continuous, slow axis step)
    spiral_scan:   Fermat spiral for ptychography

Usage:
    from hardware.smaract_mcs2 import MCS2Controller
    from hardware.picoscale import PicoScaleController

    mcs2 = MCS2Controller("usb:ix:0")
    pscale = PicoScaleController("usb:ix:1")
    mcs2.connect()
    pscale.connect()

    scanner = NanoScanner(mcs2, pscale)
    data = scanner.step_scan_2d(
        fast_axis=0, slow_axis=1,
        fast_start=-1000, fast_stop=1000, n_fast=21,
        slow_start=-1000, slow_stop=1000, n_slow=21,
        dwell_s=0.01)
    data.to_hdf5("scan_001.h5")
"""

import logging
import math
import time
import threading
from typing import Optional, Callable, Tuple

import numpy as np

from .scan_data import ScanData

log = logging.getLogger("nano-scanner")


class NanoScanner:
    """Fast nano scanning engine using MCS2 + PicoScale.

    The MCS2 controller drives piezo stages (custom motors), and the
    PicoScale laser interferometer provides sub-nm position feedback.

    Scan algorithm (PTC-based):
        Step scan: for each point:
            1. Move MCS2 to target position
            2. Wait for settling (post-step delay / dwell)
            3. Read PicoScale encoder position
            4. (Optional) Fire detector trigger
        Inter-line: wait 4x dwell for vibration damping (PTC spec)

    Fly scan:
        1. Configure PicoScale streaming at target frame rate
        2. Move MCS2 at constant velocity
        3. PicoScale records positions at streaming rate
        4. Correlate positions with detector triggers
    """

    # Axis index constants
    AXIS_X = 0
    AXIS_Y = 1
    AXIS_Z = 2

    def __init__(self, mcs2, picoscale, progress_callback=None):
        """Initialize scanner.

        Args:
            mcs2: MCS2Controller instance (connected)
            picoscale: PicoScaleController instance (connected)
            progress_callback: Optional callable(progress_pct, status_msg)
                               for reporting scan progress to UI
        """
        self.mcs2 = mcs2
        self.ps = picoscale
        self._progress_callback = progress_callback
        self._abort = threading.Event()

    def abort(self):
        """Abort the current scan."""
        self._abort.set()
        log.warning("Scan abort requested")

    @property
    def is_aborted(self) -> bool:
        return self._abort.is_set()

    def _report_progress(self, pct: float, msg: str = ""):
        """Report scan progress to callback."""
        if self._progress_callback is not None:
            self._progress_callback(pct, msg)

    # ── 1D Step Scan ─────────────────────────────────────────────

    def step_scan_1d(self, axis: int, start_nm: float, stop_nm: float,
                     n_points: int, dwell_s: float = 0.01,
                     readback_axis: Optional[int] = None) -> ScanData:
        """1D step scan: move -> settle -> read at each point.

        Args:
            axis: MCS2 channel (0=X, 1=Y, 2=Z)
            start_nm: Start position in nm
            stop_nm: Stop position in nm
            n_points: Number of scan points
            dwell_s: Settling time after move (s). PTC calls this
                     "Post-Step Delay". Typical: 5-50 ms for nano stages.
            readback_axis: PicoScale channel for readback (default: same as axis)

        Returns:
            ScanData with encoder positions and timestamps
        """
        if readback_axis is None:
            readback_axis = axis

        positions = np.linspace(start_nm, stop_nm, n_points)
        data = ScanData(
            scan_type="step_scan_1d",
            start_time=time.time(),
            scan_params={
                "axis": axis, "start_nm": start_nm, "stop_nm": stop_nm,
                "n_points": n_points, "dwell_s": dwell_s,
            },
        )

        enc_vals = []
        ts_vals = []
        target_vals = []
        self._abort.clear()

        log.info("Step scan 1D: axis=%d, [%.1f, %.1f] nm, %d pts, dwell=%.3fs",
                 axis, start_nm, stop_nm, n_points, dwell_s)
        t0 = time.monotonic()

        for i, pos in enumerate(positions):
            if self._abort.is_set():
                log.warning("Scan aborted at point %d/%d", i, n_points)
                break

            self.mcs2.move_to(axis, pos)
            time.sleep(dwell_s)

            enc = self.ps.get_position(readback_axis)
            ts = time.monotonic() - t0

            enc_vals.append(enc)
            ts_vals.append(ts)
            target_vals.append(pos)

            self._report_progress(100.0 * (i + 1) / n_points,
                                  f"Point {i+1}/{n_points}")

        # Fill data based on axis
        data.timestamps = np.array(ts_vals)
        if axis == self.AXIS_X:
            data.encoder_x = np.array(enc_vals)
            data.target_x = np.array(target_vals)
            data.encoder_y = np.zeros(len(enc_vals))
        else:
            data.encoder_y = np.array(enc_vals)
            data.target_y = np.array(target_vals)
            data.encoder_x = np.zeros(len(enc_vals))
        data.end_time = time.time()

        log.info("Step scan 1D complete: %d points in %.1fs",
                 len(enc_vals), data.duration_s)
        return data

    # ── 2D Step Scan (Raster) ────────────────────────────────────

    def step_scan_2d(self, fast_axis: int, slow_axis: int,
                     fast_start: float, fast_stop: float, n_fast: int,
                     slow_start: float, slow_stop: float, n_slow: int,
                     dwell_s: float = 0.01, snake: bool = True) -> ScanData:
        """2D raster scan with snake (boustrophedon) pattern.

        Algorithm (based on PTC Scan Function Ch.4):
            For each slow_axis position (row):
                1. Move slow axis to row position
                2. Wait 4x dwell_s for inter-line settling
                3. For each fast_axis position (column):
                    a. Move fast axis to column position
                    b. Wait dwell_s for settling
                    c. Read PicoScale encoder positions
            Snake: even rows scan L->R, odd rows scan R->L.

        Args:
            fast_axis: MCS2 channel for fast axis (usually X=0)
            slow_axis: MCS2 channel for slow axis (usually Y=1)
            fast_start, fast_stop: Fast axis range (nm)
            n_fast: Number of fast axis points
            slow_start, slow_stop: Slow axis range (nm)
            n_slow: Number of slow axis points
            dwell_s: Per-point settling time (s)
            snake: If True, alternate fast axis direction per row

        Returns:
            ScanData with 2D grid of encoder positions
        """
        fast_positions = np.linspace(fast_start, fast_stop, n_fast)
        slow_positions = np.linspace(slow_start, slow_stop, n_slow)
        total_points = n_fast * n_slow

        data = ScanData(
            scan_type="step_scan_2d",
            start_time=time.time(),
            nx=n_fast, ny=n_slow,
            scan_params={
                "fast_axis": fast_axis, "slow_axis": slow_axis,
                "fast_start": fast_start, "fast_stop": fast_stop,
                "slow_start": slow_start, "slow_stop": slow_stop,
                "n_fast": n_fast, "n_slow": n_slow,
                "dwell_s": dwell_s, "snake": snake,
            },
        )

        enc_x_list = []
        enc_y_list = []
        ts_list = []
        tgt_x_list = []
        tgt_y_list = []
        self._abort.clear()

        log.info("Step scan 2D: fast=%d [%.1f,%.1f], slow=%d [%.1f,%.1f], "
                 "%d total pts, dwell=%.3fs, snake=%s",
                 fast_axis, fast_start, fast_stop,
                 slow_axis, slow_start, slow_stop,
                 total_points, dwell_s, snake)
        t0 = time.monotonic()
        point_idx = 0

        for row_idx, slow_pos in enumerate(slow_positions):
            if self._abort.is_set():
                break

            # Move slow axis to row position
            self.mcs2.move_to(slow_axis, slow_pos)

            # Inter-line settling: 4x dwell (PTC algorithm)
            if row_idx > 0:
                time.sleep(4.0 * dwell_s)

            # Determine fast axis direction (snake pattern)
            if snake and row_idx % 2 == 1:
                fast_order = fast_positions[::-1]
            else:
                fast_order = fast_positions

            for fast_pos in fast_order:
                if self._abort.is_set():
                    break

                self.mcs2.move_to(fast_axis, fast_pos)
                time.sleep(dwell_s)

                # Read encoder positions from PicoScale
                enc_fast = self.ps.get_position(fast_axis)
                enc_slow = self.ps.get_position(slow_axis)
                ts = time.monotonic() - t0

                # Store based on axis assignment
                if fast_axis == self.AXIS_X:
                    enc_x_list.append(enc_fast)
                    enc_y_list.append(enc_slow)
                    tgt_x_list.append(fast_pos)
                    tgt_y_list.append(slow_pos)
                else:
                    enc_x_list.append(enc_slow)
                    enc_y_list.append(enc_fast)
                    tgt_x_list.append(slow_pos)
                    tgt_y_list.append(fast_pos)
                ts_list.append(ts)

                point_idx += 1
                self._report_progress(
                    100.0 * point_idx / total_points,
                    f"Row {row_idx+1}/{n_slow}, "
                    f"Point {point_idx}/{total_points}")

        data.encoder_x = np.array(enc_x_list)
        data.encoder_y = np.array(enc_y_list)
        data.target_x = np.array(tgt_x_list)
        data.target_y = np.array(tgt_y_list)
        data.timestamps = np.array(ts_list)
        data.end_time = time.time()

        log.info("Step scan 2D complete: %d points in %.1fs",
                 point_idx, data.duration_s)
        return data

    # ── 1D Fly Scan ──────────────────────────────────────────────

    def fly_scan_1d(self, axis: int, start_nm: float, stop_nm: float,
                    n_points: int, velocity_nm_s: float = 1000.0,
                    stream_rate_hz: int = 10000) -> ScanData:
        """1D fly scan: continuous motion with streaming encoder readback.

        The MCS2 moves at constant velocity while PicoScale streams
        position data at the configured rate. Positions are then
        rebinned to n_points equally-spaced intervals.

        Args:
            axis: MCS2 channel (0=X, 1=Y, 2=Z)
            start_nm: Start position (nm)
            stop_nm: Stop position (nm)
            n_points: Number of desired output points (after rebinning)
            velocity_nm_s: Scan velocity in nm/s
            stream_rate_hz: PicoScale streaming rate in Hz

        Returns:
            ScanData with rebinned encoder positions
        """
        scan_range = abs(stop_nm - start_nm)
        scan_time = scan_range / velocity_nm_s
        expected_frames = int(scan_time * stream_rate_hz)

        data = ScanData(
            scan_type="fly_scan_1d",
            start_time=time.time(),
            scan_params={
                "axis": axis, "start_nm": start_nm, "stop_nm": stop_nm,
                "n_points": n_points, "velocity_nm_s": velocity_nm_s,
                "stream_rate_hz": stream_rate_hz,
                "expected_frames": expected_frames,
            },
        )

        log.info("Fly scan 1D: axis=%d, [%.1f,%.1f] nm, v=%.1f nm/s, "
                 "stream=%d Hz, ~%d frames, rebin to %d pts",
                 axis, start_nm, stop_nm, velocity_nm_s,
                 stream_rate_hz, expected_frames, n_points)

        # Collect streaming data
        stream_positions = []
        stream_timestamps = []

        def on_stream_data(frame):
            for ch_idx, values in frame.positions.items():
                if ch_idx == 0:  # first enabled channel
                    stream_positions.extend(values)
                    n = len(values)
                    dt = 1.0 / stream_rate_hz
                    base_t = frame.timestamp
                    stream_timestamps.extend(
                        [base_t + i * dt for i in range(n)])

        # 1. Move to start position
        self.mcs2.move_to(axis, start_nm, timeout_s=30.0)
        time.sleep(0.1)  # settle

        # 2. Configure and start PicoScale streaming
        self.ps.configure_streaming(
            frame_rate=stream_rate_hz,
            channels=[axis],
            frame_aggregation=max(1, stream_rate_hz // 100))
        self.ps.start_streaming(callback=on_stream_data)

        # 3. Start continuous move
        t0 = time.monotonic()
        self.mcs2.move_to(axis, stop_nm,
                          timeout_s=scan_time + 10.0)

        # 4. Stop streaming
        self.ps.stop_streaming()
        data.end_time = time.time()

        # 5. Rebin to n_points
        raw_pos = np.array(stream_positions) / 1000.0  # pm -> nm
        raw_ts = np.array(stream_timestamps)

        if len(raw_pos) > 0:
            # Rebin by averaging into n_points bins
            target_positions = np.linspace(start_nm, stop_nm, n_points)
            binned_pos = np.interp(
                np.linspace(raw_ts[0], raw_ts[-1], n_points),
                raw_ts, raw_pos)
            binned_ts = np.linspace(0, scan_time, n_points)

            if axis == self.AXIS_X:
                data.encoder_x = binned_pos
                data.target_x = target_positions
                data.encoder_y = np.zeros(n_points)
            else:
                data.encoder_y = binned_pos
                data.target_y = target_positions
                data.encoder_x = np.zeros(n_points)
            data.timestamps = binned_ts
        else:
            log.warning("No streaming data received during fly scan")

        log.info("Fly scan 1D complete: %d raw frames -> %d rebinned pts "
                 "in %.1fs", len(raw_pos), n_points, data.duration_s)
        return data

    # ── 2D Fly Scan ──────────────────────────────────────────────

    def fly_scan_2d(self, fast_axis: int, slow_axis: int,
                    fast_start: float, fast_stop: float, n_fast: int,
                    slow_start: float, slow_stop: float, n_slow: int,
                    velocity_nm_s: float = 1000.0,
                    stream_rate_hz: int = 10000,
                    snake: bool = True) -> ScanData:
        """2D fly scan: fast axis continuous, slow axis step.

        Each row is a 1D fly scan along the fast axis.
        Between rows, the slow axis steps and settles.

        Args:
            fast_axis: Fast axis MCS2 channel (continuous motion)
            slow_axis: Slow axis MCS2 channel (step between lines)
            fast_start, fast_stop: Fast axis range (nm)
            n_fast: Points per line (after rebinning)
            slow_start, slow_stop: Slow axis range (nm)
            n_slow: Number of lines
            velocity_nm_s: Fast axis velocity (nm/s)
            stream_rate_hz: PicoScale streaming rate (Hz)
            snake: Alternate fast axis direction per row

        Returns:
            ScanData with 2D grid of encoder positions
        """
        slow_positions = np.linspace(slow_start, slow_stop, n_slow)
        total_points = n_fast * n_slow

        data = ScanData(
            scan_type="fly_scan_2d",
            start_time=time.time(),
            nx=n_fast, ny=n_slow,
            scan_params={
                "fast_axis": fast_axis, "slow_axis": slow_axis,
                "fast_start": fast_start, "fast_stop": fast_stop,
                "slow_start": slow_start, "slow_stop": slow_stop,
                "n_fast": n_fast, "n_slow": n_slow,
                "velocity_nm_s": velocity_nm_s,
                "stream_rate_hz": stream_rate_hz, "snake": snake,
            },
        )

        all_enc_x = []
        all_enc_y = []
        all_ts = []
        self._abort.clear()

        log.info("Fly scan 2D: fast=%d [%.1f,%.1f] nm, slow=%d [%.1f,%.1f] nm, "
                 "v=%.1f nm/s, %dx%d = %d pts",
                 fast_axis, fast_start, fast_stop,
                 slow_axis, slow_start, slow_stop,
                 velocity_nm_s, n_fast, n_slow, total_points)

        for row_idx, slow_pos in enumerate(slow_positions):
            if self._abort.is_set():
                break

            # Step slow axis
            self.mcs2.move_to(slow_axis, slow_pos)
            time.sleep(0.05)  # inter-line settle

            # Determine line direction
            if snake and row_idx % 2 == 1:
                line_start, line_stop = fast_stop, fast_start
            else:
                line_start, line_stop = fast_start, fast_stop

            # Fly scan this line
            line_data = self.fly_scan_1d(
                fast_axis, line_start, line_stop,
                n_fast, velocity_nm_s, stream_rate_hz)

            # Collect results
            slow_enc = self.ps.get_position(slow_axis)
            if fast_axis == self.AXIS_X:
                all_enc_x.extend(line_data.encoder_x.tolist())
                all_enc_y.extend([slow_enc] * n_fast)
            else:
                all_enc_y.extend(line_data.encoder_y.tolist())
                all_enc_x.extend([slow_enc] * n_fast)
            all_ts.extend(line_data.timestamps.tolist())

            self._report_progress(
                100.0 * (row_idx + 1) / n_slow,
                f"Line {row_idx+1}/{n_slow}")

        data.encoder_x = np.array(all_enc_x)
        data.encoder_y = np.array(all_enc_y)
        data.timestamps = np.array(all_ts)
        data.end_time = time.time()

        log.info("Fly scan 2D complete: %d points in %.1fs",
                 len(all_enc_x), data.duration_s)
        return data

    # ── Spiral Scan (Fermat) ─────────────────────────────────────

    def spiral_scan(self, x_axis: int, y_axis: int,
                    x_center: float, y_center: float,
                    radius_nm: float, dr_nm: float = 50.0,
                    dwell_s: float = 0.01) -> ScanData:
        """Fermat spiral scan for ptychography.

        Generates positions on a Fermat spiral for efficient area coverage
        with controlled overlap. Each point is a step-scan point
        (move -> settle -> read).

        Args:
            x_axis: MCS2 channel for X (0)
            y_axis: MCS2 channel for Y (1)
            x_center: Spiral center X (nm)
            y_center: Spiral center Y (nm)
            radius_nm: Maximum radius (nm)
            dr_nm: Radial step (nm). Controls point density.
            dwell_s: Settling time per point (s)

        Returns:
            ScanData with spiral positions
        """
        # Generate Fermat spiral positions
        golden_angle = math.pi * (3.0 - math.sqrt(5.0))  # ~137.508 deg
        points = []
        n = 0
        while True:
            r = dr_nm * math.sqrt(n)
            if r > radius_nm:
                break
            theta = n * golden_angle
            x = x_center + r * math.cos(theta)
            y = y_center + r * math.sin(theta)
            points.append((x, y))
            n += 1

        n_points = len(points)
        data = ScanData(
            scan_type="spiral_scan",
            start_time=time.time(),
            scan_params={
                "x_center": x_center, "y_center": y_center,
                "radius_nm": radius_nm, "dr_nm": dr_nm,
                "n_points": n_points, "dwell_s": dwell_s,
            },
        )

        enc_x_list = []
        enc_y_list = []
        ts_list = []
        self._abort.clear()

        log.info("Spiral scan: center=(%.1f,%.1f) nm, R=%.1f nm, "
                 "dr=%.1f nm, %d pts, dwell=%.3fs",
                 x_center, y_center, radius_nm, dr_nm, n_points, dwell_s)
        t0 = time.monotonic()

        for i, (px, py) in enumerate(points):
            if self._abort.is_set():
                break

            self.mcs2.move_to(x_axis, px)
            self.mcs2.move_to(y_axis, py)
            time.sleep(dwell_s)

            enc_x = self.ps.get_position(x_axis)
            enc_y = self.ps.get_position(y_axis)
            ts = time.monotonic() - t0

            enc_x_list.append(enc_x)
            enc_y_list.append(enc_y)
            ts_list.append(ts)

            self._report_progress(100.0 * (i + 1) / n_points,
                                  f"Point {i+1}/{n_points}")

        data.encoder_x = np.array(enc_x_list)
        data.encoder_y = np.array(enc_y_list)
        data.target_x = np.array([p[0] for p in points[:len(enc_x_list)]])
        data.target_y = np.array([p[1] for p in points[:len(enc_y_list)]])
        data.timestamps = np.array(ts_list)
        data.end_time = time.time()

        log.info("Spiral scan complete: %d points in %.1fs",
                 len(enc_x_list), data.duration_s)
        return data
